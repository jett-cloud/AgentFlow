"""
Workflow generator runner.

Slim planner→parallel-node-builder pipeline. Pure domain logic; the model instance is
injected by ``WorkflowGeneratorService`` so this module stays cleanly
separated from the infrastructure layer.

Pipeline:

    1. PLANNER  — short LLM call producing a high-level node list.
    2. BUILDERS — bounded concurrent LLM calls producing compact node configs.
    3. POSTPROC — fill safe defaults, lay nodes out left-to-right, dedupe
                  edge ids, and run a final structural sanity check.

Intentionally NOT here (deferred to a future iteration):

    - Mermaid rendering
    - Broad semantic auto-repair when multiple valid graph interpretations exist
    - Multi-step validation engine with classification of fixable vs. user-required errors
    - Model catalogue filtering

If quality regresses below product threshold we add those back; for now the
planner and bounded parallel node builders shipped behind cmd+k `/create` are
enough.
"""

import logging
import queue
import threading
import time
from collections.abc import Iterator
from typing import Any, cast

from core.workflow.generator.graph_postprocessor import postprocess_graph
from core.workflow.generator.graph_validator import validate_graph
from core.workflow.generator.knowledge_catalogue import KnowledgeCatalogueEntry, format_knowledge_catalogue
from core.workflow.generator.llm_response import (
    LLMJsonClient,
    StageError,
    StageJSONError,
    StageSchemaError,
    StageTruncatedError,
)
from core.workflow.generator.node_builder import BuilderInput
from core.workflow.generator.node_builder import build_graph as build_node_graph
from core.workflow.generator.output_language import (
    detect_output_language,
    localized_generator_message,
)
from core.workflow.generator.planner import (
    PlannerActionLimitError,
    PlannerAssistantMessageOutcome,
    PlannerBudgetExhaustedError,
    PlannerClarificationLimitError,
    PlannerClarificationOutcome,
    PlannerInput,
    PlannerNoProgressError,
    PlannerPlanOutcome,
    PlannerPolicy,
    PlannerPolicyDeniedError,
    iter_plan,
    resolve_generation_mode,
)
from core.workflow.generator.planner_context import PlannerContextCheckpoint, PlannerContextLimitError
from core.workflow.generator.planning_session import PlannerRequirementInvalidError
from core.workflow.generator.tool_catalogue import ToolCatalogueEntry, format_tool_catalogue
from core.workflow.generator.types import (
    GraphDict,
    GraphViewportDict,
    PlannerResultDict,
    WorkflowGenerateErrorCode,
    WorkflowGenerateErrorDict,
    WorkflowGenerateResultDict,
    WorkflowGenerationMode,
    WorkflowGenerationModeRequest,
)

logger = logging.getLogger(__name__)


_DEFAULT_VIEWPORT: GraphViewportDict = {"x": 0.0, "y": 0.0, "zoom": 0.7}


def _err(code: str, detail: str, node_id: str = "") -> WorkflowGenerateErrorDict:
    """Build a structured error dict; ``node_id`` is included only when set."""
    out: WorkflowGenerateErrorDict = {"code": code, "detail": detail}
    if node_id:
        out["node_id"] = node_id
    return out


def _errors_to_str(errors: list[WorkflowGenerateErrorDict]) -> str:
    """Concatenate structured errors into the legacy single-string envelope."""
    return "; ".join(e["detail"] for e in errors)


def _empty_result() -> WorkflowGenerateResultDict:
    """Fresh skeleton with no graph and no metadata — used for early returns."""
    return {
        "graph": {"nodes": [], "edges": [], "viewport": _DEFAULT_VIEWPORT},
        "message": "",
        "app_name": "",
        "icon": "",
        "error": "",
        "errors": [],
    }


