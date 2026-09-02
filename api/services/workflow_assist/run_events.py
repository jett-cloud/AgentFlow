"""Owner-scoped read models for durable Workflow Assist runs and events.

This module is the sole UI read boundary for Run, RunEvent, timeline, and
candidate facts. Read paths always bind rows to the complete conversation
owner; live streams open short sessions per poll and never hold a session
while waiting for new activity.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from core.db.session_factory import session_factory
from models.workflow_assist import (
    WorkflowAssistConversation,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
)
from services.workflow_assist.conversations import WorkflowAssistConversationNotFound
from services.workflow_assist.run_types import RunOwner
from services.workflow_assist.run_values import project_sse_event_payload

_EVENT_BATCH_SIZE = 200
_STREAM_POLL_INTERVAL_SECONDS = 1.0
_STREAM_MAX_POLLS = 30
_STREAM_MAX_EMPTY_POLLS = 3


@dataclass(frozen=True)
class RunSummary:
    """Run metadata exposed without embedding event payloads."""

    run_id: str
    epoch: int
    status: str
    mode: str
    candidate_revision: int
    attempt: int
    selected_node: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    termination_reason: str | None


@dataclass(frozen=True)
class RunPage:
    """An ascending epoch page with its continuation coordinate."""

    items: tuple[RunSummary, ...]
    has_more: bool
    next_after_epoch: int


@dataclass(frozen=True)
class EventEnvelope:
    """The exact v2 event envelope shared by timeline and SSE replay."""

    event: str
    run_id: str
    epoch: int
    sequence: int
    step_id: str
    created_at: datetime
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Serialize only the public v2 envelope fields."""
        return {
            "event": self.event,
            "run_id": self.run_id,
            "epoch": self.epoch,
            "sequence": self.sequence,
            "step_id": self.step_id,
            "created_at": _rfc3339_utc(self.created_at),
            "data": deepcopy(self.data),
        }


@dataclass(frozen=True)
class TimelinePage:
    """A lexicographically ordered page of user and persisted run facts."""

    items: tuple[EventEnvelope, ...]
    has_more: bool
    cursor_epoch: int
    cursor_sequence: int


@dataclass(frozen=True)
class CandidateSnapshot:
    """Server-owned candidate plus completion and run reconciliation facts."""

    graph: dict[str, Any] | None
    revision: int
    base_hash: str | None
    completion_evidence: dict[str, Any] | None
    active_run: RunSummary | None
    latest_run: RunSummary | None


@dataclass(frozen=True)
class RunReconciliation:
    """Active/latest summaries without loading or copying candidate state."""

    active_run: RunSummary | None
    latest_run: RunSummary | None


@dataclass(frozen=True)
class StreamStart:
    """Request-start replay facts used to choose SSE or an empty 204."""

    events: tuple[EventEnvelope, ...]
    terminal: bool


