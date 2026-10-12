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
from dataclasses import dataclass
from itertools import product
from typing import Any
from uuid import uuid4

from configs import dify_config
from context import capture_current_context
from core.app.entities.app_invoke_entities import InvokeFrom, UserFrom, build_dify_run_context
from core.app.workflow.layers.llm_quota import LLMQuotaLayer
from core.workflow.generator.acceptance.evidence import AcceptanceMode, FailedNodeTrace, GraphExecutionTrace
from core.workflow.generator.acceptance.mocks import MockGraphError, build_simulated_graph_scenarios
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
    GraphRunPausedEvent,
    GraphRunSucceededEvent,
    NodeRunFailedEvent,
    NodeRunStartedEvent,
    NodeRunSucceededEvent,
)
from graphon.runtime import GraphRuntimeState, VariablePool
from graphon.workflow_type_encoder import WorkflowRuntimeTypeConverter
from services.workflow_assist.acceptance_bindings import AcceptanceSessionStore, CandidateBindingResolver
from services.workflow_assist.acceptance_human_input import (
    AcceptanceHumanInputFormRepository,
    UnsupportedHumanInputFixtureError,
)
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


_MAX_SCENARIO_RUNS = 12
_MAX_HUMAN_INPUT_DEPTH = 5


@dataclass
class _PendingScenarioRun:
    runtime_snapshot: str | None
    form_repository: AcceptanceHumanInputFormRepository
    resume_depth: int
    selections: list[dict[str, str]]
    executed_node_ids: set[str]
    node_outputs: dict[str, dict[str, object]]


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
) -> GraphExecutionTrace:
    """Run bounded verification scenarios, including Human Input pause/resume branches."""
    has_human_input = any(
        isinstance(node, dict)
        and isinstance(node.get("data"), dict)
        and node["data"].get("type") == "human-input"
        for node in graph.get("nodes") or []
    )
    if mode == "live" and has_human_input:
        return _single_failure_trace(
            "graph",
            "human-input",
            "Human Input action coverage requires simulated mode",
            "policy",
        )
    try:
        if mode == "simulated":
            scenarios = build_simulated_graph_scenarios(graph, {})
        else:
            scenarios = [
                {
                    "scenario_id": "live",
                    "graph": graph,
                    "fixtures": {},
                    "selections": [],
                }
            ]
    except MockGraphError as exc:
        return _single_failure_trace("graph", "graph", exc.detail, "policy")

    combined = GraphExecutionTrace()
    graph_outputs: list[dict[str, object]] = []
    for scenario in scenarios:
        scenario_graph = scenario["graph"]
        policy_errors = execution_policy_errors(
            scenario_graph,
            mode,
            live_authorized=live_authorized,
            allow_human_input_pause=True,
        )
        if policy_errors:
            trace = GraphExecutionTrace()
            trace.extend(policy_errors)
        else:
            trace = _execute_human_input_scenarios(
                scenario_graph,
                tenant_id=tenant_id,
                app_id=app_id,
                user_id=user_id,
                workflow_id=workflow_id,
                start_inputs=start_inputs,
                live_authorized=live_authorized,
            )
        combined.extend(trace)
        combined.executed_node_ids.update(trace.executed_node_ids)
        combined.node_outputs.update(trace.node_outputs)
        if trace.graph_outputs:
            graph_outputs.append(dict(trace.graph_outputs))
        if trace.scenario_results:
            for result in trace.scenario_results:
                combined.scenario_results.append(
                    {
                        **result,
                        "scenario_id": f"{scenario['scenario_id']}:{result['scenario_id']}",
                        "selections": [*scenario["selections"], *result["selections"]],
                    }
                )
        else:
            combined.scenario_results.append(
                {
                    "scenario_id": scenario["scenario_id"],
                    "selections": list(scenario["selections"]),
                    "passed": not trace,
                    "executed_node_ids": sorted(trace.executed_node_ids),
                    "node_outputs": dict(trace.node_outputs),
                    "graph_outputs": dict(trace.graph_outputs),
                    "failed_nodes": list(trace),
                }
            )
    if len(graph_outputs) == 1:
        combined.graph_outputs = graph_outputs[0]
    elif graph_outputs:
        combined.graph_outputs = {"scenarios": graph_outputs}
    return combined


