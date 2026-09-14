"""Exercise Dify's node factory against Graphon's real container scheduler."""

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from core.app.entities.app_invoke_entities import InvokeFrom, UserFrom
from core.app.workflow.layers.llm_quota import LLMQuotaLayer
from core.repositories.human_input_repository import (
    FormCreateParams,
    HumanInputFormEntity,
    HumanInputFormRepository,
)
from core.workflow.generator.graph.graph_postprocessor import postprocess_graph
from core.workflow.generator.validation.graph_validator import validate_graph
from core.workflow.generator.compiler.node_builder import assemble_graph
from core.workflow.generator.types import GraphDict
from core.workflow.node_factory import DifyNodeFactory, get_default_root_node_id
from core.workflow.nodes.human_input.enums import HumanInputFormStatus
from core.workflow.runtime.workflow_entry import WorkflowEntry
from graphon.graph import Graph
from graphon.graph_engine.command_channels import InMemoryChannel
from graphon.graph_events import (
    GraphEngineEvent,
    GraphRunFailedEvent,
    GraphRunPausedEvent,
    GraphRunSucceededEvent,
    NodeRunSucceededEvent,
)
from graphon.runtime import GraphRuntimeState, VariablePool
from libs.datetime_utils import naive_utc_now
from tests.workflow_test_utils import build_test_graph_init_params


def _run_graph(
    graph_config: GraphDict,
    *,
    start_inputs: Mapping[str, Any] | None = None,
    graph_runtime_state: GraphRuntimeState | None = None,
    human_input_form_repository: HumanInputFormRepository | None = None,
) -> tuple[list[GraphEngineEvent], VariablePool]:
    if graph_runtime_state is None:
        pool = VariablePool()
        pool.add(["sys", "query"], "hello")
        pool.add(["sys", "workflow_execution_id"], "test-execution")
        graph_runtime_state = GraphRuntimeState(variable_pool=pool, start_at=time.perf_counter())
    else:
        pool = graph_runtime_state.variable_pool
    root_node_id = get_default_root_node_id(graph_config)
    for name, value in (start_inputs or {}).items():
        pool.add([root_node_id, name], value)
    factory = DifyNodeFactory(
        graph_init_params=build_test_graph_init_params(graph_config=graph_config),
        graph_runtime_state=graph_runtime_state,
        human_input_form_repository=human_input_form_repository,
    )
    graph = Graph.init(
        graph_config=graph_config,
        node_factory=factory,
        root_node_id=root_node_id,
    )
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


def _run_fixture(filename: str, *, parallel: bool = False) -> tuple[list[GraphEngineEvent], VariablePool]:
    fixture = Path(__file__).parents[3] / "fixtures" / "workflow" / filename
    graph_config = yaml.safe_load(fixture.read_text(encoding="utf-8"))["workflow"]["graph"]
    for node in graph_config["nodes"]:
        if node["data"]["type"] == "iteration":
            node["data"]["is_parallel"] = parallel
    return _run_graph(graph_config)


def _generated_iteration_graph(*, parallel: bool, flatten_output: bool) -> GraphDict:
    graph = assemble_graph(
        plan_nodes=[
            {"id": "start", "label": "Start", "node_type": "start", "purpose": "Start workflow"},
            {"id": "seed", "label": "Seed", "node_type": "code", "purpose": "Create input items"},
            {"id": "iteration", "label": "Map", "node_type": "iteration", "purpose": "Double each item"},
            {
                "id": "double",
                "label": "Double",
                "node_type": "code",
                "purpose": "Return the item and its double",
                "parent": "iteration",
            },
            {"id": "end", "label": "End", "node_type": "end", "purpose": "Return results"},
        ],
        plan_edges=[
            {"source": "start", "target": "seed"},
            {"source": "seed", "target": "iteration"},
            {"source": "iteration", "target": "end"},
        ],
        configs_by_id={
            "start": {"variables": []},
            "seed": {
                "variables": [],
                "outputs": {"items": {"type": "array[number]", "children": None}},
                "code": "def main():\n    return {'items': [1, 2, 3]}\n",
                "code_language": "python3",
            },
            "iteration": {
                "iterator_selector": ["seed", "items"],
                "output_selector": ["double", "result"],
                "is_parallel": parallel,
                "parallel_nums": 2,
                "flatten_output": flatten_output,
                "error_handle_mode": "terminated",
            },
            "double": {
                "variables": [{"variable": "item", "value_selector": ["iteration", "item"], "value_type": "number"}],
                "outputs": {"result": {"type": "array[number]", "children": None}},
                "code": "def main(item):\n    return {'result': [item, item * 2]}\n",
                "code_language": "python3",
            },
            "end": {
                "outputs": [
                    {
                        "variable": "result",
                        "value_selector": ["iteration", "output"],
                        "value_type": "array[number]",
                    }
                ]
            },
        },
        existing_by_id={},
    )
    return postprocess_graph(graph=graph, mode="workflow")


