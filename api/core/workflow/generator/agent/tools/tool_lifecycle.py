"""Lifecycle tools: validate, acceptance, ask_user, fail, finish, layout.

``validate_graph.ok`` means the validator ran. ``finish.ok`` means the
completion claim was accepted (hydrate is idempotent review, ``valid=true``,
revision aligned, and — when an ``AcceptanceRunner`` is injected — current
revision+hash Evidence passed). ``run_acceptance`` hydrates first so Evidence
is recorded against the bound graph.
"""

import logging
from typing import Any, cast

from core.workflow.generator.acceptance.authorization import LIVE_CONSENT_QUESTION_ID, build_live_acceptance_request
from core.workflow.generator.acceptance.evidence import (
    AcceptanceAttempt,
    canonical_graph_hash,
    finish_acceptance_reason,
)
from core.workflow.generator.agent.tools.tool_context import ToolContext
from core.workflow.generator.agent.tools.tool_results import error, ok, require_str
from core.workflow.generator.agent.types import ToolCall, ToolResult
from core.workflow.generator.compiler.agent_knowledge import collect_agent_knowledge_dataset_ids
from core.workflow.generator.contracts.workflow_contract import workflow_contract_finish_error
from core.workflow.generator.contracts.workflow_reconciliation import (
    WORKFLOW_RECONCILIATION_VERSION,
    reconcile_workflow_contract,
)
from core.workflow.generator.graph.graph_postprocessor import postprocess_graph
from core.workflow.generator.graph.types import MinimalGraphDict
from core.workflow.generator.types import GraphDict, WorkflowGenerateErrorDict
from core.workflow.generator.validation.agent_config import collect_unhydrated_inline_agent_errors
from core.workflow.generator.validation.graph_validator import validate_graph as run_graph_validator
from core.workflow.generator.variables.variable_references import VariableReferences

logger = logging.getLogger(__name__)


def note_graph_mutation(context: ToolContext) -> None:
    """After a successful non-finish mutation: sticky flag, layout, hash."""
    context.state.last_mutation_changed = True
    try:
        relayout_graph(context)
    except Exception:
        logger.exception("Workflow agent: graph layout after mutation failed")
    context.state.graph_hash = canonical_graph_hash(context.state.graph)


def relayout_graph(context: ToolContext) -> bool:
    """Fill canvas coordinates after a graph mutation.

    Does not bump ``candidate_revision``: the loop already advances revision
    when ``changed`` is true. ``finish`` uses ``_apply_accepted_layout`` for
    the final pass that may add hydrate nodes.
    """
    before = _layout_signature(context.state.graph)
    laid_out = postprocess_graph(
        graph=cast(GraphDict, context.state.graph),
        mode=context.env.mode,
        tool_entries=context.env.tool_entries if context.env.tools_available else None,
    )
    context.state.graph = cast(MinimalGraphDict, laid_out)
    return _layout_signature(laid_out) != before


