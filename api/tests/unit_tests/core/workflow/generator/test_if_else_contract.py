"""End-to-end contract checks for generated Dify if-else graphs."""

import time
from typing import Any

import pytest

from core.app.entities.app_invoke_entities import InvokeFrom, UserFrom
from core.workflow.generator.compiler.node_builder import assemble_graph
from core.workflow.generator.graph.graph_postprocessor import postprocess_graph
from core.workflow.generator.types import GraphDict
from core.workflow.generator.validation.graph_validator import validate_graph
from core.workflow.node_factory import DifyNodeFactory, get_default_root_node_id
from core.workflow.runtime.workflow_entry import WorkflowEntry
from graphon.graph import Graph
from graphon.graph_engine.command_channels import InMemoryChannel
from graphon.graph_events import GraphRunSucceededEvent, NodeRunSucceededEvent
from graphon.runtime import GraphRuntimeState, VariablePool
from tests.unit_tests.core.workflow.generator.node_fixtures import node_config
from tests.workflow_test_utils import build_test_graph_init_params

_ELIF_CASE_ID = "b61c92c8-2398-44e9-871a-278428a14c75"


def _generated_if_else_graph() -> GraphDict:
    assembled = assemble_graph(
        plan_nodes=[
            {"id": "start", "label": "Start", "node_type": "start", "purpose": "Read score"},
            {"id": "branch", "label": "Route score", "node_type": "if-else", "purpose": "Choose band"},
            {"id": "if_end", "label": "High", "node_type": "end", "purpose": "Finish high branch"},
            {"id": "elif_end", "label": "Medium", "node_type": "end", "purpose": "Finish medium branch"},
            {"id": "else_end", "label": "Low", "node_type": "end", "purpose": "Finish low branch"},
        ],
        plan_edges=[
            {"source": "start", "target": "branch"},
            {"source": "branch", "target": "if_end", "source_handle": "true"},
            {"source": "branch", "target": "elif_end", "source_handle": _ELIF_CASE_ID},
            {"source": "branch", "target": "else_end", "source_handle": "false"},
        ],
        configs_by_id={
            "start": {"variables": [{"variable": "score", "label": "Score", "type": "number", "required": False}]},
            "branch": {
                "cases": [
                    {
                        "case_id": "true",
                        "logical_operator": "and",
                        "conditions": [
                            {
                                "id": "high-score",
                                "varType": "number",
                                "variable_selector": ["start", "score"],
                                "comparison_operator": "≥",
                                "value": "22",
                            }
                        ],
                    },
                    {
                        "case_id": _ELIF_CASE_ID,
                        "logical_operator": "and",
                        "conditions": [
                            {
                                "id": "medium-score",
                                "varType": "number",
                                "variable_selector": ["start", "score"],
                                "comparison_operator": "≥",
                                "value": "10",
                            }
                        ],
                    },
                ]
            },
            "if_end": node_config("end"),
            "elif_end": node_config("end"),
            "else_end": node_config("end"),
        },
        existing_by_id={},
    )
    return postprocess_graph(graph=assembled, mode="workflow")


def _run_graph(graph_config: GraphDict, *, score: int) -> list[Any]:
    pool = VariablePool()
    pool.add(["sys", "query"], "hello")
    pool.add(["sys", "workflow_execution_id"], "if-else-contract-test")
    root_node_id = get_default_root_node_id(graph_config)
    pool.add([root_node_id, "score"], score)
    runtime_state = GraphRuntimeState(variable_pool=pool, start_at=time.perf_counter())
    factory = DifyNodeFactory(
        graph_init_params=build_test_graph_init_params(graph_config=graph_config),
        graph_runtime_state=runtime_state,
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
        graph_runtime_state=runtime_state,
        command_channel=InMemoryChannel(),
    )
    return list(entry.run())


@pytest.mark.parametrize(
    ("score", "selected_case_id", "terminal_node_id"),
    [(30, "true", "if_end"), (15, _ELIF_CASE_ID, "elif_end"), (5, "false", "else_end")],
)
def test_generated_if_else_validates_and_routes_in_real_graph_engine(
    score: int,
    selected_case_id: str,
    terminal_node_id: str,
) -> None:
    graph = _generated_if_else_graph()

    assert validate_graph(graph=graph, mode="workflow") == []
    branch = next(node for node in graph["nodes"] if node["id"] == "branch")
    assert branch["data"]["_targetBranches"] == [
        {"id": "true", "name": "CASE 1"},
        {"id": _ELIF_CASE_ID, "name": "CASE 2"},
        {"id": "false", "name": "ELSE"},
    ]

    events = _run_graph(graph, score=score)
    succeeded = [event for event in events if isinstance(event, NodeRunSucceededEvent)]
    branch_event = next(event for event in succeeded if event.node_id == "branch")

    assert isinstance(events[-1], GraphRunSucceededEvent), events[-1]
    assert branch_event.node_run_result.outputs["selected_case_id"] == selected_case_id
    assert terminal_node_id in {event.node_id for event in succeeded}