def _generated_loop_graph() -> GraphDict:
    graph = assemble_graph(
        plan_nodes=[
            {"id": "start", "label": "Start", "node_type": "start", "purpose": "Start workflow"},
            {"id": "loop", "label": "Loop", "node_type": "loop", "purpose": "Count to two"},
            {
                "id": "increment",
                "label": "Increment",
                "node_type": "assigner",
                "purpose": "Increment the counter",
                "parent": "loop",
            },
            {"id": "end", "label": "End", "node_type": "end", "purpose": "Return count"},
        ],
        plan_edges=[{"source": "start", "target": "loop"}, {"source": "loop", "target": "end"}],
        configs_by_id={
            "start": {"variables": []},
            "loop": {
                "loop_count": 10,
                "break_conditions": [
                    {
                        "id": "counter-ready",
                        "variable_selector": ["loop", "i"],
                        "comparison_operator": "≥",
                        "value": "2",
                        "varType": "number",
                    }
                ],
                "logical_operator": "and",
                "loop_variables": [
                    {
                        "id": "counter",
                        "label": "i",
                        "value": "0",
                        "value_type": "constant",
                        "var_type": "number",
                    }
                ],
            },
            "increment": {
                "version": "2",
                "items": [
                    {
                        "input_type": "constant",
                        "operation": "+=",
                        "value": 1,
                        "variable_selector": ["loop", "i"],
                        "write_mode": "over-write",
                    }
                ],
            },
            "end": {"outputs": [{"variable": "count", "value_selector": ["loop", "i"], "value_type": "number"}]},
        },
        existing_by_id={},
    )
    return postprocess_graph(graph=graph, mode="workflow")


def _generated_nested_container_graph() -> GraphDict:
    graph = assemble_graph(
        plan_nodes=[
            {"id": "start", "label": "Start", "node_type": "start", "purpose": "Start workflow"},
            {"id": "seed", "label": "Seed", "node_type": "code", "purpose": "Create two items"},
            {"id": "outer", "label": "Outer", "node_type": "iteration", "purpose": "Process each item"},
            {
                "id": "inner",
                "label": "Inner",
                "node_type": "loop",
                "purpose": "Count to two",
                "parent": "outer",
            },
            {
                "id": "increment",
                "label": "Increment",
                "node_type": "assigner",
                "purpose": "Increment inner counter",
                "parent": "inner",
            },
            {"id": "end", "label": "End", "node_type": "end", "purpose": "Return nested results"},
        ],
        plan_edges=[
            {"source": "start", "target": "seed"},
            {"source": "seed", "target": "outer"},
            {"source": "outer", "target": "end"},
        ],
        configs_by_id={
            "start": {"variables": []},
            "seed": {
                "variables": [],
                "outputs": {"items": {"type": "array[number]", "children": None}},
                "code": "def main():\n    return {'items': [1, 2]}\n",
                "code_language": "python3",
            },
            "outer": {
                "iterator_selector": ["seed", "items"],
                "output_selector": ["inner", "i"],
                "is_parallel": False,
                "parallel_nums": 2,
                "flatten_output": True,
                "error_handle_mode": "terminated",
            },
            "inner": {
                "loop_count": 10,
                "break_conditions": [
                    {
                        "id": "inner-ready",
                        "variable_selector": ["inner", "i"],
                        "comparison_operator": "≥",
                        "value": "2",
                        "varType": "number",
                    }
                ],
                "logical_operator": "and",
                "loop_variables": [
                    {
                        "id": "inner-counter",
                        "label": "i",
                        "value": "0",
                        "value_type": "constant",
                        "var_type": "number",
                    }
                ],
            },
            "increment": {
                "version": "2",
                "items": [
                    {
                        "input_type": "constant",
                        "operation": "+=",
                        "value": 1,
                        "variable_selector": ["inner", "i"],
                        "write_mode": "over-write",
                    }
                ],
            },
            "end": {
                "outputs": [
                    {"variable": "counts", "value_selector": ["outer", "output"], "value_type": "array[number]"}
                ]
            },
        },
        existing_by_id={},
    )
    return postprocess_graph(graph=graph, mode="workflow")


