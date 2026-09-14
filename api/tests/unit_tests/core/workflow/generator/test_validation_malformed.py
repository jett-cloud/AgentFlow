import pytest

from core.workflow.generator.validation.graph_validator import validate_graph
from core.workflow.generator.validation.node_config_validator import collect_node_config_errors


@pytest.mark.parametrize("value", [[], {}, None, 42])
def test_bad_code_type_is_an_observation(value):
    errors = collect_node_config_errors(
        [{"id": "code", "data": {"type": "code", "outputs": {"result": {"type": value}}}}]
    )
    assert errors[0]["code"] == "INVALID_CODE_OUTPUT"
    assert "result" in errors[0]["detail"]


@pytest.mark.parametrize("value", [[], {}, 42])
def test_bad_end_type_is_an_observation(value):
    errors = collect_node_config_errors(
        [
            {
                "id": "end",
                "data": {
                    "type": "end",
                    "outputs": [{"variable": "result", "value_selector": ["start", "q"], "value_type": value}],
                },
            }
        ]
    )
    assert errors[0]["code"] == "INVALID_END_OUTPUT"


@pytest.mark.parametrize(
    "graph",
    [
        {"nodes": [42], "edges": []},
        {"nodes": [{"id": "n", "data": []}], "edges": []},
        {"nodes": [{"id": [], "data": {"type": "start"}}], "edges": []},
        {"nodes": [{"id": "n", "data": {"type": "start"}}], "edges": [42]},
        {"nodes": {}, "edges": []},
    ],
)
def test_malformed_graph_is_an_observation(graph):
    assert validate_graph(graph=graph, mode="workflow")[0]["code"] == "INVALID_SCHEMA"


@pytest.mark.parametrize("bad_outputs", [42, [42], {"result": {"type": []}}])
def test_malformed_outputs_with_downstream_reference_do_not_crash(bad_outputs):
    graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start"}},
            {"id": "code", "data": {"type": "code", "outputs": bad_outputs}},
            {
                "id": "end",
                "data": {
                    "type": "end",
                    "outputs": [{"variable": "result", "value_type": "any", "value_selector": ["code", "result"]}],
                },
            },
        ],
        "edges": [{"source": "start", "target": "code"}, {"source": "code", "target": "end"}],
    }
    assert any(e["code"] == "INVALID_CODE_OUTPUT" for e in validate_graph(graph=graph, mode="workflow"))
