"""Generated Human Input graphs must validate and pause in GraphEngine."""

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from core.app.entities.app_invoke_entities import InvokeFrom, UserFrom
from core.repositories.human_input_repository import (
    FormCreateParams,
    HumanInputFormEntity,
    HumanInputFormRepository,
)
from core.workflow.generator.compiler.node_builder import assemble_graph
from core.workflow.generator.graph.graph_postprocessor import postprocess_graph
from core.workflow.generator.types import GraphDict
from core.workflow.generator.validation.graph_validator import validate_graph
from core.workflow.node_factory import DifyNodeFactory, get_default_root_node_id
from core.workflow.nodes.human_input.enums import HumanInputFormStatus
from core.workflow.runtime.workflow_entry import WorkflowEntry
from graphon.graph import Graph
from graphon.graph_engine.command_channels import InMemoryChannel
from graphon.graph_events import GraphRunPausedEvent, GraphRunSucceededEvent, NodeRunSucceededEvent
from graphon.runtime import GraphRuntimeState, VariablePool
from libs.datetime_utils import naive_utc_now
from tests.workflow_test_utils import build_test_graph_init_params


@dataclass
class _InMemoryHumanInputForm(HumanInputFormEntity):
    form_id: str
    node_id: str
    rendered: str
    is_submitted: bool = False
    action_id: str | None = None
    data: Mapping[str, Any] | None = None
    status_value: HumanInputFormStatus = HumanInputFormStatus.WAITING
    created: datetime = field(default_factory=naive_utc_now)
    expiration: datetime = field(default_factory=lambda: naive_utc_now() + timedelta(days=1))

    @property
    def id(self) -> str:
        return self.form_id

    @property
    def submission_token(self) -> str | None:
        return "token"

    @property
    def recipients(self) -> list:
        return []

    @property
    def rendered_content(self) -> str:
        return self.rendered

    @property
    def selected_action_id(self) -> str | None:
        return self.action_id

    @property
    def created_at(self) -> datetime:
        return self.created

    @property
    def submitted_data(self) -> Mapping[str, Any] | None:
        return self.data

    @property
    def submitted(self) -> bool:
        return self.is_submitted

    @property
    def status(self) -> HumanInputFormStatus:
        return self.status_value

    @property
    def expiration_time(self) -> datetime:
        return self.expiration


class _InMemoryHumanInputFormRepository(HumanInputFormRepository):
    def __init__(self) -> None:
        self.forms: dict[str, _InMemoryHumanInputForm] = {}

    def get_form(self, node_id: str, *, form_id: str | None = None) -> HumanInputFormEntity | None:
        if form_id is not None:
            return self.forms.get(form_id)
        return next((form for form in reversed(self.forms.values()) if form.node_id == node_id), None)

    def create_form(self, params: FormCreateParams) -> HumanInputFormEntity:
        assert params.form_id is not None
        form = _InMemoryHumanInputForm(form_id=params.form_id, node_id=params.node_id, rendered=params.rendered_content)
        self.forms[form.id] = form
        return form

    def submit_waiting(self, *, comment: str, action_id: str = "approve") -> None:
        form = next(form for form in self.forms.values() if not form.submitted)
        form.is_submitted = True
        form.action_id = action_id
        form.data = {"comment": comment}
        form.status_value = HumanInputFormStatus.SUBMITTED

    def timeout_waiting(self) -> None:
        form = next(form for form in self.forms.values() if not form.submitted)
        form.status_value = HumanInputFormStatus.TIMEOUT


def _human_input_config() -> dict[str, Any]:
    return {
        "delivery_methods": [{"type": "webapp", "enabled": True}],
        "form_content": "Please review {{#$output.comment#}}",
        "inputs": [
            {
                "type": "paragraph",
                "output_variable_name": "comment",
                "default": {"type": "constant", "selector": [], "value": ""},
            }
        ],
        "user_actions": [
            {"id": "approve", "title": "Approve", "button_style": "primary"},
            {"id": "reject", "title": "Reject", "button_style": "default"},
        ],
        "timeout": 3,
        "timeout_unit": "day",
    }


def _generated_human_input_graph() -> GraphDict:
    assembled = assemble_graph(
        plan_nodes=[
            {"id": "start", "label": "Start", "node_type": "start", "purpose": "Start"},
            {"id": "review", "label": "Review", "node_type": "human-input", "purpose": "Ask a person"},
            {"id": "approve_end", "label": "Approved", "node_type": "end", "purpose": "Finish approve"},
            {"id": "reject_end", "label": "Rejected", "node_type": "end", "purpose": "Finish reject"},
            {"id": "timeout_end", "label": "Timed out", "node_type": "end", "purpose": "Finish timeout"},
        ],
        plan_edges=[
            {"source": "start", "target": "review"},
            {"source": "review", "target": "approve_end", "source_handle": "approve"},
            {"source": "review", "target": "reject_end", "source_handle": "reject"},
            {"source": "review", "target": "timeout_end", "source_handle": "__timeout"},
        ],
        configs_by_id={
            "start": {"variables": []},
            "review": _human_input_config(),
            "approve_end": {
                "outputs": [
                    {"variable": "comment", "value_selector": ["review", "comment"], "value_type": "string"},
                    {"variable": "action", "value_selector": ["review", "__action_id"], "value_type": "string"},
                ]
            },
            "reject_end": {
                "outputs": [{"variable": "action", "value_selector": ["review", "__action_id"], "value_type": "string"}]
            },
            "timeout_end": {
                "outputs": [{"variable": "action", "value_selector": ["review", "__action_id"], "value_type": "string"}]
            },
        },
        existing_by_id={},
    )
    return postprocess_graph(graph=assembled, mode="workflow")