def _generated_iteration_with_human_input_graph() -> GraphDict:
    graph = assemble_graph(
        plan_nodes=[
            {"id": "start", "label": "Start", "node_type": "start", "purpose": "Start workflow"},
            {"id": "seed", "label": "Seed", "node_type": "code", "purpose": "Create two items"},
            {"id": "review_each", "label": "Review each", "node_type": "iteration", "purpose": "Review items"},
            {
                "id": "review",
                "label": "Review",
                "node_type": "human-input",
                "purpose": "Ask for approval",
                "parent": "review_each",
            },
            {"id": "end", "label": "End", "node_type": "end", "purpose": "Return comments"},
        ],
        plan_edges=[
            {"source": "start", "target": "seed"},
            {"source": "seed", "target": "review_each"},
            {"source": "review_each", "target": "end"},
        ],
        configs_by_id={
            "start": {"variables": []},
            "seed": {
                "variables": [],
                "outputs": {"items": {"type": "array[number]", "children": None}},
                "code": "def main():\n    return {'items': [1, 2]}\n",
                "code_language": "python3",
            },
            "review_each": {
                "iterator_selector": ["seed", "items"],
                "output_selector": ["review", "comment"],
                "is_parallel": False,
                "parallel_nums": 1,
                "flatten_output": True,
                "error_handle_mode": "terminated",
            },
            "review": {
                "delivery_methods": [{"type": "webapp", "enabled": True}],
                "form_content": "Review item {{#review_each.item#}}",
                "inputs": [
                    {
                        "type": "paragraph",
                        "output_variable_name": "comment",
                        "default": {"type": "constant", "selector": [], "value": ""},
                    }
                ],
                "user_actions": [{"id": "approve", "title": "Approve", "button_style": "primary"}],
                "timeout": 3,
                "timeout_unit": "day",
            },
            "end": {
                "outputs": [
                    {
                        "variable": "comments",
                        "value_selector": ["review_each", "output"],
                        "value_type": "array[string]",
                    }
                ]
            },
        },
        existing_by_id={},
    )
    return postprocess_graph(graph=graph, mode="workflow")


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
        form = _InMemoryHumanInputForm(
            form_id=params.form_id,
            node_id=params.node_id,
            rendered=params.rendered_content,
        )
        self.forms[form.id] = form
        return form

    def timeout_waiting(self) -> None:
        form = next(form for form in self.forms.values() if not form.submitted)
        form.status_value = HumanInputFormStatus.TIMEOUT

    def submit_waiting(self, *, comment: str) -> None:
        form = next(form for form in self.forms.values() if not form.submitted)
        form.is_submitted = True
        form.action_id = "approve"
        form.data = {"comment": comment}
        form.status_value = HumanInputFormStatus.SUBMITTED


def test_loop_recreates_child_nodes_and_stops_at_break_condition() -> None:
    events, pool = _run_fixture("loop_contains_answer.yml")

    assert isinstance(events[-1], GraphRunSucceededEvent), events[-1]
    assert pool.get(["1755203872773", "i"]).value == 2


@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("iteration_flatten_output_enabled_workflow.yml", [1, 2, 2, 4, 3, 6]),
        ("iteration_flatten_output_disabled_workflow.yml", [[1, 2], [2, 4], [3, 6]]),
    ],
)
def test_iteration_preserves_order_and_flattening(filename, expected, parallel):
    def execute_code(*, language, code, inputs):
        # Stub only the external sandbox; node validation and scheduling remain real.
        if "arg1" in inputs:
            value = inputs["arg1"]
            return {"result": [value, value * 2]}
        return {"result": [1, 2, 3]}

    with patch("core.workflow.node_factory.CodeExecutor.execute_workflow_code_template", side_effect=execute_code):
        events, pool = _run_fixture(filename, parallel=parallel)

    assert isinstance(events[-1], GraphRunSucceededEvent), events[-1]
    assert pool.get(["iteration_node", "output"]).value == expected