def _result_with_errors(
    base: WorkflowGenerateResultDict,
    errors: list[WorkflowGenerateErrorDict],
) -> WorkflowGenerateResultDict:
    """Attach a structured error list to ``base``, populating the legacy ``error`` string too."""
    base["errors"] = errors
    base["error"] = _errors_to_str(errors)
    return base


def _with_mode(result: WorkflowGenerateResultDict, mode: WorkflowGenerationMode) -> WorkflowGenerateResultDict:
    """Stamp the resolved concrete ``mode`` onto a result envelope.

    ``mode="auto"`` requests are resolved to a concrete mode from the planner
    output; echoing it back lets the frontend pick the right app type to
    create. It's present for explicit modes too so the response shape stays
    uniform.
    """
    result["mode"] = mode
    return result


def _fallback_mode(mode: WorkflowGenerationModeRequest) -> WorkflowGenerationMode:
    """Concrete mode for envelopes emitted before the planner resolved one.

    ``auto`` maps to the conversational default — the same never-fail fallback
    the old standalone classifier used — so ``result.mode`` never leaks the
    ``auto`` sentinel to the frontend.
    """
    return "advanced-chat" if mode == "auto" else mode


def _build_plan_event(
    *,
    plan: PlannerResultDict,
    plan_nodes: list[dict[str, Any]],
    start_inputs: list[dict[str, Any]],
    mode: WorkflowGenerationMode,
    assumptions: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Shape the ``plan`` event emitted before the (slower) builder runs.

    Node fields are pulled defensively: the planner schema only guarantees
    ``node_type`` is present, so ``label`` / ``purpose`` may be missing on a
    terse plan and default to empty strings.
    """
    return {
        "title": str(plan.get("title") or ""),
        "description": str(plan.get("description") or ""),
        "app_name": str(plan.get("app_name") or "").strip(),
        "icon": str(plan.get("icon") or "").strip(),
        "mode": mode,
        "assumptions": list(assumptions),
        "resource_requests": list(plan.get("resource_requests") or []),
        "nodes": [
            {
                "label": str(node.get("label") or ""),
                "node_type": str(node.get("node_type") or ""),
                "purpose": str(node.get("purpose") or ""),
            }
            for node in plan_nodes
        ],
        "start_inputs": start_inputs,
    }


def _selected_resource_catalogues(
    *,
    plan: PlannerResultDict,
    tool_entries: list[ToolCatalogueEntry],
    knowledge_entries: list[KnowledgeCatalogueEntry],
    fallback_tool_text: str,
    fallback_knowledge_text: str,
) -> tuple[str, str]:
    """Format only planner-selected resources for specialized node builders."""
    if not tool_entries and not knowledge_entries:
        return fallback_tool_text, fallback_knowledge_text
    tool_keys = {
        (str(item.get("provider_name") or ""), str(item.get("tool_name") or ""))
        for item in plan.get("resource_requests") or []
        if item.get("kind") == "tool"
    }
    dataset_ids = {
        str(item.get("dataset_id") or "")
        for item in plan.get("resource_requests") or []
        if item.get("kind") == "dataset"
    }
    selected_tools = [entry for entry in tool_entries if (entry["provider_name"], entry["tool_name"]) in tool_keys]
    selected_datasets = [entry for entry in knowledge_entries if entry["id"] in dataset_ids]
    return format_tool_catalogue(selected_tools), format_knowledge_catalogue(selected_datasets)


def _stage_error_to_envelope_code(exc: Exception) -> str:
    """Map a stage-typed exception to the result envelope's error code."""
    if isinstance(exc, StageJSONError):
        return WorkflowGenerateErrorCode.INVALID_JSON
    if isinstance(exc, PlannerRequirementInvalidError):
        return WorkflowGenerateErrorCode.PLANNER_REQUIREMENT_INVALID
    if isinstance(exc, PlannerPolicyDeniedError):
        return WorkflowGenerateErrorCode.PLANNER_POLICY_DENIED
    if isinstance(exc, StageSchemaError):
        return WorkflowGenerateErrorCode.INVALID_SCHEMA
    if isinstance(exc, StageTruncatedError):
        return WorkflowGenerateErrorCode.OUTPUT_TRUNCATED
    if isinstance(exc, PlannerNoProgressError):
        return WorkflowGenerateErrorCode.PLANNER_NO_PROGRESS
    if isinstance(exc, PlannerClarificationLimitError):
        return WorkflowGenerateErrorCode.PLANNER_CLARIFICATION_LIMIT
    if isinstance(exc, PlannerBudgetExhaustedError):
        return WorkflowGenerateErrorCode.PLANNER_BUDGET_EXHAUSTED
    if isinstance(exc, PlannerActionLimitError):
        return WorkflowGenerateErrorCode.PLANNER_ACTION_LIMIT
    if isinstance(exc, PlannerContextLimitError):
        return WorkflowGenerateErrorCode.PLANNER_CONTEXT_LIMIT
    return WorkflowGenerateErrorCode.MODEL_ERROR


class WorkflowGenerator:
    """
    Generates a Dify workflow graph from a natural-language instruction.

    Domain layer — receives an already-constructed model instance. Use
    ``services.workflow_generator_service.WorkflowGeneratorService`` to
    call this from controllers.
    """

    @classmethod
    def generate_workflow_graph(
        cls,
        *,
        model_instance,
        model_parameters: dict[str, Any],
        provider: str,
        model_name: str,
        model_mode: str,
        mode: WorkflowGenerationModeRequest,
        instruction: str,
        ideal_output: str = "",
        tool_catalogue_text: str = "",
        knowledge_catalogue_text: str = "",
        tool_catalogue_entries: list[ToolCatalogueEntry] | None = None,
        knowledge_catalogue_entries: list[KnowledgeCatalogueEntry] | None = None,
        tool_catalogue_available: bool = True,
        knowledge_catalogue_available: bool = True,
        planner_policy: PlannerPolicy = "assume_defaults",
        clarification_history: list[dict[str, Any]] | None = None,
        context_checkpoint: PlannerContextCheckpoint | None = None,
        installed_tools: set[tuple[str, str]] | None = None,
        installed_dataset_ids: set[str] | None = None,
        current_graph: dict[str, Any] | None = None,
    ) -> WorkflowGenerateResultDict:
        """
        Run planner → node builders → postprocess and return a graph payload.

        ``mode`` accepts the ``"auto"`` sentinel — the planner then chooses the
        concrete mode itself (echoed in its ``mode`` output field) so no extra
        classification call is needed; the resolution is stamped onto the
        result envelope.

        ``current_graph`` switches the pipeline from create mode to REFINE
        mode: the existing draft graph is summarized for the planner. Node
        builders receive only the config of the node they update, while configs
        marked ``keep`` are reused without an LLM call. ``None`` (the default)
        is plain create-from-scratch behaviour.

        ``tool_catalogue_text`` is the formatted list of installed tools for
        the calling tenant (see ``tool_catalogue.build_tool_catalogue`` /
        ``format_tool_catalogue``). It's injected into both the planner and
        builder prompts so the LLM can pick concrete ``provider/tool``
        identifiers instead of inventing names; node builders receive it
        only for tool nodes. An empty string skips the section entirely (useful
        for unit tests).

        ``knowledge_catalogue_text`` is the formatted list of tenant knowledge
        bases, injected into the planner and knowledge-retrieval builder
        prompts.

        ``installed_tools`` is the structural sibling — a set of
        ``(provider_name, tool_name)`` pairs the validator consults to reject
        tool nodes the planner / builder may have hallucinated. ``None``
        disables tool validation (used by unit tests and when the catalogue
        build itself failed; the service-layer fallback is already empty
        prompt text in that case).

        ``installed_dataset_ids`` is the corresponding structured set of
        valid dataset ids for knowledge-retrieval validation. ``None``
        disables dataset-id checking (same pattern as ``installed_tools``).

        Returns a dict with ``graph``, ``message``, ``error`` and ``errors``.
        On any failure ``graph`` is an empty skeleton (single start node),
        ``error`` is the concatenated human-readable diagnostic, and
        ``errors`` carries machine-readable codes the frontend maps to
        localised copy. Callers should toast the first localised entry from
        ``errors`` and keep the previous version visible.
        """

        # Consume the shared event generator and keep only the final result
        # envelope — ``generate_workflow_graph_stream`` shares the exact same
        # pipeline so the two stay behaviourally identical. The plan event is
        # ignored here.
        result: WorkflowGenerateResultDict | None = None
        for event_name, payload in cls._iter_generation_events(
            model_instance=model_instance,
            model_parameters=model_parameters,
            provider=provider,
            model_name=model_name,
            model_mode=model_mode,
            mode=mode,
            instruction=instruction,
            ideal_output=ideal_output,
            tool_catalogue_text=tool_catalogue_text,
            knowledge_catalogue_text=knowledge_catalogue_text,
            tool_catalogue_entries=tool_catalogue_entries,
            knowledge_catalogue_entries=knowledge_catalogue_entries,
            tool_catalogue_available=tool_catalogue_available,
            knowledge_catalogue_available=knowledge_catalogue_available,
            planner_policy=planner_policy,
            clarification_history=clarification_history,
            context_checkpoint=context_checkpoint,
            installed_tools=installed_tools,
            installed_dataset_ids=installed_dataset_ids,
            current_graph=current_graph,
        ):
            if event_name == "result":
                result = cast(WorkflowGenerateResultDict, payload)
        # The event generator always emits exactly one result envelope; this
        # fallback only guards against a future refactor that forgets to.
        if result is None:
            result = _with_mode(_empty_result(), _fallback_mode(mode))
        return result

    @classmethod
    def generate_workflow_graph_stream(
        cls,
        *,
        model_instance,
        model_parameters: dict[str, Any],
        provider: str,
        model_name: str,
        model_mode: str,
        mode: WorkflowGenerationModeRequest,
        instruction: str,
        ideal_output: str = "",
        tool_catalogue_text: str = "",
        knowledge_catalogue_text: str = "",
        tool_catalogue_entries: list[ToolCatalogueEntry] | None = None,
        knowledge_catalogue_entries: list[KnowledgeCatalogueEntry] | None = None,
        tool_catalogue_available: bool = True,
        knowledge_catalogue_available: bool = True,
        planner_policy: PlannerPolicy = "assume_defaults",
        clarification_history: list[dict[str, Any]] | None = None,
        context_checkpoint: PlannerContextCheckpoint | None = None,
        installed_tools: set[tuple[str, str]] | None = None,
        installed_dataset_ids: set[str] | None = None,
        current_graph: dict[str, Any] | None = None,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """
        Streaming sibling of ``generate_workflow_graph``.

        Yields a ``status`` event before planning and building, a ``plan`` event
        (title / description / app_name / icon / mode / high-level nodes /
        start_inputs) as soon as the planner returns, then a final ``result``
        event carrying the SAME envelope dict the non-streaming method returns
        (graph / message / app_name / icon / error / errors / mode, plus
        structural errors when any). On a planner / empty-plan / builder
        failure only the ``result`` event is emitted — no ``plan``.
        """
        yield from cls._iter_generation_events(
            model_instance=model_instance,
            model_parameters=model_parameters,
            provider=provider,
            model_name=model_name,
            model_mode=model_mode,
            mode=mode,
            instruction=instruction,
            ideal_output=ideal_output,
            tool_catalogue_text=tool_catalogue_text,
            knowledge_catalogue_text=knowledge_catalogue_text,
            tool_catalogue_entries=tool_catalogue_entries,
            knowledge_catalogue_entries=knowledge_catalogue_entries,
            tool_catalogue_available=tool_catalogue_available,
            knowledge_catalogue_available=knowledge_catalogue_available,
            planner_policy=planner_policy,
            clarification_history=clarification_history,
            context_checkpoint=context_checkpoint,
            installed_tools=installed_tools,
            installed_dataset_ids=installed_dataset_ids,
            current_graph=current_graph,
        )

    @classmethod
    def _iter_generation_events(
        cls,
        *,
        model_instance,
        model_parameters: dict[str, Any],
        provider: str,
        model_name: str,
        model_mode: str,
        mode: WorkflowGenerationModeRequest,
        instruction: str,
        ideal_output: str = "",
        tool_catalogue_text: str = "",
        knowledge_catalogue_text: str = "",
        tool_catalogue_entries: list[ToolCatalogueEntry] | None = None,
        knowledge_catalogue_entries: list[KnowledgeCatalogueEntry] | None = None,
        tool_catalogue_available: bool = True,
        knowledge_catalogue_available: bool = True,
        planner_policy: PlannerPolicy = "assume_defaults",
        clarification_history: list[dict[str, Any]] | None = None,
        context_checkpoint: PlannerContextCheckpoint | None = None,
        installed_tools: set[tuple[str, str]] | None = None,
        installed_dataset_ids: set[str] | None = None,
        current_graph: dict[str, Any] | None = None,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """
        Drive planner → node builders → postprocess and yield generation events.

        Shared core for both ``generate_workflow_graph`` (keeps only the final
        ``result``) and ``generate_workflow_graph_stream`` (streams every
        event). Emits ``status`` events before planning and building, at most
        one ``plan`` event — only once the planner produced a non-empty plan —
        followed by exactly one ``result`` event. On a planner / empty-plan /
        builder failure it emits only the ``result`` event carrying the error
        envelope. Every result envelope is stamped with the resolved concrete
        ``mode``.
        """

        # ── 1. PLANNER ────────────────────────────────────────────────────
        output_language = detect_output_language(instruction)
        llm_client = LLMJsonClient(model_instance=model_instance, model_parameters=model_parameters)
        tool_catalogue_entries = tool_catalogue_entries or []
        knowledge_catalogue_entries = knowledge_catalogue_entries or []
        yield (
            "status",
            {
                "stage": "planning",
                "message": localized_generator_message("planning", output_language),
            },
        )
        try:
            planner_outcome = yield from iter_plan(
                client=llm_client,
                request=PlannerInput(
                    mode=mode,
                    instruction=instruction,
                    ideal_output=ideal_output,
                    tool_catalogue_text=tool_catalogue_text,
                    knowledge_catalogue_text=knowledge_catalogue_text,
                    current_graph=current_graph,
                    policy=planner_policy,
                    tool_catalogue_entries=tool_catalogue_entries,
                    knowledge_catalogue_entries=knowledge_catalogue_entries,
                    tool_catalogue_available=tool_catalogue_available,
                    knowledge_catalogue_available=knowledge_catalogue_available,
                    clarification_history=clarification_history or [],
                    context_checkpoint=context_checkpoint,
                ),
            )
            plan_err = None
        except StageError as e:
            logger.warning("Workflow generator: %s", e)
            planner_outcome = None
            plan_err = _err(_stage_error_to_envelope_code(e), str(e))
            planner_error_checkpoint = e.context_checkpoint
        except Exception as e:
            logger.exception("Workflow generator: planner step failed")
            planner_outcome = None
            plan_err = _err(WorkflowGenerateErrorCode.MODEL_ERROR, f"Failed to plan workflow: {e}")
            planner_error_checkpoint = None
        if plan_err is not None:
            failed = _with_mode(_result_with_errors(_empty_result(), [plan_err]), _fallback_mode(mode))
            if planner_error_checkpoint is not None:
                failed["context_checkpoint"] = planner_error_checkpoint
            yield "result", cast(dict[str, Any], failed)
            return

        # The lambda return is non-None when no error fired — narrow it for type-checkers.
        planner_outcome = cast(
            PlannerPlanOutcome | PlannerClarificationOutcome | PlannerAssistantMessageOutcome,
            planner_outcome,
        )
        if isinstance(planner_outcome, PlannerClarificationOutcome):
            yield (
                "clarification",
                {
                    "clarification_id": planner_outcome.clarification_id,
                    "message": planner_outcome.message,
                    "questions": list(planner_outcome.questions),
                    "context_checkpoint": planner_outcome.context_checkpoint,
                },
            )
            return
        if isinstance(planner_outcome, PlannerAssistantMessageOutcome):
            yield (
                "assistant_message",
                {
                    "message": planner_outcome.message,
                    "context_checkpoint": planner_outcome.context_checkpoint,
                },
            )
            return
        plan = planner_outcome.plan
        # ``auto`` requests resolve here — the planner echoed its mode choice
        # (or we infer it from the plan's terminal node). Explicit modes pass
        # through unchanged. Everything downstream uses the concrete mode.
        resolved_mode = resolve_generation_mode(mode, plan)
        plan_nodes: list[dict[str, Any]] = cast(list[dict[str, Any]], plan.get("nodes", []))
        if not plan_nodes:
            empty_plan = _with_mode(
                _result_with_errors(
                    _empty_result(),
                    [_err(WorkflowGenerateErrorCode.EMPTY_PLAN, "Planner returned no nodes")],
                ),
                resolved_mode,
            )
            yield "result", cast(dict[str, Any], empty_plan)
            return

        plan_edges = [cast(dict[str, Any], edge) for edge in (plan.get("edges") or []) if isinstance(edge, dict)]

        # Planner-supplied user-input declarations. The builder uses these to
        # populate ``start.data.variables`` so downstream ``{#start.<var>#}``
        # references resolve at run time. Optional field — older prompts may
        # omit it, in which case the postprocess walker auto-fixes references.
        start_inputs: list[dict[str, Any]] = [
            cast(dict[str, Any], item)
            for item in (plan.get("start_inputs") or [])
            if isinstance(item, dict) and isinstance(item.get("variable"), str) and cast(str, item["variable"]).strip()
        ]

        # First event the stream sees: the high-level plan, before the slower
        # builder call. Non-streaming callers ignore it.
        plan_event = _build_plan_event(
                plan=plan,
                plan_nodes=plan_nodes,
                start_inputs=start_inputs,
                mode=resolved_mode,
                assumptions=planner_outcome.assumptions,
            )
        if planner_outcome.context_checkpoint is not None:
            plan_event["context_checkpoint"] = planner_outcome.context_checkpoint
        yield ("plan", plan_event)

        yield (
            "operation",
            {
                "stage": "planning",
                "action": "plan_ready",
                "count": len(plan_nodes),
                "message": localized_generator_message("plan_ready", output_language, count=len(plan_nodes)),
            },
        )

        yield (
            "status",
            {
                "stage": "building",
                "message": localized_generator_message("building", output_language),
            },
        )

        # ── 2. BUILDER ────────────────────────────────────────────────────
        builder_started_at = time.monotonic()
        thought_queue: queue.SimpleQueue[tuple[str, dict[str, Any]] | object] = queue.SimpleQueue()
        build_sentinel = object()
        build_holder: dict[str, Any] = {"graph": None, "error": None}

        selected_tool_catalogue_text, selected_knowledge_catalogue_text = _selected_resource_catalogues(
            plan=plan,
            tool_entries=tool_catalogue_entries,
            knowledge_entries=knowledge_catalogue_entries,
            fallback_tool_text=tool_catalogue_text,
            fallback_knowledge_text=knowledge_catalogue_text,
        )

        def build_graph() -> GraphDict:
            return build_node_graph(
                client=llm_client,
                request=BuilderInput(
                    provider=provider,
                    model_name=model_name,
                    model_mode=model_mode,
                    mode=resolved_mode,
                    instruction=instruction,
                    ideal_output=ideal_output,
                    plan_nodes=plan_nodes,
                    plan_edges=plan_edges,
                    tool_catalogue_text=selected_tool_catalogue_text,
                    knowledge_catalogue_text=selected_knowledge_catalogue_text,
                    start_inputs=start_inputs,
                    current_graph=current_graph,
                    output_language=output_language,
                ),
                emit=thought_queue.put,
            )

        def build_worker() -> None:
            graph, build_err = cls._run_stage(
                stage="Builder",
                failure_fallback_message="Failed to build workflow graph",
                run=build_graph,
            )
            build_holder["graph"] = graph
            build_holder["error"] = build_err
            thought_queue.put(build_sentinel)

        build_thread = threading.Thread(target=build_worker, name="workflow-node-build", daemon=True)
        build_thread.start()
        while True:
            item = thought_queue.get()
            if item is build_sentinel:
                break
            yield cast(tuple[str, dict[str, Any]], item)
        build_thread.join()
        graph = build_holder["graph"]
        build_err = build_holder["error"]
        logger.info(
            "Workflow generator: node builders completed nodes=%s elapsed_ms=%.1f",
            len(plan_nodes),
            (time.monotonic() - builder_started_at) * 1000,
        )
        if build_err is not None:
            yield (
                "result",
                cast(dict[str, Any], _with_mode(_result_with_errors(_empty_result(), [build_err]), resolved_mode)),
            )
            return
        graph = cast(GraphDict, graph)

        # ── 3. POSTPROC + VALIDATE ────────────────────────────────────────
        graph = postprocess_graph(graph=graph, mode=resolved_mode)

        # ``app_name`` / ``icon`` are planner display metadata; both default
        # to "" when the LLM omits them — the FE owns the fallback.
        result: WorkflowGenerateResultDict = {
            "graph": graph,
            "message": plan.get("description", ""),
            "app_name": str(plan.get("app_name") or "").strip(),
            "icon": str(plan.get("icon") or "").strip(),
            "error": "",
            "errors": [],
        }
        _with_mode(result, resolved_mode)

        # Final structural sanity check — fail closed if start/end shape is
        # wrong, container topology is broken, a tool was hallucinated, or a
        # variable reference points at a node that won't expose it. We still
        # return the partial graph so the caller can debug or salvage it.
        structural_errors = validate_graph(
            graph=graph,
            mode=resolved_mode,
            installed_tools=installed_tools,
            installed_dataset_ids=installed_dataset_ids,
        )
        if structural_errors:
            logger.warning("Workflow generator: structural validation failed: %s", structural_errors)
            yield "result", cast(dict[str, Any], _result_with_errors(result, structural_errors))
            return
        yield "result", cast(dict[str, Any], result)

    @classmethod
    def _run_stage(
        cls,
        *,
        stage: str,
        failure_fallback_message: str,
        run,
    ) -> tuple[Any, WorkflowGenerateErrorDict | None]:
        """
        Execute one pipeline stage and translate exceptions into a typed envelope entry.

        Returns ``(result, None)`` on success and ``(None, error)`` on failure.
        Stage-specific JSON / schema errors map to their dedicated codes; any
        other exception is logged with the stack trace and mapped to
        ``MODEL_ERROR`` (the LLM call itself blew up — provider auth, quota,
        network — caller usually wants this as a retry hint).
        """
        try:
            return run(), None
        except StageError as e:
            logger.warning("Workflow generator: %s", e)
            return None, _err(_stage_error_to_envelope_code(e), str(e))
        except Exception as e:
            logger.exception("Workflow generator: %s step failed", stage.lower())
            return None, _err(WorkflowGenerateErrorCode.MODEL_ERROR, f"{failure_fallback_message}: {e}")
