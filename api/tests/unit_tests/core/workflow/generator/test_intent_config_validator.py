from core.workflow.generator.compiler.intents.node_intent import NodeBuildIntent
from core.workflow.generator.validation.intent_config_validator import validate_node_config_against_intent


def test_intent_validation_distinguishes_flattened_nested_selector() -> None:
    intent = NodeBuildIntent.model_validate(
        {
            "objective": "Read the current question",
            "inputs": [{"source": ["iteration", "item", "question"], "role": "query"}],
        }
    )

    issues = validate_node_config_against_intent(
        node_id="retrieve",
        node_type="knowledge-retrieval",
        title="Retrieve",
        intent=intent,
        config={"query_variable_selector": ["iteration", "item.question"]},
    )

    assert [issue.code for issue in issues] == ["INTENT_INPUT_MISSING"]