@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize(
    ("flatten_output", "expected"),
    [
        (True, [1, 2, 2, 4, 3, 6]),
        (False, [[1, 2], [2, 4], [3, 6]]),
    ],
)
def test_generated_iteration_graph_validates_and_runs_in_graphon(parallel, flatten_output, expected):
    graph = _generated_iteration_graph(parallel=parallel, flatten_output=flatten_output)

    errors = validate_graph(graph=graph, mode="workflow")
    assert errors == []

    def execute_code(*, language, code, inputs):
        if not inputs:
            return {"items": [1, 2, 3]}
        item = inputs["item"]
        return {"result": [item, item * 2]}

    with patch("core.workflow.node_factory.CodeExecutor.execute_workflow_code_template", side_effect=execute_code):
        events, pool = _run_graph(graph)

    assert isinstance(events[-1], GraphRunSucceededEvent), events[-1]
    assert pool.get(["iteration", "output"]).value == expected


def _run_generated_failing_iteration(
    mode: str,
) -> tuple[list[GraphEngineEvent], VariablePool]:
    graph = _generated_iteration_graph(parallel=False, flatten_output=False)
    for node in graph["nodes"]:
        data = node["data"]
        if data["type"] == "iteration":
            data["error_handle_mode"] = mode
    return _run_graph(graph)


@pytest.mark.parametrize(
    ("mode", "run_failed", "keeps_failed_item"),
    [
        ("terminated", True, False),
        ("continue-on-error", False, True),
        ("remove-abnormal-output", False, False),
    ],
)
def test_generated_iteration_error_modes(mode: str, run_failed: bool, keeps_failed_item: bool) -> None:
    def execute_code(*, language, code, inputs):
        if not inputs:
            return {"items": [1, 2, 3]}
        item = inputs["item"]
        if item == 2:
            raise ValueError("fixed failure")
        return {"result": [item, item * 2]}

    with patch("core.workflow.node_factory.CodeExecutor.execute_workflow_code_template", side_effect=execute_code):
        events, pool = _run_generated_failing_iteration(mode)

    assert any(isinstance(event, GraphRunFailedEvent) for event in events) is run_failed
    if not run_failed:
        output = pool.get(["iteration", "output"]).value
        assert any(item is None for item in output) is keeps_failed_item


def test_quota_layer_observes_each_generated_iteration_child_execution():
    graph = _generated_iteration_graph(parallel=False, flatten_output=True)

    def execute_code(*, language, code, inputs):
        if not inputs:
            return {"items": [1, 2, 3]}
        item = inputs["item"]
        return {"result": [item, item * 2]}

    with (
        patch("core.workflow.node_factory.CodeExecutor.execute_workflow_code_template", side_effect=execute_code),
        patch.object(LLMQuotaLayer, "_supports_quota", side_effect=lambda node: node.id == "double"),
        patch.object(LLMQuotaLayer, "_extract_model_identity_from_node", return_value=("provider", "model")),
        patch.object(LLMQuotaLayer, "_extract_model_identity_from_result_event", return_value=("provider", "model")),
        patch("core.app.workflow.layers.llm_quota.ensure_llm_quota_available_for_model") as check_quota,
        patch("core.app.workflow.layers.llm_quota.deduct_llm_quota_for_model") as deduct_quota,
    ):
        events, _ = _run_graph(graph)

    assert isinstance(events[-1], GraphRunSucceededEvent), events[-1]
    assert check_quota.call_count == 3
    assert deduct_quota.call_count == 3


def test_generated_loop_graph_validates_and_runs_until_break_condition():
    graph = _generated_loop_graph()

    errors = validate_graph(graph=graph, mode="workflow")
    assert errors == []

    events, pool = _run_graph(graph)

    assert isinstance(events[-1], GraphRunSucceededEvent), events[-1]
    assert pool.get(["loop", "i"]).value == 2