def validation_content(context: ToolContext) -> dict[str, object]:
    """Run the graph validator and return the shared observation envelope.

    ``repeated_after_repair`` is true only when a previous validate failed,
    a later tool returned ``changed=true``, and this run's error signature
    matches the previous one. Queries and no-ops do not set the flag.
    """
    errors = run_graph_validator(
        graph=cast(GraphDict, context.state.graph),
        mode=context.env.mode,
        installed_tools=context.env.installed_tools,
        installed_dataset_ids=context.env.installed_dataset_ids,
        environment_variables=context.env.environment_variables,
        conversation_variables=context.env.conversation_variables,
        tool_entries=context.env.tool_entries if context.env.tools_available else None,
    )
    if context.env.require_resource_context:
        for node in context.state.graph.get("nodes") or []:
            if not isinstance(node, dict) or not isinstance(node.get("data"), dict):
                continue
            data = node.get("data") or {}
            missing_tools = (data.get("type") == "tool" or data.get("dify_tools")) and not context.env.tools_available
            missing_datasets = (
                data.get("type") == "knowledge-retrieval" or bool(collect_agent_knowledge_dataset_ids(data))
            ) and not context.env.knowledge_available
            if missing_tools or missing_datasets:
                errors.append(
                    {
                        "code": "CAPABILITY_UNAVAILABLE",
                        "node_id": node["id"],
                        "detail": "Tenant resource catalogue is unavailable; membership was not verified",
                    }
                )
            refs: set[tuple[str, str]] = set()
            VariableReferences._collect_refs_in_data(data, refs)
            for namespace, names in (
                ("env", context.env.environment_variables),
                ("conversation", context.env.conversation_variables),
            ):
                if names is None and any(source == namespace for source, _ in refs):
                    errors.append(
                        {
                            "code": "CAPABILITY_UNAVAILABLE",
                            "node_id": node["id"],
                            "detail": f"Draft {namespace} namespace is unavailable; references were not verified",
                        }
                    )
    mapped = _map_validation_errors(errors)
    signature = _error_signature(mapped)
    valid = len(mapped) == 0
    repeated = (
        context.state.last_error_signature is not None
        and context.state.last_mutation_changed
        and signature == context.state.last_error_signature
    )
    context.state.last_validation_revision = context.state.candidate_revision
    context.state.last_error_signature = None if valid else signature
    context.state.last_mutation_changed = False
    return {"valid": valid, "errors": mapped, "repeated_after_repair": repeated}


def validate_graph(call: ToolCall, context: ToolContext) -> ToolResult:
    try:
        content = validation_content(context)
    except Exception:
        logger.exception("Workflow agent: graph validator failed")
        return error(call, "CAPABILITY_UNAVAILABLE", "Graph validator failed")
    return ok(call, changed=False, content=content)


