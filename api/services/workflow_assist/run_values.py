"""Pure persistence-value preparation shared by Workflow Assist modules.

These helpers copy and validate caller-owned values before a transactional
state transition mutates ORM state. Event payload sizing uses the same
dialect-aware bind contract as ``WorkflowAssistRunEvent.payload``.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.engine.interfaces import Dialect

from models.types import LimitedAdjustedJSON, validate_json_value, validate_text_byte_limit
from models.workflow_assist import WORKFLOW_ASSIST_RUN_EVENT_PAYLOAD_MAX_BYTES, WORKFLOW_ASSIST_RUN_INPUT_MAX_BYTES

_SECRET_FIELD_PARTS = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "authorization",
    "access_token",
    "refresh_token",
    "private_key",
    "privatekey",
    "encrypted",
)
_MAX_CANDIDATE_GRAPH_BYTES = 4 * 1024 * 1024
PROMPT_SKIP_RANGES_KEY = "prompt_skip_ranges"


def sequence_in_prompt_skip_ranges(sequence: int, ranges: object) -> bool:
    """Return whether a conversation message sequence sits inside a retry hole."""
    if not isinstance(ranges, list):
        return False
    for item in ranges:
        if not isinstance(item, dict):
            continue
        after = item.get("after")
        until = item.get("until")
        if isinstance(after, int) and isinstance(until, int) and after < sequence <= until:
            return True
    return False


_RUN_EVENT_PAYLOAD_TYPE = LimitedAdjustedJSON(
    max_bytes=WORKFLOW_ASSIST_RUN_EVENT_PAYLOAD_MAX_BYTES,
    field_name="event payload",
)


class WorkflowAssistConversationPayloadTooLargeError(ValueError):
    """Raised when a persisted Workflow Assist value exceeds its byte budget."""

    error_code = "CONVERSATION_STATE_TOO_LARGE"


def sanitize_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Return a recursively copied mapping with secret-shaped keys removed."""
    sanitized = _sanitize_value(value)
    if not isinstance(sanitized, dict):
        raise ValueError("Workflow-assist payload must serialize to an object")
    return sanitized


_TOOL_CALL_PUBLIC_ARGUMENT_KEYS = ("id", "mode", "type", "title", "purpose", "node_id")


def project_sse_event_payload(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Project a persisted run event into the browser-visible SSE/timeline payload."""
    data = sanitize_payload(payload) if isinstance(payload, dict) else {}
    data.pop("graph", None)
    data.pop("candidate_graph", None)
    if event == "tool_call":
        return _project_tool_call(data)
    if event == "tool_result":
        return _project_tool_result(data)
    if event == "candidate.updated":
        projected: dict[str, Any] = {}
        if "revision" in data:
            projected["revision"] = data["revision"]
        if isinstance(data.get("diff"), dict):
            projected["diff"] = data["diff"]
        return projected
    return data


def _project_tool_call(data: dict[str, Any]) -> dict[str, Any]:
    raw_arguments = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
    public_arguments = {
        key: raw_arguments[key]
        for key in _TOOL_CALL_PUBLIC_ARGUMENT_KEYS
        if isinstance(raw_arguments.get(key), str) and raw_arguments[key]
    }
    name = str(data.get("name") or "")
    projected: dict[str, Any] = {
        "tool_call_id": data.get("tool_call_id") or data.get("id"),
        "name": name,
        "summary": _tool_call_summary(name, public_arguments),
    }
    if public_arguments:
        projected["arguments"] = public_arguments
    return projected


def _project_tool_result(data: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {
        "tool_call_id": data.get("tool_call_id") or data.get("id"),
        "name": data.get("name"),
        "ok": data.get("ok"),
        "summary": data.get("summary") or "",
    }
    if "changed" in data:
        projected["changed"] = data["changed"]
    if "elapsed_ms" in data:
        projected["elapsed_ms"] = data["elapsed_ms"]
    node_ids = data.get("changed_node_ids")
    if isinstance(node_ids, list):
        projected["changed_node_ids"] = [item for item in node_ids if isinstance(item, str)]
    if data.get("ok") is False:
        if isinstance(data.get("error"), str) and data["error"]:
            projected["error"] = data["error"]
        if isinstance(data.get("retryable"), bool):
            projected["retryable"] = data["retryable"]
    return {key: value for key, value in projected.items() if value is not None}


def _tool_call_summary(name: str, arguments: dict[str, str]) -> str:
    if name == "build_node":
        mode = arguments.get("mode") or "create"
        title = arguments.get("title") or arguments.get("id") or ""
        node_type = arguments.get("type") or ""
        return " ".join(part for part in (mode, "node", title, node_type) if part)
    if name == "connect":
        return f"connect {arguments.get('id') or ''}".strip()
    if name:
        return name
    return "tool"


def ensure_payload_size(value: dict[str, Any], *, max_bytes: int) -> None:
    """Enforce the legacy compact-JSON byte budget used by Conversation values."""
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    if len(serialized) > max_bytes:
        raise WorkflowAssistConversationPayloadTooLargeError(
            f"Workflow-assist persistence payload exceeds the {max_bytes}-byte limit"
        )


def prepare_candidate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Copy, sanitize, JSON-validate, and size-check a server candidate graph."""
    sanitized_graph = sanitize_payload(graph)
    validate_json_value(sanitized_graph, field_name="candidate graph")
    ensure_payload_size(sanitized_graph, max_bytes=_MAX_CANDIDATE_GRAPH_BYTES)
    return sanitized_graph


def prepare_model_config(model_config: dict[str, Any]) -> dict[str, Any]:
    """Copy and JSON-validate persisted model selection/configuration."""
    sanitized_config = sanitize_payload(model_config)
    return validate_json_value(sanitized_config, field_name="model_config")


def prepare_run_input(message: str) -> str:
    """Normalize a non-empty user turn and enforce its exact UTF-8 budget."""
    normalized_message = message.strip()
    if not normalized_message:
        raise ValueError("message must be non-empty")
    return validate_text_byte_limit(
        normalized_message,
        max_bytes=WORKFLOW_ASSIST_RUN_INPUT_MAX_BYTES,
        field_name="input",
    )


def prepare_run_event_payload(payload: dict[str, Any], *, dialect: Dialect) -> dict[str, Any]:
    """Copy and validate an event payload against the exact dialect bind contract."""
    sanitized_payload = sanitize_payload(payload)
    processor = _RUN_EVENT_PAYLOAD_TYPE.bind_processor(dialect)
    if processor is None:
        raise RuntimeError("Workflow Assist event payload type has no bind processor")
    processor(sanitized_payload)
    return sanitized_payload


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_value(item) for key, item in value.items() if not _is_secret_field(str(key))}
    if isinstance(value, list | tuple):
        return [_sanitize_value(item) for item in value]
    return value


def _is_secret_field(field_name: str) -> bool:
    normalized = field_name.lower().replace("-", "_")
    return any(part in normalized for part in _SECRET_FIELD_PARTS)
