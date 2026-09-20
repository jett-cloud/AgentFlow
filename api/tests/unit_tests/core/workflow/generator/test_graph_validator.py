from copy import deepcopy
from typing import cast

import pytest

from core.workflow.generator.compiler.tool_parameter_normalize import apply_tool_parameters_to_graph
from core.workflow.generator.graph.graph_postprocessor import postprocess_graph
from core.workflow.generator.types import GraphDict, WorkflowGenerateErrorCode
from core.workflow.generator.validation.graph_validator import validate_graph
from tests.unit_tests.core.workflow.generator.node_fixtures import node_config


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


def test_validate_graph_rejects_direct_terminal_edge_that_bypasses_a_longer_path() -> None:
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {"id": "start", "data": {"type": "start", "variables": []}},
                {"id": "parse", "data": {"type": "code", **node_config("code")}},
                {"id": "iterate", "data": {"type": "code", **node_config("code")}},
                {"id": "judge", "data": {"type": "llm", **node_config("llm")}},
                {"id": "end", "data": {"type": "end", **node_config("end")}},
            ],
            "edges": [
                {"source": "start", "target": "parse"},
                {"source": "parse", "target": "end"},
                {"source": "parse", "target": "iterate"},
                {"source": "iterate", "target": "judge"},
                {"source": "judge", "target": "end"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )

    errors = validate_graph(graph=graph, mode="workflow")

    assert any(
        error["code"] == "INVALID_SCHEMA"
        and error.get("node_id") == "parse"
        and "bypasses downstream work" in error["detail"]
        for error in errors
    )


def test_validate_graph_rejects_runtime_valid_llm_with_empty_prompt():
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {"id": "start", "data": {"type": "start", "variables": []}},
                {
                    "id": "llm",
                    "data": {
                        "type": "llm",
                        "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
                        "prompt_template": [{"role": "user", "text": "  "}],
                        "context": {"enabled": False, "variable_selector": []},
                    },
                },
                {"id": "end", "data": {"type": "end", "outputs": []}},
            ],
            "edges": [{"source": "start", "target": "llm"}, {"source": "llm", "target": "end"}],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )

    errors = validate_graph(graph=graph, mode="workflow")

    assert any(
        error["code"] == "INVALID_NODE_CONFIG"
        and error.get("node_id") == "llm"
        and "prompt_template" in error["detail"]
        for error in errors
    )


@pytest.mark.parametrize(
    ("source_handle", "error_strategy", "expected_valid"),
    [
        ("source", None, True),
        ("unexpected", None, False),
        ("fail-branch", None, False),
        ("fail-branch", "fail-branch", True),
    ],
)
def test_validate_graph_checks_http_request_output_handle(
    source_handle: str,
    error_strategy: str | None,
    expected_valid: bool,
) -> None:
    http_data = {
        "type": "http-request",
        "method": "get",
        "url": "https://example.com",
        "authorization": {"type": "no-auth", "config": None},
        "headers": "",
        "params": "",
        "body": {"type": "none", "data": []},
    }
    if error_strategy:
        http_data["error_strategy"] = error_strategy
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {"id": "start", "data": {"type": "start", "variables": []}},
                {
                    "id": "http",
                    "data": http_data,
                },
                {"id": "end", "data": {"type": "end", "outputs": []}},
            ],
            "edges": [
                {"source": "start", "target": "http", "sourceHandle": "source"},
                {"source": "http", "target": "end", "sourceHandle": source_handle},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )

    errors = validate_graph(graph=graph, mode="workflow")
    handle_errors = [error for error in errors if error.get("node_id") == "http" and "handle" in error["detail"]]

    assert (not handle_errors) is expected_valid


@pytest.mark.parametrize(
    ("source_handle", "error_strategy", "expected_valid"),
    [
        ("source", None, True),
        ("unexpected", None, False),
        ("fail-branch", None, False),
        ("fail-branch", "fail-branch", True),
    ],
)
def test_validate_graph_checks_tool_output_handle(
    source_handle: str,
    error_strategy: str | None,
    expected_valid: bool,
) -> None:
    tool_data: dict[str, object] = {
        "type": "tool",
        "provider_id": "search",
        "provider_type": "builtin",
        "provider_name": "search",
        "tool_name": "search",
        "tool_label": "Search",
        "tool_configurations": {},
        "tool_parameters": {"query": {"type": "constant", "value": "q"}},
    }
    if error_strategy:
        tool_data["error_strategy"] = error_strategy
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {"id": "start", "data": {"type": "start", "variables": []}},
                {"id": "tool", "data": tool_data},
                {"id": "end", "data": {"type": "end", "outputs": []}},
            ],
            "edges": [
                {"source": "start", "target": "tool", "sourceHandle": "source"},
                {"source": "tool", "target": "end", "sourceHandle": source_handle},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )

    errors = validate_graph(graph=graph, mode="workflow")
    handle_errors = [error for error in errors if error.get("node_id") == "tool" and "handle" in error["detail"]]

    assert (not handle_errors) is expected_valid
    if handle_errors:
        assert handle_errors[0]["code"] == "INVALID_SCHEMA"


