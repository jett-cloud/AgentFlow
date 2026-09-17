"""Conversation persistence for resumable workflow-assist editing.

The service is the sole write boundary for workflow-assist history. It scopes
every lookup by tenant, app, and account, applies soft deletion, and strips
secret-shaped fields from arbitrary JSON before it reaches the database.

Candidate graphs and compaction checkpoints live on dedicated conversation
columns, not in `state`. Assist chat does not write `planning_session`,
`pending_clarification`, `clarification_history`, or `request_kind`.
Tool-loop writers must `acquire_run` (which commits the lease) before any LLM
call, then fence later writes with that lease.
Fenced candidate writes also commit, including the 0-row miss path, so the
row lock is not held across an LLM call. A superseded lease updates zero
rows and returns False; it does not raise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound

from configs import dify_config
from libs.datetime_utils import naive_utc_now
from libs.pagination import PaginatedResult, paginate_query
from models.workflow_assist import (
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
)
from services.workflow_assist.protocol_rollout import protocol_for_new_conversation


class WorkflowAssistConversationNotFound(NotFound):
    """Raised when a conversation is absent or outside the caller's ownership scope."""


class WorkflowAssistConversationPayloadTooLargeError(ValueError):
    """Raised when persisted resume state or an event exceeds its storage budget."""

    error_code = "CONVERSATION_STATE_TOO_LARGE"


class WorkflowAssistConversationWriteConflictError(RuntimeError):
    """Raised when concurrent writers still collide after conversation locking."""

    error_code = "CONVERSATION_WRITE_CONFLICT"


@dataclass(frozen=True)
class ConversationRunLease:
    """Durable fence for one HTTP tool-loop run against a conversation row."""

    conversation_id: str
    run_id: str
    epoch: int
    attempt_id: str | None = None


@dataclass(frozen=True)
class WorkflowAssistConversationDetail:
    """A conversation and its ordered history returned after ownership validation."""

    conversation: WorkflowAssistConversation
    messages: list[WorkflowAssistMessage]


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
_SYSTEM_STATE_KEYS = (
    "clarification_history",
    "last_plan_draft_hash",
    "pending_clarification",
    "planning_session",
    "retry_pending_clarification",
    "last_validation",
    "last_accepted_finish",
    "run_heartbeat_at",
    "run_redelivery_count",
    "prompt_skip_ranges",
)
_MAX_STATE_BYTES = 1024 * 1024
_MAX_MESSAGE_PAYLOAD_BYTES = 512 * 1024
_MAX_CANDIDATE_GRAPH_BYTES = 4 * 1024 * 1024
_MAX_COMPACTED_STATE_BYTES = 1024 * 1024