def _execute_human_input_scenarios(
    graph: MinimalGraphDict,
    *,
    tenant_id: str,
    app_id: str,
    user_id: str,
    workflow_id: str,
    start_inputs: Mapping[str, object] | None,
    live_authorized: bool,
) -> GraphExecutionTrace:
    combined = GraphExecutionTrace()
    terminal_outputs: list[dict[str, object]] = []
    resolved_workflow_id = workflow_id.strip() or f"assist-accept-{uuid4().hex[:12]}"
    workflow_execution_id = f"assist-run-{uuid4().hex}"
    pending = [
        _PendingScenarioRun(
            runtime_snapshot=None,
            form_repository=AcceptanceHumanInputFormRepository(),
            resume_depth=0,
            selections=[],
            executed_node_ids=set(),
            node_outputs={},
        )
    ]
    completed_runs = 0
    while pending:
        current = pending.pop(0)
        if completed_runs + len(pending) >= _MAX_SCENARIO_RUNS:
            combined.extend(
                _single_failure_trace(
                    "graph",
                    "human-input",
                    f"Human Input scenarios exceed the verification limit of {_MAX_SCENARIO_RUNS}",
                    "policy",
                )
            )
            break
        try:
            engine, runtime_state = _build_acceptance_engine(
                graph,
                tenant_id=tenant_id,
                app_id=app_id,
                user_id=user_id,
                workflow_id=resolved_workflow_id,
                workflow_execution_id=workflow_execution_id,
                start_inputs=start_inputs,
                live_authorized=live_authorized,
                runtime_snapshot=current.runtime_snapshot,
                human_input_form_repository=current.form_repository,
            )
            events = list(iter_dify_graph_engine_events(engine))
        except Exception as exc:
            logger.exception("Workflow assist acceptance: GraphEngine scenario failed")
            category = _failure_category(str(exc))
            failure = _single_failure_trace("graph", "graph", _safe_error(category), category)
            combined.extend(failure)
            combined.scenario_results.append(
                {
                    "scenario_id": f"path-{completed_runs + 1}",
                    "selections": current.selections,
                    "passed": False,
                    "executed_node_ids": sorted(current.executed_node_ids),
                    "node_outputs": dict(current.node_outputs),
                    "graph_outputs": {},
                    "failed_nodes": list(failure),
                }
            )
            completed_runs += 1
            continue

        trace = failed_traces_from_events(events, allow_pause=True)
        executed = current.executed_node_ids | trace.executed_node_ids
        node_outputs = {**current.node_outputs, **trace.node_outputs}
        combined.executed_node_ids.update(executed)
        combined.node_outputs.update(node_outputs)
        paused = next((event for event in reversed(events) if isinstance(event, GraphRunPausedEvent)), None)
        if trace or paused is None:
            combined.extend(trace)
            if trace.graph_outputs:
                terminal_outputs.append(dict(trace.graph_outputs))
            combined.scenario_results.append(
                {
                    "scenario_id": f"path-{completed_runs + 1}",
                    "selections": current.selections,
                    "passed": not trace,
                    "executed_node_ids": sorted(executed),
                    "node_outputs": dict(node_outputs),
                    "graph_outputs": dict(trace.graph_outputs),
                    "failed_nodes": list(trace),
                }
            )
            completed_runs += 1
            continue

        if current.resume_depth >= _MAX_HUMAN_INPUT_DEPTH:
            failure = _single_failure_trace(
                "graph",
                "human-input",
                f"Human Input resume depth exceeds {_MAX_HUMAN_INPUT_DEPTH}",
                "policy",
            )
            combined.extend(failure)
            combined.scenario_results.append(
                {
                    "scenario_id": f"path-{completed_runs + 1}",
                    "selections": current.selections,
                    "passed": False,
                    "executed_node_ids": sorted(executed),
                    "node_outputs": dict(node_outputs),
                    "graph_outputs": {},
                    "failed_nodes": list(failure),
                }
            )
            completed_runs += 1
            continue

        pause_options: list[tuple[str, str, list[str]]] = []
        for reason in paused.reasons:
            node_id = str(getattr(reason, "node_id", "") or "")
            form = current.form_repository.get_form(node_id)
            actions = [str(action.id) for action in getattr(form.form_config, "user_actions", [])] if form else []
            if form is None or not actions:
                failure = _single_failure_trace(
                    node_id or "graph",
                    "human-input",
                    "Paused Human Input has no verifiable actions",
                    "policy",
                )
                combined.extend(failure)
                combined.scenario_results.append(
                    {
                        "scenario_id": f"path-{completed_runs + 1}",
                        "selections": current.selections,
                        "passed": False,
                        "executed_node_ids": sorted(executed),
                        "node_outputs": dict(node_outputs),
                        "graph_outputs": {},
                        "failed_nodes": list(failure),
                    }
                )
                completed_runs += 1
                pause_options = []
                break
            pause_options.append((node_id, form.id, actions))
        if not pause_options:
            continue
        combinations = list(product(*(actions for _, _, actions in pause_options)))
        if completed_runs + len(pending) + len(combinations) > _MAX_SCENARIO_RUNS:
            combined.extend(
                _single_failure_trace(
                    "graph",
                    "human-input",
                    f"Human Input action combinations exceed {_MAX_SCENARIO_RUNS}",
                    "policy",
                )
            )
            break
        snapshot = runtime_state.dumps()
        for action_ids in combinations:
            repository = current.form_repository.clone()
            selections = list(current.selections)
            try:
                for (node_id, form_id, _), action_id in zip(pause_options, action_ids):
                    selections.append({"node_id": node_id, "kind": "human_action", "value": action_id})
                    repository.submit(form_id=form_id, action_id=action_id)
            except UnsupportedHumanInputFixtureError as exc:
                failure = _single_failure_trace(node_id, "human-input", str(exc), "policy")
                combined.extend(failure)
                combined.scenario_results.append(
                    {
                        "scenario_id": f"path-{completed_runs + 1}",
                        "selections": selections,
                        "passed": False,
                        "executed_node_ids": sorted(executed),
                        "node_outputs": dict(node_outputs),
                        "graph_outputs": {},
                        "failed_nodes": list(failure),
                    }
                )
                completed_runs += 1
                continue
            pending.append(
                _PendingScenarioRun(
                    runtime_snapshot=snapshot,
                    form_repository=repository,
                    resume_depth=current.resume_depth + 1,
                    selections=selections,
                    executed_node_ids=executed,
                    node_outputs=node_outputs,
                )
            )
    if len(terminal_outputs) == 1:
        combined.graph_outputs = terminal_outputs[0]
    elif terminal_outputs:
        combined.graph_outputs = {"scenarios": terminal_outputs}
    return combined