def _run_graph(
    graph_config: GraphDict,
    *,
    graph_runtime_state: GraphRuntimeState | None = None,
    human_input_form_repository: HumanInputFormRepository | None = None,
) -> tuple[list[Any], VariablePool]:
    if graph_runtime_state is None:
        pool = VariablePool()
        pool.add(["sys", "query"], "hello")
        pool.add(["sys", "workflow_execution_id"], "hitl-contract")
        graph_runtime_state = GraphRuntimeState(variable_pool=pool, start_at=time.perf_counter())
    else:
        pool = graph_runtime_state.variable_pool
    root_node_id = get_default_root_node_id(graph_config)
    factory = DifyNodeFactory(
        graph_init_params=build_test_graph_init_params(graph_config=graph_config),
        graph_runtime_state=graph_runtime_state,
        human_input_form_repository=human_input_form_repository,
    )
    graph = Graph.init(graph_config=graph_config, node_factory=factory, root_node_id=root_node_id)
    entry = WorkflowEntry(
        tenant_id="tenant",
        app_id="app",
        workflow_id="workflow",
        graph_config=graph_config,
        graph=graph,
        user_id="user",
        user_from=UserFrom.ACCOUNT,
        invoke_from=InvokeFrom.DEBUGGER,
        call_depth=0,
        variable_pool=pool,
        graph_runtime_state=graph_runtime_state,
        command_channel=InMemoryChannel(),
    )
    return list(entry.run()), pool


def test_generated_human_input_graph_validates_without_target_branches() -> None:
    graph = _generated_human_input_graph()
    review = next(node for node in graph["nodes"] if node["id"] == "review")
    assert "_targetBranches" not in review["data"]
    assert validate_graph(graph=graph, mode="workflow") == []
    handles = [edge["sourceHandle"] for edge in graph["edges"] if edge["source"] == "review"]
    assert sorted(handles) == ["__timeout", "approve", "reject"]

    review["data"]["_targetBranches"] = [{"id": "stale", "name": "STALE"}]
    assert validate_graph(graph=graph, mode="workflow") == []
    assert sorted(edge["sourceHandle"] for edge in graph["edges"] if edge["source"] == "review") == [
        "__timeout",
        "approve",
        "reject",
    ]


def test_generated_human_input_pauses_resumes_on_approve_and_timeout() -> None:
    graph = _generated_human_input_graph()
    repository = _InMemoryHumanInputFormRepository()
    initial_state = GraphRuntimeState(variable_pool=VariablePool(), start_at=time.perf_counter())
    initial_state.variable_pool.add(["sys", "query"], "hello")
    initial_state.variable_pool.add(["sys", "workflow_execution_id"], "hitl-contract")
    paused_events, _ = _run_graph(
        graph,
        graph_runtime_state=initial_state,
        human_input_form_repository=repository,
    )
    assert isinstance(paused_events[-1], GraphRunPausedEvent)
    assert len(repository.forms) == 1

    repository.submit_waiting(comment="looks good", action_id="approve")
    resumed_events, pool = _run_graph(
        graph,
        graph_runtime_state=GraphRuntimeState.from_snapshot(initial_state.dumps()),
        human_input_form_repository=repository,
    )
    succeeded = [event for event in resumed_events if isinstance(event, NodeRunSucceededEvent)]
    assert isinstance(resumed_events[-1], GraphRunSucceededEvent)
    assert "approve_end" in {event.node_id for event in succeeded}
    review_event = next(event for event in succeeded if event.node_id == "review")
    assert review_event.node_run_result.outputs["comment"].value == "looks good"
    assert review_event.node_run_result.outputs["__action_id"].value == "approve"
    assert "__action_value" in review_event.node_run_result.outputs
    assert "__rendered_content" in review_event.node_run_result.outputs
    assert pool.get(["review", "comment"]).value == "looks good"

    timeout_graph = _generated_human_input_graph()
    timeout_repository = _InMemoryHumanInputFormRepository()
    timeout_state = GraphRuntimeState(variable_pool=VariablePool(), start_at=time.perf_counter())
    timeout_state.variable_pool.add(["sys", "query"], "hello")
    timeout_state.variable_pool.add(["sys", "workflow_execution_id"], "hitl-timeout")
    timeout_paused, _ = _run_graph(
        timeout_graph,
        graph_runtime_state=timeout_state,
        human_input_form_repository=timeout_repository,
    )
    assert isinstance(timeout_paused[-1], GraphRunPausedEvent)
    timeout_repository.timeout_waiting()
    timeout_resumed, _ = _run_graph(
        timeout_graph,
        graph_runtime_state=GraphRuntimeState.from_snapshot(timeout_state.dumps()),
        human_input_form_repository=timeout_repository,
    )
    timeout_succeeded = [event for event in timeout_resumed if isinstance(event, NodeRunSucceededEvent)]
    assert isinstance(timeout_resumed[-1], GraphRunSucceededEvent)
    assert "timeout_end" in {event.node_id for event in timeout_succeeded}
    timeout_review = next(event for event in timeout_succeeded if event.node_id == "review")
    assert timeout_review.node_run_result.edge_source_handle == "__timeout"