class WorkflowAssistRunEventService:
    """Read durable Workflow Assist facts for one authenticated owner.

    The session is caller-owned. Every query first validates the active
    conversation and repeats the complete owner predicates on nested facts.
    """

    session: Session

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_runs(self, *, owner: RunOwner, after_epoch: int, limit: int) -> RunPage:
        """Return Run metadata after an exclusive epoch cursor, oldest first."""
        _validate_non_negative(after_epoch, field_name="after_epoch")
        _validate_limit(limit, maximum=100)
        self._get_conversation(owner)
        rows = tuple(
            self.session.scalars(
                select(WorkflowAssistRun)
                .where(
                    *self._run_owner_predicates(owner),
                    WorkflowAssistRun.epoch > after_epoch,
                )
                .order_by(WorkflowAssistRun.epoch.asc())
                .limit(limit + 1)
            ).all()
        )
        visible = rows[:limit]
        summaries = tuple(_run_summary(run) for run in visible)
        next_after_epoch = summaries[-1].epoch if summaries else after_epoch
        return RunPage(items=summaries, has_more=len(rows) > limit, next_after_epoch=next_after_epoch)

    def timeline(
        self,
        *,
        owner: RunOwner,
        after_epoch: int,
        after_sequence: int,
        limit: int,
    ) -> TimelinePage:
        """Merge sequence-zero Run inputs with RunEvents after a tuple cursor."""
        _validate_non_negative(after_epoch, field_name="after_epoch")
        _validate_non_negative(after_sequence, field_name="after_sequence")
        _validate_limit(limit, maximum=500)
        self._get_conversation(owner)

        user_runs = tuple(
            self.session.scalars(
                select(WorkflowAssistRun)
                .where(
                    *self._run_owner_predicates(owner),
                    WorkflowAssistRun.epoch > after_epoch,
                )
                .order_by(WorkflowAssistRun.epoch.asc())
                .limit(limit + 1)
            ).all()
        )
        user_events = tuple(
            EventEnvelope(
                event="user.message",
                run_id=run.id,
                epoch=run.epoch,
                sequence=0,
                step_id=f"user:{run.id}",
                created_at=run.created_at,
                data={"text": run.input, **({"references": run.references} if run.references else {})},
            )
            for run in user_runs
        )
        persisted = tuple(
            self.session.scalars(
                select(WorkflowAssistRunEvent)
                .join(WorkflowAssistRun, self._event_run_join())
                .where(
                    *self._event_owner_predicates(owner),
                    *self._run_owner_predicates(owner),
                    or_(
                        WorkflowAssistRunEvent.epoch > after_epoch,
                        and_(
                            WorkflowAssistRunEvent.epoch == after_epoch,
                            WorkflowAssistRunEvent.sequence > after_sequence,
                        ),
                    ),
                )
                .order_by(WorkflowAssistRunEvent.epoch.asc(), WorkflowAssistRunEvent.sequence.asc())
                .limit(limit + 1)
            ).all()
        )
        merged = sorted(
            (*user_events, *(_event_envelope(event) for event in persisted)),
            key=lambda item: (item.epoch, item.sequence),
        )
        visible = tuple(merged[:limit])
        cursor_epoch = visible[-1].epoch if visible else after_epoch
        cursor_sequence = visible[-1].sequence if visible else after_sequence
        return TimelinePage(
            items=visible,
            has_more=len(merged) > limit,
            cursor_epoch=cursor_epoch,
            cursor_sequence=cursor_sequence,
        )

    def list_events(
        self,
        *,
        owner: RunOwner,
        run_id: str,
        after: int,
        limit: int = _EVENT_BATCH_SIZE,
    ) -> tuple[EventEnvelope, ...]:
        """Replay a bounded, strictly-after sequence page for one owned Run."""
        _validate_non_negative(after, field_name="after")
        _validate_limit(limit, maximum=_EVENT_BATCH_SIZE)
        self._get_conversation(owner)
        run = self._get_run(owner, run_id)
        return self._list_events_for_run(owner=owner, run=run, after=after, limit=limit)

    def _list_events_for_run(
        self,
        *,
        owner: RunOwner,
        run: WorkflowAssistRun,
        after: int,
        limit: int,
    ) -> tuple[EventEnvelope, ...]:
        """Read one event page after its owned Run snapshot has been resolved."""
        records = self.session.scalars(
            select(WorkflowAssistRunEvent)
            .where(
                *self._event_owner_predicates(owner),
                WorkflowAssistRunEvent.run_id == run.id,
                WorkflowAssistRunEvent.epoch == run.epoch,
                WorkflowAssistRunEvent.sequence > after,
            )
            .order_by(WorkflowAssistRunEvent.sequence.asc())
            .limit(limit)
        ).all()
        return tuple(_event_envelope(record) for record in records)

    def get_candidate(self, *, owner: RunOwner) -> CandidateSnapshot:
        """Return candidate and run reconciliation facts from owned database rows."""
        conversation = self._get_conversation(owner)
        active = self._get_optional_run(owner, conversation.active_run_id)
        latest = self._get_optional_run(owner, conversation.latest_run_id)
        evidence = None
        if conversation.completion_run_id is not None:
            evidence = {
                "run_id": conversation.completion_run_id,
                "epoch": conversation.completion_epoch,
                "candidate_revision": conversation.completion_candidate_revision,
                "candidate_base_hash": conversation.completion_candidate_base_hash,
                "app_mode": _enum_value(conversation.completion_app_mode),
                "assertion": _enum_value(conversation.completion_assertion),
            }
        return CandidateSnapshot(
            graph=deepcopy(conversation.candidate_graph),
            revision=conversation.candidate_revision,
            base_hash=conversation.candidate_base_hash,
            completion_evidence=evidence,
            active_run=_run_summary(active) if active is not None else None,
            latest_run=_run_summary(latest) if latest is not None else None,
        )

    def get_reconciliation(self, *, owner: RunOwner) -> RunReconciliation:
        """Return only the Run pointers needed by a command conflict response."""
        pointers = self.session.execute(
            select(
                WorkflowAssistConversation.active_run_id,
                WorkflowAssistConversation.latest_run_id,
            ).where(
                WorkflowAssistConversation.id == owner.conversation_id,
                WorkflowAssistConversation.tenant_id == owner.tenant_id,
                WorkflowAssistConversation.app_id == owner.app_id,
                WorkflowAssistConversation.account_id == owner.account_id,
                WorkflowAssistConversation.is_deleted.is_(False),
            )
        ).one_or_none()
        if pointers is None:
            raise WorkflowAssistConversationNotFound()
        active = self._get_optional_run(owner, pointers.active_run_id)
        latest = self._get_optional_run(owner, pointers.latest_run_id)
        return RunReconciliation(
            active_run=_run_summary(active) if active is not None else None,
            latest_run=_run_summary(latest) if latest is not None else None,
        )

    def stream_start(self, *, owner: RunOwner, run_id: str, after: int) -> StreamStart:
        """Read Run status before its event page in the same short session.

        A visible terminal status implies the atomically committed terminal
        event is visible to the later event query. If a terminal commit lands
        after the status read, the frozen active state keeps the stream open
        for a lossless replay on this or the next poll.
        """
        _validate_non_negative(after, field_name="after")
        self._get_conversation(owner)
        run = self._get_run(owner, run_id)
        terminal = run.status.is_terminal
        events = self._list_events_for_run(owner=owner, run=run, after=after, limit=_EVENT_BATCH_SIZE)
        return StreamStart(events=events, terminal=terminal)

    def _get_conversation(self, owner: RunOwner) -> WorkflowAssistConversation:
        conversation = self.session.scalar(
            select(WorkflowAssistConversation).where(
                WorkflowAssistConversation.id == owner.conversation_id,
                WorkflowAssistConversation.tenant_id == owner.tenant_id,
                WorkflowAssistConversation.app_id == owner.app_id,
                WorkflowAssistConversation.account_id == owner.account_id,
                WorkflowAssistConversation.is_deleted.is_(False),
            )
        )
        if conversation is None:
            raise WorkflowAssistConversationNotFound()
        return conversation

    def _get_run(self, owner: RunOwner, run_id: str) -> WorkflowAssistRun:
        run = self.session.scalar(
            select(WorkflowAssistRun).where(
                *self._run_owner_predicates(owner),
                WorkflowAssistRun.id == run_id,
            )
        )
        if run is None:
            # Deliberately share the owner-bound 404 so cross-owner ids cannot
            # be distinguished from absent ids.
            raise WorkflowAssistConversationNotFound()
        return run

    def _get_optional_run(self, owner: RunOwner, run_id: str | None) -> WorkflowAssistRun | None:
        if run_id is None:
            return None
        return self.session.scalar(
            select(WorkflowAssistRun).where(
                *self._run_owner_predicates(owner),
                WorkflowAssistRun.id == run_id,
            )
        )

    @staticmethod
    def _run_owner_predicates(owner: RunOwner) -> tuple[Any, ...]:
        return (
            WorkflowAssistRun.tenant_id == owner.tenant_id,
            WorkflowAssistRun.app_id == owner.app_id,
            WorkflowAssistRun.created_by == owner.account_id,
            WorkflowAssistRun.conversation_id == owner.conversation_id,
        )

    @staticmethod
    def _event_owner_predicates(owner: RunOwner) -> tuple[Any, ...]:
        return (
            WorkflowAssistRunEvent.tenant_id == owner.tenant_id,
            WorkflowAssistRunEvent.app_id == owner.app_id,
            WorkflowAssistRunEvent.created_by == owner.account_id,
            WorkflowAssistRunEvent.conversation_id == owner.conversation_id,
        )

    @staticmethod
    def _event_run_join() -> Any:
        return and_(
            WorkflowAssistRun.id == WorkflowAssistRunEvent.run_id,
            WorkflowAssistRun.epoch == WorkflowAssistRunEvent.epoch,
            WorkflowAssistRun.tenant_id == WorkflowAssistRunEvent.tenant_id,
            WorkflowAssistRun.app_id == WorkflowAssistRunEvent.app_id,
            WorkflowAssistRun.created_by == WorkflowAssistRunEvent.created_by,
            WorkflowAssistRun.conversation_id == WorkflowAssistRunEvent.conversation_id,
        )


