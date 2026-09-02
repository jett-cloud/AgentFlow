"""LLM invocation and JSON response handling for workflow generation."""

import logging
import re
import time
from collections.abc import Callable, Generator, Iterator, Sequence
from typing import Any, Protocol, cast

import json_repair

from graphon.model_runtime.entities.llm_entities import LLMResult, LLMResultChunk
from graphon.model_runtime.entities.message_entities import (
    PromptMessage,
    PromptMessageTool,
    TextPromptMessageContent,
    UserPromptMessage,
)
from graphon.model_runtime.errors.invoke import (
    InvokeConnectionError,
    InvokeRateLimitError,
    InvokeServerUnavailableError,
)

logger = logging.getLogger(__name__)

JSON_RETRY_HINT = (
    "Your previous response was not valid JSON. Return ONLY a single JSON object. "
    "Do not include any prose, markdown code fences, comments, or trailing commas."
)
RAW_PREVIEW_CHARS = 200
PLANNER_FALLBACK_MAX_TOKENS = 8192
INVOKE_MAX_ATTEMPTS = 3
INVOKE_BACKOFF_SECONDS = (0.5, 1.5)

_TRANSIENT_INVOKE_ERRORS = (
    InvokeConnectionError,
    InvokeServerUnavailableError,
    InvokeRateLimitError,
)
_TRUNCATED_FINISH_REASONS = frozenset({"length", "max_tokens", "max_token", "output_limit"})
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK_RE = re.compile(r"<think\b[^>]*>.*\Z", re.DOTALL | re.IGNORECASE)


class ModelInvoker(Protocol):
    def invoke_llm(
        self,
        *,
        prompt_messages: Sequence[PromptMessage],
        model_parameters: dict[str, Any],
        stream: bool,
        tools: Sequence[PromptMessageTool] | None = None,
    ) -> Any: ...

    def get_model_schema(self) -> Any: ...

    def get_llm_num_tokens(self, prompt_messages: Sequence[PromptMessage]) -> int: ...


class StageError(ValueError):
    """Base for stage failures mapped by the orchestration layer."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.context_checkpoint: dict[str, object] | None = None


class StageJSONError(StageError):
    """Raised when a stage response cannot be parsed as a JSON object."""

    def __init__(self, stage: str, detail: str) -> None:
        super().__init__(stage, f"{stage} JSON invalid: {detail}")


class StageSchemaError(StageError):
    """Raised when parsed stage JSON violates the stage contract."""

    def __init__(self, stage: str, detail: str) -> None:
        super().__init__(stage, f"{stage} schema invalid: {detail}")


class StageTruncatedError(StageError):
    """Raised when the provider reports an output-token-limit stop."""

    def __init__(self, stage: str, detail: str) -> None:
        super().__init__(stage, f"{stage} output truncated: {detail}")


def extract_chunk_text_delta(chunk: LLMResultChunk) -> str:
    message = chunk.delta.message
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, TextPromptMessageContent):
                parts.append(item.data)
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return message.get_text_content() or ""


def chunk_finish_reason(chunk: LLMResultChunk) -> str:
    """Normalize a chunk finish reason for comparison."""
    reason = getattr(chunk.delta, "finish_reason", None)
    if not isinstance(reason, str):
        return ""
    return reason.strip().lower().replace("-", "_")


def strip_reasoning_blocks(raw: str) -> str:
    """Drop ``<think>`` reasoning that some providers inline into content."""
    return _UNCLOSED_THINK_RE.sub("", _THINK_BLOCK_RE.sub("", raw)).strip()


def extract_reasoning_blocks(raw: str) -> str:
    """Return concatenated ``<think>`` bodies, including a trailing unclosed block."""
    if not raw:
        return ""
    bodies = [match.group(1) for match in re.finditer(r"<think\b[^>]*>(.*?)</think\s*>", raw, re.DOTALL | re.IGNORECASE)]
    unclosed = re.search(r"<think\b[^>]*>(.*)\Z", _THINK_BLOCK_RE.sub("", raw), re.DOTALL | re.IGNORECASE)
    if unclosed is not None:
        bodies.append(unclosed.group(1))
    return "".join(bodies)


def parse_stage_json(raw: str) -> dict[str, Any] | None:
    """Read one stage response as a JSON object, applying bounded repair."""
    for candidate in (strip_reasoning_blocks(raw), raw):
        if not candidate.strip():
            continue
        try:
            parsed = json_repair.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return cast(dict[str, Any], parsed)
        if isinstance(parsed, list):
            objects = [item for item in parsed if isinstance(item, dict)]
            if objects:
                return cast(dict[str, Any], max(objects, key=len))
    return None


def json_failure_detail(raw: str) -> str:
    """Describe why a response could not be read as a JSON object."""
    stripped = raw.strip()
    if not stripped:
        return "empty model response (0 chars)"
    preview = " ".join(stripped[:RAW_PREVIEW_CHARS].split())
    ellipsis = "…" if len(stripped) > RAW_PREVIEW_CHARS else ""
    return f'no JSON object in response ({len(stripped)} chars); response began: "{preview}{ellipsis}"'


def model_max_output_tokens(model_instance: ModelInvoker) -> int | None:
    """Return the model's declared output-token ceiling when available."""
    try:
        for rule in model_instance.get_model_schema().parameter_rules:
            if rule.name == "max_tokens" and isinstance(rule.max, (int, float)):
                return int(rule.max)
    except Exception:
        logger.info("Workflow generator: could not read the model's max_tokens ceiling", exc_info=True)
    return None


