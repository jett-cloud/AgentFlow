"""run limits."""

from __future__ import annotations

import time
from typing import Protocol

from core.workflow.generator.agent.types import (
    AgentEvent,
)

_FUSE_MESSAGES = {
    "max_model_calls": "Agent model-call limit reached",
    "max_tool_calls": "Agent tool-call limit reached",
    "max_total_tokens": "Agent token limit reached",
    "max_elapsed_time": "Agent elapsed-time limit reached",
    "empty_response": "Agent received empty model responses",
}


class AgentCancellation(Protocol):
    """Read-only abort signal for one agent run. Values are §3.4 reasons."""

    def reason(self) -> str | None: ...


class AgentRunLimits(Protocol):
    """Runaway thresholds. ``max_model_calls`` is required and must be a positive int."""

    max_model_calls: int


def _require_max_model_calls(limits: AgentRunLimits) -> int:
    value = getattr(limits, "max_model_calls", None)
    if not isinstance(value, int) or value <= 0:
        raise ValueError("limits.max_model_calls must be a positive int")
    return value


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _guard_reason(
    limits: AgentRunLimits,
    usage: dict[str, int],
    started_at: float,
    *,
    max_model_calls: int,
    model_already_counted: bool = False,
) -> str | None:
    """Return the spent fuse name, or None if the run may continue.

    Model-call budget is checked *before* the next invoke: ``usage['model_calls']``
    is the number already made. Tool / token / elapsed checks use current totals.
    ``model_already_counted`` skips the model comparison when we just billed a
    tool call on the same iteration.
    """
    if not model_already_counted and usage["model_calls"] >= max_model_calls:
        return "max_model_calls"
    max_tools = _optional_int(getattr(limits, "max_tool_calls", None))
    if max_tools is not None and usage["tool_calls"] > max_tools:
        return "max_tool_calls"
    max_tokens = _optional_int(getattr(limits, "max_total_tokens", None))
    if max_tokens is not None and usage["tokens"] >= max_tokens:
        return "max_total_tokens"
    max_elapsed = getattr(limits, "max_elapsed_time", None)
    if isinstance(max_elapsed, (int, float)) and max_elapsed > 0:
        if time.monotonic() - started_at >= max_elapsed:
            return "max_elapsed_time"
    return None


def _aborted(cancellation: AgentCancellation) -> AgentEvent | None:
    value = cancellation.reason()
    if isinstance(value, str) and value:
        return ("aborted", {"termination_reason": value})
    return None


def _error_event(termination_reason: str, message: str, usage: dict[str, int]) -> AgentEvent:
    return (
        "error",
        {
            "message": message,
            "errors": [],
            "termination_reason": termination_reason,
            "usage": dict(usage),
        },
    )
