"""Parse model turns into typed tool calls and reject malformed protocol."""

from __future__ import annotations

import json
import uuid
from typing import Any

from core.workflow.generator.agent.types import (
    ToolCall,
)
from core.workflow.generator.model_io.llm_response import extract_reasoning_blocks, strip_reasoning_blocks


class WorkflowAgentProtocolError(ValueError):
    """A tool envelope cannot be dispatched without inventing its arguments."""


def _split_public_and_reasoning(text: str | None) -> tuple[str | None, str | None]:
    if not isinstance(text, str) or not text:
        return None, None
    reasoning = extract_reasoning_blocks(text).strip() or None
    public = strip_reasoning_blocks(text) or None
    return public, reasoning


def _parse_turn(turn: object, json_seq: int) -> tuple[list[ToolCall], str | None]:
    if turn is None:
        return [], None
    if isinstance(turn, str):
        stripped = turn.strip()
        return [], stripped or None
    raw = _turn_mapping(turn)
    text = _turn_text(raw)
    native = raw.get("tool_calls")
    if isinstance(native, list) and native:
        calls = [_normalize_call(item, json_seq + index) for index, item in enumerate(native)]
        return calls, _strip_embedded_tool_json(text)
    if isinstance(raw.get("name"), str) and "arguments" in raw:
        return [_normalize_call(raw, json_seq)], _strip_embedded_tool_json(text)
    return [], text


def _turn_text(raw: dict[str, Any]) -> str | None:
    text = raw.get("text")
    if isinstance(text, str) and text.strip():
        return text
    return None


def _is_tool_call_object(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    name = value.get("name")
    has_name = isinstance(name, str) and bool(name.strip())
    if has_name and "arguments" in value:
        return True
    call_id = value.get("id")
    return has_name and isinstance(call_id, str) and call_id.lower().startswith("call")


def _matching_brace(text: str, start: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _strip_embedded_tool_json(text: str | None) -> str | None:
    if not isinstance(text, str) or not text:
        return None
    output: list[str] = []
    cursor = 0
    while cursor < len(text):
        start = text.find("{", cursor)
        if start < 0:
            output.append(text[cursor:])
            break
        output.append(text[cursor:start])
        end = _matching_brace(text, start)
        if end < 0:
            output.append(text[start:])
            break
        snippet = text[start : end + 1]
        try:
            parsed = json.loads(snippet)
        except json.JSONDecodeError:
            output.append(snippet)
        else:
            if not _is_tool_call_object(parsed):
                output.append(snippet)
        cursor = end + 1
    stripped = "".join(output)
    stripped = "\n".join(line.rstrip() for line in stripped.splitlines())
    while "\n\n\n" in stripped:
        stripped = stripped.replace("\n\n\n", "\n\n")
    stripped = stripped.strip()
    return stripped or None


def _turn_mapping(turn: object) -> dict[str, Any]:
    if isinstance(turn, dict):
        return turn
    mapping: dict[str, Any] = {}
    for key in ("text", "tool_calls", "name", "arguments", "id"):
        if hasattr(turn, key):
            mapping[key] = getattr(turn, key)
    return mapping


def _normalize_call(raw: object, seq: int) -> ToolCall:
    """Validate the envelope; malformed arguments must not become an empty call."""
    payload = raw if isinstance(raw, dict) else _turn_mapping(raw)
    call_id = payload.get("id")
    if not isinstance(call_id, str) or not call_id:
        call_id = f"json-{seq}-{uuid.uuid4().hex[:8]}"
    name = str(payload.get("name") or "")
    if not name.strip():
        raise WorkflowAgentProtocolError("Tool name is missing")
    arguments = payload.get("arguments")
    if arguments is None or arguments == "":
        arguments = {}
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise WorkflowAgentProtocolError("Tool arguments are not complete JSON") from exc
        arguments = parsed
    if not isinstance(arguments, dict):
        raise WorkflowAgentProtocolError("Tool arguments must be an object")
    return {"id": call_id, "name": name, "arguments": arguments}
