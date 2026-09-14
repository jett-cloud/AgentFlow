import pytest
from pydantic import ValidationError

from core.workflow.generator.validation.node_config_validator import collect_node_config_errors
from core.workflow.graph.adapters.node_config_schema import validate_workflow_node_data


@pytest.mark.parametrize(
    ("node_type", "config"),
    [
        ("llm", {}),
        ("code", {"outputs": {"result": {"type": "string"}}}),
        ("http-request", {}),
        ("not-a-node", {}),
    ],
)
def test_runtime_required_fields_are_checked_before_execution(node_type, config):
    errors = collect_node_config_errors([{"id": "n", "data": {"type": node_type, "title": "N", **config}}])
    assert errors
    assert errors[0]["node_id"] == "n"


def test_llm_schema_does_not_require_provider_io():
    errors = collect_node_config_errors(
        [
            {
                "id": "n",
                "data": {
                    "type": "llm",
                    "title": "N",
                    "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {}},
                    "prompt_template": [{"role": "user", "text": "hello"}],
                    "context": {"enabled": False, "variable_selector": []},
                },
            }
        ]
    )
    assert errors == []


@pytest.mark.parametrize(
    "variable",
    [
        {"variable": "enabled", "label": "Enabled", "type": "checkbox", "default": False},
        {
            "variable": "payload",
            "label": "Payload",
            "type": "json_object",
            "json_schema": {"type": "object", "properties": {}},
        },
    ],
)
def test_start_schema_accepts_current_input_types(variable):
    validate_workflow_node_data({"id": "start", "data": {"type": "start", "variables": [variable]}})


def test_start_schema_rejects_legacy_json_object_alias():
    with pytest.raises(ValidationError):
        validate_workflow_node_data(
            {
                "id": "start",
                "data": {
                    "type": "start",
                    "variables": [{"variable": "payload", "label": "Payload", "type": "json-object"}],
                },
            }
        )


def _knowledge_retrieval_payloads() -> list[dict[str, object]]:
    model = {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {}}
    return [
        {
            "type": "knowledge-retrieval",
            "title": "Search",
            "query_variable_selector": ["start", "query"],
            "query_attachment_selector": [],
            "dataset_ids": ["ds-1"],
            "retrieval_mode": "single",
            "single_retrieval_config": {"model": model},
        },
        {
            "type": "knowledge-retrieval",
            "title": "Search",
            "query_variable_selector": ["start", "query"],
            "query_attachment_selector": [],
            "dataset_ids": ["ds-1"],
            "retrieval_mode": "multiple",
            "multiple_retrieval_config": {
                "top_k": 4,
                "score_threshold": None,
                "reranking_enable": True,
                "reranking_mode": "reranking_model",
                "reranking_model": {"provider": "cohere", "model": "rerank-english-v3.0"},
            },
        },
        {
            "type": "knowledge-retrieval",
            "title": "Search",
            "query_variable_selector": ["start", "query"],
            "query_attachment_selector": [],
            "dataset_ids": ["ds-1"],
            "retrieval_mode": "multiple",
            "multiple_retrieval_config": {
                "top_k": 4,
                "score_threshold": None,
                "reranking_mode": "weighted_score",
                "weights": {
                    "vector_setting": {
                        "vector_weight": 0.7,
                        "embedding_provider_name": "openai",
                        "embedding_model_name": "text-embedding-3-small",
                    },
                    "keyword_setting": {"keyword_weight": 0.3},
                },
            },
        },
    ]


@pytest.mark.parametrize("data", _knowledge_retrieval_payloads())
def test_knowledge_retrieval_schema_accepts_frontend_legal_configs(data: dict[str, object]) -> None:
    from core.workflow.generator.validation.node_config_validator import collect_generated_node_completeness_errors

    validate_workflow_node_data({"id": "kr", "data": data})
    assert collect_generated_node_completeness_errors([{"id": "kr", "data": data}]) == []
