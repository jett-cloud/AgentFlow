"""core.workflow.generator.model io.budget."""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING, Any, cast

from core.workflow.generator.model_io.llm_response import LLMJsonClient

if TYPE_CHECKING:
    pass


class ModelCallBudgetExceededError(RuntimeError):
    """A main-agent, compactor, or nested Builder call exceeded one run budget."""


class RunCancelledError(RuntimeError):
    """A nested model call was about to start after its agent run was cancelled."""


@dataclass
class ModelCallBudget:
    """Thread-safe shared model-call counter for one agent-loop invocation."""

    limit: int
    cancellation_reason: Callable[[], str | None] | None = field(default=None, repr=False)
    _used: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    def reserve(self) -> None:
        reason = self.cancellation_reason() if self.cancellation_reason is not None else None
        if reason:
            raise RunCancelledError(reason)
        with self._lock:
            if self._used >= self.limit:
                raise ModelCallBudgetExceededError("Agent model-call limit reached")
            self._used += 1


class _BudgetedLLMJsonClient:
    """Reserve one shared-budget slot for every logical ``iter_json`` call."""

    def __init__(self, client: LLMJsonClient, budget: ModelCallBudget | None) -> None:
        self._client = client
        self._budget = budget

    def iter_json(self, *, messages: Any, stage: str, **kwargs: Any) -> Generator[str, None, dict[str, Any]]:
        if self._budget is not None:
            self._budget.reserve()
        return (yield from self._client.iter_json(messages=messages, stage=stage, **kwargs))


def budgeted_llm_json_client(client: LLMJsonClient, budget: ModelCallBudget | None) -> LLMJsonClient:
    """Wrap a Builder client without changing direct tool calls outside the loop."""
    if budget is None:
        return client
    return cast(LLMJsonClient, _BudgetedLLMJsonClient(client, budget))