def run_acceptance(call: ToolCall, context: ToolContext) -> ToolResult:
    if context.env.acceptance_runner is None:
        return error(call, "CAPABILITY_UNAVAILABLE", "Acceptance runner is not available")
    mode = call["arguments"].get("mode") or "simulated"
    if mode not in {"simulated", "live"}:
        return error(call, "INVALID_ARGUMENT", "mode must be simulated or live")
    if mode == "live" and context.env.authorize_live_acceptance is None:
        return error(
            call,
            "LIVE_RUN_REQUIRES_CONSENT",
            "Live acceptance requires ask_user consent with question id live_run_consent",
        )
    case_ids_raw = call["arguments"].get("case_ids")
    if case_ids_raw is None:
        case_ids = ["default"]
    elif isinstance(case_ids_raw, list) and all(isinstance(item, str) and item for item in case_ids_raw):
        case_ids = [str(item) for item in case_ids_raw]
    else:
        return error(call, "INVALID_ARGUMENT", "case_ids must be a list of strings")
    try:
        preflight = validation_content(context)
    except Exception:
        logger.exception("Workflow agent: acceptance preflight failed")
        return error(call, "CAPABILITY_UNAVAILABLE", "Acceptance preflight failed")
    if not preflight["valid"]:
        return {
            "tool_call_id": call["id"],
            "name": call["name"],
            "ok": False,
            "changed": False,
            "content": preflight,
            "error": "Repair graph validation errors before acceptance",
            "error_code": "INVALID_NODE_CONFIG",
            "retryable": True,
        }
    try:
        hydrate_changed = _apply_hydrate(context)
    except Exception as exc:
        mapped = _hydrate_failure(call, exc)
        if mapped is not None:
            return mapped
        logger.exception("Workflow agent: graph hydrate failed")
        return error(call, "CAPABILITY_UNAVAILABLE", "Graph hydrate failed")
    try:
        before_preparation = canonical_graph_hash(context.state.graph)
        layout_changed = relayout_graph(context)
        preparation_changed = layout_changed or before_preparation != canonical_graph_hash(context.state.graph)
        if preparation_changed and not hydrate_changed:
            context.state.candidate_revision += 1
        hydrate_changed = hydrate_changed or preparation_changed
        prepared_validation = validation_content(context)
    except Exception:
        logger.exception("Workflow agent: acceptance graph preparation failed")
        return error(call, "CAPABILITY_UNAVAILABLE", "Acceptance graph preparation failed")
    if not prepared_validation["valid"]:
        return {
            "tool_call_id": call["id"],
            "name": call["name"],
            "ok": False,
            "changed": hydrate_changed,
            "content": prepared_validation,
            "error": "Repair prepared graph before acceptance",
            "error_code": "INVALID_NODE_CONFIG",
            "retryable": True,
        }
    binding_error = _unhydrated_binding_error(context)
    if binding_error is not None:
        return error(call, str(binding_error["code"]), binding_error["detail"])
    graph_hash = canonical_graph_hash(context.state.graph)
    context.state.graph_hash = graph_hash
    if mode == "live":
        # Reserve durably before any external call; failures and worker retries cannot reuse the grant.
        if (
            len(case_ids) != 1
            or context.env.authorize_live_acceptance is None
            or not context.env.authorize_live_acceptance(context.state.candidate_revision, graph_hash)
        ):
            return error(call, "LIVE_RUN_REQUIRES_CONSENT", "Authorize one live case for the current candidate graph")
    try:
        attempts = context.env.acceptance_runner.run(
            graph=context.state.graph,
            revision=context.state.candidate_revision,
            graph_hash=graph_hash,
            case_ids=case_ids,
            mode=mode,
        )
    except ValueError as exc:
        return error(call, "INVALID_ARGUMENT", str(exc))
    except Exception:
        logger.exception("Workflow agent: acceptance runner failed")
        return error(call, "CAPABILITY_UNAVAILABLE", "Acceptance runner failed")
    failed_nodes: list[dict[str, object]] = []
    unverified: list[str] = []
    unexecuted: list[str] = []
    assertions: list[object] = []
    for attempt in attempts:
        _bind_attempt_to_completion_context(attempt, context)
        context.state.attempts[attempt["attempt_id"]] = attempt
        failed_nodes.extend(cast(list[dict[str, object]], attempt.get("failed_nodes") or []))
        unverified.extend(str(item) for item in (attempt.get("unverified_nodes") or []) if isinstance(item, str))
        unexecuted.extend(str(item) for item in (attempt.get("unexecuted_node_ids") or []) if isinstance(item, str))
        assertions.extend(attempt.get("assertions") or [])
    passed = bool(attempts) and all(attempt["passed"] for attempt in attempts)
    executed = bool(attempts) and all(bool(attempt.get("executed")) for attempt in attempts)
    content: dict[str, object] = {
        "passed": passed,
        "executed": executed,
        "revision": context.state.candidate_revision,
        "graph_hash": graph_hash,
        "failed_nodes": failed_nodes,
        "unverified_nodes": sorted(set(unverified)),
        "unexecuted_node_ids": sorted(set(unexecuted)),
        "executed_node_ids": sorted(
            {node_id for attempt in attempts for node_id in attempt.get("executed_node_ids", [])}
        ),
        "mode": mode,
        "runtime_contract_passed": bool(attempts)
        and all(bool(attempt.get("runtime_contract_passed", True)) for attempt in attempts),
        "business_verified": bool(attempts)
        and all(bool(attempt.get("business_verified", False)) for attempt in attempts),
        "assertions": assertions,
    }
    if attempts:
        last = attempts[-1]
        content["attempt_id"] = last["attempt_id"]
        content["trace_summary"] = last["trace_summary"]
        content["status"] = last["status"]
    return ok(call, changed=hydrate_changed, content=content)


