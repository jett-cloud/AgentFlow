"""Persistent, account-scoped workflow-assist conversation records.

Workflow-assist conversations are console-only editing history. They are scoped
by tenant, app, and editor account so a shared workflow draft never exposes one
editor's instructions or generated graph previews to another editor. JSON
payloads contain only resume-safe data; callers must use the service sanitizer
before writing request or stream data because model and tool secrets must never
be retained here.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, validates

from libs.datetime_utils import naive_utc_now
from libs.uuid_utils import uuidv7

from .base import Base, DefaultFieldsMixin
from .types import (
    AdjustedJSON,
    EnumText,
    LimitedAdjustedJSON,
    LimitedLongText,
    StringUUID,
    validate_json_value,
    validate_text_byte_limit,
)

WORKFLOW_ASSIST_RUN_INPUT_MAX_BYTES = 64 * 1024
WORKFLOW_ASSIST_RUN_EVENT_PAYLOAD_MAX_BYTES = 256 * 1024


class WorkflowAssistMode(StrEnum):
    """App modes supported by workflow-assist runs and completion evidence."""

    WORKFLOW = "workflow"
    ADVANCED_CHAT = "advanced-chat"


class WorkflowAssistCompletionAssertion(StrEnum):
    """Server-verified fact required before applying a candidate graph."""

    WORKFLOW_STRUCTURE_REACHES_TERMINAL = "workflow_structure_reaches_terminal"


class WorkflowAssistRunStatus(StrEnum):
    """Lifecycle states for a persisted workflow-assist turn."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    DONE = "done"
    FAILED = "failed"
    ERROR = "error"
    ABORTED = "aborted"
    TURN_COMPLETE = "turn_complete"

    @property
    def is_terminal(self) -> bool:
        """Return whether no further ordinary events may be appended to the run."""
        return self in WORKFLOW_ASSIST_RUN_TERMINAL_STATUSES


WORKFLOW_ASSIST_RUN_ACTIVE_STATUSES = frozenset({WorkflowAssistRunStatus.QUEUED, WorkflowAssistRunStatus.RUNNING})
WORKFLOW_ASSIST_RUN_TERMINAL_STATUSES = frozenset(
    {
        WorkflowAssistRunStatus.WAITING_USER,
        WorkflowAssistRunStatus.DONE,
        WorkflowAssistRunStatus.FAILED,
        WorkflowAssistRunStatus.ERROR,
        WorkflowAssistRunStatus.ABORTED,
        WorkflowAssistRunStatus.TURN_COMPLETE,
    }
)


class WorkflowAssistRunEventType(StrEnum):
    """Persisted event vocabulary consumed by the resumable UI timeline."""

    STATUS = "status"
    MESSAGE_DELTA = "message.delta"
    REASONING_DELTA = "reasoning.delta"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    CANDIDATE_UPDATED = "candidate.updated"
    WAITING_USER = "waiting_user"
    DONE = "done"
    FAILED = "failed"
    ERROR = "error"
    ABORTED = "aborted"
    TURN_COMPLETE = "turn_complete"


class WorkflowAssistConversation(DefaultFieldsMixin, Base):
    """One resumable workflow-assist conversation owned by a console account.

    Agent-loop state lives in dedicated columns rather than the size-limited
    legacy ``state`` payload. ``run_epoch`` fences delayed writes from an HTTP
    run after a newer turn has superseded it.
    """

    __tablename__ = "workflow_assist_conversations"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="workflow_assist_conversation_pkey"),
        Index(
            "workflow_assist_conversation_owner_updated_idx",
            "tenant_id",
            "app_id",
            "account_id",
            "is_deleted",
            "updated_at",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    app_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    account_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New workflow chat")
    draft_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[dict[str, Any]] = mapped_column(AdjustedJSON(), nullable=False, default=dict)
    candidate_graph: Mapped[dict[str, Any] | None] = mapped_column(AdjustedJSON(), nullable=True)
    candidate_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa.text("0"))
    candidate_base_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    compacted_until_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compacted_state: Mapped[dict[str, Any] | None] = mapped_column(AdjustedJSON(), nullable=True)
    active_run_id: Mapped[str | None] = mapped_column(StringUUID, nullable=True)
    latest_run_id: Mapped[str | None] = mapped_column(StringUUID, nullable=True)
    run_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa.text("0"))
    last_run_termination_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completion_run_id: Mapped[str | None] = mapped_column(StringUUID, nullable=True)
    completion_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_candidate_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_candidate_base_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completion_app_mode: Mapped[WorkflowAssistMode | None] = mapped_column(
        EnumText(WorkflowAssistMode, length=32), nullable=True
    )
    completion_assertion: Mapped[WorkflowAssistCompletionAssertion | None] = mapped_column(
        EnumText(WorkflowAssistCompletionAssertion, length=64), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, server_default=sa.text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WorkflowAssistMessage(DefaultFieldsMixin, Base):
    """An ordered, sanitized event or user message belonging to a conversation."""

    __tablename__ = "workflow_assist_messages"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="workflow_assist_message_pkey"),
        sa.UniqueConstraint("conversation_id", "sequence", name="workflow_assist_message_conversation_sequence_unique"),
        Index("workflow_assist_message_conversation_sequence_idx", "conversation_id", "sequence"),
        Index("workflow_assist_message_owner_idx", "tenant_id", "app_id", "account_id"),
    )

    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    app_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    account_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    conversation_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    retryable: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False, server_default=sa.text("false"))
    payload: Mapped[dict[str, Any]] = mapped_column(AdjustedJSON(), nullable=False, default=dict)


