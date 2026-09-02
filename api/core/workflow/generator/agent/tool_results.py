"""ToolResult envelopes and the retryable lookup table.

``retryable`` is looked up from ``RETRYABLE_BY_ERROR_CODE``; handlers must not
set it ad hoc. Failures are always a ``ToolResult`` with ``ok=False``, never an
exception.
"""

from typing import Any

from core.workflow.generator.agent.types import ToolCall, ToolResult

RETRYABLE_BY_ERROR_CODE: dict[str, bool] = {
    "NODE_NOT_FOUND": True,
    "NODE_EXISTS": True,
    "INVALID_PARENT": True,
    "AMBIGUOUS_EDGE": True,
    "INVALID_ARGUMENT": True,
    "TYPE_UNCHANGED_USE_UPDATE": True,
    "UNKNOWN_DATASET": True,
    "UNKNOWN_TOOL": True,
    "PERMISSION_DENIED": False,
    "RESOURCE_FORBIDDEN": False,
    "UNSUPPORTED_NODE_TYPE": False,
    "CAPABILITY_UNAVAILABLE": False,
    "LIVE_RUN_REQUIRES_CONSENT": True,
}


def retryable(error_code: str) -> bool:
    return RETRYABLE_BY_ERROR_CODE[error_code]


def ok(call: ToolCall, *, changed: bool, content: dict[str, object]) -> ToolResult:
    return {
        "tool_call_id": call["id"],
        "name": call["name"],
        "ok": True,
        "changed": changed,
        "content": content,
        "error": None,
        "error_code": None,
        "retryable": False,
    }


def error(call: ToolCall, error_code: str, message: str) -> ToolResult:
    return {
        "tool_call_id": call["id"],
        "name": call["name"],
        "ok": False,
        "changed": False,
        "content": None,
        "error": message,
        "error_code": error_code,
        "retryable": retryable(error_code),
    }


def require_str(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if isinstance(value, str) and value:
        return value
    return None