class WorkflowAssistConversationService:
    """Manage account-scoped workflow-assist conversation state in one SQLAlchemy session."""

    session: Session

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        tenant_id: str,
        app_id: str,
        account_id: str,
        title: str = "New workflow chat",
        draft_hash: str | None = None,
        state: dict[str, Any] | None = None,
    ) -> WorkflowAssistConversation:
        """Create an empty resume record, storing only sanitized state."""
        sanitized_state = _sanitize_payload(state or {})
        _ensure_payload_size(sanitized_state, max_bytes=_MAX_STATE_BYTES)
        conversation = WorkflowAssistConversation(
            tenant_id=tenant_id,
            app_id=app_id,
            account_id=account_id,
            title=title.strip()[:255] or "New workflow chat",
            draft_hash=draft_hash,
            state=sanitized_state,
            contract_protocol_version=protocol_for_new_conversation(
                dify_config.WORKFLOW_ASSIST_CONTRACT_ROLLOUT
            ),
        )
        self.session.add(conversation)
        self.session.flush()
        return conversation

    def list(
        self,
        *,
        tenant_id: str,
        app_id: str,
        account_id: str,
        page: int,
        limit: int,
    ) -> PaginatedResult[WorkflowAssistConversation]:
        """Return non-deleted conversations newest first for one editor and app."""
        statement = (
            select(WorkflowAssistConversation)
            .where(
                WorkflowAssistConversation.tenant_id == tenant_id,
                WorkflowAssistConversation.app_id == app_id,
                WorkflowAssistConversation.account_id == account_id,
                WorkflowAssistConversation.is_deleted.is_(False),
            )
            .order_by(WorkflowAssistConversation.updated_at.desc(), WorkflowAssistConversation.id.desc())
        )
        return paginate_query(statement, session=self.session, page=page, per_page=limit, max_per_page=100)

    def get(
        self,
        *,
        tenant_id: str,
        app_id: str,
        account_id: str,
        conversation_id: str,
        lock: bool = False,
    ) -> WorkflowAssistConversationDetail:
        """Load a conversation and messages after applying complete ownership predicates."""
        conversation = self._get_active(
            tenant_id=tenant_id,
            app_id=app_id,
            account_id=account_id,
            conversation_id=conversation_id,
            lock=lock,
        )
        messages = list(
            self.session.scalars(
                select(WorkflowAssistMessage)
                .where(
                    WorkflowAssistMessage.tenant_id == tenant_id,
                    WorkflowAssistMessage.app_id == app_id,
                    WorkflowAssistMessage.account_id == account_id,
                    WorkflowAssistMessage.conversation_id == conversation.id,
                )
                .order_by(WorkflowAssistMessage.sequence.asc())
            ).all()
        )
        return WorkflowAssistConversationDetail(conversation=conversation, messages=messages)

    def update(
        self,
        *,
        tenant_id: str,
        app_id: str,
        account_id: str,
        conversation_id: str,
        title: str | None = None,
        draft_hash: str | None = None,
        state: dict[str, Any] | None = None,
        preserve_system_state: bool = True,
    ) -> WorkflowAssistConversation:
        """Update title and/or sanitized resume state for an owned conversation.

        Title-only callers omit `draft_hash` and `state` so the candidate graph
        and resume snapshot stay unchanged. Blank titles fall back to
        "New workflow chat".
        """
        conversation = self._get_active(
            tenant_id=tenant_id,
            app_id=app_id,
            account_id=account_id,
            conversation_id=conversation_id,
        )
        if title is not None:
            conversation.title = title.strip()[:255] or "New workflow chat"
        if draft_hash is not None:
            conversation.draft_hash = draft_hash
        if state is not None:
            sanitized_state = _sanitize_payload(state)
            if preserve_system_state:
                for key in _SYSTEM_STATE_KEYS:
                    if key in conversation.state:
                        sanitized_state[key] = conversation.state[key]
                    else:
                        sanitized_state.pop(key, None)
            _ensure_payload_size(sanitized_state, max_bytes=_MAX_STATE_BYTES)
            conversation.state = sanitized_state
        conversation.updated_at = naive_utc_now()
        return conversation

    def append_message(
        self,
        *,
        conversation: WorkflowAssistConversation,
        role: Literal["user", "assistant", "system"],
        event_type: str,
        payload: dict[str, Any],
        status: str = "completed",
        retryable: bool = False,
    ) -> WorkflowAssistMessage:
        """Append one sanitized, ordered history record to an already authorized conversation."""
        locked_conversation = self._lock_owned(conversation)
        if locked_conversation is None:
            raise WorkflowAssistConversationNotFound()
        return self._append_on_locked(
            locked_conversation,
            role=role,
            event_type=event_type,
            payload=payload,
            status=status,
            retryable=retryable,
        )

    def append_message_fenced(
        self,
        *,
        conversation: WorkflowAssistConversation,
        lease: ConversationRunLease,
        role: Literal["user", "assistant", "system"],
        event_type: str,
        payload: dict[str, Any],
        status: str = "completed",
        retryable: bool = False,
    ) -> WorkflowAssistMessage | None:
        """Append a history row only while ``lease`` still owns the conversation.

        Returns ``None`` (and commits) when the fence is lost so a superseded
        run stops writing. Does not raise for a lost fence.
        """
        locked_conversation = self._lock_for_lease(conversation, lease)
        if locked_conversation is None:
            self.session.commit()
            return None
        stamped_payload = dict(payload)
        stamped_payload["run_id"] = lease.run_id
        message = self._append_on_locked(
            locked_conversation,
            role=role,
            event_type=event_type,
            payload=stamped_payload,
            status=status,
            retryable=retryable,
        )
        self.session.commit()
        return message

    def update_message_status_fenced(
        self,
        *,
        conversation: WorkflowAssistConversation,
        lease: ConversationRunLease,
        sequence: int,
        status: str,
    ) -> bool:
        """Set one existing row's status if the lease still owns the conversation.

        Completing a pending ``ask_user`` is a status transition, not a payload
        rewrite. Returns False when the fence is lost.
        """
        locked_conversation = self._lock_for_lease(conversation, lease)
        if locked_conversation is None:
            self.session.commit()
            return False
        message = self.session.scalar(
            select(WorkflowAssistMessage).where(
                WorkflowAssistMessage.conversation_id == conversation.id,
                WorkflowAssistMessage.sequence == sequence,
            )
        )
        if message is not None and message.status != status:
            message.status = status[:32]
            locked_conversation.updated_at = naive_utc_now()
            self.session.flush()
        self.session.commit()
        return True

    def persist_run_termination(
        self,
        *,
        conversation: WorkflowAssistConversation,
        lease: ConversationRunLease,
        reason: str,
        status_text: str | None = None,
        clear_active: bool = False,
    ) -> bool:
        """Persist ``last_run_termination_reason`` and an optional durable status line.

        False means the lease lost the fence; the caller must stop writing.
        ``clear_active`` drops ``active_run_id`` so a later turn is a new run,
        not a supersession of a finished one.
        """
        locked_conversation = self._lock_for_lease(conversation, lease)
        if locked_conversation is None:
            self.session.commit()
            return False
        locked_conversation.last_run_termination_reason = reason[:64]
        if clear_active:
            locked_conversation.active_run_id = None
        locked_conversation.updated_at = naive_utc_now()
        if status_text:
            self._append_on_locked(
                locked_conversation,
                role="assistant",
                event_type="message",
                payload={"text": status_text, "kind": "run_status"},
                status="completed",
            )
        self.session.commit()
        return True

    def request_user_abort(self, conversation: WorkflowAssistConversation) -> bool:
        """Persist ``user_abort`` under the current live lease so workers can observe Stop.

        Does not clear ``active_run_id``; the stream that owns the lease emits
        ``aborted`` and then clears. When there is no live run, also writes the
        durable status sentence.
        """
        locked_conversation = self._lock_owned(conversation)
        if locked_conversation is None:
            self.session.commit()
            return False
        locked_conversation.last_run_termination_reason = "user_abort"
        locked_conversation.updated_at = naive_utc_now()
        if locked_conversation.active_run_id is None:
            self._append_on_locked(
                locked_conversation,
                role="assistant",
                event_type="message",
                payload={"text": "已停止。", "kind": "run_status"},
                status="completed",
            )
        self.session.commit()
        return True

    def termination_reason_for_lease(self, lease: ConversationRunLease) -> str | None:
        """Read ``last_run_termination_reason`` for ``lease`` from the database."""
        return self.session.scalar(
            select(WorkflowAssistConversation.last_run_termination_reason).where(
                WorkflowAssistConversation.id == lease.conversation_id,
                WorkflowAssistConversation.active_run_id == lease.run_id,
                WorkflowAssistConversation.run_epoch == lease.epoch,
            )
        )

    def pin_candidate_base_hash(self, conversation: WorkflowAssistConversation, draft_hash: str | None) -> None:
        """Set ``candidate_base_hash`` only when it is still unset.

        User turns and tool edits must not change a pinned value. Successful
        Apply writes the returned hash separately.
        """
        if not draft_hash or conversation.candidate_base_hash is not None:
            return
        conversation.candidate_base_hash = draft_hash
        conversation.updated_at = naive_utc_now()
        self.session.flush()

    def delete(
        self,
        *,
        tenant_id: str,
        app_id: str,
        account_id: str,
        conversation_id: str,
    ) -> None:
        """End an owned conversation lifecycle while retaining its LLM message history.

        Run events are deleted before runs because both records belong only to
        the UI replay lifecycle. The caller's transaction makes their cleanup,
        pointer invalidation, and the conversation soft delete atomic.
        """
        conversation = self._get_active(
            tenant_id=tenant_id,
            app_id=app_id,
            account_id=account_id,
            conversation_id=conversation_id,
            lock=True,
        )
        owner_predicates = (
            WorkflowAssistRunEvent.tenant_id == tenant_id,
            WorkflowAssistRunEvent.app_id == app_id,
            WorkflowAssistRunEvent.created_by == account_id,
            WorkflowAssistRunEvent.conversation_id == conversation.id,
        )
        self.session.execute(sa_delete(WorkflowAssistRunEvent).where(*owner_predicates))
        self.session.execute(
            sa_delete(WorkflowAssistRun).where(
                WorkflowAssistRun.tenant_id == tenant_id,
                WorkflowAssistRun.app_id == app_id,
                WorkflowAssistRun.created_by == account_id,
                WorkflowAssistRun.conversation_id == conversation.id,
            )
        )
        deleted_at = naive_utc_now()
        conversation.active_run_id = None
        conversation.latest_run_id = None
        conversation.is_deleted = True
        conversation.deleted_at = deleted_at
        conversation.updated_at = deleted_at

    def acquire_run(
        self,
        *,
        conversation: WorkflowAssistConversation,
        run_id: str,
        supersede: bool = False,
    ) -> ConversationRunLease:
        """Lock the conversation, bump `run_epoch`, publish `run_id`, and commit.

        Always increments `run_epoch` so any prior lease fails fenced writes.
        `supersede` is accepted for callers that replace a live turn; this method
        does not persist a termination reason. The commit happens here so the
        fence is durable before any LLM call, and so this session does not hold
        a transaction across model I/O.
        """
        locked_conversation = self.session.scalar(
            select(WorkflowAssistConversation)
            .where(
                WorkflowAssistConversation.id == conversation.id,
                WorkflowAssistConversation.tenant_id == conversation.tenant_id,
                WorkflowAssistConversation.app_id == conversation.app_id,
                WorkflowAssistConversation.account_id == conversation.account_id,
                WorkflowAssistConversation.is_deleted.is_(False),
            )
            .with_for_update()
        )
        if locked_conversation is None:
            raise WorkflowAssistConversationNotFound()
        now = naive_utc_now()
        locked_conversation.run_epoch += 1
        locked_conversation.active_run_id = run_id
        locked_conversation.active_attempt_id = None
        locked_conversation.active_run_started_at = now
        locked_conversation.active_run_heartbeat_at = None
        locked_conversation.updated_at = now
        lease = ConversationRunLease(
            conversation_id=locked_conversation.id,
            run_id=run_id,
            epoch=locked_conversation.run_epoch,
        )
        self.session.commit()
        return lease

    def begin_queued_run(
        self,
        *,
        conversation: WorkflowAssistConversation,
        run_id: str,
    ) -> ConversationRunLease:
        """Lock, bump epoch, publish ``run_id``, and leave the transaction open.

        Used by atomic ``submit_turn``. Callers must commit or rollback.
        """
        locked_conversation = self.session.scalar(
            select(WorkflowAssistConversation)
            .where(
                WorkflowAssistConversation.id == conversation.id,
                WorkflowAssistConversation.tenant_id == conversation.tenant_id,
                WorkflowAssistConversation.app_id == conversation.app_id,
                WorkflowAssistConversation.account_id == conversation.account_id,
                WorkflowAssistConversation.is_deleted.is_(False),
            )
            .with_for_update()
        )
        if locked_conversation is None:
            raise WorkflowAssistConversationNotFound()
        now = naive_utc_now()
        locked_conversation.run_epoch += 1
        locked_conversation.active_run_id = run_id
        locked_conversation.active_attempt_id = None
        locked_conversation.active_run_started_at = now
        locked_conversation.active_run_heartbeat_at = None
        locked_conversation.updated_at = now
        self.session.flush()
        return ConversationRunLease(
            conversation_id=locked_conversation.id,
            run_id=run_id,
            epoch=locked_conversation.run_epoch,
        )

    def claim_attempt(
        self,
        *,
        conversation: WorkflowAssistConversation,
        lease: ConversationRunLease,
    ) -> ConversationRunLease | None:
        """CAS-claim a queued run. Commits. Duplicate delivery returns None."""
        locked_conversation = self.session.scalar(
            select(WorkflowAssistConversation)
            .where(
                WorkflowAssistConversation.id == conversation.id,
                WorkflowAssistConversation.tenant_id == conversation.tenant_id,
                WorkflowAssistConversation.app_id == conversation.app_id,
                WorkflowAssistConversation.account_id == conversation.account_id,
                WorkflowAssistConversation.is_deleted.is_(False),
                WorkflowAssistConversation.active_run_id == lease.run_id,
                WorkflowAssistConversation.run_epoch == lease.epoch,
                WorkflowAssistConversation.active_attempt_id.is_(None),
            )
            .with_for_update()
        )
        if locked_conversation is None:
            self.session.rollback()
            return None
        attempt_id = uuid4().hex
        now = naive_utc_now()
        locked_conversation.active_attempt_id = attempt_id
        locked_conversation.active_run_heartbeat_at = now
        locked_conversation.updated_at = now
        self.session.commit()
        return ConversationRunLease(
            conversation_id=locked_conversation.id,
            run_id=lease.run_id,
            epoch=lease.epoch,
            attempt_id=attempt_id,
        )

    def save_candidate_state(
        self,
        conversation_id: str,
        lease: ConversationRunLease,
        *,
        graph: dict[str, Any],
        revision: int,
        base_hash: str | None,
        compacted_until_sequence: int | None,
        compacted_state: dict[str, Any] | None,
        contract_protocol_version: int | None = None,
        workflow_contract: dict[str, object] | None = None,
        contract_revision: int | None = None,
        contract_hash: str | None = None,
        extra_state: dict[str, Any] | None = None,
    ) -> bool:
        """Persist candidate graph and compaction checkpoint if `lease` still owns the row.

        True means the write is durable (committed). False means the lease lost the
        fence (`active_run_id` / `run_epoch` no longer match); never raises for a
        lost fence. The transaction is committed on both paths so a 0-row UPDATE
        does not hold the row. Payloads are sanitized before the byte-cap check.

        ``candidate_base_hash`` is not written here — pin it on create / first
        draft hash, and update it only after a successful Apply. Compaction
        columns are written only when ``compacted_until_sequence`` is not None
        so a later persist cannot store None over a previous checkpoint.
        A supplied workflow contract uses revision/hash compare-and-set; equal
        replay is allowed only for the same hash. ``extra_state`` is merged
        into the existing ``state`` JSON (it does not replace the whole blob),
        so ``last_accepted_finish`` can sit beside unrelated resume keys.
        """
        sanitized_graph = _sanitize_payload(graph)
        _ensure_payload_size(sanitized_graph, max_bytes=_MAX_CANDIDATE_GRAPH_BYTES)
        values: dict[str, Any] = {
            "candidate_graph": sanitized_graph,
            "candidate_revision": revision,
            "updated_at": naive_utc_now(),
        }
        if compacted_until_sequence is not None:
            sanitized_compacted_state: dict[str, Any] | None = None
            if compacted_state is not None:
                sanitized_compacted_state = _sanitize_payload(compacted_state)
                _ensure_payload_size(sanitized_compacted_state, max_bytes=_MAX_COMPACTED_STATE_BYTES)
            values["compacted_until_sequence"] = compacted_until_sequence
            values["compacted_state"] = sanitized_compacted_state
        contract_predicate = None
        if workflow_contract is not None:
            if contract_protocol_version != 1 or not isinstance(contract_revision, int) or contract_revision < 1:
                raise ValueError("Workflow contract metadata is invalid")
            if not isinstance(contract_hash, str) or len(contract_hash) != 64:
                raise ValueError("Workflow contract hash is invalid")
            sanitized_contract = _sanitize_payload(workflow_contract)
            _ensure_payload_size(sanitized_contract, max_bytes=_MAX_STATE_BYTES)
            if (
                sanitized_contract.get("protocol_version") != contract_protocol_version
                or sanitized_contract.get("revision") != contract_revision
                or sanitized_contract.get("contract_hash") != contract_hash
            ):
                raise ValueError("Workflow contract metadata does not match its body")
            values.update(
                {
                    "workflow_contract": sanitized_contract,
                    "contract_revision": contract_revision,
                    "contract_hash": contract_hash,
                    "completion_run_id": None,
                    "completion_epoch": None,
                    "completion_candidate_revision": None,
                    "completion_candidate_base_hash": None,
                    "completion_app_mode": None,
                    "completion_assertion": None,
                    "completion_contract_protocol_version": None,
                    "completion_contract_revision": None,
                    "completion_contract_hash": None,
                }
            )
            current_revision = func.coalesce(WorkflowAssistConversation.contract_revision, 0)
            contract_predicate = and_(
                WorkflowAssistConversation.contract_protocol_version == contract_protocol_version,
                or_(
                    current_revision == contract_revision - 1,
                    and_(
                        current_revision == contract_revision,
                        WorkflowAssistConversation.contract_hash == contract_hash,
                    ),
                ),
            )
        if extra_state is not None:
            current = self.session.get(WorkflowAssistConversation, conversation_id)
            merged: dict[str, Any] = {}
            if current is not None and isinstance(current.state, dict):
                merged.update(current.state)
            merged.update(_sanitize_payload(extra_state))
            _ensure_payload_size(merged, max_bytes=_MAX_STATE_BYTES)
            values["state"] = merged
        _ = base_hash
        statement = update(WorkflowAssistConversation).where(
            WorkflowAssistConversation.id == conversation_id,
            WorkflowAssistConversation.active_run_id == lease.run_id,
            WorkflowAssistConversation.run_epoch == lease.epoch,
        )
        if contract_predicate is not None:
            statement = statement.where(contract_predicate)
        result = self.session.execute(statement.values(**values))
        updated = (result.rowcount or 0) > 0
        self.session.commit()
        return updated

    def _lock_owned(self, conversation: WorkflowAssistConversation) -> WorkflowAssistConversation | None:
        return self.session.scalar(
            select(WorkflowAssistConversation)
            .where(
                WorkflowAssistConversation.id == conversation.id,
                WorkflowAssistConversation.tenant_id == conversation.tenant_id,
                WorkflowAssistConversation.app_id == conversation.app_id,
                WorkflowAssistConversation.account_id == conversation.account_id,
                WorkflowAssistConversation.is_deleted.is_(False),
            )
            .with_for_update()
        )

    def _lock_for_lease(
        self,
        conversation: WorkflowAssistConversation,
        lease: ConversationRunLease,
    ) -> WorkflowAssistConversation | None:
        return self.session.scalar(
            select(WorkflowAssistConversation)
            .where(
                WorkflowAssistConversation.id == conversation.id,
                WorkflowAssistConversation.tenant_id == conversation.tenant_id,
                WorkflowAssistConversation.app_id == conversation.app_id,
                WorkflowAssistConversation.account_id == conversation.account_id,
                WorkflowAssistConversation.is_deleted.is_(False),
                WorkflowAssistConversation.active_run_id == lease.run_id,
                WorkflowAssistConversation.run_epoch == lease.epoch,
            )
            .with_for_update()
        )

    def _append_on_locked(
        self,
        locked_conversation: WorkflowAssistConversation,
        *,
        role: Literal["user", "assistant", "system"],
        event_type: str,
        payload: dict[str, Any],
        status: str = "completed",
        retryable: bool = False,
    ) -> WorkflowAssistMessage:
        sequence = (
            self.session.scalar(
                select(func.coalesce(func.max(WorkflowAssistMessage.sequence), 0)).where(
                    WorkflowAssistMessage.conversation_id == locked_conversation.id
                )
            )
            or 0
        ) + 1
        sanitized_payload = _sanitize_payload(payload)
        _ensure_payload_size(sanitized_payload, max_bytes=_MAX_MESSAGE_PAYLOAD_BYTES)
        message = WorkflowAssistMessage(
            tenant_id=locked_conversation.tenant_id,
            app_id=locked_conversation.app_id,
            account_id=locked_conversation.account_id,
            conversation_id=locked_conversation.id,
            sequence=sequence,
            role=role,
            event_type=event_type[:64],
            status=status[:32],
            retryable=retryable,
            payload=sanitized_payload,
        )
        self.session.add(message)
        locked_conversation.updated_at = naive_utc_now()
        try:
            self.session.flush()
        except IntegrityError as exc:
            raise WorkflowAssistConversationWriteConflictError(
                "Concurrent workflow-assist message append failed"
            ) from exc
        return message

    def _get_active(
        self,
        *,
        tenant_id: str,
        app_id: str,
        account_id: str,
        conversation_id: str,
        lock: bool = False,
    ) -> WorkflowAssistConversation:
        statement = (
            select(WorkflowAssistConversation)
            .where(
                WorkflowAssistConversation.id == conversation_id,
                WorkflowAssistConversation.tenant_id == tenant_id,
                WorkflowAssistConversation.app_id == app_id,
                WorkflowAssistConversation.account_id == account_id,
                WorkflowAssistConversation.is_deleted.is_(False),
            )
            .limit(1)
        )
        if lock:
            statement = statement.with_for_update()
        conversation = self.session.scalar(statement)
        if conversation is None:
            raise WorkflowAssistConversationNotFound()
        return conversation


def _sanitize_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Drop secret-shaped mapping keys while preserving ordinary graph and credential references."""
    sanitized = _sanitize_value(value)
    if not isinstance(sanitized, dict):
        raise ValueError("Workflow-assist payload must serialize to an object")
    return sanitized


def _ensure_payload_size(value: dict[str, Any], *, max_bytes: int) -> None:
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    if len(serialized) > max_bytes:
        raise WorkflowAssistConversationPayloadTooLargeError(
            f"Workflow-assist persistence payload exceeds the {max_bytes}-byte limit"
        )


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_value(item) for key, item in value.items() if not _is_secret_field(str(key))}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item) for item in value]
    return value


def _is_secret_field(field_name: str) -> bool:
    normalized = field_name.lower().replace("-", "_")
    return any(part in normalized for part in _SECRET_FIELD_PARTS)