def clamp_for_planner(params: dict[str, Any], max_output_tokens: int | None = None) -> dict[str, Any]:
    """Pin planner temperature and fill a model-aware output budget."""
    out = dict(params)
    out.setdefault("temperature", 0.2)
    if isinstance(out.get("temperature"), (int, float)) and out["temperature"] > 0.5:
        out["temperature"] = 0.2
    out.setdefault("max_tokens", max_output_tokens or PLANNER_FALLBACK_MAX_TOKENS)
    return out


class LLMJsonClient:
    """Deep module for retrying model calls and returning JSON objects."""

    def __init__(self, *, model_instance: ModelInvoker, model_parameters: dict[str, Any]) -> None:
        self.model_instance = model_instance
        self.model_parameters = model_parameters
        self.last_usage: tuple[int, int] | None = None

    def _capture_usage(self, result: object) -> None:
        for candidate in (result, getattr(result, "delta", None), getattr(result, "message", None)):
            usage = getattr(candidate, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            completion_tokens = getattr(usage, "completion_tokens", None)
            if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
                self.last_usage = (max(prompt_tokens, 0), max(completion_tokens, 0))
                return

    def _iter_text_with_retry(
        self,
        *,
        prompt_messages: Sequence[PromptMessage],
        model_parameters: dict[str, Any],
        stage: str,
        on_attempt_start: Callable[[], None] | None = None,
    ) -> Iterator[str]:
        last_exc: Exception | None = None
        for attempt in range(INVOKE_MAX_ATTEMPTS):
            if on_attempt_start is not None:
                on_attempt_start()
            try:
                stream_result = self.model_instance.invoke_llm(
                    prompt_messages=prompt_messages,
                    model_parameters=model_parameters,
                    stream=True,
                )
                self._capture_usage(stream_result)
                if isinstance(stream_result, LLMResult) or (
                    hasattr(stream_result, "message")
                    and callable(getattr(stream_result.message, "get_text_content", None))
                ):
                    text = stream_result.message.get_text_content() or ""
                    if text:
                        yield text
                    return

                streamed_chars = 0
                finish_reason = ""
                for chunk in stream_result:
                    self._capture_usage(chunk)
                    finish_reason = chunk_finish_reason(chunk) or finish_reason
                    delta = extract_chunk_text_delta(chunk)
                    if delta:
                        streamed_chars += len(delta)
                        yield delta
                if finish_reason in _TRUNCATED_FINISH_REASONS:
                    raise StageTruncatedError(
                        stage,
                        f"model stopped at its output limit after {streamed_chars} chars "
                        f"(finish_reason={finish_reason!r})",
                    )
                if streamed_chars == 0:
                    logger.warning(
                        "Workflow generator: %s stream produced no text; retrying without streaming",
                        stage,
                    )
                    blocking_result = self.model_instance.invoke_llm(
                        prompt_messages=prompt_messages,
                        model_parameters=model_parameters,
                        stream=False,
                    )
                    self._capture_usage(blocking_result)
                    blocking_text = blocking_result.message.get_text_content() or ""
                    if blocking_text:
                        yield blocking_text
                return
            except _TRANSIENT_INVOKE_ERRORS as exc:
                last_exc = exc
                if attempt >= INVOKE_MAX_ATTEMPTS - 1:
                    break
                delay = INVOKE_BACKOFF_SECONDS[min(attempt, len(INVOKE_BACKOFF_SECONDS) - 1)]
                logger.info(
                    "Workflow generator: %s transient invoke error (attempt %s/%s): %s; retrying in %ss",
                    stage,
                    attempt + 1,
                    INVOKE_MAX_ATTEMPTS,
                    exc,
                    delay,
                )
                time.sleep(delay)
        assert last_exc is not None
        raise last_exc

    def iter_json(
        self,
        *,
        messages: Sequence[PromptMessage],
        stage: str,
        model_parameters: dict[str, Any] | None = None,
    ) -> Generator[str, None, dict[str, Any]]:
        """Yield text deltas and return the parsed object through StopIteration."""
        parameters = model_parameters if model_parameters is not None else self.model_parameters
        self.last_usage = None
        last_detail = ""
        for attempt in range(2):
            attempt_messages = messages if attempt == 0 else [*messages, UserPromptMessage(content=JSON_RETRY_HINT)]
            chunks: list[str] = []
            for delta in self._iter_text_with_retry(
                prompt_messages=attempt_messages,
                model_parameters=parameters,
                stage=stage,
                on_attempt_start=chunks.clear,
            ):
                chunks.append(delta)
                yield delta
            text = "".join(chunks)
            parsed = parse_stage_json(text)
            if parsed is not None:
                if attempt > 0:
                    logger.info("Workflow generator: %s JSON parse recovered on retry", stage)
                return parsed
            last_detail = json_failure_detail(text)
            logger.warning(
                "Workflow generator: %s returned no JSON object on attempt %s: %s",
                stage,
                attempt + 1,
                last_detail,
            )
        raise StageJSONError(stage, last_detail or "JSON parse failed")

    def invoke_json(
        self,
        *,
        messages: Sequence[PromptMessage],
        stage: str,
        model_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Consume the streaming implementation and return only its JSON value."""
        iterator = self.iter_json(
            messages=messages,
            stage=stage,
            model_parameters=model_parameters,
        )
        try:
            while True:
                next(iterator)
        except StopIteration as stop:
            return cast(dict[str, Any], stop.value)