def _llm_output_ref_graph(*, template: str, extra_llm: dict | None = None) -> GraphDict:
    llm_data: dict[str, object] = {
        "type": "llm",
        "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
        "prompt_template": [{"role": "user", "text": "Summarize."}],
        "context": {"enabled": False, "variable_selector": []},
    }
    if extra_llm:
        llm_data.update(extra_llm)
    return cast(
        GraphDict,
        {
            "nodes": [
                {"id": "start", "data": {"type": "start", "variables": []}},
                {"id": "llm", "data": llm_data},
                {
                    "id": "out",
                    "data": {
                        "type": "template-transform",
                        "template": template,
                        "variables": [{"variable": "value", "value_selector": ["llm", "text"]}],
                    },
                },
                {
                    "id": "end",
                    "data": {
                        "type": "end",
                        "outputs": [
                            {"variable": "result", "value_selector": ["out", "output"], "value_type": "string"}
                        ],
                    },
                },
            ],
            "edges": [
                {"source": "start", "target": "llm"},
                {"source": "llm", "target": "out"},
                {"source": "out", "target": "end"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )


def test_validate_graph_accepts_official_llm_outputs():
    graph = _llm_output_ref_graph(
        template="{{#llm.text#}} {{#llm.reasoning_content#}} {{#llm.usage#}} {{#llm.structured_output.summary#}}",
        extra_llm={
            "structured_output_enabled": True,
            "structured_output": {"schema": {"type": "object", "properties": {"summary": {"type": "string"}}}},
        },
    )

    errors = validate_graph(graph=graph, mode="workflow")

    assert not any(error["code"] in {"UNRESOLVED_REFERENCE", "UNKNOWN_NODE_REFERENCE"} for error in errors)


def test_validate_graph_rejects_undeclared_llm_output_and_flattened_schema_fields():
    missing = validate_graph(graph=_llm_output_ref_graph(template="{{#llm.missing#}}"), mode="workflow")
    flattened = validate_graph(
        graph=_llm_output_ref_graph(
            template="{{#llm.summary#}}",
            extra_llm={
                "structured_output_enabled": True,
                "structured_output": {"schema": {"type": "object", "properties": {"summary": {"type": "string"}}}},
            },
        ),
        mode="workflow",
    )

    assert any(error["code"] == "UNRESOLVED_REFERENCE" and "llm.missing" in error["detail"] for error in missing)
    assert any(error["code"] == "UNRESOLVED_REFERENCE" and "llm.summary" in error["detail"] for error in flattened)


from ._runner_test_support import (
    GraphValidator,
    WorkflowGenerator,
    _GraphFixtureModel,
    json,
)


@pytest.mark.parametrize(
    ("mode", "wrong_type"),
    [("workflow", "answer"), ("advanced-chat", "end")],
)
def test_response_node_type_must_match_mode(mode, wrong_type):
    nodes = [
        {"id": "start", "data": {"type": "start", "variables": []}},
        {
            "id": "wrong",
            "data": {"type": wrong_type, **({"outputs": []} if wrong_type == "end" else {"answer": "Hi"})},
        },
    ]

    errors = GraphValidator._collect_response_node_errors(nodes=nodes, edges=[], mode=mode)

    assert len(errors) == 1
    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_NODE_CONFIG
    assert errors[0]["node_id"] == "wrong"
    assert mode in errors[0]["detail"]


def test_end_node_rejects_outgoing_edges():
    nodes = [
        {"id": "end", "data": {"type": "end", "outputs": []}},
        {"id": "next", "data": {"type": "template-transform", "template": "x", "variables": []}},
    ]
    edges = [{"source": "end", "target": "next"}]

    errors = GraphValidator._collect_response_node_errors(nodes=nodes, edges=edges, mode="workflow")

    assert any(error["node_id"] == "end" and "outgoing" in error["detail"] for error in errors)


def test_answer_node_allows_an_outgoing_control_edge():
    nodes = [
        {"id": "answer", "data": {"type": "answer", "answer": "Hi"}},
        {"id": "next", "data": {"type": "template-transform", "template": "x", "variables": []}},
    ]
    edges = [{"source": "answer", "target": "next"}]

    assert (
        GraphValidator._collect_response_node_errors(
            nodes=nodes,
            edges=edges,
            mode="advanced-chat",
        )
        == []
    )


def _workflow_start_node() -> dict:
    return {
        "id": "start",
        "data": {
            "type": "start",
            "variables": [
                {
                    "variable": "query",
                    "label": "Query",
                    "type": "paragraph",
                    "required": True,
                    "max_length": 4096,
                    "options": [],
                }
            ],
        },
    }


def test_validate_graph_rejects_duplicate_end_output_names():
    graph = cast(
        GraphDict,
        {
            "nodes": [
                _workflow_start_node(),
                {
                    "id": "end",
                    "data": {
                        "type": "end",
                        "outputs": [
                            {
                                "variable": "result",
                                "value_selector": ["start", "query"],
                                "value_type": "string",
                            },
                            {
                                "variable": "result",
                                "value_selector": ["start", "query"],
                                "value_type": "string",
                            },
                        ],
                    },
                },
            ],
            "edges": [{"source": "start", "target": "end"}],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )

    errors = validate_graph(graph=graph, mode="workflow")

    assert any(
        error["code"] == WorkflowGenerateErrorCode.INVALID_END_OUTPUT
        and error.get("node_id") == "end"
        and "duplicate" in error["detail"]
        for error in errors
    )


def test_validate_graph_rejects_invalid_end_output_name():
    graph = cast(
        GraphDict,
        {
            "nodes": [
                _workflow_start_node(),
                {
                    "id": "end",
                    "data": {
                        "type": "end",
                        "outputs": [
                            {
                                "variable": "1 invalid",
                                "value_selector": ["start", "query"],
                                "value_type": "string",
                            }
                        ],
                    },
                },
            ],
            "edges": [{"source": "start", "target": "end"}],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )

    errors = validate_graph(graph=graph, mode="workflow")

    assert any(
        error["code"] == WorkflowGenerateErrorCode.INVALID_END_OUTPUT
        and error.get("node_id") == "end"
        and "invalid name" in error["detail"]
        for error in errors
    )


@pytest.mark.parametrize(
    ("container_type", "start_type"),
    [("iteration", "iteration-start"), ("loop", "loop-start")],
)
def test_collect_container_errors_rejects_nested_end(container_type, start_type):
    nodes = [
        {"id": "box", "data": {"type": container_type, "start_node_id": "entry"}},
        {"id": "entry", "parentId": "box", "data": {"type": start_type}},
        {"id": "nested_end", "parentId": "box", "data": {"type": "end", "outputs": []}},
        {"id": "child", "parentId": "box", "data": {"type": "code"}},
    ]

    errors = GraphValidator._collect_container_errors(nodes=nodes)

    assert any(
        error["code"] == WorkflowGenerateErrorCode.INVALID_CONTAINER
        and error.get("node_id") == "nested_end"
        and "end" in error["detail"].lower()
        for error in errors
    )


def test_collect_container_errors_allows_nested_answer():
    nodes = [
        {"id": "box", "data": {"type": "iteration", "start_node_id": "entry"}},
        {"id": "entry", "parentId": "box", "data": {"type": "iteration-start"}},
        {"id": "answer", "parentId": "box", "data": {"type": "answer", "answer": "Hi"}},
    ]

    assert GraphValidator._collect_container_errors(nodes=nodes) == []


def test_validate_graph_rejects_end_inside_iteration():
    graph = cast(
        GraphDict,
        {
            "nodes": [
                _workflow_start_node(),
                {
                    "id": "iter",
                    "data": {
                        "type": "iteration",
                        "start_node_id": "iterstart",
                        "iterator_selector": ["start", "query"],
                        "output_selector": ["child", "text"],
                    },
                },
                {
                    "id": "iterstart",
                    "parentId": "iter",
                    "data": {"type": "iteration-start", "parentId": "iter"},
                },
                {
                    "id": "child",
                    "parentId": "iter",
                    "data": {
                        "type": "template-transform",
                        "parentId": "iter",
                        "template": "{{#iter.item#}}",
                        "variables": [],
                    },
                },
                {
                    "id": "nested_end",
                    "parentId": "iter",
                    "data": {"type": "end", "parentId": "iter", **node_config("end")},
                },
                {"id": "end", "data": {"type": "end", **node_config("end")}},
            ],
            "edges": [
                {"source": "start", "target": "iter"},
                {"source": "iterstart", "target": "child"},
                {"source": "iter", "target": "end"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )

    errors = validate_graph(graph=graph, mode="workflow")

    assert any(
        error["code"] == WorkflowGenerateErrorCode.INVALID_CONTAINER and error.get("node_id") == "nested_end"
        for error in errors
    )


def test_validate_workflow_rejects_answer_even_when_end_exists():
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {
                    "id": "start",
                    "data": {
                        "type": "start",
                        "variables": [
                            {
                                "variable": "query",
                                "label": "Query",
                                "type": "paragraph",
                                "required": True,
                                "max_length": 4096,
                                "options": [],
                            }
                        ],
                    },
                },
                {"id": "answer", "data": {"type": "answer", "answer": "intermediate"}},
                {
                    "id": "end",
                    "data": {
                        "type": "end",
                        "outputs": [
                            {
                                "variable": "result",
                                "value_selector": ["start", "query"],
                                "value_type": "string",
                            }
                        ],
                    },
                },
            ],
            "edges": [
                {"source": "start", "target": "answer"},
                {"source": "start", "target": "end"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )

    errors = validate_graph(graph=graph, mode="workflow")

    assert any(
        error["code"] == WorkflowGenerateErrorCode.INVALID_NODE_CONFIG and error.get("node_id") == "answer"
        for error in errors
    )


def test_validate_advanced_chat_rejects_end_even_when_answer_exists():
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {
                    "id": "start",
                    "data": {
                        "type": "start",
                        "variables": [
                            {
                                "variable": "query",
                                "label": "Query",
                                "type": "paragraph",
                                "required": True,
                                "max_length": 4096,
                                "options": [],
                            }
                        ],
                    },
                },
                {
                    "id": "end",
                    "data": {
                        "type": "end",
                        "outputs": [
                            {
                                "variable": "result",
                                "value_selector": ["start", "query"],
                                "value_type": "string",
                            }
                        ],
                    },
                },
                {"id": "answer", "data": {"type": "answer", "answer": "done"}},
            ],
            "edges": [
                {"source": "start", "target": "end"},
                {"source": "start", "target": "answer"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )

    errors = validate_graph(graph=graph, mode="advanced-chat")

    assert any(
        error["code"] == WorkflowGenerateErrorCode.INVALID_NODE_CONFIG and error.get("node_id") == "end"
        for error in errors
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
                        "data": {
                            "type": "llm",
                            "title": "LLM",
                            "prompt_template": [{"role": "user", "text": "Process the input."}],
                        },
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
    agent_errors = GraphValidator._collect_unknown_tools(
        nodes=agent_nodes, installed_tools={("github-official", "get_file_contents")}
    )
    assert any(item["code"] == "UNKNOWN_TOOL" for item in agent_errors)


def test_human_input_edges_accept_action_and_timeout_handles():
    nodes = [
        {
            "id": "review",
            "data": {
                "type": "human-input",
                "user_actions": [{"id": "approve"}, {"id": "reject"}],
            },
        }
    ]
    edges = [
        {"source": "review", "target": "accepted", "sourceHandle": "approve"},
        {"source": "review", "target": "rejected", "sourceHandle": "reject"},
        {"source": "review", "target": "expired", "sourceHandle": "__timeout"},
    ]

    errors = GraphValidator._collect_human_input_edge_errors(nodes=nodes, edges=edges)

    assert errors == []


def test_human_input_edges_reject_unknown_timeout_handle():
    nodes = [
        {
            "id": "review",
            "data": {"type": "human-input", "user_actions": [{"id": "approve"}]},
        }
    ]
    edges = [{"source": "review", "target": "expired", "sourceHandle": "timeout"}]

    errors = GraphValidator._collect_human_input_edge_errors(nodes=nodes, edges=edges)

    assert len(errors) == 1
    assert errors[0]["code"] == "INVALID_SCHEMA"
    assert "__timeout" in errors[0]["detail"]


def test_human_input_edges_reject_empty_and_source_handles():
    nodes = [
        {
            "id": "review",
            "data": {"type": "human-input", "user_actions": [{"id": "approve"}]},
        }
    ]
    errors = GraphValidator._collect_human_input_edge_errors(
        nodes=nodes,
        edges=[
            {"source": "review", "target": "end"},
            {"source": "review", "target": "end", "sourceHandle": "source"},
        ],
    )
    assert len(errors) == 2
    assert all(item["code"] == "INVALID_SCHEMA" for item in errors)


def test_if_else_edges_accept_declared_case_ids_and_implicit_else():
    first_case_id = "b61c92c8-2398-44e9-871a-278428a14c75"
    nodes = [
        {
            "id": "branch",
            "data": {
                "type": "if-else",
                "cases": [
                    {"case_id": first_case_id},
                    {"case_id": "2398798f-d51c-443e-861d-19de88c86874"},
                ],
            },
        }
    ]
    edges = [
        {"source": "branch", "target": "if", "sourceHandle": first_case_id},
        {"source": "branch", "target": "else", "sourceHandle": "false"},
    ]

    assert GraphValidator._collect_branch_edge_errors(nodes=nodes, edges=edges) == []


@pytest.mark.parametrize("source_handle", [None, "source", "true", "missing-case"])
def test_if_else_edges_reject_handles_not_declared_by_cases(source_handle: str | None):
    case_id = "b61c92c8-2398-44e9-871a-278428a14c75"
    nodes = [{"id": "branch", "data": {"type": "if-else", "cases": [{"case_id": case_id}]}}]
    edges = [{"source": "branch", "target": "next", "sourceHandle": source_handle}]

    errors = GraphValidator._collect_branch_edge_errors(nodes=nodes, edges=edges)

    assert len(errors) == 1
    assert errors[0]["code"] == "INVALID_SCHEMA"
    assert case_id in errors[0]["detail"]
    assert "false" in errors[0]["detail"]


def test_generated_official_if_else_survives_postprocess_and_full_validation():
    case_id = "b61c92c8-2398-44e9-871a-278428a14c75"
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {
                    "id": "start",
                    "data": {
                        "type": "start",
                        "variables": [{"variable": "query", "label": "Query", "type": "text-input", "required": False}],
                    },
                },
                {
                    "id": "branch",
                    "data": {
                        "type": "if-else",
                        "cases": [
                            {
                                "case_id": case_id,
                                "logical_operator": "and",
                                "conditions": [
                                    {
                                        "id": "condition-1",
                                        "varType": "string",
                                        "variable_selector": ["start", "query"],
                                        "comparison_operator": "is null",
                                        "value": "",
                                    }
                                ],
                            }
                        ],
                        "_targetBranches": [{"id": "stale", "name": "STALE"}],
                    },
                },
                {"id": "if_end", "data": {"type": "end", **node_config("end")}},
                {"id": "else_end", "data": {"type": "end", **node_config("end")}},
            ],
            "edges": [
                {"source": "start", "target": "branch"},
                {"source": "branch", "target": "if_end", "sourceHandle": case_id},
                {"source": "branch", "target": "else_end", "sourceHandle": "false"},
            ],
            "viewport": {"x": 0.0, "y": 0.0, "zoom": 0.7},
        },
    )

    generated = postprocess_graph(graph=deepcopy(graph), mode="workflow")
    errors = validate_graph(graph=generated, mode="workflow")
    branch = next(node for node in generated["nodes"] if node["id"] == "branch")

    assert errors == []
    assert branch["data"]["cases"][0]["case_id"] == case_id
    assert branch["data"]["cases"][0]["conditions"][0]["comparison_operator"] == "is null"
    assert branch["data"]["_targetBranches"] == [
        {"id": case_id, "name": "IF"},
        {"id": "false", "name": "ELSE"},
    ]


def test_question_classifier_edges_share_strict_declared_branch_handle_validation():
    nodes = [
        {
            "id": "classify",
            "data": {
                "type": "question-classifier",
                "classes": [{"id": "billing"}, {"id": "support"}],
            },
        }
    ]
    edges = [
        {"source": "classify", "target": "a", "sourceHandle": "billing"},
        {"source": "classify", "target": "b", "sourceHandle": "unknown"},
    ]

    errors = GraphValidator._collect_branch_edge_errors(nodes=nodes, edges=edges)

    assert len(errors) == 1
    assert errors[0]["node_id"] == "classify"
    assert "unknown" in errors[0]["detail"]
    assert "billing" in errors[0]["detail"]


def test_collect_unknown_dataset_ids_in_agent_knowledge() -> None:
    nodes = [
        {
            "id": "ag1",
            "data": {
                "type": "agent",
                "knowledge": {
                    "sets": [
                        {
                            "datasets": [
                                {"id": "ds-installed"},
                                {"id": "ds-missing"},
                            ]
                        }
                    ]
                },
            },
        }
    ]

    errors = GraphValidator._collect_unknown_dataset_ids(
        nodes=nodes,
        installed_dataset_ids={"ds-installed"},
    )

    assert errors == [
        {
            "code": "UNKNOWN_DATASET",
            "detail": "Agent node 'ag1' references uninstalled datasets: ds-missing",
            "node_id": "ag1",
        }
    ]


def test_collect_unresolved_refs():

    # Missing node ref
    nodes = [{"id": "n1", "data": {"type": "llm", "prompt_template": [{"text": "{{#unknown.var#}}"}]}}]
    # To trigger the parsing we need to mock _collect_refs_in_data behavior or let it parse naturally
    # If the ref parsing finds "unknown", "var", it will check by_id

    # Actually _collect_refs_in_data modifies the set

    errors = GraphValidator._collect_unresolved_refs(nodes=nodes, mode="workflow")
    assert len(errors) >= 1
    assert errors[0]["code"] == "UNKNOWN_NODE_REFERENCE"


def _iteration_graph_nodes() -> list[dict]:
    return [
        {"id": "start", "data": {"type": "start", "variables": [{"variable": "questions"}]}},
        {
            "id": "node_iter",
            "data": {
                "type": "iteration",
                "iterator_selector": ["start", "questions"],
                "output_selector": ["node_assemble", "result"],
            },
        },
        {
            "id": "node_retrieval",
            "parentId": "node_iter",
            "data": {
                "type": "knowledge-retrieval",
                "query_variable_selector": ["node_iter", "item", "question"],
            },
        },
        {
            "id": "node_assemble",
            "parentId": "node_iter",
            "data": {
                "type": "code",
                "variables": [
                    {"variable": "item", "value_selector": ["node_iter", "item"]},
                    {"variable": "index", "value_selector": ["node_iter", "index"]},
                ],
                "outputs": {"result": {"type": "object"}},
            },
        },
        {
            "id": "node_end",
            "data": {
                "type": "end",
                "outputs": [{"variable": "report", "value_selector": ["node_iter", "output"]}],
            },
        },
    ]


def test_iteration_child_may_reference_item_index_and_nested_fields():
    errors = GraphValidator._collect_unresolved_refs(nodes=_iteration_graph_nodes(), mode="workflow")
    assert errors == []


def test_node_outside_iteration_cannot_reference_item():
    nodes = _iteration_graph_nodes()
    nodes[-1]["data"]["outputs"] = [{"variable": "report", "value_selector": ["node_iter", "item"]}]

    errors = GraphValidator._collect_unresolved_refs(nodes=nodes, mode="workflow")

    assert any(error["code"] == "UNRESOLVED_REFERENCE" and "node_iter.item" in error["detail"] for error in errors)


def test_node_outside_iteration_cannot_reference_inner_child_output():
    nodes = _iteration_graph_nodes()
    nodes[-1]["data"]["outputs"] = [{"variable": "report", "value_selector": ["node_assemble", "result"]}]

    errors = GraphValidator._collect_unresolved_refs(nodes=nodes, mode="workflow")

    assert any(
        error["code"] == "UNRESOLVED_REFERENCE" and "node_assemble.result" in error["detail"] for error in errors
    )


def test_nested_selector_is_visible_to_unresolved_ref_collection():
    nodes = [
        {"id": "start", "data": {"type": "start", "variables": [{"variable": "query"}]}},
        {
            "id": "code1",
            "data": {
                "type": "code",
                "outputs": {"result": {"type": "object"}},
            },
        },
        {
            "id": "llm1",
            "data": {
                "type": "llm",
                "prompt_template": [{"text": "{{#code1.result.foo#}}"}],
                "context": {"enabled": True, "variable_selector": ["code1", "result", "foo"]},
            },
        },
    ]

    errors = GraphValidator._collect_unresolved_refs(nodes=nodes, mode="workflow")
    assert errors == []


def test_downstream_may_reference_agent_default_text_output():
    nodes = [
        {"id": "start", "data": {"type": "start", "variables": [{"variable": "query"}]}},
        {"id": "node_agent_gen", "data": {"type": "agent", "agent_task": "出题"}},
        {
            "id": "node_end",
            "data": {
                "type": "end",
                "outputs": [{"variable": "questions", "value_selector": ["node_agent_gen", "text"]}],
            },
        },
    ]

    errors = GraphValidator._collect_unresolved_refs(nodes=nodes, mode="workflow")
    assert errors == []


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


def test_collect_container_errors_rejects_wrong_start_node_type():
    nodes = [
        {"id": "loop", "data": {"type": "loop", "start_node_id": "entry"}},
        {"id": "entry", "parentId": "loop", "data": {"type": "iteration-start"}},
        {"id": "child", "parentId": "loop", "data": {"type": "code"}},
    ]

    errors = GraphValidator._collect_container_errors(nodes=nodes)

    assert any(error["code"] == "INVALID_CONTAINER" and "loop-start" in error["detail"] for error in errors)


def test_collect_dangling_id_refs_rejects_missing_container_start_node():
    nodes = [{"id": "loop", "data": {"type": "loop", "start_node_id": "missing-entry"}}]

    errors = GraphValidator._collect_dangling_id_refs(nodes=nodes, known_ids={"loop"})

    assert len(errors) == 1
    assert errors[0]["code"] == "UNKNOWN_NODE_REFERENCE"
    assert "start_node_id" in errors[0]["detail"]


def test_collect_container_errors_rejects_start_owned_by_another_container():
    nodes = [
        {"id": "outer", "data": {"type": "iteration", "start_node_id": "entry"}},
        {"id": "other", "data": {"type": "iteration", "start_node_id": "other-entry"}},
        {"id": "entry", "parentId": "other", "data": {"type": "iteration-start"}},
        {"id": "other-entry", "parentId": "other", "data": {"type": "iteration-start"}},
        {"id": "outer-child", "parentId": "outer", "data": {"type": "code"}},
        {"id": "other-child", "parentId": "other", "data": {"type": "code"}},
    ]

    errors = GraphValidator._collect_container_errors(nodes=nodes)

    assert any(error["code"] == "INVALID_CONTAINER" and "owned by" in error["detail"] for error in errors)


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


def test_sys_files_is_valid_in_workflow_and_query_is_not():
    nodes = [
        {"id": "start", "data": {"type": "start", "variables": []}},
        {
            "id": "llm1",
            "data": {"type": "llm", "prompt_template": [{"text": "{{#sys.files#}} {{#sys.query#}}"}]},
        },
        {"id": "end", "data": {"type": "end", "outputs": []}},
    ]

    errors = GraphValidator._collect_unresolved_refs(nodes=nodes, mode="workflow")

    details = [error["detail"] for error in errors]
    assert any("sys.query" in detail for detail in details)
    assert not any("sys.files" in detail for detail in details)


def test_env_and_conversation_unknown_names_fail_when_declarations_are_empty():
    nodes = [
        {"id": "start", "data": {"type": "start", "variables": []}},
        {
            "id": "llm1",
            "data": {"type": "llm", "prompt_template": [{"text": "{{#env.API_KEY#}} {{#conversation.topic#}}"}]},
        },
    ]

    errors = GraphValidator._collect_unresolved_refs(
        nodes=nodes,
        mode="advanced-chat",
        environment_variables=set(),
        conversation_variables=set(),
    )

    details = [error["detail"] for error in errors]
    assert any("env.API_KEY" in detail for detail in details)
    assert any("conversation.topic" in detail for detail in details)


def test_env_load_failure_skips_membership_check():
    nodes = [
        {"id": "start", "data": {"type": "start", "variables": []}},
        {"id": "llm1", "data": {"type": "llm", "prompt_template": [{"text": "{{#env.API_KEY#}}"}]}},
    ]

    errors = GraphValidator._collect_unresolved_refs(
        nodes=nodes,
        mode="workflow",
        environment_variables=None,
    )

    assert errors == []


def test_multi_selector_parameter_extractor_query_is_invalid_schema():
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {"id": "start", "data": {"type": "start", "variables": [{"variable": "query"}]}},
                {
                    "id": "pe1",
                    "data": {
                        "type": "parameter-extractor",
                        "query": [["start", "query"], ["start", "query"]],
                        "parameters": [{"name": "topic", "type": "string", "description": "t", "required": True}],
                    },
                },
                {"id": "end", "data": {"type": "end", "outputs": []}},
            ],
            "edges": [{"source": "start", "target": "pe1"}, {"source": "pe1", "target": "end"}],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )

    errors = validate_graph(graph=graph, mode="workflow")

    assert any(error["code"] == "INVALID_SCHEMA" and error.get("node_id") == "pe1" for error in errors)


def test_nested_container_cannot_read_inner_private_nodes():
    nodes = [
        {"id": "start", "data": {"type": "start", "variables": [{"variable": "rows"}]}},
        {"id": "outer", "data": {"type": "iteration", "iterator_selector": ["start", "rows"]}},
        {
            "id": "inner",
            "parentId": "outer",
            "data": {"type": "iteration", "iterator_selector": ["outer", "item"]},
        },
        {
            "id": "secret",
            "parentId": "inner",
            "data": {"type": "code", "outputs": {"result": {"type": "string"}}},
        },
        {
            "id": "outer_child",
            "parentId": "outer",
            "data": {
                "type": "llm",
                "prompt_template": [{"text": "{{#secret.result#}}"}],
            },
        },
    ]

    errors = GraphValidator._collect_unresolved_refs(nodes=nodes, mode="workflow")

    assert any(error["code"] == "UNRESOLVED_REFERENCE" and "secret.result" in error["detail"] for error in errors)


def test_unknown_tool_parameter_fails_only_when_schema_is_known():
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {"id": "start", "data": {"type": "start", "variables": []}},
                {
                    "id": "t1",
                    "data": {
                        "type": "tool",
                        "provider_id": "google",
                        "provider_name": "google",
                        "tool_name": "search",
                        "tool_parameters": {"bogus": {"type": "constant", "value": "x"}},
                    },
                },
                {"id": "end", "data": {"type": "end", "outputs": []}},
            ],
            "edges": [
                {"source": "start", "target": "t1"},
                {"source": "t1", "target": "end"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )

    known = validate_graph(
        graph=graph,
        mode="workflow",
        tool_parameter_names={("google", "search"): frozenset({"q"})},
    )
    skipped = validate_graph(graph=graph, mode="workflow")
    other_tool = validate_graph(
        graph=graph,
        mode="workflow",
        tool_parameter_names={("time", "now"): frozenset({"q"})},
    )

    assert any(error["code"] == "INVALID_SCHEMA" and "bogus" in error["detail"] for error in known)
    assert not any("bogus" in error.get("detail", "") for error in skipped)
    assert not any("bogus" in error.get("detail", "") for error in other_tool)


def _required_tool_graph(parameters: dict[str, object]) -> GraphDict:
    return cast(
        GraphDict,
        {
            "nodes": [
                {"id": "start", "data": {"type": "start", "variables": []}},
                {
                    "id": "tool_1",
                    "data": {
                        "type": "tool",
                        "provider_id": "image/provider",
                        "provider_name": "image/provider",
                        "tool_name": "generate",
                        "tool_parameters": parameters,
                    },
                },
                {"id": "end", "data": {"type": "end", "outputs": []}},
            ],
            "edges": [{"source": "start", "target": "tool_1"}, {"source": "tool_1", "target": "end"}],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )


def _required_tool_entry(*, include_schema: bool = True) -> dict[str, object]:
    entry: dict[str, object] = {
        "provider_name": "image/provider",
        "provider_type": "builtin",
        "plugin_id": "image/provider",
        "tool_name": "generate",
        "tool_label": "Generate",
        "description": "Generate an image",
    }
    if include_schema:
        entry["parameters"] = (
            {"name": "prompt", "type": "string", "form": "llm", "required": True},
            {"name": "image", "type": "file", "form": "llm", "required": True},
            {"name": "size", "type": "select", "form": "form", "required": False, "default": "2K"},
        )
    return entry


def test_known_tool_schema_reports_missing_required_non_file_with_node_id() -> None:
    errors = validate_graph(
        graph=_required_tool_graph({}),
        mode="workflow",
        tool_entries=[_required_tool_entry()],
    )

    assert any(
        error["code"] == "INVALID_NODE_CONFIG" and error.get("node_id") == "tool_1" and "prompt" in error["detail"]
        for error in errors
    )


def test_known_tool_schema_reports_missing_required_file_with_node_id() -> None:
    graph = _required_tool_graph({"prompt": {"type": "constant", "value": "draw"}})

    errors = validate_graph(graph=graph, mode="workflow", tool_entries=[_required_tool_entry()])

    assert any(
        error["code"] == "INVALID_NODE_CONFIG" and error.get("node_id") == "tool_1" and "image" in error["detail"]
        for error in errors
    )


def test_missing_optional_file_is_allowed() -> None:
    entry = _required_tool_entry()
    entry["parameters"] = (
        {"name": "prompt", "type": "string", "form": "llm", "required": True},
        {"name": "image", "type": "file", "form": "llm", "required": False},
        {"name": "size", "type": "select", "form": "form", "required": False, "default": "2K"},
    )
    graph = _required_tool_graph({"prompt": {"type": "constant", "value": "draw"}})

    errors = validate_graph(graph=graph, mode="workflow", tool_entries=[entry])

    assert not any("missing required parameter" in error["detail"] for error in errors)


def test_normalized_tool_default_satisfies_validation() -> None:
    entry = _required_tool_entry()
    graph = _required_tool_graph({"prompt": {"type": "constant", "value": "draw"}})
    apply_tool_parameters_to_graph(graph["nodes"], [entry])

    errors = validate_graph(graph=graph, mode="workflow", tool_entries=[entry])

    assert not any(error["code"] == "INVALID_NODE_CONFIG" and "size" in error["detail"] for error in errors)
    tool = next(node for node in graph["nodes"] if node["id"] == "tool_1")
    assert tool["data"]["tool_parameters"]["size"] == {"type": "constant", "value": "2K"}


def test_unknown_tool_schema_skips_required_parameter_check() -> None:
    errors = validate_graph(
        graph=_required_tool_graph({}),
        mode="workflow",
        tool_entries=[_required_tool_entry(include_schema=False)],
    )

    assert not any("missing required parameter" in error["detail"] for error in errors)


def test_unknown_tool_output_fails_only_when_schema_is_known():
    nodes = [
        {"id": "start", "data": {"type": "start", "variables": []}},
        {
            "id": "t1",
            "data": {"type": "tool", "provider_id": "google", "provider_name": "google", "tool_name": "search"},
        },
        {
            "id": "llm1",
            "data": {"type": "llm", "prompt_template": [{"text": "{{#t1.mystery#}} {{#t1.text#}}"}]},
        },
    ]

    known = GraphValidator._collect_unresolved_refs(
        nodes=nodes,
        mode="workflow",
        tool_output_names={("google", "search"): frozenset({"text"})},
    )
    skipped = GraphValidator._collect_unresolved_refs(nodes=nodes, mode="workflow")

    details = [error["detail"] for error in known]
    assert any("t1.mystery" in detail for detail in details)
    assert not any("t1.text" in detail for detail in details)
    assert skipped == []


def _start_to_document_extractor_graph(input_type: str) -> GraphDict:
    return cast(
        GraphDict,
        {
            "nodes": [
                {
                    "id": "start",
                    "data": {
                        "type": "start",
                        "variables": [
                            {
                                "variable": "document",
                                "label": "Document",
                                "type": input_type,
                                **(
                                    {
                                        "allowed_file_types": ["document"],
                                        "allowed_file_upload_methods": ["local_file"],
                                    }
                                    if input_type in {"file", "file-list"}
                                    else {}
                                ),
                            }
                        ],
                    },
                },
                {
                    "id": "extract",
                    "data": {
                        "type": "document-extractor",
                        "variable_selector": ["start", "document"],
                    },
                },
                {
                    "id": "end",
                    "data": {
                        "type": "end",
                        "outputs": [
                            {"variable": "text", "value_selector": ["extract", "text"], "value_type": "string"}
                        ],
                    },
                },
            ],
            "edges": [
                {"source": "start", "target": "extract"},
                {"source": "extract", "target": "end"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )


def test_document_extractor_rejects_non_file_start_variable() -> None:
    errors = validate_graph(graph=_start_to_document_extractor_graph("paragraph"), mode="workflow")

    error = next(error for error in errors if error["code"] == "INVALID_NODE_CONFIG")
    assert error["node_id"] == "extract"
    assert "start.document" in error["detail"]
    assert "paragraph" in error["detail"]
    assert "file-list" in error["detail"]


@pytest.mark.parametrize("input_type", ["file", "file-list"])
def test_document_extractor_accepts_file_start_variables(input_type: str) -> None:
    errors = validate_graph(graph=_start_to_document_extractor_graph(input_type), mode="workflow")

    assert not any(error["code"] == "INVALID_NODE_CONFIG" and error.get("node_id") == "extract" for error in errors)


def iteration_graph(*, output_selector: list[str], child_type: str = "code") -> GraphDict:
    return {
        "nodes": [
            {"id": "start", "data": {"type": "start", "variables": []}},
            {
                "id": "iter",
                "data": {
                    "type": "iteration",
                    "start_node_id": "iterstart",
                    "iterator_selector": ["seed", "items"],
                    "output_selector": output_selector,
                },
            },
            {"id": "iterstart", "parentId": "iter", "data": {"type": "iteration-start"}},
            {
                "id": "child",
                "parentId": "iter",
                "data": {"type": child_type, "outputs": {"result": {"type": "number"}}},
            },
            {
                "id": "human",
                "parentId": "iter",
                "data": {
                    "type": "human-input",
                    "form_content": "Review",
                    "delivery_methods": [{"type": "webapp", "enabled": True}],
                    "user_actions": [{"id": "approve", "title": "Approve", "button_style": "primary"}],
                    "inputs": [{"type": "paragraph", "output_variable_name": "comment"}],
                },
            },
            {"id": "seed", "data": {"type": "code", "outputs": {"items": {"type": "array[number]"}}}},
            {"id": "outside", "data": {"type": "code", "outputs": {"result": {"type": "number"}}}},
            {"id": "end", "data": {"type": "end", "outputs": []}},
        ],
        "edges": [
            {"source": "start", "target": "seed"},
            {"source": "seed", "target": "iter"},
            {"source": "iterstart", "target": "child"},
            {"source": "iter", "target": "end"},
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def test_iteration_output_selector_rejects_a_node_outside_the_container() -> None:
    graph = cast(GraphDict, iteration_graph(output_selector=["outside", "result"]))
    errors = GraphValidator._validate_structure(graph=graph, mode="workflow")
    assert any(
        error["code"] == WorkflowGenerateErrorCode.INVALID_CONTAINER and error.get("node_id") == "iter"
        for error in errors
    )


def test_iteration_output_selector_accepts_direct_human_input_output() -> None:
    graph = cast(GraphDict, iteration_graph(output_selector=["human", "comment"]))
    errors = GraphValidator._validate_structure(graph=graph, mode="workflow")
    assert not [error for error in errors if error.get("node_id") == "iter"]


def test_iteration_iterator_selector_rejects_a_scalar_source() -> None:
    graph = cast(GraphDict, iteration_graph(output_selector=["child", "result"]))
    for node in graph["nodes"]:
        if node["id"] == "seed":
            node["data"]["outputs"] = {"items": {"type": "number"}}
        if node["id"] == "iter":
            node["data"]["iterator_input_type"] = "array"
    errors = validate_graph(graph=graph, mode="workflow")
    assert any(
        error["code"] == WorkflowGenerateErrorCode.INVALID_NODE_CONFIG and error.get("node_id") == "iter"
        for error in errors
    )


def test_loop_end_must_be_a_direct_child_and_unique() -> None:
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {"id": "start", "data": {"type": "start", "variables": []}},
                {
                    "id": "loop",
                    "data": {
                        "type": "loop",
                        "start_node_id": "loopstart",
                        "loop_count": 1,
                        "logical_operator": "and",
                        "break_conditions": [],
                        "loop_variables": [],
                    },
                },
                {"id": "loopstart", "parentId": "loop", "data": {"type": "loop-start"}},
                {"id": "exit-a", "parentId": "loop", "data": {"type": "loop-end", "loop_id": "loop"}},
                {"id": "exit-b", "parentId": "loop", "data": {"type": "loop-end", "loop_id": "loop"}},
                {"id": "end", "data": {"type": "end", "outputs": []}},
            ],
            "edges": [
                {"source": "start", "target": "loop"},
                {"source": "loopstart", "target": "exit-a"},
                {"source": "loop", "target": "end"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
    )
    errors = GraphValidator._validate_structure(graph=graph, mode="workflow")
    assert any(
        error["code"] == WorkflowGenerateErrorCode.INVALID_CONTAINER and error.get("node_id") == "loop"
        for error in errors
    )


def test_loop_end_rejects_data_parent_id_without_wrapper() -> None:
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {"id": "start", "data": {"type": "start", "variables": []}},
                {
                    "id": "loop",
                    "data": {
                        "type": "loop",
                        "start_node_id": "loopstart",
                        "loop_count": 1,
                        "logical_operator": "and",
                        "break_conditions": [],
                        "loop_variables": [],
                    },
                },
                {"id": "loopstart", "parentId": "loop", "data": {"type": "loop-start"}},
                {
                    "id": "child",
                    "parentId": "loop",
                    "data": {"type": "code", "outputs": {"result": {"type": "number"}}},
                },
                {"id": "exit", "data": {"type": "loop-end", "parentId": "loop", "loop_id": "loop"}},
                {"id": "end", "data": {"type": "end", "outputs": []}},
            ],
            "edges": [
                {"source": "start", "target": "loop"},
                {"source": "loopstart", "target": "child"},
                {"source": "loop", "target": "end"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
    )
    errors = GraphValidator._validate_structure(graph=graph, mode="workflow")
    assert any(
        error["code"] == WorkflowGenerateErrorCode.INVALID_CONTAINER and error.get("node_id") == "exit"
        for error in errors
    )


def test_loop_end_rejects_missing_data_loop_id() -> None:
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {"id": "start", "data": {"type": "start", "variables": []}},
                {
                    "id": "loop",
                    "data": {
                        "type": "loop",
                        "start_node_id": "loopstart",
                        "loop_count": 1,
                        "logical_operator": "and",
                        "break_conditions": [],
                        "loop_variables": [],
                    },
                },
                {"id": "loopstart", "parentId": "loop", "data": {"type": "loop-start"}},
                {"id": "exit", "parentId": "loop", "data": {"type": "loop-end"}},
                {"id": "end", "data": {"type": "end", "outputs": []}},
            ],
            "edges": [
                {"source": "start", "target": "loop"},
                {"source": "loopstart", "target": "exit"},
                {"source": "loop", "target": "end"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
    )
    errors = GraphValidator._validate_structure(graph=graph, mode="workflow")
    assert any(
        error["code"] == WorkflowGenerateErrorCode.INVALID_CONTAINER and error.get("node_id") == "exit"
        for error in errors
    )
