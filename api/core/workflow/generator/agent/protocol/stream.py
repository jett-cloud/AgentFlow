"""Assemble one native-tool model turn from streamed chunks.

Public text is emitted as soon as it cannot still be a ``<think>`` tag prefix.
Reasoning is a cross-chunk grammar: the filter holds an ambiguous suffix and
never publishes bytes while inside an open think block. Think bodies and
provider ``reasoning_content`` are captured on a separate channel. Tool-call
argument fragments are merged by ``index`` (or ``id``) and only become
dispatchable ``tool_calls`` when the concatenated arguments parse as JSON.
Incomplete JSON is rejected, never executed. Text-channel tool protocols are
quarantined before publication; callers can retry with native tools. Safe held
text is available from ``drain_final_events`` after ``finish``.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Iterator
from typing import Any

from core.workflow.generator.agent.protocol.protocol_text import ProtocolTextBuffer
from core.workflow.generator.agent.types import ToolCall
from core.workflow.generator.model_io.llm_response import extract_chunk_text_delta

StreamTextEvent = tuple[str, dict[str, Any]]

_OPEN_TAG_RE = re.compile(r"^<think\b[^>]*>", re.IGNORECASE)
_OPEN_INCOMPLETE_RE = re.compile(r"^<think\b[^>]*$", re.IGNORECASE)
_CLOSE_TAG_RE = re.compile(r"^</think\s*>", re.IGNORECASE)
_CLOSE_INCOMPLETE_RE = re.compile(r"^</think\s*$", re.IGNORECASE)
_OPEN_PREFIX = "<think"
_CLOSE_PREFIX = "</think"
REASONING_MAX_BYTES = 32 * 1024
_TRUNCATION_MARK = "…[truncated]"


class _ReasoningFilter:
    """Split ``<think>`` bodies from public text across streamed chunks."""

    _in_reasoning: bool
    _hold: str

    def __init__(self) -> None:
        self._in_reasoning = False
        self._hold = ""

    def push(self, text: str) -> tuple[str, str]:
        data = self._hold + text
        self._hold = ""
        public: list[str] = []
        reasoning: list[str] = []
        index = 0
        length = len(data)
        while index < length:
            if self._in_reasoning:
                lt = data.find("<", index)
                if lt < 0:
                    reasoning.append(data[index:])
                    return "".join(public), "".join(reasoning)
                rest = data[lt:]
                closed = _CLOSE_TAG_RE.match(rest)
                if closed is not None:
                    if lt > index:
                        reasoning.append(data[index:lt])
                    self._in_reasoning = False
                    index = lt + closed.end()
                    continue
                if _is_possible_close_prefix(rest):
                    if lt > index:
                        reasoning.append(data[index:lt])
                    self._hold = rest
                    return "".join(public), "".join(reasoning)
                reasoning.append(data[index : lt + 1])
                index = lt + 1
                continue
            lt = data.find("<", index)
            if lt < 0:
                public.append(data[index:])
                return "".join(public), "".join(reasoning)
            public.append(data[index:lt])
            rest = data[lt:]
            opened = _OPEN_TAG_RE.match(rest)
            if opened is not None:
                self._in_reasoning = True
                index = lt + opened.end()
                continue
            if _is_possible_open_prefix(rest):
                self._hold = rest
                return "".join(public), "".join(reasoning)
            public.append("<")
            index = lt + 1
        return "".join(public), "".join(reasoning)

    def flush(self) -> str:
        """Release a held public suffix at end of turn. Never leak in-think bytes."""
        if self._in_reasoning:
            self._hold = ""
            return ""
        leftover = self._hold
        self._hold = ""
        return leftover


def _is_possible_open_prefix(rest: str) -> bool:
    lower = rest.lower()
    return _OPEN_PREFIX.startswith(lower) or _OPEN_INCOMPLETE_RE.match(rest) is not None


def _is_possible_close_prefix(rest: str) -> bool:
    lower = rest.lower()
    return _CLOSE_PREFIX.startswith(lower) or _CLOSE_INCOMPLETE_RE.match(rest) is not None


class StreamTurnAssembler:
    """Fold provider chunks into public text events and a complete turn."""

    message_id: str
    stream_mode: str
    _text_parts: list[str]
    _reasoning_parts: list[str]
    _text_delta_index: int
    _reasoning_delta_index: int
    _calls: dict[str, dict[str, Any]]
    _order: int
    _filter: _ReasoningFilter
    _capped: bool

    def __init__(self, *, message_id: str, stream_mode: str = "native") -> None:
        self.message_id = message_id
        self.stream_mode = stream_mode
        self._text_parts = []
        self._reasoning_parts = []
        self._text_delta_index = 0
        self._reasoning_delta_index = 0
        self._calls = {}
        self._order = 0
        self._filter = _ReasoningFilter()
        self._capped = False
        self._protocol = ProtocolTextBuffer()
        self._final_events: list[StreamTextEvent] = []

    def push(self, chunk: object) -> list[StreamTextEvent]:
        """Consume one chunk. Returns public text and/or reasoning events."""
        events: list[StreamTextEvent] = []
        public, think_delta = self._filter.push(_chunk_text(chunk))
        public = self._protocol.push(public)
        provider_reasoning = _chunk_reasoning(chunk)
        reasoning_delta = think_delta
        if provider_reasoning and not _already_captured(self._reasoning_so_far() + think_delta, provider_reasoning):
            reasoning_delta = f"{think_delta}{provider_reasoning}" if think_delta else provider_reasoning
        if reasoning_delta:
            clipped = self._append_reasoning(reasoning_delta)
            if clipped:
                events.append(
                    (
                        "reasoning",
                        {
                            "delta": clipped,
                            "message_id": self.message_id,
                            "delta_index": self._reasoning_delta_index,
                        },
                    )
                )
                self._reasoning_delta_index += 1
        if public:
            events.append(
                (
                    "text",
                    {
                        "delta": public,
                        "message_id": self.message_id,
                        "delta_index": self._text_delta_index,
                    },
                )
            )
            self._text_delta_index += 1
            self._text_parts.append(public)
        for fragment in _chunk_tool_fragments(chunk):
            self._merge_fragment(fragment)
        return events

    def finish(self) -> dict[str, Any]:
        """Return the completed turn. Incomplete tool JSON is omitted."""
        leftover = self._protocol.push(self._filter.flush())
        checked = self._protocol.finish()
        leftover += checked.text
        if leftover:
            self._text_parts.append(leftover)
            self._final_events.append(
                (
                    "text",
                    {
                        "delta": leftover,
                        "message_id": self.message_id,
                        "delta_index": self._text_delta_index,
                    },
                )
            )
            self._text_delta_index += 1
        tool_calls: list[dict[str, Any]] = []
        invalid_native = False
        for item in sorted(self._calls.values(), key=lambda row: int(row["order"])):
            parsed = _parse_arguments(str(item.get("arguments") or ""))
            name = str(item.get("name") or "")
            if parsed is None or not name:
                invalid_native = True
                continue
            call_id = str(item.get("id") or "")
            tool_calls.append({"id": call_id, "name": name, "arguments": parsed})
        return {
            "text": "".join(self._text_parts),
            "reasoning": "".join(self._reasoning_parts),
            "tool_calls": [] if invalid_native else tool_calls,
            "protocol_error": checked.protocol_error or invalid_native,
            "stream_mode": self.stream_mode,
            "message_id": self.message_id,
        }

    def drain_final_events(self) -> list[StreamTextEvent]:
        """Deliver held safe text exactly once, after finish and before dispatch."""
        events, self._final_events = self._final_events, []
        return events

    def _reasoning_so_far(self) -> str:
        return "".join(self._reasoning_parts)

    def _append_reasoning(self, delta: str) -> str:
        if self._capped or not delta:
            return ""
        current = self._reasoning_so_far().encode("utf-8")
        mark = _TRUNCATION_MARK.encode("utf-8")
        encoded = delta.encode("utf-8")
        if len(current) + len(encoded) <= REASONING_MAX_BYTES:
            self._reasoning_parts.append(delta)
            return delta
        room = REASONING_MAX_BYTES - len(current)
        if room <= len(mark):
            self._capped = True
            return ""
        keep = encoded[: room - len(mark)]
        while keep and (keep[-1] & 0xC0) == 0x80:
            keep = keep[:-1]
        clipped = keep.decode("utf-8", errors="ignore") + _TRUNCATION_MARK
        self._reasoning_parts.append(clipped)
        self._capped = True
        return clipped

    def _merge_fragment(self, fragment: dict[str, Any]) -> None:
        key = _merge_key(fragment, fallback=len(self._calls))
        current = self._calls.get(key)
        if current is None:
            current = {"id": "", "name": "", "arguments": "", "order": self._order}
            self._order += 1
            self._calls[key] = current
        call_id = fragment.get("id")
        if isinstance(call_id, str) and call_id:
            current["id"] = call_id
        name = fragment.get("name")
        if isinstance(name, str) and name:
            current["name"] = name
        arguments = fragment.get("arguments")
        if isinstance(arguments, str) and arguments:
            current["arguments"] = str(current["arguments"]) + arguments
        elif isinstance(arguments, dict):
            current["arguments"] = json.dumps(arguments, ensure_ascii=False)


def assemble_stream_turn(
    chunks: Iterable[object],
    *,
    blocking_result: object | None = None,
    message_id: str | None = None,
) -> tuple[list[StreamTextEvent], dict[str, Any]]:
    """Fold a stream, or one blocking result, into text events plus a turn."""
    resolved_id = message_id or f"agent-message-{uuid.uuid4().hex[:12]}"
    if blocking_result is not None:
        assembler = StreamTurnAssembler(message_id=resolved_id, stream_mode="fallback")
        events = assembler.push(_blocking_as_chunk(blocking_result))
        turn = assembler.finish()
        events.extend(assembler.drain_final_events())
        return events, turn
    assembler = StreamTurnAssembler(message_id=resolved_id, stream_mode="native")
    events: list[StreamTextEvent] = []
    for chunk in chunks:
        events.extend(assembler.push(chunk))
    turn = assembler.finish()
    events.extend(assembler.drain_final_events())
    return events, turn


def iter_complete_tool_calls(turn: dict[str, Any]) -> Iterator[ToolCall]:
    """Yield dispatchable tool calls from a finished streamed turn."""
    for item in turn.get("tool_calls") or []:
        if not isinstance(item, dict):
            continue
        yield {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "arguments": item["arguments"] if isinstance(item.get("arguments"), dict) else {},
        }


def _already_captured(captured: str, candidate: str) -> bool:
    return bool(candidate) and candidate in captured


def _chunk_text(chunk: object) -> str:
    if isinstance(chunk, dict):
        text = chunk.get("text")
        return text if isinstance(text, str) else ""
    try:
        return extract_chunk_text_delta(chunk)  # type: ignore[arg-type]
    except Exception:
        message = getattr(getattr(chunk, "delta", None), "message", None)
        content = getattr(message, "content", None)
        return content if isinstance(content, str) else ""


def _chunk_reasoning(chunk: object) -> str:
    if isinstance(chunk, dict):
        value = chunk.get("reasoning_content")
        return value if isinstance(value, str) else ""
    message = getattr(getattr(chunk, "delta", None), "message", None)
    value = getattr(message, "reasoning_content", None)
    if isinstance(value, str) and value:
        return value
    delta = getattr(chunk, "delta", None)
    nested = getattr(delta, "reasoning_content", None)
    return nested if isinstance(nested, str) else ""


def _chunk_tool_fragments(chunk: object) -> list[dict[str, Any]]:
    if isinstance(chunk, dict):
        raw = chunk.get("tool_calls")
        return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    message = getattr(getattr(chunk, "delta", None), "message", None)
    raw_calls = getattr(message, "tool_calls", None) or []
    fragments: list[dict[str, Any]] = []
    for item in raw_calls:
        function = getattr(item, "function", None)
        fragments.append(
            {
                "id": getattr(item, "id", "") or "",
                "index": getattr(item, "index", None),
                "name": getattr(function, "name", None) if function is not None else getattr(item, "name", None),
                "arguments": getattr(function, "arguments", None)
                if function is not None
                else getattr(item, "arguments", None),
            }
        )
    return fragments


def _blocking_as_chunk(result: object) -> object:
    message = getattr(result, "message", result)
    text = ""
    get_text = getattr(message, "get_text_content", None)
    if callable(get_text):
        text = get_text() or ""
    elif isinstance(getattr(message, "content", None), str):
        text = message.content
    reasoning = getattr(message, "reasoning_content", None)
    chunk = SimpleChunk(text=text, tool_calls=getattr(message, "tool_calls", None) or [])
    if isinstance(reasoning, str) and reasoning:
        chunk.delta.message.reasoning_content = reasoning
    return chunk


class SimpleChunk:
    """Minimal LLMResultChunk-shaped object for the blocking fallback path."""

    def __init__(self, *, text: str, tool_calls: list[object]) -> None:
        self.delta = SimpleDelta(message=SimpleMessage(content=text, tool_calls=tool_calls))


class SimpleDelta:
    def __init__(self, *, message: SimpleMessage) -> None:
        self.message = message
        self.finish_reason = None


class SimpleMessage:
    def __init__(self, *, content: str, tool_calls: list[object]) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content: str | None = None


def _merge_key(fragment: dict[str, Any], fallback: int) -> str:
    index = fragment.get("index")
    if isinstance(index, int):
        return f"i:{index}"
    call_id = fragment.get("id")
    if isinstance(call_id, str) and call_id:
        return f"id:{call_id}"
    return f"i:{fallback}"


def _parse_arguments(raw: str) -> dict[str, Any] | None:
    stripped = raw.strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
