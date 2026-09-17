from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any, Protocol

import json_repair

from core.errors.error import ProviderTokenNotInitError
from core.model_manager import ModelManager
from graphon.model_runtime.entities.message_entities import UserPromptMessage
from graphon.model_runtime.entities.model_entities import ModelType
from services.tool_plugin_generator.model_capabilities import from_model_schema
from services.tool_plugin_generator.prompts import FILL_JSON_SCHEMA, build_fill_prompt
from services.tool_plugin_generator.scaffold import ToolPluginFill
from services.tool_plugin_generator.schema_normalize import normalize_tool_parameters

__all__ = [
    "FILL_JSON_SCHEMA",
    "LLMFillClient",
    "LLMFillConfigurationError",
    "LLMFillResponseError",
    "TenantLLMFillClient",
    "build_fill_prompt",
    "parse_llm_fill_payload",
    "resolve_tenant_llm_instance",
]


class LLMFillClient(Protocol):
    def complete(self, prompt: str, on_event: Callable[[str], None] | None = None) -> dict[str, Any]: ...


class LLMFillConfigurationError(RuntimeError):
    """Raised when the workspace has no usable LLM configuration."""


class LLMFillResponseError(ValueError):
    """Raised when a provider cannot produce a valid scaffold JSON object."""

    def __init__(self, *, provider: str, model: str, parsed_type: str, validation_error: str) -> None:
        super().__init__(
            f"LLM fill response invalid: provider={provider}, model={model}, "
            f"parsed_type={parsed_type}, validation_error={validation_error}"
        )
        self.provider = provider
        self.model = model
        self.parsed_type = parsed_type
        self.validation_error = validation_error


def resolve_tenant_llm_instance(
    *,
    tenant_id: str,
    model_manager: ModelManager,
    provider: str | None,
    model: str | None,
):
    """Resolve a workspace-configured LLM instance.

    When both provider and model are set, use that exact workspace model.
    Otherwise fall back to the workspace default LLM (Integrations → Model Provider).
    """
    try:
        if provider and model:
            return model_manager.get_model_instance(
                tenant_id=tenant_id,
                provider=provider,
                model_type=ModelType.LLM,
                model=model,
            )
        if model and not provider:
            # Backward-compatible: model name only → default provider + that model.
            default_provider, _ = model_manager.get_default_provider_model_name(
                tenant_id=tenant_id,
                model_type=ModelType.LLM,
            )
            if not default_provider:
                raise ProviderTokenNotInitError("Default LLM provider not found")
            return model_manager.get_model_instance(
                tenant_id=tenant_id,
                provider=default_provider,
                model_type=ModelType.LLM,
                model=model,
            )
        return model_manager.get_default_model_instance(
            tenant_id=tenant_id,
            model_type=ModelType.LLM,
        )
    except ProviderTokenNotInitError as exc:
        raise LLMFillConfigurationError(
            "Tool plugin generation requires a workspace LLM provider and credentials. "
            "Configure them under Integrations → Model Provider, then select a model."
        ) from exc


