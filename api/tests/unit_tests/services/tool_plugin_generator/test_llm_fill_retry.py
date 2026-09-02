from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.tool_plugin_generator.llm_fill import LLMFillResponseError, TenantLLMFillClient


def _client(raw_responses: list[str], *, response_format: str | None = "json_object") -> TenantLLMFillClient:
    manager = MagicMock()
    instance = manager.get_model_instance.return_value
    manager.get_default_model_instance.return_value = instance
    instance.get_model_schema.return_value = SimpleNamespace(
        model="qwen-plus",
        features=[],
        parameter_rules=(
            [SimpleNamespace(name="response_format", options=[response_format])]
            if response_format
            else []
        ),
    )
    responses = [
        SimpleNamespace(message=SimpleNamespace(get_text_content=lambda value=value: value))
        for value in raw_responses
    ]
    instance.invoke_llm.side_effect = responses
    return TenantLLMFillClient(tenant_id="tenant-1", model_manager=manager, provider="dashscope", model="qwen-plus")


def test_fill_retries_with_correction_when_first_response_is_not_object():
    client = _client(["[]", '{"invoke_python_body":"ok","provider_label":"P","tool_label":"T"}'])

    result = client.complete("Generate")

    assert result["tool_label"] == "T"
    assert client.model_manager.get_default_model_instance.return_value.invoke_llm.call_count == 2


def test_fill_retries_when_first_payload_fails_validation():
    client = _client(
        [
            '{"invoke_python_body":"ok","provider_label":"P","tool_label":"T","parameters":{}}',
            '{"invoke_python_body":"ok","provider_label":"P","tool_label":"T"}',
        ]
    )

    result = client.complete("Generate")

    assert result["invoke_python_body"] == "ok"


def test_fill_error_reports_provider_model_and_parsed_type_after_retry():
    client = _client(["null", "[]"])

    with pytest.raises(LLMFillResponseError, match="provider=dashscope.*model=qwen-plus.*parsed_type=list"):
        client.complete("Generate")


def test_fill_omits_response_format_for_model_without_json_mode():
    client = _client(['{"invoke_python_body":"ok","provider_label":"P","tool_label":"T"}'], response_format=None)

    client.complete("Generate")

    call = client.model_manager.get_model_instance.return_value.invoke_llm.call_args
    assert "response_format" not in call.kwargs["model_parameters"]


def test_fill_falls_back_to_prompt_only_when_provider_rejects_json_mode():
    client = _client(['{"invoke_python_body":"ok","provider_label":"P","tool_label":"T"}'])
    instance = client.model_manager.get_model_instance.return_value
    success = SimpleNamespace(
        message=SimpleNamespace(
            get_text_content=lambda: '{"invoke_python_body":"ok","provider_label":"P","tool_label":"T"}'
        )
    )
    instance.invoke_llm.side_effect = [ValueError("response_format is unsupported"), success]
    client.complete("Generate")

    first, second = instance.invoke_llm.call_args_list
    assert "response_format" in first.kwargs["model_parameters"]
    assert "response_format" not in second.kwargs["model_parameters"]
