from core.workflow.generator.compiler.intents.node_intent import NodeBuildIntent
from core.workflow.generator.compiler.ordinary_node_compiler import compile_structured_node_config


def test_builder_config_restores_nested_selector_from_declared_input() -> None:
    intent = NodeBuildIntent.model_validate(
        {
            "objective": "Retrieve knowledge for the current test case",
            "inputs": [
                {
                    "source": ["test_iteration", "item", "question"],
                    "role": "query",
                }
            ],
            "outputs": [{"name": "result", "type": "array[object]"}],
        }
    )

    compiled = compile_structured_node_config(
        intent=intent,
        builder_config={
            "query_variable_selector": ["test_iteration", "item.question"],
            "nested": {
                "variables": [
                    {"value_selector": ["test_iteration", "item.question"]},
                ]
            },
        },
    )

    assert compiled["query_variable_selector"] == ["test_iteration", "item", "question"]
    assert compiled["nested"]["variables"][0]["value_selector"] == [
        "test_iteration",
        "item",
        "question",
    ]


def test_builder_config_does_not_expand_unrelated_two_part_values() -> None:
    intent = NodeBuildIntent.model_validate(
        {
            "objective": "Retrieve knowledge",
            "inputs": [
                {
                    "source": ["test_iteration", "item", "question"],
                    "role": "query",
                }
            ],
        }
    )

    compiled = compile_structured_node_config(
        intent=intent,
        builder_config={
            "query_variable_selector": ["start", "query"],
            "dataset_ids": ["dataset-a", "dataset-b"],
        },
    )

    assert compiled["query_variable_selector"] == ["start", "query"]
    assert compiled["dataset_ids"] == ["dataset-a", "dataset-b"]


def test_code_output_preserves_declared_object_children() -> None:
    intent = NodeBuildIntent.model_validate(
        {
            "objective": "Parse test cases",
            "outputs": [
                {
                    "name": "cases",
                    "type": "array[object]",
                    "children": {
                        "question": {"type": "string"},
                        "expected_answer": {"type": "string"},
                    },
                }
            ],
            "structure": {
                "kind": "code",
                "language": "python3",
                "code": "def main():\n    return {'cases': []}",
                "bindings": [],
            },
        }
    )

    compiled = compile_structured_node_config(intent=intent, builder_config={})

    assert compiled["outputs"]["cases"] == {
        "type": "array[object]",
        "children": {
            "question": {"type": "string", "children": None},
            "expected_answer": {"type": "string", "children": None},
        },
    }