class WorkflowAssistRunEventStream:
    """Replay persisted events and briefly poll without retaining sessions.

    ``start`` performs the request-start terminal check. Every later poll owns
    a fresh session that is closed before heartbeat emission or sleeping.
    """

    owner: RunOwner
    run_id: str
    after: int
    create_session: Callable[[], AbstractContextManager[Session]]
    sleep: Callable[[float], None]
    poll_interval: float
    max_polls: int
    max_empty_polls: int

    def __init__(
        self,
        *,
        owner: RunOwner,
        run_id: str,
        after: int,
        create_session: Callable[[], AbstractContextManager[Session]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        poll_interval: float = _STREAM_POLL_INTERVAL_SECONDS,
        max_polls: int = _STREAM_MAX_POLLS,
        max_empty_polls: int = _STREAM_MAX_EMPTY_POLLS,
    ) -> None:
        _validate_non_negative(after, field_name="after")
        if max_polls < 1 or max_empty_polls < 1:
            raise ValueError("stream polling limits must be positive")
        self.owner = owner
        self.run_id = run_id
        self.after = after
        self.create_session = create_session or session_factory.create_session
        self.sleep = sleep
        self.poll_interval = poll_interval
        self.max_polls = max_polls
        self.max_empty_polls = max_empty_polls

    def start(self) -> StreamStart:
        """Load replay facts before the HTTP response status is selected."""
        return self._load(self.after)

    def iter_chunks(self, start: StreamStart) -> Iterator[str]:
        """Yield replayable SSE frames, then bounded heartbeat polling."""
        cursor = self.after
        for event in start.events:
            cursor = event.sequence
            yield _sse_frame(event)
        if start.terminal and len(start.events) < _EVENT_BATCH_SIZE:
            return

        empty_polls = 0
        for _poll in range(self.max_polls):
            batch = self._load(cursor)
            if batch.events:
                empty_polls = 0
                for event in batch.events:
                    cursor = event.sequence
                    yield _sse_frame(event)
                if batch.terminal and len(batch.events) < _EVENT_BATCH_SIZE:
                    return
                continue
            if batch.terminal:
                return
            empty_polls += 1
            yield ": heartbeat\n\n"
            self.sleep(self.poll_interval)
            if empty_polls >= self.max_empty_polls:
                return

    def _load(self, after: int) -> StreamStart:
        with self.create_session() as session:
            return WorkflowAssistRunEventService(session).stream_start(
                owner=self.owner,
                run_id=self.run_id,
                after=after,
            )


def _validate_non_negative(value: int, *, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _validate_limit(value: int, *, maximum: int) -> None:
    if value < 1 or value > maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")


def _enum_value(value: object | None) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _rfc3339_utc(value: datetime) -> str:
    """Serialize database-naive UTC or aware time as canonical RFC3339 UTC."""
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat().replace("+00:00", "Z")


def _run_summary(run: WorkflowAssistRun) -> RunSummary:
    return RunSummary(
        run_id=run.id,
        epoch=run.epoch,
        status=_enum_value(run.status) or "",
        mode=_enum_value(run.mode) or "",
        candidate_revision=run.candidate_revision,
        attempt=run.attempt,
        selected_node=run.selected_node,
        queued_at=run.queued_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        termination_reason=run.termination_reason,
    )


def _event_envelope(event: WorkflowAssistRunEvent) -> EventEnvelope:
    event_name = _enum_value(event.event) or ""
    payload = event.payload if isinstance(event.payload, dict) else {}
    return EventEnvelope(
        event=event_name,
        run_id=event.run_id,
        epoch=event.epoch,
        sequence=event.sequence,
        step_id=event.step_id,
        created_at=event.created_at,
        data=project_sse_event_payload(event_name, payload),
    )


def _sse_frame(event: EventEnvelope) -> str:
    payload = json.dumps(event.as_dict(), ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.sequence}\nevent: {event.event}\ndata: {payload}\n\n"
