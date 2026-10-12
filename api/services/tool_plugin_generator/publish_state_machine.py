"""Explicit lifecycle and trace recording for one tool-plugin publish attempt."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from time import monotonic
from typing import Any
from uuid import uuid4


class PublishState(StrEnum):
    PREPARING = "preparing"
    PREFLIGHT = "preflight"
    STAGE_CLEANUP = "stage_cleanup"
    STAGE_INSTALL = "stage_install"
    STAGE_VERIFY = "stage_verify"
    COMMIT_INSTALL = "commit_install"
    PERSIST = "persist"
    CLEANUP = "cleanup"
    PUBLISHED = "published"
    FAILED = "failed"
    ROLLBACK_FAILED = "rollback_failed"


_TERMINAL_STATES = frozenset(
    {PublishState.PUBLISHED, PublishState.FAILED, PublishState.ROLLBACK_FAILED}
)

_ALLOWED_TRANSITIONS: dict[PublishState, frozenset[PublishState]] = {
    PublishState.PREPARING: frozenset({PublishState.PREFLIGHT, PublishState.FAILED}),
    PublishState.PREFLIGHT: frozenset(
        {PublishState.STAGE_CLEANUP, PublishState.COMMIT_INSTALL, PublishState.FAILED}
    ),
    PublishState.STAGE_CLEANUP: frozenset(
        {PublishState.STAGE_INSTALL, PublishState.FAILED, PublishState.ROLLBACK_FAILED}
    ),
    PublishState.STAGE_INSTALL: frozenset(
        {
            PublishState.STAGE_VERIFY,
            PublishState.CLEANUP,
            PublishState.FAILED,
            PublishState.ROLLBACK_FAILED,
        }
    ),
    PublishState.STAGE_VERIFY: frozenset(
        {
            PublishState.CLEANUP,
            PublishState.PERSIST,
            PublishState.FAILED,
            PublishState.ROLLBACK_FAILED,
        }
    ),
    PublishState.CLEANUP: frozenset(
        {PublishState.COMMIT_INSTALL, PublishState.FAILED, PublishState.ROLLBACK_FAILED}
    ),
    PublishState.COMMIT_INSTALL: frozenset(
        {
            PublishState.STAGE_VERIFY,
            PublishState.PERSIST,
            PublishState.FAILED,
            PublishState.ROLLBACK_FAILED,
        }
    ),
    PublishState.PERSIST: frozenset(
        {PublishState.PUBLISHED, PublishState.FAILED, PublishState.ROLLBACK_FAILED}
    ),
}


@dataclass(frozen=True)
class PublishStageResult:
    stage: str
    status: str
    started_at: str
    duration_ms: int
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass
class PublishAttempt:
    publish_mode: str
    attempt_id: str = field(default_factory=lambda: str(uuid4()))
    state: PublishState = PublishState.PREPARING
    draft_digest: str | None = None
    canonical_digest: str | None = None
    stages: list[PublishStageResult] = field(default_factory=list)
    before_transition: Callable[[PublishState], None] | None = field(default=None, repr=False, compare=False)
    on_change: Callable[[dict[str, Any]], None] | None = field(default=None, repr=False, compare=False)

    def _notify_change(self) -> None:
        if self.on_change is not None:
            self.on_change(self.to_trace())

    @property
    def terminal(self) -> bool:
        return self.state in _TERMINAL_STATES

    @staticmethod
    def allowed_targets(state: PublishState) -> frozenset[PublishState]:
        """Return the declared next states for tests, diagnostics, and UI adapters."""
        return _ALLOWED_TRANSITIONS.get(state, frozenset())

    def transition(self, target: PublishState) -> None:
        if self.terminal:
            raise ValueError(f"Cannot transition terminal publish attempt from {self.state} to {target}")
        allowed = self.allowed_targets(self.state)
        if target not in allowed:
            raise ValueError(f"Invalid publish transition: {self.state} -> {target}")
        if self.before_transition is not None:
            self.before_transition(target)
        self.state = target
        self._notify_change()

    def fail(self, *, rollback_failed: bool = False) -> None:
        """Move a non-terminal attempt to its truthful terminal failure state."""
        self.transition(PublishState.ROLLBACK_FAILED if rollback_failed else PublishState.FAILED)

    def publish(self) -> None:
        """Mark a successfully persisted attempt as published."""
        self.transition(PublishState.PUBLISHED)

    def record_stage(
        self,
        stage: PublishState,
        *,
        started_monotonic: float,
        started_at: datetime,
        status: str = "completed",
        details: dict[str, Any] | None = None,
    ) -> PublishStageResult:
        result = PublishStageResult(
            stage=stage.value,
            status=status,
            started_at=started_at.astimezone(UTC).isoformat(),
            duration_ms=max(0, int((monotonic() - started_monotonic) * 1000)),
            details=details,
        )
        self.stages.append(result)
        self._notify_change()
        return result

    @contextmanager
    def execute_stage(
        self,
        stage: PublishState,
        *,
        details: dict[str, Any] | None = None,
    ) -> Iterator[None]:
        if stage is not self.state:
            self.transition(stage)
        started_at = datetime.now(UTC)
        started_monotonic = monotonic()
        try:
            yield
        except Exception:
            self.record_stage(
                stage,
                started_monotonic=started_monotonic,
                started_at=started_at,
                status="failed",
                details=details,
            )
            raise
        self.record_stage(
            stage,
            started_monotonic=started_monotonic,
            started_at=started_at,
            details=details,
        )

    def to_trace(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "state": self.state.value,
            "publish_mode": self.publish_mode,
            "draft_digest": self.draft_digest,
            "canonical_digest": self.canonical_digest,
            "completed_stages": [item.stage for item in self.stages if item.status == "completed"],
            "stages": [item.to_dict() for item in self.stages],
        }
