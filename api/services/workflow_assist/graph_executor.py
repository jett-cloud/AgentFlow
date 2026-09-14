"""In-memory GraphEngine adapter for workflow-assist acceptance.

Runs a candidate graph through GraphEngine with an InMemoryChannel. Does not
attach WorkflowPersistenceLayer, so a passing or failing attempt never writes
WorkflowRun rows. Callers must already be inside a Flask app context (the
Celery path uses preserve_flask_contexts). Metered nodes still need the
tenant's configured provider credentials.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from typing import Any
from uuid import uuid4

from configs import dify_config
from context import capture_current_context
from core.app.entities.app_invoke_entities import InvokeFrom, UserFrom, build_dify_run_context
from core.app.workflow.layers.llm_quota import LLMQuotaLayer
from core.workflow.generator.acceptance.evidence import AcceptanceMode, FailedNodeTrace, GraphExecutionTrace
from core.workflow.generator.graph.types import MinimalGraphDict
from core.workflow.node_factory import DifyGraphInitContext, DifyNodeFactory, get_default_root_node_id
from core.workflow.runtime.variables.system_variables import build_bootstrap_variables, build_system_variables
from core.workflow.runtime.variables.variable_pool_initializer import add_node_inputs_to_pool, add_variables_to_pool
from core.workflow.runtime.workflow_entry import iter_dify_graph_engine_events
from graphon.graph import Graph
from graphon.graph_engine import GraphEngine, GraphEngineConfig
from graphon.graph_engine.command_channels import InMemoryChannel
from graphon.graph_engine.layers import ExecutionLimitsLayer
from graphon.graph_events import (
    GraphEngineEvent,
    GraphRunAbortedEvent,
    GraphRunFailedEvent,
    GraphRunSucceededEvent,
    NodeRunFailedEvent,
    NodeRunStartedEvent,
    NodeRunSucceededEvent,
)
from graphon.runtime import GraphRuntimeState, VariablePool
from services.workflow_assist.acceptance_bindings import AcceptanceSessionStore, CandidateBindingResolver
from services.workflow_assist.effect_policy import execution_policy_errors

logger = logging.getLogger(__name__)

GraphExecutor = Callable[[MinimalGraphDict, AcceptanceMode, Mapping[str, object]], list[FailedNodeTrace]]

_FILE_VARIABLE_TYPES = frozenset({"file", "file-list"})
_TYPE_PLACEHOLDERS: dict[str, Any] = {
    "number": 0,
    "integer": 0,
    "boolean": False,
    "object": {},
    "array": [],
    "array[string]": [],
    "array[number]": [],
    "array[object]": [],
    "array[boolean]": [],
    "array[file]": [],
}


def build_acceptance_graph_executor(
    *,
    tenant_id: str,
    app_id: str,
    user_id: str,
    workflow_id: str = "",
    live_authorized: bool = False,
) -> GraphExecutor:
    """Bind tenant identity into a GraphExecutor for WorkflowAssistAcceptanceRunner."""

    def execute(
        graph: MinimalGraphDict,
        mode: AcceptanceMode,
        start_inputs: Mapping[str, object],
    ) -> list[FailedNodeTrace]:
        return execute_acceptance_graph(
            graph,
            tenant_id=tenant_id,
            app_id=app_id,
            user_id=user_id,
            workflow_id=workflow_id,
            mode=mode,
            start_inputs=start_inputs,
            live_authorized=live_authorized,
        )

    return execute


def execute_acceptance_graph(
    graph: MinimalGraphDict,
    *,
    tenant_id: str,
    app_id: str,
    user_id: str,
    mode: AcceptanceMode,
    workflow_id: str = "",
    start_inputs: Mapping[str, object] | None = None,
    live_authorized: bool = False,
) -> list[FailedNodeTrace]:
    """Run ``graph`` once and return node/graph failures. Empty means the run succeeded."""
    policy_errors = execution_policy_errors(graph, mode, live_authorized=live_authorized)
    if policy_errors:
        return policy_errors
    try:
        engine = _build_acceptance_engine(
            graph,
            tenant_id=tenant_id,
            app_id=app_id,
            user_id=user_id,
            workflow_id=workflow_id,
            start_inputs=start_inputs,
            live_authorized=live_authorized,
        )
    except Exception as exc:
        logger.exception("Workflow assist acceptance: failed to build GraphEngine")
        category = _failure_category(str(exc))
        return [{"id": "graph", "type": "graph", "error": _safe_error(category), "category": category}]
    try:
        events = iter_dify_graph_engine_events(engine)
        return failed_traces_from_events(events)
    except Exception as exc:
        logger.exception("Workflow assist acceptance: GraphEngine run failed")
        category = _failure_category(str(exc))
        return [{"id": "graph", "type": "graph", "error": _safe_error(category), "category": category}]


def failed_traces_from_events(events: Iterable[GraphEngineEvent]) -> GraphExecutionTrace:
    """Map engine failure and abort events to the model-facing trace list."""
    traces = GraphExecutionTrace()
    graph_error: str | None = None
    graph_error_category = "runtime"
    succeeded = False
    for event in events:
        if isinstance(event, (NodeRunStartedEvent, NodeRunSucceededEvent, NodeRunFailedEvent)):
            traces.executed_node_ids.add(str(event.node_id))
        if isinstance(event, GraphRunSucceededEvent):
            succeeded = True
            traces.graph_outputs = _plain_outputs(event.outputs)
        if isinstance(event, NodeRunSucceededEvent):
            traces.node_outputs[str(event.node_id)] = _plain_outputs(event.node_run_result.outputs)
        if isinstance(event, NodeRunFailedEvent):
            category = _failure_category(str(event.error or "node failed"))
            traces.append(
                {
                    "id": str(event.node_id),
                    "type": _node_type_name(event.node_type),
                    "error": _safe_error(category),
                    "category": category,
                }
            )
        elif isinstance(event, GraphRunFailedEvent):
            graph_error_category = _failure_category(str(event.error or "graph failed"))
            graph_error = _safe_error(graph_error_category)
        elif isinstance(event, GraphRunAbortedEvent):
            graph_error = "Acceptance execution aborted"
    if not traces and graph_error:
        traces.append({"id": "graph", "type": "graph", "error": graph_error, "category": graph_error_category})
    if not traces and not succeeded:
        traces.append(
            {"id": "graph", "type": "graph", "error": "Execution ended without graph success (paused or incomplete)"}
        )
    return traces


def _plain_outputs(outputs: object) -> dict[str, object]:
    if not isinstance(outputs, Mapping):
        return {}
    return {str(key): value for key, value in outputs.items()}


def _failure_category(error: str) -> str:
    normalized = error.casefold()
    if any(
        token in normalized for token in ("credential", "api key", "unauthorized", "authorization", "authentication")
    ):
        return "credential"
    if any(token in normalized for token in ("quota", "rate limit", "too many requests")):
        return "quota"
    if any(token in normalized for token in ("network", "connection", "dns", "timed out")):
        return "network"
    return "runtime"


def _safe_error(category: str) -> str:
    """Expose a stable repair category, never provider/user-controlled error text."""
    return f"Acceptance execution failed ({category})"


def _build_acceptance_engine(
    graph: MinimalGraphDict,
    *,
    tenant_id: str,
    app_id: str,
    user_id: str,
    workflow_id: str = "",
    start_inputs: Mapping[str, object] | None = None,
    live_authorized: bool = False,
) -> GraphEngine:
    graph_config = _graph_config(graph)
    resolved_workflow_id = workflow_id.strip() or f"assist-accept-{uuid4().hex[:12]}"
    resolver = CandidateBindingResolver(
        graph=graph,
        tenant_id=tenant_id,
        app_id=app_id,
        workflow_id=resolved_workflow_id,
    )
    session_store = AcceptanceSessionStore()
    run_context = build_dify_run_context(
        tenant_id=tenant_id,
        app_id=app_id,
        user_id=user_id,
        user_from=UserFrom.ACCOUNT,
        invoke_from=InvokeFrom.DEBUGGER,
    )
    graph_init_context = DifyGraphInitContext(
        workflow_id=resolved_workflow_id,
        graph_config=graph_config,
        run_context=run_context,
        call_depth=0,
    )
    variable_pool = VariablePool()
    add_variables_to_pool(
        variable_pool,
        build_bootstrap_variables(
            system_variables=build_system_variables(
                user_id=user_id,
                app_id=app_id,
                workflow_id=resolved_workflow_id,
                files=[],
                query="",
            ),
        ),
    )
    root_node_id = get_default_root_node_id(graph_config)
    resolved_start_inputs = _placeholder_start_inputs(graph_config)
    if start_inputs is not None:
        resolved_start_inputs.update(start_inputs)
    add_node_inputs_to_pool(
        variable_pool,
        node_id=root_node_id,
        inputs=resolved_start_inputs,
    )
    graph_runtime_state = GraphRuntimeState(
        variable_pool=variable_pool,
        start_at=time.perf_counter(),
        execution_context=capture_current_context(),
    )
    node_factory = DifyNodeFactory.from_graph_init_context(
        graph_init_context=graph_init_context,
        graph_runtime_state=graph_runtime_state,
        agent_binding_resolver=resolver,
        agent_session_store=session_store,
    )
    engine_graph = Graph.init(
        graph_config=graph_config,
        node_factory=node_factory,
        root_node_id=root_node_id,
    )
    engine = GraphEngine(
        workflow_id=resolved_workflow_id,
        graph=engine_graph,
        graph_runtime_state=graph_runtime_state,
        command_channel=InMemoryChannel(),
        config=GraphEngineConfig(
            min_workers=dify_config.GRAPH_ENGINE_MIN_WORKERS,
            max_workers=dify_config.GRAPH_ENGINE_MAX_WORKERS,
            scale_up_threshold=dify_config.GRAPH_ENGINE_SCALE_UP_THRESHOLD,
            scale_down_idle_time=dify_config.GRAPH_ENGINE_SCALE_DOWN_IDLE_TIME,
        ),
    )
    engine.layer(
        ExecutionLimitsLayer(
            max_steps=min(dify_config.WORKFLOW_MAX_EXECUTION_STEPS, 32)
            if live_authorized
            else dify_config.WORKFLOW_MAX_EXECUTION_STEPS,
            max_time=min(dify_config.WORKFLOW_MAX_EXECUTION_TIME, 60)
            if live_authorized
            else dify_config.WORKFLOW_MAX_EXECUTION_TIME,
        )
    )
    engine.layer(LLMQuotaLayer(tenant_id=tenant_id))
    return engine


def _graph_config(graph: MinimalGraphDict) -> dict[str, Any]:
    nodes = deepcopy(list(graph.get("nodes") or []))
    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.setdefault("data", {})
        if isinstance(data, dict) and data.get("type") == "end":
            data.setdefault("outputs", [])
    return {
        "nodes": nodes,
        "edges": deepcopy(list(graph.get("edges") or [])),
    }


def _placeholder_start_inputs(graph_config: Mapping[str, Any]) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    nodes = graph_config.get("nodes")
    if not isinstance(nodes, list):
        return inputs
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        data = node.get("data")
        if not isinstance(data, Mapping) or data.get("type") != "start":
            continue
        variables = data.get("variables")
        if not isinstance(variables, list):
            continue
        for variable in variables:
            if not isinstance(variable, Mapping):
                continue
            name = variable.get("variable")
            if not isinstance(name, str) or not name:
                continue
            placeholder = _placeholder_for_type(str(variable.get("type") or "string"))
            if placeholder is not None:
                inputs[name] = placeholder
    return inputs


def _placeholder_for_type(value_type: str) -> Any | None:
    if value_type in _FILE_VARIABLE_TYPES:
        return None
    if value_type in _TYPE_PLACEHOLDERS:
        return _TYPE_PLACEHOLDERS[value_type]
    return "acceptance"


def _node_type_name(node_type: object) -> str:
    if isinstance(node_type, str) and node_type:
        return node_type
    value = getattr(node_type, "value", None)
    if isinstance(value, str) and value:
        return value
    return str(node_type)