def test_generated_loop_stops_at_loop_count() -> None:
    graph = _generated_loop_graph()
    for node in graph["nodes"]:
        if node["id"] == "loop":
            node["data"]["loop_count"] = 2
            node["data"]["break_conditions"] = []
    events, pool = _run_graph(graph)
    assert isinstance(events[-1], GraphRunSucceededEvent), events[-1]
    assert pool.get(["loop", "i"]).value == 2


def test_generated_loop_or_break_condition_can_stop_early() -> None:
    graph = _generated_loop_graph()
    for node in graph["nodes"]:
        if node["id"] == "loop":
            node["data"]["logical_operator"] = "or"
            node["data"]["break_conditions"] = [
                {
                    "id": "never",
                    "variable_selector": ["loop", "i"],
                    "comparison_operator": "≥",
                    "value": "99",
                    "varType": "number",
                },
                {
                    "id": "ready",
                    "variable_selector": ["loop", "i"],
                    "comparison_operator": "≥",
                    "value": "2",
                    "varType": "number",
                },
            ]
    events, pool = _run_graph(graph)
    assert isinstance(events[-1], GraphRunSucceededEvent), events[-1]
    assert pool.get(["loop", "i"]).value == 2


def test_generated_loop_end_stops_the_loop_not_the_workflow() -> None:
    graph = assemble_graph(
        plan_nodes=[
            {"id": "start", "label": "Start", "node_type": "start", "purpose": "Start workflow"},
            {"id": "loop", "label": "Loop", "node_type": "loop", "purpose": "Exit immediately"},
            {
                "id": "exit",
                "label": "Exit",
                "node_type": "loop-end",
                "purpose": "Leave the loop",
                "parent": "loop",
            },
            {"id": "end", "label": "End", "node_type": "end", "purpose": "Finish"},
        ],
        plan_edges=[{"source": "start", "target": "loop"}, {"source": "loop", "target": "end"}],
        configs_by_id={
            "start": {"variables": []},
            "loop": {
                "loop_count": 10,
                "break_conditions": [],
                "logical_operator": "and",
                "loop_variables": [
                    {
                        "id": "counter",
                        "label": "i",
                        "value": 0,
                        "value_type": "constant",
                        "var_type": "number",
                    }
                ],
            },
            "end": {"outputs": [{"variable": "count", "value_selector": ["loop", "i"], "value_type": "number"}]},
        },
        existing_by_id={},
    )
    graph = postprocess_graph(graph=graph, mode="workflow")
    assert validate_graph(graph=graph, mode="workflow") == []
    events, pool = _run_graph(graph)
    assert isinstance(events[-1], GraphRunSucceededEvent), events[-1]
    assert pool.get(["loop", "i"]).value == 0


def test_generated_loop_fails_when_a_child_node_fails() -> None:
    graph = assemble_graph(
        plan_nodes=[
            {"id": "start", "label": "Start", "node_type": "start", "purpose": "Start workflow"},
            {"id": "loop", "label": "Loop", "node_type": "loop", "purpose": "Run failing body"},
            {
                "id": "boom",
                "label": "Boom",
                "node_type": "code",
                "purpose": "Fail",
                "parent": "loop",
            },
            {"id": "end", "label": "End", "node_type": "end", "purpose": "Finish"},
        ],
        plan_edges=[{"source": "start", "target": "loop"}, {"source": "loop", "target": "end"}],
        configs_by_id={
            "start": {"variables": []},
            "loop": {
                "loop_count": 3,
                "break_conditions": [],
                "logical_operator": "and",
                "loop_variables": [],
            },
            "boom": {
                "code": "def main():\n    raise ValueError('fixed failure')\n",
                "code_language": "python3",
                "outputs": {"result": {"type": "string", "children": None}},
                "variables": [],
            },
            "end": {"outputs": []},
        },
        existing_by_id={},
    )
    graph = postprocess_graph(graph=graph, mode="workflow")

    def execute_code(*, language, code, inputs):
        raise ValueError("fixed failure")

    with patch("core.workflow.node_factory.CodeExecutor.execute_workflow_code_template", side_effect=execute_code):
        events, _ = _run_graph(graph)

    assert any(isinstance(event, GraphRunFailedEvent) for event in events)


