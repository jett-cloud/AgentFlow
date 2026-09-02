from copy import deepcopy
from typing import cast

from core.workflow.generator.graph_validator import validate_graph
from core.workflow.generator.types import GraphDict


def test_validate_graph_reports_unreachable_end_without_mutating_graph():
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {"id": "start", "data": {"type": "start"}},
                {"id": "end", "data": {"type": "end"}},
            ],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )
    before = deepcopy(graph)

    errors = validate_graph(graph=graph, mode="workflow")

    assert any(error["code"] == "INVALID_SCHEMA" for error in errors)
    assert graph == before


from ._runner_test_support import (
    GraphValidator,
    WorkflowGenerator,
    _GraphFixtureModel,
    json,
)


class TestWorkflowGeneratorGraphCycleValidation:
    """A workflow graph must be a DAG; cycles hang or error the run."""

    def test_self_loop_is_flagged_with_the_node_id(self):
        graph = {
            "nodes": [],
            "edges": [{"source": "a", "target": "a"}],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        }
        errors = GraphValidator._collect_edge_cycle_errors(graph=cast(GraphDict, graph), known_ids={"a"})
        assert len(errors) == 1
        assert errors[0]["code"] == "GRAPH_CYCLE"
        assert errors[0]["node_id"] == "a"

    def test_two_node_cycle_is_flagged_once(self):
        graph = {
            "nodes": [],
            "edges": [
                {"source": "start", "target": "a"},
                {"source": "a", "target": "b"},
                {"source": "b", "target": "a"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        }
        errors = GraphValidator._collect_edge_cycle_errors(graph=cast(GraphDict, graph), known_ids={"start", "a", "b"})
        assert len(errors) == 1
        assert errors[0]["code"] == "GRAPH_CYCLE"
        assert "a" in errors[0]["detail"]
        assert "b" in errors[0]["detail"]

    def test_acyclic_graph_produces_no_errors(self):
        graph = {
            "nodes": [],
            "edges": [
                {"source": "start", "target": "a"},
                {"source": "start", "target": "b"},
                {"source": "a", "target": "end"},
                {"source": "b", "target": "end"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        }
        errors = GraphValidator._collect_edge_cycle_errors(
            graph=cast(GraphDict, graph), known_ids={"start", "a", "b", "end"}
        )
        assert errors == []

    def test_cyclic_builder_output_surfaces_graph_cycle_code(self):
        planner = json.dumps(
            {
                "title": "t",
                "description": "d",
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "x"},
                    {"label": "LLM", "node_type": "llm", "purpose": "x"},
                    {"label": "End", "node_type": "end", "purpose": "x"},
                ],
            }
        )
        builder = json.dumps(
            {
                "nodes": [
                    {
                        "id": "node1",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "start", "title": "Start", "variables": []},
                    },
                    {
                        "id": "node2",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "llm", "title": "LLM"},
                    },
                    {
                        "id": "node3",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "end", "title": "End", "outputs": []},
                    },
                ],
                "edges": [
                    {"source": "node1", "target": "node2"},
                    {"source": "node2", "target": "node2"},
                    {"source": "node2", "target": "node3"},
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )
        model_instance = _GraphFixtureModel(planner, builder)

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert any(e["code"] == "GRAPH_CYCLE" for e in result["errors"])


class TestWorkflowGeneratorDuplicateNodeIds:
    """Duplicate planner ids make every cross-reference ambiguous."""

    def test_duplicate_ids_surface_dedicated_code(self):
        planner = json.dumps(
            {
                "title": "t",
                "description": "d",
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "x"},
                    {"label": "End", "node_type": "end", "purpose": "x"},
                ],
            }
        )
        builder = json.dumps(
            {
                "nodes": [
                    {
                        "id": "node1",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "start", "title": "Start", "variables": []},
                    },
                    {
                        "id": "node1",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "end", "title": "End", "outputs": []},
                    },
                ],
                "edges": [{"source": "node1", "target": "node1"}],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )
        model_instance = _GraphFixtureModel(planner, builder)

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        codes = {e["code"] for e in result["errors"]}
        assert codes == {"INVALID_SCHEMA"}


def test_collect_container_errors():
    nodes = [{"id": "n1", "data": {"type": "llm"}}, {"id": "n2", "data": {"type": "code", "parentId": "n1"}}]

    errors = GraphValidator._collect_container_errors(nodes=nodes)

    assert len(errors) >= 1
    assert errors[0]["code"] == "INVALID_CONTAINER"


def test_collect_unknown_tools():

    # Missing tool/provider info
    nodes = [
        {"id": "n1", "data": {"type": "tool", "provider_id": "", "tool_name": ""}},
        {"id": "n2", "data": {"type": "tool", "provider_id": "p1", "tool_name": "t1"}},
    ]
    installed_tools = {("p1", "t1")}
    errors = GraphValidator._collect_unknown_tools(nodes=nodes, installed_tools=installed_tools)
    assert len(errors) >= 1
    assert "missing provider" in errors[0]["detail"]

    agent_nodes = [
        {
            "id": "ag1",
            "data": {
                "type": "agent",
                "dify_tools": [{"provider_type": "mcp", "provider_id": "missing-mcp", "tool_name": None}],
            },
        }
    ]
    agent_errors = GraphValidator._collect_unknown_tools(nodes=agent_nodes, installed_tools={("github-official", "get_file_contents")})
    assert any(item["code"] == "UNKNOWN_TOOL" for item in agent_errors)


def test_collect_unresolved_refs():

    # Missing node ref
    nodes = [{"id": "n1", "data": {"type": "llm", "prompt_template": [{"text": "{{#unknown.var#}}"}]}}]
    # To trigger the parsing we need to mock _collect_refs_in_data behavior or let it parse naturally
    # If the ref parsing finds "unknown", "var", it will check by_id

    # Actually _collect_refs_in_data modifies the set

    errors = GraphValidator._collect_unresolved_refs(nodes=nodes, mode="workflow")
    assert len(errors) >= 1
    assert errors[0]["code"] == "UNKNOWN_NODE_REFERENCE"


def test_collect_edge_cycle_errors():

    # Self-loop
    graph = {"nodes": [{"id": "n1"}], "edges": [{"source": "n1", "target": "n1"}]}
    errors = GraphValidator._collect_edge_cycle_errors(graph=graph, known_ids={"n1"})
    assert len(errors) >= 1
    assert "itself" in errors[0]["detail"]


def test_collect_container_errors_empty_container():

    # Empty container
    nodes = [
        {"id": "n1", "data": {"type": "iteration"}},
    ]
    errors = GraphValidator._collect_container_errors(nodes=nodes)
    assert len(errors) >= 1
    assert "no child nodes" in errors[0]["detail"]


def test_collect_container_errors_cycle():

    # Ancestor cycle
    nodes = [
        {"id": "n1", "data": {"type": "iteration", "parentId": "n2"}},
        {"id": "n2", "data": {"type": "iteration", "parentId": "n1"}},
    ]
    errors = GraphValidator._collect_container_errors(nodes=nodes)
    assert len(errors) >= 1
    assert "Cycle" in errors[0]["detail"]


def test_missing_terminal_mode_auto():
    graph = {"nodes": [{"id": "n1", "data": {"type": "start"}}], "edges": []}

    errors = validate_graph(graph=graph, mode="workflow", installed_tools=set())

    assert any(error["code"] == "MISSING_TERMINAL" for error in errors)