class TenantLLMFillClient:
    """Complete scaffold fill prompts with a tenant-scoped workspace LLM."""

    tenant_id: str
    provider: str | None
    model: str | None
    model_manager: ModelManager

    def __init__(
        self,
        *,
        tenant_id: str,
        model_manager: ModelManager,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.provider = provider
        self.model = model
        self.model_manager = model_manager

    def complete(self, prompt: str, on_event: Callable[[str], None] | None = None) -> dict[str, Any]:
        model_instance = resolve_tenant_llm_instance(
            tenant_id=self.tenant_id,
            model_manager=self.model_manager,
            provider=self.provider,
            model=self.model,
        )
        model_schema = model_instance.get_model_schema()
        capabilities = from_model_schema(model_schema)
        provider = str(self.provider or "default")
        schema_model = getattr(model_schema, "model", None)
        model = str(self.model or (schema_model if isinstance(schema_model, str) else "unknown"))
        correction = (
            "\n\nCorrection: return exactly one JSON object matching the requested schema. "
            "Do not return an array, null, markdown, or explanatory text."
        )
        last_error = "unknown response error"
        parsed_type = "unknown"
        response_format = capabilities.response_format
        for attempt in range(2):
            request_prompt = prompt if attempt == 0 else prompt + correction
            parameters: dict[str, Any] = {"temperature": 0.1}
            if response_format:
                parameters["response_format"] = response_format
            try:
                response = model_instance.invoke_llm(
                    prompt_messages=[UserPromptMessage(content=request_prompt)],
                    model_parameters=parameters,
                    stream=on_event is not None,
                )
                raw_response = _read_response_text(response, on_event=on_event)
                try:
                    payload = json.loads(raw_response)
                except json.JSONDecodeError:
                    payload = json_repair.loads(raw_response)
                parsed_type = type(payload).__name__
                if not isinstance(payload, dict):
                    raise ValueError("response must be a JSON object")
                # Preserve the historical partial-payload contract. Once the
                # generator starts emitting the scaffold body, validate known
                # fields and use the single retry for corrective output.
                if "invoke_python_body" in payload:
                    parse_llm_fill_payload(payload)
                return payload
            except Exception as exc:
                last_error = str(exc) or type(exc).__name__
                if attempt == 0:
                    # A provider can advertise JSON mode but reject the
                    # parameter for a specific deployment. Retry once with
                    # prompt-only JSON instructions instead of repeating it.
                    response_format = None
                    continue
        raise LLMFillResponseError(
            provider=provider,
            model=model,
            parsed_type=parsed_type,
            validation_error=last_error,
        )


def _read_response_text(response: Any, *, on_event: Callable[[str], None] | None) -> str:
    """Read a provider response while keeping reasoning separate from JSON text."""
    if on_event is None or not _is_stream(response):
        reasoning = _string_value(getattr(response, "reasoning_content", None))
        message = getattr(response, "message", None)
        if not reasoning:
            reasoning = _string_value(getattr(message, "reasoning_content", None))
        if reasoning and on_event is not None:
            on_event(reasoning)
        return _message_text(message)

    final_parts: list[str] = []
    parser = _ThinkingStreamParser()
    for chunk in response:
        reasoning = _string_value(getattr(chunk, "reasoning_content", None))
        if not reasoning:
            delta = getattr(chunk, "delta", None)
            reasoning = _string_value(getattr(delta, "reasoning_content", None))
            if not reasoning:
                reasoning = _string_value(getattr(getattr(delta, "message", None), "reasoning_content", None))
        if reasoning:
            on_event(reasoning)

        delta = getattr(chunk, "delta", None)
        text = _message_text(getattr(delta, "message", None))
        if not text:
            continue
        thinking, visible = parser.feed(text)
        for item in thinking:
            if item:
                on_event(item)
        final_parts.extend(visible)

    thinking, visible = parser.finish()
    for item in thinking:
        if item:
            on_event(item)
    final_parts.extend(visible)
    return "".join(final_parts)


def _is_stream(response: Any) -> bool:
    return isinstance(response, Iterable) and not hasattr(response, "message")


def _string_value(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _message_text(message: Any) -> str:
    if message is None:
        return ""
    getter = getattr(message, "get_text_content", None)
    if callable(getter):
        content = getter()
    else:
        content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(item if isinstance(item, str) else str(getattr(item, "data", "")) for item in content)
    return ""


class _ThinkingStreamParser:
    """Split inline ``<think>`` fragments from the final JSON stream."""

    _open_tag = "<think>"
    _close_tag = "</think>"

    def __init__(self) -> None:
        self._in_thinking = False
        self._content_started = False
        self._pending = ""

    def feed(self, text: str) -> tuple[list[str], list[str]]:
        thinking: list[str] = []
        visible: list[str] = []
        remaining = self._pending + text
        self._pending = ""
        while remaining:
            if self._content_started:
                visible.append(remaining)
                break
            if self._in_thinking:
                index = remaining.find(self._close_tag)
                if index < 0:
                    keep = self._suffix_prefix_length(remaining, self._close_tag)
                    body = remaining[:-keep] if keep else remaining
                    if body:
                        thinking.append(body)
                    if keep:
                        self._pending = remaining[-keep:]
                    break
                if index:
                    thinking.append(remaining[:index])
                remaining = remaining[index + len(self._close_tag) :]
                self._in_thinking = False
                continue

            stripped = remaining.lstrip()
            whitespace_length = len(remaining) - len(stripped)
            if not stripped:
                visible.append(remaining)
                break
            if stripped.startswith(self._open_tag):
                if whitespace_length:
                    visible.append(remaining[:whitespace_length])
                remaining = stripped[len(self._open_tag) :]
                self._in_thinking = True
                continue
            if self._open_tag.startswith(stripped):
                if whitespace_length:
                    visible.append(remaining[:whitespace_length])
                self._pending = stripped
                break
            self._content_started = True
            visible.append(remaining)
            break
        return thinking, visible

    def finish(self) -> tuple[list[str], list[str]]:
        if not self._pending:
            return [], []
        pending = self._pending
        self._pending = ""
        return ([pending], []) if self._in_thinking else ([], [pending])

    @staticmethod
    def _suffix_prefix_length(value: str, tag: str) -> int:
        for length in range(min(len(value), len(tag) - 1), 0, -1):
            if tag.startswith(value[-length:]):
                return length
        return 0


def _normalize_credentials(credentials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for credential in credentials:
        if not isinstance(credential, dict):
            continue
        name = credential.get("name")
        if not name:
            continue
        normalized.append({"name": str(name), **{k: v for k, v in credential.items() if k != "name"}})
    return normalized


def parse_llm_fill_payload(data: dict[str, Any]) -> ToolPluginFill:
    invoke_python_body = data.get("invoke_python_body")
    if not invoke_python_body or not str(invoke_python_body).strip():
        raise ValueError("invoke_python_body is required")

    provider_label = data.get("provider_label")
    tool_label = data.get("tool_label")
    if not provider_label or not tool_label:
        raise ValueError("provider_label and tool_label are required")

    parameters = data.get("parameters") or []
    if not isinstance(parameters, list):
        raise ValueError("parameters must be a list")

    raw_credentials = data.get("credentials") or []
    if not isinstance(raw_credentials, list):
        raise ValueError("credentials must be a list")

    return ToolPluginFill(
        provider_label=str(provider_label),
        tool_label=str(tool_label),
        tool_description=str(data.get("tool_description") or tool_label),
        parameters=normalize_tool_parameters(parameters),
        credentials=_normalize_credentials(raw_credentials),
        invoke_python_body=str(invoke_python_body).strip(),
        readme=str(data.get("readme") or ""),
    )


def parse_llm_fill_response(raw: str | dict[str, Any]) -> ToolPluginFill:
    if isinstance(raw, dict):
        return parse_llm_fill_payload(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM response is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("LLM response must be a JSON object")
    return parse_llm_fill_payload(data)