def test_generated_nested_containers_validate_and_run_in_graphon():
    graph = _generated_nested_container_graph()

    errors = validate_graph(graph=graph, mode="workflow")
    assert errors == []

    def execute_code(*, language, code, inputs):
        return {"items": [1, 2]}

    with patch("core.workflow.node_factory.CodeExecutor.execute_workflow_code_template", side_effect=execute_code):
        events, pool = _run_graph(graph)

    assert isinstance(events[-1], GraphRunSucceededEvent), events[-1]
    assert pool.get(["outer", "output"]).value == [2, 2]


def test_generated_iteration_pauses_and_resumes_for_two_human_input_executions():
    graph = _generated_iteration_with_human_input_graph()
    assert validate_graph(graph=graph, mode="workflow") == []

    repository = _InMemoryHumanInputFormRepository()

    def execute_code(*, language, code, inputs):
        return {"items": [1, 2]}

    with patch("core.workflow.node_factory.CodeExecutor.execute_workflow_code_template", side_effect=execute_code):
        initial_state = GraphRuntimeState(variable_pool=VariablePool(), start_at=time.perf_counter())
        initial_state.variable_pool.add(["sys", "query"], "hello")
        initial_state.variable_pool.add(["sys", "workflow_execution_id"], "test-execution")
        initial_events, _ = _run_graph(
            graph,
            graph_runtime_state=initial_state,
            human_input_form_repository=repository,
        )

        assert isinstance(initial_events[-1], GraphRunPausedEvent), initial_events[-1]
        assert len(repository.forms) == 1

        repository.submit_waiting(comment="first")
        first_resume_state = GraphRuntimeState.from_snapshot(initial_state.dumps())
        first_resume_events, _ = _run_graph(
            graph,
            graph_runtime_state=first_resume_state,
            human_input_form_repository=repository,
        )

        assert isinstance(first_resume_events[-1], GraphRunPausedEvent), first_resume_events[-1]
        assert len(repository.forms) == 2
        assert len(set(repository.forms)) == 2

        repository.submit_waiting(comment="second")
        second_resume_state = GraphRuntimeState.from_snapshot(first_resume_state.dumps())
        second_resume_events, pool = _run_graph(
            graph,
            graph_runtime_state=second_resume_state,
            human_input_form_repository=repository,
        )

    assert isinstance(second_resume_events[-1], GraphRunSucceededEvent), second_resume_events[-1]
    assert pool.get(["review_each", "output"]).value == ["first", "second"]


def _generated_loop_with_human_input_graph() -> GraphDict:
    graph = assemble_graph(
        plan_nodes=[
            {"id": "start", "label": "Start", "node_type": "start", "purpose": "Start workflow"},
            {"id": "loop", "label": "Loop", "node_type": "loop", "purpose": "Count to two"},
            {
                "id": "review",
                "label": "Review",
                "node_type": "human-input",
                "purpose": "Ask for approval",
                "parent": "loop",
            },
            {
                "id": "increment",
                "label": "Increment",
                "node_type": "assigner",
                "purpose": "Increment the counter",
                "parent": "loop",
            },
            {"id": "end", "label": "End", "node_type": "end", "purpose": "Return count"},
        ],
        plan_edges=[
            {"source": "start", "target": "loop"},
            {"source": "loop", "target": "end"},
            {"source": "review", "target": "increment", "source_handle": "approve"},
            {"source": "review", "target": "increment", "source_handle": "__timeout"},
        ],
        configs_by_id={
            "start": {"variables": []},
            "loop": {
                "loop_count": 10,
                "break_conditions": [
                    {
                        "id": "counter-ready",
                        "variable_selector": ["loop", "i"],
                        "comparison_operator": "≥",
                        "value": "2",
                        "varType": "number",
                    }
                ],
                "logical_operator": "and",
                "loop_variables": [
                    {
                        "id": "counter",
                        "label": "i",
                        "value": "0",
                        "value_type": "constant",
                        "var_type": "number",
                    }
                ],
            },
            "review": {
                "delivery_methods": [{"type": "webapp", "enabled": True}],
                "form_content": "Review round",
                "inputs": [
                    {
                        "type": "paragraph",
                        "output_variable_name": "comment",
                        "default": {"type": "constant", "selector": [], "value": ""},
                    }
                ],
                "user_actions": [{"id": "approve", "title": "Approve", "button_style": "primary"}],
                "timeout": 3,
                "timeout_unit": "day",
            },
            "increment": {
                "version": "2",
                "items": [
                    {
                        "input_type": "constant",
                        "operation": "+=",
                        "value": 1,
                        "variable_selector": ["loop", "i"],
                        "write_mode": "over-write",
                    }
                ],
            },
            "end": {"outputs": [{"variable": "count", "value_selector": ["loop", "i"], "value_type": "number"}]},
        },
        existing_by_id={},
    )
    return postprocess_graph(graph=graph, mode="workflow")


