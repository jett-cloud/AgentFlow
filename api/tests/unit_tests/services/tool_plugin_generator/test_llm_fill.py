from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.errors.error import ProviderTokenNotInitError
from graphon.model_runtime.entities.message_entities import UserPromptMessage
from graphon.model_runtime.entities.model_entities import ModelType
from services.tool_plugin_generator.llm_fill import (
    LLMFillConfigurationError,
    LLMFillResponseError,
    TenantLLMFillClient,
    parse_llm_fill_payload,
)


def test_parse_llm_fill_payload_requires_invoke_body():
    with pytest.raises(ValueError):
        parse_llm_fill_payload({"provider_label": "X", "tool_label": "Y", "parameters": []})


def test_parse_llm_fill_payload_rejects_parameter_without_name():
    payload = {
        "provider_label": "X",
        "tool_label": "Y",
        "parameters": [{"type": "string", "required": True, "label": "Text"}],
        "invoke_python_body": "yield self.create_text_message('ok')",
    }
    with pytest.raises(ValueError, match="non-empty name"):
        parse_llm_fill_payload(payload)


def test_parse_llm_fill_payload_normalizes_parameter_form_and_label():
    payload = {
        "provider_label": "X",
        "tool_label": "Y",
        "parameters": [{"name": "parent_id", "type": "string", "required": True, "label": "Parent ID"}],
        "invoke_python_body": "yield self.create_text_message('ok')",
    }
    fill = parse_llm_fill_payload(payload)
    assert fill.parameters[0]["form"] == "llm"
    assert fill.parameters[0]["label"] == {"en_US": "Parent ID"}


def test_tenant_llm_fill_client_uses_default_llm():
    model_manager = MagicMock()
    model_instance = model_manager.get_default_model_instance.return_value
    response = model_instance.invoke_llm.return_value
    response.message.get_text_content.return_value = '{"provider_label": "Echo", "parameters": []}'
    client = TenantLLMFillClient(tenant_id="tenant-1", model_manager=model_manager)

    result = client.complete("Generate a plugin")

    assert result == {"provider_label": "Echo", "parameters": []}
    model_manager.get_default_model_instance.assert_called_once_with(
        tenant_id="tenant-1",
        model_type=ModelType.LLM,
    )
    model_instance.invoke_llm.assert_called_once_with(
        prompt_messages=[UserPromptMessage(content="Generate a plugin")],
        model_parameters={
            "temperature": 0.1,
            "response_format": "json_object",
        },
        stream=False,
    )


def test_tenant_llm_fill_streams_reasoning_without_client_max_tokens():
    model_manager = MagicMock()
    model_instance = model_manager.get_default_model_instance.return_value
    model_instance.get_model_schema.return_value = SimpleNamespace(features=[])

    captured: dict[str, object] = {}

    def invoke_llm(**kwargs):
        captured.update(kwargs)
        return iter(
            [
                SimpleNamespace(
                    delta=SimpleNamespace(message=SimpleNamespace(content='<think>plan</think>{')),
                ),
                SimpleNamespace(
                    delta=SimpleNamespace(message=SimpleNamespace(content='"provider_label":"Echo"}')),
                ),
            ]
        )

    model_instance.invoke_llm.side_effect = invoke_llm
    client = TenantLLMFillClient(tenant_id="tenant-1", model_manager=model_manager)
    thinking: list[str] = []

    result = client.complete("Generate a plugin", on_event=thinking.append)

    assert result == {"provider_label": "Echo"}
    assert thinking == ["plan"]
    assert captured["stream"] is True
    assert "max_tokens" not in captured["model_parameters"]


def test_tenant_llm_fill_handles_think_tags_split_across_chunks():
    model_manager = MagicMock()
    model_instance = model_manager.get_default_model_instance.return_value
    model_instance.get_model_schema.return_value = SimpleNamespace(features=[])
    model_instance.invoke_llm.return_value = iter(
        [
            SimpleNamespace(delta=SimpleNamespace(message=SimpleNamespace(content="<thi"))),
            SimpleNamespace(delta=SimpleNamespace(message=SimpleNamespace(content="nk>plan</thi"))),
            SimpleNamespace(delta=SimpleNamespace(message=SimpleNamespace(content="nk>{\"provider_label\":\"Echo\"}"))),
        ]
    )
    client = TenantLLMFillClient(tenant_id="tenant-1", model_manager=model_manager)
    thinking: list[str] = []

    result = client.complete("Generate a plugin", on_event=thinking.append)

    assert result == {"provider_label": "Echo"}
    assert "".join(thinking) == "plan"