def inspect_attempt(call: ToolCall, context: ToolContext) -> ToolResult:
    attempt_id = require_str(call["arguments"], "attempt_id")
    if attempt_id is None:
        return error(call, "INVALID_ARGUMENT", "attempt_id is required")
    attempt = context.state.attempts.get(attempt_id)
    if attempt is None:
        return error(call, "INVALID_ARGUMENT", f"Unknown attempt {attempt_id!r}")
    return ok(call, changed=False, content=cast(dict[str, object], dict(attempt)))


def ask_user(call: ToolCall, context: ToolContext) -> ToolResult:
    questions = call["arguments"].get("questions")
    if not isinstance(questions, list) or not questions:
        return error(call, "INVALID_ARGUMENT", "questions is required")
    if any(isinstance(question, dict) and question.get("id") == LIVE_CONSENT_QUESTION_ID for question in questions):
        try:
            request = build_live_acceptance_request(context.state.graph, revision=context.state.candidate_revision)
        except Exception:
            logger.exception("Workflow assist: could not prepare live consent")
            return error(call, "CAPABILITY_UNAVAILABLE", "Could not prepare live execution scope")
        # The model cannot choose the graph hash, scope, budget, or authorization identifier.
        questions = [
            {
                "id": LIVE_CONSENT_QUESTION_ID,
                "kind": "live_acceptance",
                "question": "Authorize a live trial of this candidate?",
                "execution_request": request.model_dump(mode="json"),
            }
        ]
        call["arguments"] = {"questions": questions}
    return ok(call, changed=False, content={"questions": questions})


def fail(call: ToolCall, context: ToolContext) -> ToolResult:
    reason = call["arguments"].get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return error(call, "INVALID_ARGUMENT", "reason is required")
    return ok(call, changed=False, content={"reason": reason})


def finish(call: ToolCall, context: ToolContext) -> ToolResult:
    contract_error = workflow_contract_finish_error(call, context)
    if contract_error is not None:
        return contract_error
    summary = call["arguments"].get("summary")
    if not isinstance(summary, str):
        return error(call, "INVALID_ARGUMENT", "summary is required")
    try:
        preflight = validation_content(context)
    except Exception:
        logger.exception("Workflow agent: finish preflight failed")
        return error(call, "CAPABILITY_UNAVAILABLE", "Graph validator failed")
    if not preflight["valid"]:
        contract_report = _contract_report(context)
        return {
            "tool_call_id": call["id"],
            "name": call["name"],
            "ok": False,
            "changed": False,
            "content": {
                **preflight,
                "summary": summary,
                **({"contract_report": contract_report} if contract_report is not None else {}),
            },
            "error": None,
            "error_code": None,
            "retryable": False,
        }
    try:
        hydrate_changed = _apply_hydrate(context)
    except Exception as exc:
        mapped = _hydrate_failure(call, exc)
        if mapped is not None:
            return mapped
        logger.exception("Workflow agent: graph hydrate failed")
        return error(call, "CAPABILITY_UNAVAILABLE", "Graph hydrate failed")
    try:
        envelope = validation_content(context)
    except Exception:
        logger.exception("Workflow agent: graph validator failed")
        return error(call, "CAPABILITY_UNAVAILABLE", "Graph validator failed")
    envelope = _merge_unhydrated_binding_errors(context, envelope)
    content: dict[str, object] = {**envelope, "summary": summary}
    contract_report = _contract_report(context)
    if contract_report is not None:
        content["contract_report"] = contract_report
    valid = bool(envelope["valid"]) and (contract_report is None or contract_report["passed"])
    content["valid"] = valid
    aligned = context.state.last_validation_revision == context.state.candidate_revision
    graph_hash = canonical_graph_hash(context.state.graph)
    context.state.graph_hash = graph_hash
    acceptance_reason = finish_acceptance_reason(
        attempts=context.state.attempts,
        revision=context.state.candidate_revision,
        graph_hash=graph_hash,
        runner_present=context.env.acceptance_runner is not None,
        contract_revision=(
            context.state.contract_revision if context.state.contract_protocol_version is not None else None
        ),
        contract_hash=context.state.contract_hash if context.state.contract_protocol_version is not None else None,
        app_mode=context.env.mode if context.state.contract_protocol_version is not None else None,
        candidate_base_hash=context.state.candidate_base_hash,
        validation_version=WORKFLOW_RECONCILIATION_VERSION
        if context.state.contract_protocol_version is not None
        else None,
    )
    if valid and aligned and acceptance_reason is None:
        try:
            layout_changed = _apply_accepted_layout(context)
        except Exception:
            logger.exception("Workflow agent: graph layout failed")
            return error(call, "CAPABILITY_UNAVAILABLE", "Graph layout failed")
        return ok(call, changed=hydrate_changed or layout_changed, content=content)
    if acceptance_reason is not None and valid and aligned:
        content["acceptance"] = _acceptance_rejection(context, acceptance_reason)
    return {
        "tool_call_id": call["id"],
        "name": call["name"],
        "ok": False,
        "changed": hydrate_changed,
        "content": content,
        "error": None,
        "error_code": None,
        "retryable": False,
    }