def test_generated_loop_pauses_and_resumes_for_two_human_input_executions() -> None:
    graph = _generated_loop_with_human_input_graph()
    assert validate_graph(graph=graph, mode="workflow") == []

    repository = _InMemoryHumanInputFormRepository()
    initial_state = GraphRuntimeState(variable_pool=VariablePool(), start_at=time.perf_counter())
    initial_state.variable_pool.add(["sys", "query"], "hello")
    initial_state.variable_pool.add(["sys", "workflow_execution_id"], "loop-hitl")
    initial_events, _ = _run_graph(graph, graph_runtime_state=initial_state, human_input_form_repository=repository)

    assert isinstance(initial_events[-1], GraphRunPausedEvent), initial_events[-1]
    replay_events, _ = _run_graph(
        graph,
        graph_runtime_state=GraphRuntimeState.from_snapshot(initial_state.dumps()),
        human_input_form_repository=repository,
    )
    assert isinstance(replay_events[-1], GraphRunPausedEvent), replay_events[-1]
    assert len(repository.forms) == 1

    first_form_id = next(iter(repository.forms))
    repository.submit_waiting(comment="first")
    first_resume_state = GraphRuntimeState.from_snapshot(initial_state.dumps())
    first_resume_events, _ = _run_graph(
        graph,
        graph_runtime_state=first_resume_state,
        human_input_form_repository=repository,
    )
    assert isinstance(first_resume_events[-1], GraphRunPausedEvent), first_resume_events[-1]
    assert len(repository.forms) == 2
    assert len(set(repository.forms)) == 2
    second_form_id = next(form_id for form_id in repository.forms if form_id != first_form_id)
    assert first_form_id != second_form_id

    repository.submit_waiting(comment="second")
    second_resume_state = GraphRuntimeState.from_snapshot(first_resume_state.dumps())
    second_resume_events, pool = _run_graph(
        graph,
        graph_runtime_state=second_resume_state,
        human_input_form_repository=repository,
    )
    assert isinstance(second_resume_events[-1], GraphRunSucceededEvent), second_resume_events[-1]
    assert pool.get(["loop", "i"]).value == 2

    stale_state = GraphRuntimeState.from_snapshot(first_resume_state.dumps())
    stale_events, _ = _run_graph(graph, graph_runtime_state=stale_state, human_input_form_repository=repository)
    assert isinstance(stale_events[-1], GraphRunSucceededEvent)
    assert len(repository.forms) == 2


def test_generated_loop_human_input_timeout_uses_timeout_handle() -> None:
    graph = _generated_loop_with_human_input_graph()
    repository = _InMemoryHumanInputFormRepository()
    initial_state = GraphRuntimeState(variable_pool=VariablePool(), start_at=time.perf_counter())
    initial_state.variable_pool.add(["sys", "query"], "hello")
    initial_state.variable_pool.add(["sys", "workflow_execution_id"], "loop-timeout")
    initial_events, _ = _run_graph(graph, graph_runtime_state=initial_state, human_input_form_repository=repository)
    assert isinstance(initial_events[-1], GraphRunPausedEvent)

    repository.timeout_waiting()
    resume_state = GraphRuntimeState.from_snapshot(initial_state.dumps())
    resume_events, _ = _run_graph(graph, graph_runtime_state=resume_state, human_input_form_repository=repository)
    succeeded = [
        event
        for event in resume_events
        if isinstance(event, NodeRunSucceededEvent) and event.node_id == "review"
    ]
    assert succeeded
    assert succeeded[0].node_run_result.edge_source_handle == "__timeout"
