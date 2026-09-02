"""Lifecycle tools: validate, acceptance, ask_user, fail, finish, layout.

``validate_graph.ok`` means the validator ran. ``finish.ok`` means the
completion claim was accepted (fresh hydrate+validate, ``valid=true``,
revision aligned, and — when an ``AcceptanceRunner`` is injected — current
revision+hash Evidence passed).
"""

import logging
from typing import cast

from core.workflow.generator.agent.evidence import canonical_graph_hash, finish_acceptance_reason
from core.workflow.generator.agent.tool_context import ToolContext
from core.workflow.generator.agent.tool_results import error, ok, require_str
from core.workflow.generator.agent.types import MinimalGraphDict, ToolCall, ToolResult
from core.workflow.generator.graph_postprocessor import postprocess_graph
from core.workflow.generator.graph_validator import validate_graph as run_graph_validator
from core.workflow.generator.types import GraphDict, WorkflowGenerateErrorDict

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
    laid_out = postprocess_graph(graph=cast(GraphDict, context.state.graph), mode=context.env.mode)
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
    if mode == "live" and not context.env.live_run_authorized:
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
    graph_hash = canonical_graph_hash(context.state.graph)
    context.state.graph_hash = graph_hash
    try:
        attempts = context.env.acceptance_runner.run(
            graph=context.state.graph,
            revision=context.state.candidate_revision,
            graph_hash=graph_hash,
            case_ids=case_ids,
            mode=mode,
        )
    except Exception:
        logger.exception("Workflow agent: acceptance runner failed")
        return error(call, "CAPABILITY_UNAVAILABLE", "Acceptance runner failed")
    failed_nodes: list[dict[str, object]] = []
    unverified: list[str] = []
    for attempt in attempts:
        context.state.attempts[attempt["attempt_id"]] = attempt
        failed_nodes.extend(cast(list[dict[str, object]], attempt.get("failed_nodes") or []))
        unverified.extend(str(item) for item in (attempt.get("unverified_nodes") or []) if isinstance(item, str))
    passed = bool(attempts) and all(attempt["passed"] for attempt in attempts)
    content: dict[str, object] = {
        "passed": passed,
        "revision": context.state.candidate_revision,
        "graph_hash": graph_hash,
        "failed_nodes": failed_nodes,
        "unverified_nodes": sorted(set(unverified)),
        "mode": mode,
    }
    if attempts:
        last = attempts[-1]
        content["attempt_id"] = last["attempt_id"]
        content["trace_summary"] = last["trace_summary"]
        content["status"] = last["status"]
    return ok(call, changed=False, content=content)


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
    return ok(call, changed=False, content={"questions": questions})


def fail(call: ToolCall, context: ToolContext) -> ToolResult:
    reason = call["arguments"].get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return error(call, "INVALID_ARGUMENT", "reason is required")
    return ok(call, changed=False, content={"reason": reason})


def finish(call: ToolCall, context: ToolContext) -> ToolResult:
    summary = call["arguments"].get("summary")
    if not isinstance(summary, str):
        return error(call, "INVALID_ARGUMENT", "summary is required")
    try:
        hydrate_changed = _apply_hydrate(context)
    except Exception:
        logger.exception("Workflow agent: graph hydrate failed")
        return error(call, "CAPABILITY_UNAVAILABLE", "Graph hydrate failed")
    try:
        envelope = validation_content(context)
    except Exception:
        logger.exception("Workflow agent: graph validator failed")
        return error(call, "CAPABILITY_UNAVAILABLE", "Graph validator failed")
    content: dict[str, object] = {**envelope, "summary": summary}
    valid = bool(envelope["valid"])
    aligned = context.state.last_validation_revision == context.state.candidate_revision
    graph_hash = canonical_graph_hash(context.state.graph)
    context.state.graph_hash = graph_hash
    acceptance_reason = finish_acceptance_reason(
        attempts=context.state.attempts,
        revision=context.state.candidate_revision,
        graph_hash=graph_hash,
        runner_present=context.env.acceptance_runner is not None,
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
    this call's validate is aligned, and sets ``last_mutation_changed`` so a
    rejected claim can report ``repeated_after_repair``.
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