def _apply_hydrate(context: ToolContext) -> bool:
    """Run ``hydrate_graph`` if present. Returns whether the candidate changed.

    A real change rebinds ``context.state.graph``, bumps ``candidate_revision`` so
    this call's validate and acceptance Evidence stay aligned, and sets
    ``last_mutation_changed`` so a rejected claim can report ``repeated_after_repair``.
    ``run_acceptance`` hydrates first; ``finish`` then treats hydrate as idempotent
    review and must not rewrite Evidence hashes.
    """
    if context.env.hydrate_graph is None:
        return False
    hydrated = context.env.hydrate_graph(context.state.graph)
    if hydrated == context.state.graph:
        return False
    context.state.graph = hydrated
    context.state.candidate_revision += 1
    context.state.last_mutation_changed = True
    return True


def _contract_report(context: ToolContext) -> dict[str, object] | None:
    """Return the shared graph/contract report for new-protocol sessions."""
    contract = context.state.workflow_contract
    if context.state.contract_protocol_version is None or contract is None:
        return None
    return cast(
        dict[str, object],
        reconcile_workflow_contract(
            contract=contract,
            graph=context.state.graph,
            mode=context.env.mode,
            candidate_base_hash=context.state.candidate_base_hash,
            installed_tools=context.env.installed_tools,
            installed_dataset_ids=context.env.installed_dataset_ids,
            installed_models={(entry["provider"], entry["name"]) for entry in context.env.agent_model_entries}
            if context.env.models_available
            else None,
        ),
    )


def _bind_attempt_to_completion_context(attempt: AcceptanceAttempt, context: ToolContext) -> None:
    """Attach server-owned contract and run coordinates to sandbox evidence."""
    attempt["candidate_base_hash"] = context.state.candidate_base_hash
    for evidence in attempt.get("evidence") or []:
        evidence["candidate_base_hash"] = attempt["candidate_base_hash"]
    if context.state.contract_protocol_version is None:
        return
    attempt["contract_revision"] = context.state.contract_revision
    if context.state.contract_hash is not None:
        attempt["contract_hash"] = context.state.contract_hash
    attempt["app_mode"] = context.env.mode
    attempt["validation_version"] = WORKFLOW_RECONCILIATION_VERSION
    if context.env.run_id is not None:
        attempt["run_id"] = context.env.run_id
    if context.env.run_epoch is not None:
        attempt["epoch"] = context.env.run_epoch
    for evidence in attempt.get("evidence") or []:
        evidence["contract_revision"] = attempt["contract_revision"]
        if "contract_hash" in attempt:
            evidence["contract_hash"] = attempt["contract_hash"]
        evidence["app_mode"] = attempt["app_mode"]
        evidence["validation_version"] = attempt["validation_version"]
        if "run_id" in attempt:
            evidence["run_id"] = attempt["run_id"]
        if "epoch" in attempt:
            evidence["epoch"] = attempt["epoch"]


