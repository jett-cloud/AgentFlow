from copy import deepcopy

from core.workflow.graph.adapters.if_else_adapter import adapt_if_else_node_data_for_graph


def test_adapt_if_else_node_data_maps_official_null_operators_without_mutating_input() -> None:
    original = {
        "type": "if-else",
        "title": "Branch",
        "cases": [
            {
                "case_id": "sorted-uuid",
                "logical_operator": "and",
                "conditions": [
                    {
                        "id": "condition-1",
                        "varType": "string",
                        "variable_selector": ["start", "value"],
                        "comparison_operator": "is null",
                        "value": "",
                        "future": True,
                    },
                    {
                        "id": "condition-2",
                        "varType": "string",
                        "variable_selector": ["start", "value"],
                        "comparison_operator": "is not null",
                        "value": "",
                    },
                ],
            }
        ],
    }
    snapshot = deepcopy(original)

    actual = adapt_if_else_node_data_for_graph(original)

    assert original == snapshot
    assert actual["cases"][0]["case_id"] == "sorted-uuid"
    assert actual["cases"][0]["conditions"][0]["comparison_operator"] == "null"
    assert actual["cases"][0]["conditions"][1]["comparison_operator"] == "not null"
    assert actual["cases"][0]["conditions"][0]["future"] is True


def test_adapt_if_else_node_data_maps_nested_file_conditions_and_keeps_other_operators() -> None:
    actual = adapt_if_else_node_data_for_graph(
        {
            "type": "if-else",
            "cases": [
                {
                    "case_id": "true",
                    "logical_operator": "and",
                    "conditions": [
                        {
                            "variable_selector": ["start", "files"],
                            "comparison_operator": "all of",
                            "sub_variable_condition": {
                                "case_id": "nested",
                                "logical_operator": "or",
                                "conditions": [
                                    {"key": "name", "comparison_operator": "is null", "value": ""},
                                    {"key": "size", "comparison_operator": ">", "value": "22"},
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    )

    condition = actual["cases"][0]["conditions"][0]
    assert condition["comparison_operator"] == "all of"
    assert condition["sub_variable_condition"]["conditions"][0]["comparison_operator"] == "null"
    assert condition["sub_variable_condition"]["conditions"][1]["comparison_operator"] == ">"


def test_adapt_if_else_node_data_copies_non_if_else_data_without_rewriting_it() -> None:
    original = {"type": "llm", "comparison_operator": "is null"}

    actual = adapt_if_else_node_data_for_graph(original)

    assert actual == original
    assert actual is not original
