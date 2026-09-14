import pytest

from core.workflow.generator.variables.reference_availability import collect_reference_availability_errors


def test_downstream_and_self_references_are_not_available():
    graph = {
        "nodes": [
            {"id": "a", "data": {"type": "llm", "prompt_template": "{{#b.text#}} {{#a.text#}}"}},
            {"id": "b", "data": {"type": "llm"}},
        ],
        "edges": [{"source": "a", "target": "b"}],
    }
    errors = collect_reference_availability_errors(graph)
    assert len(errors) == 2
    assert all(e["node_id"] == "a" for e in errors)


def test_upstream_reference_is_available():
    graph = {
        "nodes": [
            {"id": "a", "data": {"type": "llm"}},
            {"id": "b", "data": {"type": "llm", "prompt_template": "{{#a.text#}}"}},
        ],
        "edges": [{"source": "a", "target": "b"}],
    }
    assert collect_reference_availability_errors(graph) == []


@pytest.mark.parametrize(("consumer_type", "expected_errors"), [("llm", 1), ("variable-aggregator", 0)])
def test_exclusive_branch_outputs_require_an_aggregator(consumer_type, expected_errors):
    graph = {
        "nodes": [
            {"id": "branch", "data": {"type": "if-else"}},
            {"id": "yes", "data": {"type": "llm"}},
            {"id": "no", "data": {"type": "llm"}},
            {"id": "join", "data": {"type": consumer_type, "variables": [["yes", "text"]]}},
        ],
        "edges": [
            {"source": "branch", "target": "yes", "sourceHandle": "true"},
            {"source": "branch", "target": "no", "sourceHandle": "false"},
            {"source": "yes", "target": "join"},
            {"source": "no", "target": "join"},
        ],
    }
    assert len(collect_reference_availability_errors(graph)) == expected_errors


def test_parallel_sibling_is_not_an_upstream_dependency():
    graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start"}},
            {"id": "a", "data": {"type": "llm"}},
            {"id": "b", "data": {"type": "llm", "prompt_template": "{{#a.text#}}"}},
        ],
        "edges": [{"source": "start", "target": "a"}, {"source": "start", "target": "b"}],
    }
    assert collect_reference_availability_errors(graph)[0]["node_id"] == "b"


def test_container_values_and_ancestor_dependencies_are_available():
    graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start"}},
            {"id": "iteration", "data": {"type": "iteration", "output_selector": ["child", "text"]}},
            {
                "id": "child",
                "parentId": "iteration",
                "data": {"type": "llm", "prompt_template": "{{#iteration.item#}} {{#start.query#}} {{#env.secret#}}"},
            },
        ],
        "edges": [{"source": "start", "target": "iteration"}],
    }
    assert collect_reference_availability_errors(graph) == []


def test_loop_break_condition_may_read_its_declared_loop_variable():
    graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start"}},
            {
                "id": "loop",
                "data": {
                    "type": "loop",
                    "loop_variables": [{"label": "i", "var_type": "number", "value_type": "constant", "value": 0}],
                    "break_conditions": [
                        {
                            "variable_selector": ["loop", "i"],
                            "comparison_operator": "≥",
                            "value": 2,
                        }
                    ],
                },
            },
        ],
        "edges": [{"source": "start", "target": "loop"}],
    }

    assert collect_reference_availability_errors(graph) == []