class WorkflowAssistRun(DefaultFieldsMixin, Base):
    """One durable user turn with its fencing identity and worker lease state.

    References intentionally have no database foreign keys. All consumers must
    query with the complete tenant, app, creator, and conversation owner scope.
    """

    __tablename__ = "workflow_assist_runs"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="workflow_assist_run_pkey"),
        Index(
            "workflow_assist_run_owner_conversation_epoch_idx",
            "tenant_id",
            "app_id",
            "created_by",
            "conversation_id",
            "epoch",
        ),
        Index("workflow_assist_run_queue_reaper_idx", "status", "queued_at"),
        Index("workflow_assist_run_heartbeat_reaper_idx", "status", "heartbeat_at"),
    )

    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    app_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    created_by: Mapped[str] = mapped_column(StringUUID, nullable=False)
    conversation_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa.text("0"))
    status: Mapped[WorkflowAssistRunStatus] = mapped_column(
        EnumText(WorkflowAssistRunStatus, length=32),
        nullable=False,
        default=WorkflowAssistRunStatus.QUEUED,
        server_default=WorkflowAssistRunStatus.QUEUED.value,
    )
    input: Mapped[str] = mapped_column(
        LimitedLongText(max_bytes=WORKFLOW_ASSIST_RUN_INPUT_MAX_BYTES, field_name="input"),
        nullable=False,
    )
    mode: Mapped[WorkflowAssistMode] = mapped_column(EnumText(WorkflowAssistMode, length=32), nullable=False)
    model_config: Mapped[dict[str, Any]] = mapped_column(AdjustedJSON(), nullable=False, default=dict)
    selected_node: Mapped[str | None] = mapped_column(String(255), nullable=True)
    references: Mapped[list[Any] | None] = mapped_column(AdjustedJSON(), nullable=True)
    next_event_sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=sa.text("1"),
    )
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=naive_utc_now,
        server_default=func.current_timestamp(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    termination_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa.text("0"))

    @validates("input")
    def _validate_input_size(self, _key: str, value: str) -> str:
        return validate_text_byte_limit(
            value,
            max_bytes=WORKFLOW_ASSIST_RUN_INPUT_MAX_BYTES,
            field_name="input",
        )


class WorkflowAssistRunEvent(Base):
    """Immutable replay and audit record for one committed run step.

    ``(run_id, sequence)`` preserves cursor order and ``(run_id, step_id)``
    makes a worker retry idempotent. References deliberately omit foreign keys.
    """

    __tablename__ = "workflow_assist_run_events"
    __table_args__ = (
        sa.PrimaryKeyConstraint("id", name="workflow_assist_run_event_pkey"),
        sa.UniqueConstraint(
            "run_id",
            "sequence",
            name="workflow_assist_run_event_run_sequence_unique",
        ),
        sa.UniqueConstraint(
            "run_id",
            "step_id",
            name="workflow_assist_run_event_run_step_unique",
        ),
        Index(
            "workflow_assist_run_event_owner_timeline_idx",
            "tenant_id",
            "app_id",
            "created_by",
            "conversation_id",
            "epoch",
            "sequence",
        ),
    )

    id: Mapped[str] = mapped_column(StringUUID, primary_key=True, default=lambda: str(uuidv7()))
    tenant_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    app_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    created_by: Mapped[str] = mapped_column(StringUUID, nullable=False)
    conversation_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    run_id: Mapped[str] = mapped_column(StringUUID, nullable=False)
    epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    step_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event: Mapped[WorkflowAssistRunEventType] = mapped_column(
        EnumText(WorkflowAssistRunEventType, length=32), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        LimitedAdjustedJSON(
            max_bytes=WORKFLOW_ASSIST_RUN_EVENT_PAYLOAD_MAX_BYTES,
            field_name="event payload",
        ),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=naive_utc_now,
        server_default=func.current_timestamp(),
    )

    @validates("payload")
    def _validate_payload(self, _key: str, value: dict[str, Any]) -> dict[str, Any]:
        return validate_json_value(value, field_name="event payload")