def _hydrate_failure(call: ToolCall, exc: BaseException) -> ToolResult | None:
    """Map a hydrate domain error onto a recoverable tool envelope."""
    code = getattr(exc, "code", None)
    detail = getattr(exc, "detail", None)
    if isinstance(code, str) and code and isinstance(detail, str) and detail:
        return error(call, code, detail)
    return None


def _layout_signature(graph: MinimalGraphDict | GraphDict) -> tuple[tuple[object, ...], ...]:
    nodes = graph.get("nodes") or []
    return tuple(
        (
            node.get("id"),
            (node.get("position") or {}).get("x") if isinstance(node.get("position"), dict) else None,
            (node.get("position") or {}).get("y") if isinstance(node.get("position"), dict) else None,
            node.get("width"),
            node.get("height"),
        )
        for node in nodes
        if isinstance(node, dict)
    )


def _apply_accepted_layout(context: ToolContext) -> bool:
    """Normalize positions after an accepted finish claim.

    ``postprocess_graph`` mutates node dicts in place, so identity/equality of
    the graph mapping cannot detect whether coordinates were filled. Compare a
    layout signature instead and keep the claim aligned when they change.
    """
    if not relayout_graph(context):
        return False
    context.state.candidate_revision += 1
    context.state.last_validation_revision = context.state.candidate_revision
    return True


def _unhydrated_binding_error(context: ToolContext) -> WorkflowGenerateErrorDict | None:
    """Return the first missing-id error after hydrate, if hydrate is injected."""
    extras = _post_hydrate_binding_errors(context)
    return extras[0] if extras else None


def _merge_unhydrated_binding_errors(context: ToolContext, envelope: dict[str, object]) -> dict[str, object]:
    """After hydrate, require inline Agent binding ids.

    ``validate_graph`` is pre-hydrate and must not fail on missing ids.
    """
    extras = _map_validation_errors(_post_hydrate_binding_errors(context))
    if not extras:
        return envelope
    mapped = list(cast(list[dict[str, object]], envelope.get("errors") or []))
    mapped.extend(extras)
    context.state.last_error_signature = _error_signature(mapped)
    context.state.last_mutation_changed = False
    return {**envelope, "valid": False, "errors": mapped}


def _post_hydrate_binding_errors(context: ToolContext) -> list[WorkflowGenerateErrorDict]:
    if context.env.hydrate_graph is None:
        return []
    nodes = cast(
        list[dict[str, Any]],
        [node for node in (context.state.graph.get("nodes") or []) if isinstance(node, dict)],
    )
    return collect_unhydrated_inline_agent_errors(nodes)


def _map_validation_errors(errors: list[WorkflowGenerateErrorDict]) -> list[dict[str, object]]:
    mapped: list[dict[str, object]] = []
    for item in errors:
        mapped.append(
            {
                "code": item["code"],
                "node_id": item.get("node_id") or "",
                "detail": item["detail"],
            }
        )
    return mapped


def _error_signature(errors: list[dict[str, object]]) -> tuple[str, ...]:
    return tuple(sorted(f"{item['code']}@{item['node_id']}" for item in errors))


def _acceptance_rejection(context: ToolContext, reason: str) -> dict[str, object]:
    failed_nodes: list[dict[str, object]] = []
    attempt_id = ""
    for attempt in context.state.attempts.values():
        failed_nodes.extend(cast(list[dict[str, object]], attempt.get("failed_nodes") or []))
        attempt_id = attempt["attempt_id"]
    return {
        "required": True,
        "passed": False,
        "reason": reason,
        "attempt_id": attempt_id,
        "failed_nodes": failed_nodes,
    }
