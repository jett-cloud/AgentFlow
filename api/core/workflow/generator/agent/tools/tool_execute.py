"""Execution tools: run the candidate or probe one node, then hand the results back to the Agent.

Execution is an observation. These tools prepare the candidate exactly like
``run_acceptance`` (validate, hydrate, layout), never record acceptance
Evidence and never complete the run; only ``finish`` does.

Consent is enforced here, not by the model. ``run_workflow`` selects its own
strategy: local-only graphs run simulated, ``always_execute`` or a one-shot
grant runs external nodes live, and a decline for the current graph falls back
to a simulated mock graph. ``run_node`` keeps an explicit level because an
external target cannot be meaningfully tested by echoing its own fixture.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Literal, cast

from core.workflow.generator.acceptance.effects import classify_node_effect, external_node_ids
from core.workflow.generator.acceptance.evidence import AcceptanceMode, GraphExecutionTrace, canonical_graph_hash
from core.workflow.generator.acceptance.mocks import (
    Fixtures,
    MockGraphError,
    build_mocked_graph,
    build_node_probe_graph,
    describe_mock_target,
)
from core.workflow.generator.agent.tools.tool_context import (
    GraphExecuteFn,
    ToolContext,
    WorkflowExecutionRecord,
    WorkflowVerificationLevel,
)
from core.workflow.generator.agent.tools.tool_lifecycle import prepare_candidate_for_execution
from core.workflow.generator.agent.tools.tool_results import error, ok, require_str
from core.workflow.generator.agent.types import ToolCall, ToolResult
from core.workflow.generator.graph.graph_postprocessor import postprocess_graph
from core.workflow.generator.graph.types import MinimalGraphDict
from core.workflow.generator.types import GraphDict

logger = logging.getLogger(__name__)

_LEVELS = ("live", "mock")
_WorkflowExecutionStrategy = Literal["local_only", "live", "mock", "requires_consent"]
_MAX_VALUE_CHARS = 2000
_MAX_NODE_OUTPUT_CHARS = 16000


def run_workflow(call: ToolCall, context: ToolContext) -> ToolResult:
    execute_graph = context.env.execute_graph
    if execute_graph is None:
        return error(call, "CAPABILITY_UNAVAILABLE", "Workflow execution is not available")
    if "level" in call["arguments"]:
        return error(call, "INVALID_ARGUMENT", "run_workflow execution strategy is selected by the system")
    start_inputs = _parse_start_inputs(call)
    if isinstance(start_inputs, str):
        return error(call, "INVALID_ARGUMENT", start_inputs)
    mocks = call["arguments"].get("mocks") or {}
    if not _is_fixtures(mocks):
        return error(call, "INVALID_ARGUMENT", "mocks must map node ids to output objects")
    rejection, changed = prepare_candidate_for_execution(call, context, purpose="execution")
    if rejection is not None:
        return rejection
    graph = context.state.graph
    graph_hash = canonical_graph_hash(graph)
    context.state.graph_hash = graph_hash
    has_external = bool(external_node_ids(graph))
    strategy = _resolve_workflow_execution_strategy(context, graph_hash, has_external)
    if strategy == "requires_consent":
        return error(
            call,
            "LIVE_RUN_REQUIRES_CONSENT",
            "Live execution requires ask_user consent with question id live_run_consent for the current candidate",
        )
    run_graph: MinimalGraphDict = graph
    mocked: Fixtures = {}
    engine_mode: AcceptanceMode = "simulated"
    if strategy == "mock":
        try:
            run_graph, mocked = build_mocked_graph(graph, cast(Mapping[str, Mapping[str, object]], mocks))
        except MockGraphError as exc:
            return error(call, exc.code, exc.detail)
    elif strategy == "live":
        engine_mode = "live"
    trace = _execute(call, execute_graph, run_graph, engine_mode, start_inputs)
    if not isinstance(trace, list):
        return trace
    node_outputs = _node_outputs(trace)
    context.state.last_node_outputs = {**node_outputs, **mocked}
    context.state.last_workflow_execution = WorkflowExecutionRecord(
        revision=context.state.candidate_revision,
        graph_hash=graph_hash,
        passed=not trace,
        verification_level=cast(WorkflowVerificationLevel, strategy),
    )
    clipped, truncated = _clip_node_outputs({key: value for key, value in node_outputs.items() if key not in mocked})
    content: dict[str, object] = {
        "passed": not trace,
        "verification_level": strategy,
        "revision": context.state.candidate_revision,
        "graph_hash": graph_hash,
        "failed_nodes": list(trace),
        "executed_node_ids": sorted(getattr(trace, "executed_node_ids", set())),
        "graph_outputs": _clip_mapping(getattr(trace, "graph_outputs", {})),
        "node_outputs": clipped,
        "node_outputs_truncated": truncated,
        "mocked_outputs": _clip_node_outputs(mocked)[0],
    }
    return ok(call, changed=changed, content=content)


def run_node(call: ToolCall, context: ToolContext) -> ToolResult:
    execute_graph = context.env.execute_graph
    if execute_graph is None:
        return error(call, "CAPABILITY_UNAVAILABLE", "Workflow execution is not available")
    node_id = require_str(call["arguments"], "node_id")
    if node_id is None:
        return error(call, "INVALID_ARGUMENT", "node_id is required")
    parsed = _parse_level_and_inputs(call)
    if isinstance(parsed, str):
        return error(call, "INVALID_ARGUMENT", parsed)
    level, start_inputs = parsed
    upstream = call["arguments"].get("upstream_outputs") or {}
    if not _is_fixtures(upstream):
        return error(call, "INVALID_ARGUMENT", "upstream_outputs must map upstream node ids to output objects")
    rejection, changed = prepare_candidate_for_execution(call, context, purpose="execution")
    if rejection is not None:
        return rejection
    graph = context.state.graph
    try:
        probe, applied = build_node_probe_graph(
            graph,
            node_id,
            upstream_outputs=cast(Mapping[str, Mapping[str, object]], upstream),
            observed_outputs=context.state.last_node_outputs,
        )
    except MockGraphError as exc:
        return error(call, exc.code, exc.detail)
    target = next(node for node in graph["nodes"] if node["id"] == node_id)
    external = classify_node_effect(target) != "local_execute"
    graph_hash = canonical_graph_hash(graph)
    context.state.graph_hash = graph_hash
    engine_mode: AcceptanceMode = "simulated"
    if external:
        if level == "mock":
            return error(
                call,
                "INVALID_ARGUMENT",
                f"{node_id} calls external providers; level=mock would only echo a fixture. "
                "Use level=live, or run_workflow to let the system test its consumers",
            )
        denied = _live_gate(call, context, graph_hash)
        if denied is not None:
            return denied
        engine_mode = "live"
    try:
        prepared_probe = cast(
            MinimalGraphDict,
            postprocess_graph(
                graph=cast(GraphDict, probe),
                mode=context.env.mode,
                tool_entries=context.env.tool_entries if context.env.tools_available else None,
            ),
        )
    except Exception:
        logger.exception("Workflow agent: probe graph preparation failed")
        return error(call, "CAPABILITY_UNAVAILABLE", "Probe graph preparation failed")
    trace = _execute(call, execute_graph, prepared_probe, engine_mode, start_inputs)
    if not isinstance(trace, list):
        return trace
    node_outputs = _node_outputs(trace)
    if node_id in node_outputs:
        context.state.last_node_outputs[node_id] = node_outputs[node_id]
    content: dict[str, object] = {
        "passed": not trace,
        "verification_level": "live" if external else "local_only",
        "node_id": node_id,
        "revision": context.state.candidate_revision,
        "graph_hash": graph_hash,
        "outputs": _clip_mapping(node_outputs.get(node_id, {})),
        "failed_nodes": list(trace),
        "upstream_outputs": _clip_node_outputs(applied)[0],
    }
    return ok(call, changed=changed, content=content)


def inspect_mock_targets(call: ToolCall, context: ToolContext) -> ToolResult:
    node_id = call["arguments"].get("node_id")
    if node_id is not None and (not isinstance(node_id, str) or not node_id):
        return error(call, "INVALID_ARGUMENT", "node_id must be a non-empty string")
    graph = context.state.graph
    target_ids = [node_id] if node_id else external_node_ids(graph)
    try:
        targets = [describe_mock_target(graph, target_id) for target_id in target_ids]
    except MockGraphError as exc:
        return error(call, exc.code, exc.detail)
    return ok(call, changed=False, content={"targets": targets})


def _parse_level_and_inputs(call: ToolCall) -> tuple[str, dict[str, object]] | str:
    level = call["arguments"].get("level", "mock")
    if level not in _LEVELS:
        return "level must be live or mock"
    start_inputs = call["arguments"].get("start_inputs") or {}
    if not isinstance(start_inputs, dict):
        return "start_inputs must be an object keyed by start variable"
    return str(level), dict(start_inputs)


def _parse_start_inputs(call: ToolCall) -> dict[str, object] | str:
    start_inputs = call["arguments"].get("start_inputs") or {}
    if not isinstance(start_inputs, dict):
        return "start_inputs must be an object keyed by start variable"
    return dict(start_inputs)


def _resolve_workflow_execution_strategy(
    context: ToolContext, graph_hash: str, has_external: bool
) -> _WorkflowExecutionStrategy:
    if not has_external:
        return "local_only"
    if context.env.execution_consent_mode == "always_execute":
        return "live"
    if context.env.live_consent_declined_hash == graph_hash:
        return "mock"
    authorize = context.env.authorize_live_acceptance
    if authorize is not None and authorize(context.state.candidate_revision, graph_hash):
        return "live"
    return "requires_consent"


def _is_fixtures(value: object) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, dict) for key, item in value.items()
    )


def _live_gate(call: ToolCall, context: ToolContext, graph_hash: str) -> ToolResult | None:
    if context.env.execution_consent_mode == "always_execute":
        return None
    if context.env.live_consent_declined_hash == graph_hash:
        return error(
            call,
            "EXECUTION_CONSENT_DENIED",
            "The user did not approve live execution for this candidate; use run_workflow for automatic fallback",
        )
    authorize = context.env.authorize_live_acceptance
    if authorize is None or not authorize(context.state.candidate_revision, graph_hash):
        return error(
            call,
            "LIVE_RUN_REQUIRES_CONSENT",
            "Live execution requires ask_user consent with question id live_run_consent for the current candidate",
        )
    return None


def _execute(
    call: ToolCall,
    execute_graph: GraphExecuteFn,
    graph: MinimalGraphDict,
    mode: AcceptanceMode,
    start_inputs: Mapping[str, object],
) -> GraphExecutionTrace | ToolResult:
    try:
        return execute_graph(graph, mode, start_inputs)
    except Exception:
        logger.exception("Workflow agent: %s engine run failed", call["name"])
        return error(call, "CAPABILITY_UNAVAILABLE", "Workflow execution failed to start")


def _node_outputs(trace: GraphExecutionTrace) -> dict[str, dict[str, object]]:
    outputs = getattr(trace, "node_outputs", None)
    if not isinstance(outputs, Mapping):
        return {}
    return {str(node_id): dict(values) for node_id, values in outputs.items() if isinstance(values, Mapping)}


def _clip_value(value: object) -> object:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= _MAX_VALUE_CHARS:
        return value
    return {"truncated": True, "preview": text[:_MAX_VALUE_CHARS]}


def _clip_mapping(values: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _clip_value(value) for key, value in values.items()}


def _clip_node_outputs(
    outputs: Mapping[str, Mapping[str, object]],
) -> tuple[dict[str, dict[str, object]], bool]:
    clipped: dict[str, dict[str, object]] = {}
    used = 0
    for node_id, values in outputs.items():
        item = _clip_mapping(values)
        used += len(json.dumps(item, ensure_ascii=False, default=str))
        if used > _MAX_NODE_OUTPUT_CHARS:
            return clipped, True
        clipped[node_id] = item
    return clipped, False