def test_tenant_llm_fill_preserves_think_tags_inside_json_values():
    model_manager = MagicMock()
    model_instance = model_manager.get_default_model_instance.return_value
    model_instance.get_model_schema.return_value = SimpleNamespace(features=[])
    model_instance.invoke_llm.return_value = iter(
        [
            SimpleNamespace(
                delta=SimpleNamespace(
                    message=SimpleNamespace(content='{"provider_label":"<think>keep me</think>"}')
                )
            )
        ]
    )
    client = TenantLLMFillClient(tenant_id="tenant-1", model_manager=model_manager)
    thinking: list[str] = []

    result = client.complete("Generate a plugin", on_event=thinking.append)

    assert result == {"provider_label": "<think>keep me</think>"}
    assert thinking == []


def test_tenant_llm_fill_reads_reasoning_from_aggregate_message():
    model_manager = MagicMock()
    model_instance = model_manager.get_default_model_instance.return_value
    model_instance.get_model_schema.return_value = SimpleNamespace(features=[])
    model_instance.invoke_llm.return_value = SimpleNamespace(
        message=SimpleNamespace(
            reasoning_content="provider reasoning",
            get_text_content=lambda: '{"provider_label":"Echo"}',
        )
    )
    client = TenantLLMFillClient(tenant_id="tenant-1", model_manager=model_manager)
    thinking: list[str] = []

    result = client.complete("Generate a plugin", on_event=thinking.append)

    assert result == {"provider_label": "Echo"}
    assert thinking == ["provider reasoning"]


def test_tenant_llm_fill_keeps_non_stream_content_out_of_thinking_events():
    model_manager = MagicMock()
    model_instance = model_manager.get_default_model_instance.return_value
    model_instance.get_model_schema.return_value = SimpleNamespace(features=[])
    response = SimpleNamespace(
        message=SimpleNamespace(get_text_content=lambda: '{"provider_label":"Echo"}'),
    )
    model_instance.invoke_llm.return_value = response
    client = TenantLLMFillClient(tenant_id="tenant-1", model_manager=model_manager)
    thinking: list[str] = []

    result = client.complete("Generate a plugin", on_event=thinking.append)

    assert result == {"provider_label": "Echo"}
    assert thinking == []


def test_tenant_llm_fill_preserves_reasoning_before_stream_interruption():
    model_manager = MagicMock()
    model_instance = model_manager.get_default_model_instance.return_value
    model_instance.get_model_schema.return_value = SimpleNamespace(features=[])

    def broken_stream(**_kwargs):
        def chunks():
            yield SimpleNamespace(
                delta=SimpleNamespace(message=SimpleNamespace(content="<think>partial")),
            )
            raise RuntimeError("connection closed")

        return chunks()

    model_instance.invoke_llm.side_effect = broken_stream
    client = TenantLLMFillClient(tenant_id="tenant-1", model_manager=model_manager)
    thinking: list[str] = []

    with pytest.raises(LLMFillResponseError, match="connection closed"):
        client.complete("Generate a plugin", on_event=thinking.append)

    assert thinking == ["partial", "partial"]


def test_tenant_llm_fill_client_uses_explicit_provider_and_model():
    model_manager = MagicMock()
    model_instance = model_manager.get_model_instance.return_value
    response = model_instance.invoke_llm.return_value
    response.message.get_text_content.return_value = "{}"
    client = TenantLLMFillClient(
        tenant_id="tenant-1",
        provider="langgenius/openai/openai",
        model="gpt-4.1",
        model_manager=model_manager,
    )

    client.complete("Generate a plugin")

    model_manager.get_model_instance.assert_called_once_with(
        tenant_id="tenant-1",
        provider="langgenius/openai/openai",
        model_type=ModelType.LLM,
        model="gpt-4.1",
    )
    model_manager.get_default_provider_model_name.assert_not_called()


def test_tenant_llm_fill_client_reports_missing_default_model():
    model_manager = MagicMock()
    model_manager.get_default_model_instance.side_effect = ProviderTokenNotInitError("missing")
    client = TenantLLMFillClient(tenant_id="tenant-1", model_manager=model_manager)

    with pytest.raises(LLMFillConfigurationError, match="workspace LLM provider"):
        client.complete("Generate a plugin")


def test_tenant_llm_fill_client_rejects_non_object_response():
    model_manager = MagicMock()
    response = model_manager.get_default_model_instance.return_value.invoke_llm.return_value
    response.message.get_text_content.return_value = "[]"
    client = TenantLLMFillClient(tenant_id="tenant-1", model_manager=model_manager)

    with pytest.raises(ValueError, match="JSON object"):
        client.complete("Generate a plugin")
