"""Execution tools: run the candidate or probe one node, then hand the results back to the Agent.

Execution is an observation. These tools prepare the candidate exactly like
``run_acceptance`` (validate, hydrate, layout), never record acceptance
Evidence and never complete the run; only ``finish`` does.

Consent is enforced here, not by the model. ``level=live`` on a graph with
external nodes runs in ``always_execute`` mode without consulting an older
decline, or when ``authorize_live_acceptance`` reserves the current revision
and graph hash in ``always_ask`` mode. An unapproved consent for the current
hash returns ``EXECUTION_CONSENT_DENIED`` only while the mode remains
``always_ask``. ``level=mock`` swaps external nodes for fixed-output code nodes
and always runs the engine in simulated mode.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import cast

from core.workflow.generator.acceptance.effects import external_node_ids
from core.workflow.generator.acceptance.evidence import AcceptanceMode, GraphExecutionTrace, canonical_graph_hash
from core.workflow.generator.acceptance.mocks import Fixtures, MockGraphError, build_mocked_graph
from core.workflow.generator.agent.tools.tool_context import GraphExecuteFn, ToolContext
from core.workflow.generator.agent.tools.tool_lifecycle import prepare_candidate_for_execution
from core.workflow.generator.agent.tools.tool_results import error, ok
from core.workflow.generator.agent.types import ToolCall, ToolResult
from core.workflow.generator.graph.types import MinimalGraphDict

logger = logging.getLogger(__name__)

_LEVELS = ("live", "mock")
_MAX_VALUE_CHARS = 2000
_MAX_NODE_OUTPUT_CHARS = 16000


def run_workflow(call: ToolCall, context: ToolContext) -> ToolResult:
    execute_graph = context.env.execute_graph
    if execute_graph is None:
        return error(call, "CAPABILITY_UNAVAILABLE", "Workflow execution is not available")
    parsed = _parse_level_and_inputs(call)
    if isinstance(parsed, str):
        return error(call, "INVALID_ARGUMENT", parsed)
    level, start_inputs = parsed
    mocks = call["arguments"].get("mocks") or {}
    if not _is_fixtures(mocks):
        return error(call, "INVALID_ARGUMENT", "mocks must map node ids to output objects")
    if level == "live" and mocks:
        return error(call, "INVALID_ARGUMENT", "mocks are only accepted with level=mock")
    rejection, changed = prepare_candidate_for_execution(call, context, purpose="execution")
    if rejection is not None:
        return rejection
    graph = context.state.graph
    graph_hash = canonical_graph_hash(graph)
    context.state.graph_hash = graph_hash
    has_external = bool(external_node_ids(graph))
    run_graph: MinimalGraphDict = graph
    mocked: Fixtures = {}
    engine_mode: AcceptanceMode = "simulated"
    if level == "mock":
        try:
            run_graph, mocked = build_mocked_graph(graph, cast(Mapping[str, Mapping[str, object]], mocks))
        except MockGraphError as exc:
            return error(call, exc.code, exc.detail)
    elif has_external:
        denied = _live_gate(call, context, graph_hash)
        if denied is not None:
            return denied
        engine_mode = "live"
    trace = _execute(call, execute_graph, run_graph, engine_mode, start_inputs)
    if not isinstance(trace, list):
        return trace
    node_outputs = _node_outputs(trace)
    context.state.last_node_outputs = {**node_outputs, **mocked}
    clipped, truncated = _clip_node_outputs({key: value for key, value in node_outputs.items() if key not in mocked})
    content: dict[str, object] = {
        "passed": not trace,
        "verification_level": ("live" if level == "live" else "mock") if has_external else "local_only",
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


def _parse_level_and_inputs(call: ToolCall) -> tuple[str, dict[str, object]] | str:
    level = call["arguments"].get("level", "mock")
    if level not in _LEVELS:
        return "level must be live or mock"
    start_inputs = call["arguments"].get("start_inputs") or {}
    if not isinstance(start_inputs, dict):
        return "start_inputs must be an object keyed by start variable"
    return str(level), dict(start_inputs)


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
            "The user did not approve live execution for this candidate; test with level=mock",
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
