from core.workflow.generator.compiler.intents.node_intent import NodeBuildIntent
from core.workflow.generator.compiler.ordinary_node_compiler import compile_structured_node_config


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