def failed_traces_from_events(
    events: Iterable[GraphEngineEvent], *, allow_pause: bool = False
) -> GraphExecutionTrace:
    """Map engine failure and abort events to the model-facing trace list."""
    traces = GraphExecutionTrace()
    graph_error: str | None = None
    graph_error_category = "runtime"
    succeeded = False
    paused = False
    for event in events:
        if isinstance(event, (NodeRunStartedEvent, NodeRunSucceededEvent, NodeRunFailedEvent)):
            traces.executed_node_ids.add(str(event.node_id))
        if isinstance(event, GraphRunSucceededEvent):
            succeeded = True
            traces.graph_outputs = _plain_outputs(event.outputs)
        if isinstance(event, GraphRunPausedEvent):
            paused = True
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
    if not traces and not succeeded and not (allow_pause and paused):
        traces.append(
            {"id": "graph", "type": "graph", "error": "Execution ended without graph success (paused or incomplete)"}
        )
    return traces


def _single_failure_trace(
    node_id: str,
    node_type: str,
    message: str,
    category: str,
) -> GraphExecutionTrace:
    trace = GraphExecutionTrace()
    trace.append(
        {
            "id": node_id,
            "type": node_type,
            "error": message,
            "category": category,  # type: ignore[typeddict-item]
        }
    )
    return trace


def _plain_outputs(outputs: object) -> dict[str, object]:
    if not isinstance(outputs, Mapping):
        return {}
    converted = WorkflowRuntimeTypeConverter().to_json_encodable(outputs)
    return {str(key): value for key, value in converted.items()}


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
    workflow_execution_id: str = "",
    start_inputs: Mapping[str, object] | None = None,
    live_authorized: bool = False,
    runtime_snapshot: str | None = None,
    human_input_form_repository: AcceptanceHumanInputFormRepository | None = None,
) -> tuple[GraphEngine, GraphRuntimeState]:
    graph_config = _graph_config(graph)
    resolved_workflow_id = workflow_id.strip() or f"assist-accept-{uuid4().hex[:12]}"
    resolved_execution_id = workflow_execution_id.strip() or f"assist-run-{uuid4().hex}"
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
    root_node_id = get_default_root_node_id(graph_config)
    if runtime_snapshot is None:
        variable_pool = VariablePool()
        add_variables_to_pool(
            variable_pool,
            build_bootstrap_variables(
                system_variables=build_system_variables(
                    workflow_execution_id=resolved_execution_id,
                    user_id=user_id,
                    app_id=app_id,
                    workflow_id=resolved_workflow_id,
                    files=[],
                    query="",
                ),
            ),
        )
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
    else:
        graph_runtime_state = GraphRuntimeState.from_snapshot(runtime_snapshot)
    node_factory = DifyNodeFactory.from_graph_init_context(
        graph_init_context=graph_init_context,
        graph_runtime_state=graph_runtime_state,
        agent_binding_resolver=resolver,
        agent_session_store=session_store,
        human_input_form_repository=human_input_form_repository,
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
    return engine, graph_runtime_state


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
