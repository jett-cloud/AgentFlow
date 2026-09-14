"""llm."""

from __future__ import annotations

from collections.abc import Generator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, cast, overload, override

from pydantic import JsonValue

from core.llm_generator.output_parser.errors import OutputParserError
from core.llm_generator.output_parser.structured_output import invoke_llm_with_structured_output
from core.model_manager import ModelInstance
from core.prompt.utils.prompt_message_util import PromptMessageUtil
from graphon.model_runtime.entities import LLMMode
from graphon.model_runtime.entities.llm_entities import (
    LLMPollingResult,
    LLMResult,
    LLMResultChunk,
    LLMResultChunkWithStructuredOutput,
    LLMResultWithStructuredOutput,
)
from graphon.model_runtime.entities.message_entities import PromptMessage, PromptMessageTool
from graphon.model_runtime.entities.model_entities import AIModelEntity
from graphon.model_runtime.model_providers.base.large_language_model import LargeLanguageModel
from graphon.nodes.llm.runtime_protocols import (
    LLMPollingCapableProtocol,
    LLMProtocol,
    PromptMessageSerializerProtocol,
)

if TYPE_CHECKING:
    pass


class DifyPreparedLLM(LLMProtocol):
    """Workflow-layer adapter that hides the full `ModelInstance` API from `graphon` nodes."""

    def __init__(self, model_instance: ModelInstance, request_metadata: Mapping[str, object] | None = None) -> None:
        self._model_instance = model_instance
        self._request_metadata = request_metadata

    @property
    @override
    def provider(self) -> str:
        return self._model_instance.provider

    @property
    @override
    def model_name(self) -> str:
        return self._model_instance.model_name

    @property
    @override
    def parameters(self) -> Mapping[str, Any]:
        return self._model_instance.parameters

    @parameters.setter
    @override
    def parameters(self, value: Mapping[str, Any]) -> None:
        self._model_instance.parameters = value

    @property
    @override
    def stop(self) -> Sequence[str] | None:
        return self._model_instance.stop

    @override
    def get_model_schema(self) -> AIModelEntity:
        model_schema = cast(LargeLanguageModel, self._model_instance.model_type_instance).get_model_schema(
            self._model_instance.model_name,
            self._model_instance.credentials,
        )
        if model_schema is None:
            raise ValueError(f"Model schema not found for {self._model_instance.model_name}")
        return model_schema

    @override
    def get_llm_num_tokens(self, prompt_messages: Sequence[PromptMessage]) -> int:
        return self._model_instance.get_llm_num_tokens(prompt_messages)

    @overload
    def invoke_llm(
        self,
        *,
        prompt_messages: Sequence[PromptMessage],
        model_parameters: Mapping[str, Any],
        tools: Sequence[PromptMessageTool] | None,
        stop: Sequence[str] | None,
        stream: Literal[False],
    ) -> LLMResult: ...

    @overload
    def invoke_llm(
        self,
        *,
        prompt_messages: Sequence[PromptMessage],
        model_parameters: Mapping[str, Any],
        tools: Sequence[PromptMessageTool] | None,
        stop: Sequence[str] | None,
        stream: Literal[True],
    ) -> Generator[LLMResultChunk, None, None]: ...

    @override
    def invoke_llm(
        self,
        *,
        prompt_messages: Sequence[PromptMessage],
        model_parameters: Mapping[str, Any],
        tools: Sequence[PromptMessageTool] | None,
        stop: Sequence[str] | None,
        stream: bool,
    ) -> LLMResult | Generator[LLMResultChunk, None, None]:
        return self._model_instance.invoke_llm(
            prompt_messages=list(prompt_messages),
            model_parameters=dict(model_parameters),
            tools=list(tools or []),
            stop=list(stop or []),
            stream=stream,
            request_metadata=self._request_metadata,
        )

    @overload
    def invoke_llm_with_structured_output(
        self,
        *,
        prompt_messages: Sequence[PromptMessage],
        json_schema: Mapping[str, Any],
        model_parameters: Mapping[str, Any],
        stop: Sequence[str] | None,
        stream: Literal[False],
    ) -> LLMResultWithStructuredOutput: ...

    @overload
    def invoke_llm_with_structured_output(
        self,
        *,
        prompt_messages: Sequence[PromptMessage],
        json_schema: Mapping[str, Any],
        model_parameters: Mapping[str, Any],
        stop: Sequence[str] | None,
        stream: Literal[True],
    ) -> Generator[LLMResultChunkWithStructuredOutput, None, None]: ...

    @override
    def invoke_llm_with_structured_output(
        self,
        *,
        prompt_messages: Sequence[PromptMessage],
        json_schema: Mapping[str, Any],
        model_parameters: Mapping[str, Any],
        stop: Sequence[str] | None,
        stream: bool,
    ) -> LLMResultWithStructuredOutput | Generator[LLMResultChunkWithStructuredOutput, None, None]:
        return invoke_llm_with_structured_output(
            provider=self.provider,
            model_schema=self.get_model_schema(),
            model_instance=self._model_instance,
            prompt_messages=prompt_messages,
            json_schema=json_schema,
            model_parameters=model_parameters,
            stop=list(stop or []),
            stream=stream,
        )

    @override
    def is_structured_output_parse_error(self, error: Exception) -> bool:
        return isinstance(error, OutputParserError)


class DifyPreparedPollingLLM(DifyPreparedLLM, LLMPollingCapableProtocol):
    """Prepared workflow LLM adapter that exposes Graphon's polling protocol."""

    def __init__(self, model_instance: ModelInstance, request_metadata: Mapping[str, object] | None = None) -> None:
        from core.plugin.impl.model_runtime import PluginModelRuntime

        super().__init__(model_instance, request_metadata=request_metadata)
        model_type_instance = model_instance.model_type_instance
        if not isinstance(model_type_instance, LargeLanguageModel):
            raise TypeError("Polling wrapper requires a large-language-model instance.")

        plugin_model_runtime = model_type_instance.model_runtime
        if not isinstance(plugin_model_runtime, PluginModelRuntime):
            raise TypeError("Polling wrapper requires a plugin-backed model runtime.")

        self._plugin_model_runtime = plugin_model_runtime

    @override
    def start_llm_polling(
        self,
        *,
        prompt_messages: Sequence[PromptMessage],
        model_parameters: Mapping[str, Any],
        tools: Sequence[PromptMessageTool] | None,
        stop: Sequence[str] | None,
        json_schema: Mapping[str, Any] | None,
    ) -> LLMPollingResult:
        return self._plugin_model_runtime.start_llm_polling(
            provider=self.provider,
            model=self.model_name,
            credentials=self._model_instance.credentials,
            prompt_messages=prompt_messages,
            model_parameters=dict(model_parameters),
            tools=tools,
            stop=stop,
            json_schema=dict(json_schema) if json_schema is not None else None,
        )

    @override
    def check_llm_polling(
        self,
        *,
        plugin_state: Mapping[str, JsonValue],
    ) -> LLMPollingResult:
        return self._plugin_model_runtime.check_llm_polling(
            provider=self.provider,
            model=self.model_name,
            credentials=self._model_instance.credentials,
            plugin_state=dict(plugin_state),
        )


class DifyPromptMessageSerializer(PromptMessageSerializerProtocol):
    @override
    def serialize(
        self,
        *,
        model_mode: LLMMode,
        prompt_messages: Sequence[PromptMessage],
    ) -> Any:
        return PromptMessageUtil.prompt_messages_to_prompt_for_saving(
            model_mode=model_mode,
            prompt_messages=prompt_messages,
        )
