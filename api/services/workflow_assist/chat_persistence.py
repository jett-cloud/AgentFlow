"""Persist Workflow Assist Agent events under a run or conversation lease.

HTTP SSE writes messages and candidate state through conversation-fenced helpers.
Durable Celery runs commit step-level RunEvents, including message.delta aggregation.
Closing the SSE generator is ``transport_disconnect``; only ``POST .../chat/abort``
is ``user_abort``. A lost lease fences further writes.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterator
from enum import StrEnum
from typing import Any, Literal, Protocol, cast

from sqlalchemy import select

from core.db.session_factory import session_factory
from core.workflow.generator.agent.types import AgentEvent, AgentMessage, AgentMessageEventType, AgentSession
from core.workflow.generator.graph.graph_ops import empty_graph
from models.workflow_assist import (
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistRunEventType,
    WorkflowAssistRunStatus,
)
from services.workflow_assist.conversations import ConversationRunLease, WorkflowAssistConversationService
from services.workflow_assist.run_coordinator import RunCoordinator
from services.workflow_assist.run_types import (
    AgentCheckpoint,
    AgentResponseOutbox,
    CandidateMutation,
    CommitStepOutcome,
    RunLease,
    WorkflowContractCheckpoint,
)

MESSAGE_DELTA_INTERVAL_SECONDS = 0.1
MESSAGE_DELTA_MAX_BYTES = 8 * 1024


class RunTerminationSignal(Protocol):
    """Cancellation object that persist_run_termination may mark as persisted."""

    lease: ConversationRunLease | None
    persisted: bool


def persist_user_turn(
    conversations: WorkflowAssistConversationService,
    conversation: WorkflowAssistConversation,
    lease: ConversationRunLease,
    session: AgentSession,
    prior_last: WorkflowAssistMessage | None,
) -> bool:
    if (
        prior_last is not None
        and prior_last.event_type == "tool_call"
        and prior_last.status == "pending"
        and isinstance(prior_last.payload, dict)
        and prior_last.payload.get("name") == "ask_user"
    ):
        if not conversations.update_message_status_fenced(
            conversation=conversation,
            lease=lease,
            sequence=prior_last.sequence,
            status="completed",
        ):
            return False
        result = session.messages[-1]
        row = conversations.append_message_fenced(
            conversation=conversation,
            lease=lease,
            role=result.role,
            event_type=result.event_type,
            payload=result.payload,
            status=result.status,
        )
        return row is not None
    user_message = session.messages[-1]
    row = conversations.append_message_fenced(
        conversation=conversation,
        lease=lease,
        role=user_message.role,
        event_type=user_message.event_type,
        payload=user_message.payload,
        status=user_message.status,
    )
    return row is not None


def persist_tail(
    conversations: WorkflowAssistConversationService,
    conversation: WorkflowAssistConversation,
    lease: ConversationRunLease,
    session: AgentSession,
    *,
    last_persisted: int,
    watermark_at_start: int | None,
) -> bool:
    for message in session.messages:
        if message.sequence <= last_persisted:
            continue
        row = conversations.append_message_fenced(
            conversation=conversation,
            lease=lease,
            role=message.role,
            event_type=message.event_type,
            payload=message.payload,
            status=message.status,
        )
        if row is None:
            return False
    graph = session.candidate_graph if isinstance(session.candidate_graph, dict) else empty_graph()
    advanced = session.compacted_until_sequence is not None and (
        watermark_at_start is None or session.compacted_until_sequence > watermark_at_start
    )
    return conversations.save_candidate_state(
        conversation.id,
        lease,
        graph=dict(graph),
        revision=session.candidate_revision,
        base_hash=session.candidate_base_hash,
        compacted_until_sequence=session.compacted_until_sequence if advanced else None,
        compacted_state=session.compacted_state if advanced else None,
        contract_protocol_version=session.contract_protocol_version,
        workflow_contract=session.workflow_contract,
        contract_revision=session.contract_revision,
        contract_hash=session.contract_hash,
    )


def persist_run_termination(
    conversations: WorkflowAssistConversationService,
    conversation: WorkflowAssistConversation,
    cancellation: RunTerminationSignal,
    reason: str,
    *,
    clear_active: bool,
    status_text: str | None = None,
) -> None:
    """Write a fenced run termination; skip the status line if already persisted."""
    lease = cancellation.lease
    if lease is None:
        return
    if cancellation.persisted:
        text = None
    else:
        text = status_text
    wrote = conversations.persist_run_termination(
        conversation=conversation,
        lease=lease,
        reason=reason,
        status_text=text,
        clear_active=clear_active,
    )
    if wrote and text:
        cancellation.persisted = True


class AgentEventPumpOutcome(StrEnum):
    """Why the adapter stopped before consuming more Agent events."""

    FENCED = "fenced"


class MessageDeltaAggregator:
    """Aggregate UTF-8 text by elapsed time or a byte ceiling."""

    interval_seconds: float
    max_bytes: int
    _parts: list[str]
    _bytes: int
    _started_at: float | None

    def __init__(self, *, interval_seconds: float, max_bytes: int) -> None:
        if interval_seconds <= 0 or max_bytes <= 0:
            raise ValueError("message delta limits must be positive")
        self.interval_seconds = interval_seconds
        self.max_bytes = max_bytes
        self._parts = []
        self._bytes = 0
        self._started_at = None

    def push(self, text: str, *, now: float) -> list[str]:
        """Add text and return every full/time-expired chunk ready to commit."""
        chunks: list[str] = []
        for character in text:
            encoded_bytes = len(character.encode("utf-8"))
            if encoded_bytes > self.max_bytes:
                raise ValueError("message delta limit cannot hold one Unicode character")
            if self._parts and self._bytes + encoded_bytes > self.max_bytes:
                chunks.append(self.flush())
            if self._started_at is None:
                self._started_at = now
            self._parts.append(character)
            self._bytes += encoded_bytes
            if self._bytes == self.max_bytes:
                chunks.append(self.flush())
        if self._parts and self._started_at is not None and now - self._started_at >= self.interval_seconds:
            chunks.append(self.flush())
        return chunks

    def flush(self) -> str:
        text = "".join(self._parts)
        self._parts = []
        self._bytes = 0
        self._started_at = None
        return text

    def has_pending(self) -> bool:
        return bool(self._parts)


class _TimedMessageDeltaWriter:
    """Commit buffered text at the deadline even while the Agent source blocks.

    A recovery envelope may include older completed assistant rows plus at most one
    current stream message. Older rows are committed as ordinary history before the
    current row is staged as the one-message response outbox.
    """

    lease: RunLease
    aggregator: MessageDeltaAggregator
    sequence: int
    _lock: threading.Lock
    _timer: threading.Timer | None
    _fenced: bool
    _error: BaseException | None
    _pending_checkpoint: AgentCheckpoint | None
    _pending_response: AgentResponseOutbox | None
    _message_sequence: int | None
    _chunk_index: int

    def __init__(
        self,
        lease: RunLease,
        *,
        event_type: WorkflowAssistRunEventType = WorkflowAssistRunEventType.MESSAGE_DELTA,
        step_prefix: str = "message",
    ) -> None:
        self.lease = lease
        self._event_type = event_type
        self._step_prefix = step_prefix
        self.aggregator = MessageDeltaAggregator(
            interval_seconds=MESSAGE_DELTA_INTERVAL_SECONDS,
            max_bytes=MESSAGE_DELTA_MAX_BYTES,
        )
        self.sequence = 0
        self._lock = threading.Lock()
        self._timer = None
        self._fenced = False
        self._error = None
        self._pending_checkpoint = None
        self._pending_response = None
        self._message_id: str | None = None
        self._message_sequence = None
        self._chunk_index = 0
        self._explicit_delta_index: int | None = None
        self._stream_mode: str | None = None
        self._emitted: list[str] = []

    def push(
        self,
        text: str,
        *,
        now: float,
        recovery_messages: list[dict[str, Any]] | None = None,
        checkpoint: AgentCheckpoint | None = None,
        message_id: str | None = None,
        delta_index: int | None = None,
        stream_mode: str | None = None,
    ) -> bool:
        with self._lock:
            self._raise_if_error()
            incoming_id = _delta_message_id(message_id, recovery_messages, current=self._message_id)
            if self._message_id is not None and incoming_id != self._message_id:
                pending = self.aggregator.flush()
                if pending and not self._commit_locked(pending, final=True):
                    return False
                self._reset_message_locked()
            if incoming_id is None:
                raise ValueError("Assistant prose requires message_id or a durable Agent message sequence")
            self._message_id = incoming_id
            if stream_mode:
                self._stream_mode = stream_mode
            history: list[dict[str, Any]] = []
            response: AgentResponseOutbox | None = None
            if recovery_messages:
                history, response = _partition_stream_recovery(
                    recovery_messages,
                    message_identity=incoming_id,
                    checkpoint=checkpoint,
                )
            if response is not None and self._pending_response is None:
                if not _stage_response_outbox(lease=self.lease, history=history, response=response):
                    self._fenced = True
                    return False
                self._pending_response = response
                self._message_sequence = response.sequence
            if checkpoint is not None:
                self._pending_checkpoint = checkpoint
            if (
                delta_index is not None
                and self._explicit_delta_index is not None
                and delta_index != self._explicit_delta_index
            ):
                pending = self.aggregator.flush()
                if pending and not self._commit_locked(pending, final=False):
                    return False
            if delta_index is not None:
                self._explicit_delta_index = delta_index
            chunks = self.aggregator.push(text, now=now)
            if delta_index is not None:
                leftover = self.aggregator.flush()
                if leftover:
                    chunks.append(leftover)
            for index, chunk in enumerate(chunks):
                final = index == len(chunks) - 1 and not self.aggregator.has_pending()
                if not self._commit_locked(chunk, final=final):
                    return False
            if self.aggregator.has_pending() and self._timer is None:
                timer = threading.Timer(MESSAGE_DELTA_INTERVAL_SECONDS, self._flush_on_deadline)
                timer.daemon = True
                self._timer = timer
                timer.start()
            return not self._fenced

    def flush(self) -> bool:
        with self._lock:
            self._cancel_timer_locked()
            self._raise_if_error()
            text = self.aggregator.flush()
            return not text or self._commit_locked(text, final=True)

    def check(self) -> bool:
        with self._lock:
            self._raise_if_error()
            return not self._fenced

    def cancel(self) -> None:
        with self._lock:
            self._cancel_timer_locked()

    def _flush_on_deadline(self) -> None:
        with self._lock:
            self._timer = None
            try:
                text = self.aggregator.flush()
                if text:
                    self._commit_locked(text, final=True)
            except BaseException as exc:
                self._error = exc

    def _commit_locked(self, text: str, *, final: bool) -> bool:
        self.sequence += 1
        if self._message_id is None:
            raise ValueError("Assistant prose requires message_id or a durable Agent message sequence")
        if self._explicit_delta_index is not None:
            index = self._explicit_delta_index
        else:
            index = self._chunk_index
            self._chunk_index += 1
        payload: dict[str, Any] = {"text": text, "message_id": self._message_id, "delta_index": index}
        if self._stream_mode:
            payload["stream_mode"] = self._stream_mode
        self._emitted.append(text)
        if final:
            self._merge_reasoning_locked("".join(self._emitted))
        committed = _commit_step(
            lease=self.lease,
            step_id=f"{self._step_prefix}:{self._message_id}:{index}",
            event=self._event_type,
            payload=payload,
            checkpoint=self._pending_checkpoint if final else None,
            response_outbox=self._pending_response if final else None,
        )
        if final:
            self._pending_checkpoint = None
            self._pending_response = None
        if not committed:
            self._fenced = True
        return committed

    def _reset_message_locked(self) -> None:
        self._message_id = None
        self._message_sequence = None
        self._chunk_index = 0
        self._explicit_delta_index = None
        self._stream_mode = None
        self._emitted = []

    def _merge_reasoning_locked(self, reasoning: str) -> None:
        if self._event_type is not WorkflowAssistRunEventType.REASONING_DELTA or not reasoning:
            return
        if self._pending_response is None:
            return
        payload = dict(self._pending_response.payload)
        existing = payload.get("reasoning")
        if isinstance(existing, str) and existing.strip():
            return
        payload["reasoning"] = reasoning
        self._pending_response = AgentResponseOutbox(
            sequence=self._pending_response.sequence,
            payload=payload,
            checkpoint=self._pending_response.checkpoint,
        )

    def _cancel_timer_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _raise_if_error(self) -> None:
        if self._error is not None:
            raise self._error


def _commit_step(
    *,
    lease: RunLease,
    step_id: str,
    event: WorkflowAssistRunEventType,
    payload: dict[str, Any],
    candidate: CandidateMutation | None = None,
    recovery_messages: list[dict[str, Any]] | None = None,
    checkpoint: AgentCheckpoint | None = None,
    response_outbox: AgentResponseOutbox | None = None,
) -> bool:
    with session_factory.create_session() as session:
        result = RunCoordinator(session).commit_step(
            lease=lease,
            step_id=step_id,
            event=event,
            payload=payload,
            candidate=candidate,
            checkpoint=checkpoint,
            response_outbox=response_outbox,
        )
        if result.outcome is CommitStepOutcome.COMMITTED and recovery_messages and response_outbox is None:
            conversation = session.scalar(
                select(WorkflowAssistConversation).where(
                    WorkflowAssistConversation.id == lease.owner.conversation_id,
                    WorkflowAssistConversation.tenant_id == lease.owner.tenant_id,
                    WorkflowAssistConversation.app_id == lease.owner.app_id,
                    WorkflowAssistConversation.account_id == lease.owner.account_id,
                )
            )
            if conversation is None:
                raise ValueError("recovery message conversation disappeared")
            conversations = WorkflowAssistConversationService(session)
            for recovery in recovery_messages:
                row = conversations.append_message(
                    conversation=conversation,
                    role=_recovery_role(recovery),
                    event_type=_required_text(recovery, "event_type"),
                    payload=_recovery_payload(recovery),
                    status=str(recovery.get("status") or "completed"),
                )
                expected_sequence = recovery.get("sequence")
                if isinstance(expected_sequence, int) and row.sequence != expected_sequence:
                    raise ValueError("recovery message sequence diverged from AgentSession")
        session.commit()
        return result.outcome is not CommitStepOutcome.FENCED


def _recovery_role(payload: dict[str, Any]) -> Literal["user", "assistant"]:
    role = payload.get("role")
    if role not in {"user", "assistant"}:
        raise ValueError("recovery message requires an Agent role")
    return cast(Literal["user", "assistant"], role)


def _recovery_payload(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("payload")
    if not isinstance(value, dict):
        raise ValueError("recovery message requires a payload")
    return value


def _recovery_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.pop("_recovery_messages", [])
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise ValueError("Agent recovery messages must be a list of objects")
    return raw


def _is_assistant_prose_recovery(item: dict[str, Any]) -> bool:
    return item.get("role") == "assistant" and item.get("event_type") == "message"


def _recovery_message_identity(item: dict[str, Any]) -> str | None:
    if not _is_assistant_prose_recovery(item):
        return None
    payload = _recovery_payload(item)
    message_id = payload.get("message_id")
    if isinstance(message_id, str) and message_id.strip():
        return message_id.strip()
    sequence = item.get("sequence")
    return str(sequence) if isinstance(sequence, int) and sequence > 0 else None


def _partition_stream_recovery(
    recovery_messages: list[dict[str, Any]],
    *,
    message_identity: str,
    checkpoint: AgentCheckpoint | None,
) -> tuple[list[dict[str, Any]], AgentResponseOutbox]:
    matching_indexes = [
        index for index, item in enumerate(recovery_messages) if _recovery_message_identity(item) == message_identity
    ]
    if len(matching_indexes) != 1:
        raise ValueError("Assistant stream identity must match exactly one durable recovery message")
    current_index = matching_indexes[0]
    if current_index != len(recovery_messages) - 1:
        raise ValueError("Assistant stream recovery must be the trailing durable message")
    current = recovery_messages[current_index]
    return recovery_messages[:current_index], _response_outbox([current], checkpoint)


def _partition_terminal_recovery(
    recovery_messages: list[dict[str, Any]],
    checkpoint: AgentCheckpoint | None,
) -> tuple[list[dict[str, Any]], AgentResponseOutbox | None, list[dict[str, Any]]]:
    """Split mixed terminal recovery into history, one prose outbox, and later rows.

    Streamed replies often share a terminal envelope with a following ``ask_user``
    tool_call. The outbox contract still allows only one assistant message.
    """
    prose_indexes = [index for index, item in enumerate(recovery_messages) if _is_assistant_prose_recovery(item)]
    if not prose_indexes:
        return recovery_messages, None, []
    last_index = prose_indexes[-1]
    outbox = _response_outbox([recovery_messages[last_index]], checkpoint)
    return recovery_messages[:last_index], outbox, recovery_messages[last_index + 1 :]


def _append_recovery_messages(*, lease: RunLease, recovery_messages: list[dict[str, Any]]) -> None:
    """Write durable AgentSession rows that do not belong to the current response outbox."""
    if not recovery_messages:
        return
    with session_factory.create_session() as session:
        conversation = session.scalar(
            select(WorkflowAssistConversation).where(
                WorkflowAssistConversation.id == lease.owner.conversation_id,
                WorkflowAssistConversation.tenant_id == lease.owner.tenant_id,
                WorkflowAssistConversation.app_id == lease.owner.app_id,
                WorkflowAssistConversation.account_id == lease.owner.account_id,
            )
        )
        if conversation is None:
            raise ValueError("recovery message conversation disappeared")
        conversations = WorkflowAssistConversationService(session)
        for recovery in recovery_messages:
            row = conversations.append_message(
                conversation=conversation,
                role=_recovery_role(recovery),
                event_type=_required_text(recovery, "event_type"),
                payload=_recovery_payload(recovery),
                status=str(recovery.get("status") or "completed"),
            )
            expected_sequence = recovery.get("sequence")
            if isinstance(expected_sequence, int) and row.sequence != expected_sequence:
                raise ValueError("recovery message sequence diverged from AgentSession")
        session.commit()


def _response_outbox(
    recovery_messages: list[dict[str, Any]] | None,
    checkpoint: AgentCheckpoint | None,
) -> AgentResponseOutbox:
    if recovery_messages is None or len(recovery_messages) != 1:
        raise ValueError("Assistant prose requires exactly one durable recovery message")
    recovery = recovery_messages[0]
    sequence = recovery.get("sequence")
    if not isinstance(sequence, int) or sequence < 1:
        raise ValueError("Assistant prose requires a positive durable sequence")
    if _recovery_role(recovery) != "assistant" or _required_text(recovery, "event_type") != "message":
        raise ValueError("Assistant prose recovery must be an assistant message")
    payload = _recovery_payload(recovery)
    if not isinstance(payload.get("text"), str):
        raise ValueError("Assistant prose recovery requires text")
    reasoning = payload.get("reasoning")
    if not payload["text"].strip() and not (isinstance(reasoning, str) and reasoning.strip()):
        raise ValueError("Assistant prose recovery requires text or reasoning")
    return AgentResponseOutbox(sequence=sequence, payload=payload, checkpoint=checkpoint)


def _recovery_agent_message(recovery: dict[str, Any]) -> AgentMessage:
    sequence = recovery.get("sequence")
    if not isinstance(sequence, int) or sequence < 1:
        raise ValueError("Agent recovery history requires a positive durable sequence")
    event_type = _required_text(recovery, "event_type")
    if event_type not in {"message", "tool_call", "tool_result"}:
        raise ValueError("Agent recovery history event type is invalid")
    return AgentMessage(
        sequence=sequence,
        role=_recovery_role(recovery),
        event_type=cast(AgentMessageEventType, event_type),
        status=str(recovery.get("status") or "completed"),
        payload=_recovery_payload(recovery),
    )


def _stage_response_outbox(
    *,
    lease: RunLease,
    history: list[dict[str, Any]],
    response: AgentResponseOutbox,
) -> bool:
    prepared_history = tuple(_recovery_agent_message(recovery) for recovery in history)
    with session_factory.create_session() as session:
        outcome = RunCoordinator(session).stage_agent_response(
            lease=lease,
            history=prepared_history,
            response=response,
        )
        session.commit()
        return outcome is not CommitStepOutcome.FENCED


def _agent_checkpoint(payload: dict[str, Any]) -> AgentCheckpoint | None:
    raw = payload.pop("_agent_checkpoint", None)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("Agent checkpoint must be an object")
    watermark = raw.get("compacted_until_sequence")
    compacted_state = raw.get("compacted_state")
    last_validation = raw.get("last_validation")
    workflow_contract = _workflow_contract_checkpoint(raw.get("workflow_contract"))
    if watermark is not None and not isinstance(watermark, int):
        raise ValueError("Agent checkpoint watermark must be an integer")
    if compacted_state is not None and not isinstance(compacted_state, dict):
        raise ValueError("Agent checkpoint compacted state must be an object")
    if last_validation is not None and not isinstance(last_validation, dict):
        raise ValueError("Agent checkpoint validation must be an object")
    return AgentCheckpoint(
        compacted_until_sequence=watermark,
        compacted_state=compacted_state,
        last_validation=last_validation,
        workflow_contract=workflow_contract,
    )


def _workflow_contract_checkpoint(value: object) -> WorkflowContractCheckpoint | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Workflow contract checkpoint must be an object")
    protocol_version = value.get("protocol_version")
    revision = value.get("revision")
    contract_hash = value.get("contract_hash")
    contract = value.get("contract")
    if not isinstance(protocol_version, int) or not isinstance(revision, int):
        raise ValueError("Workflow contract checkpoint versions must be integers")
    if not isinstance(contract_hash, str) or not isinstance(contract, dict):
        raise ValueError("Workflow contract checkpoint requires hash and contract")
    return WorkflowContractCheckpoint(
        protocol_version=protocol_version,
        revision=revision,
        contract_hash=contract_hash,
        contract=cast(dict[str, object], contract),
    )


def _recovery_message_sequence(recovery_messages: list[dict[str, Any]] | None) -> int | None:
    if not recovery_messages:
        return None
    for message in recovery_messages:
        if message.get("event_type") == "message" and isinstance(message.get("sequence"), int):
            return message["sequence"]
    return None


def _delta_message_id(
    message_id: str | None,
    recovery_messages: list[dict[str, Any]] | None,
    *,
    current: str | None,
) -> str | None:
    if isinstance(message_id, str) and message_id.strip():
        return message_id.strip()
    sequence = _recovery_message_sequence(recovery_messages)
    if sequence is not None:
        return str(sequence)
    return current


def _node_map(graph: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        return {}
    return {
        node["id"]: node
        for node in graph["nodes"]
        if isinstance(node, dict) and isinstance(node.get("id"), str) and node["id"]
    }


def _closed_graph_diff(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, list[str]]:
    before = _node_map(previous)
    after = _node_map(current)
    return {
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "changed": sorted(node_id for node_id in before.keys() & after.keys() if before[node_id] != after[node_id]),
    }


def _load_candidate_graph(lease: RunLease) -> dict[str, Any] | None:
    with session_factory.create_session() as session:
        graph = session.scalar(
            select(WorkflowAssistConversation.candidate_graph).where(
                WorkflowAssistConversation.id == lease.owner.conversation_id,
                WorkflowAssistConversation.tenant_id == lease.owner.tenant_id,
                WorkflowAssistConversation.app_id == lease.owner.app_id,
                WorkflowAssistConversation.account_id == lease.owner.account_id,
            )
        )
        return graph if isinstance(graph, dict) else None


def _canonical_draft_hash(value: object) -> str | None:
    """Accept only the 64-character SHA256 hex used by ``Workflow.unique_hash``."""
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None:
        return value
    return None


def _load_candidate_base_hash(lease: RunLease) -> str | None:
    with session_factory.create_session() as session:
        row = session.execute(
            select(WorkflowAssistConversation.candidate_base_hash, WorkflowAssistConversation.draft_hash).where(
                WorkflowAssistConversation.id == lease.owner.conversation_id,
                WorkflowAssistConversation.tenant_id == lease.owner.tenant_id,
                WorkflowAssistConversation.app_id == lease.owner.app_id,
                WorkflowAssistConversation.account_id == lease.owner.account_id,
            )
        ).one_or_none()
        if row is None:
            return None
        candidate_base_hash, draft_hash = row
        return _canonical_draft_hash(candidate_base_hash) or _canonical_draft_hash(draft_hash)


def _terminate(
    *,
    lease: RunLease,
    status: WorkflowAssistRunStatus,
    payload: dict[str, Any],
    reason: str | None,
    response_outbox: AgentResponseOutbox | None = None,
) -> bool:
    with session_factory.create_session() as session:
        terminated = RunCoordinator(session).terminate(
            lease=lease,
            status=status,
            step_id=f"terminal:{status.value}",
            payload=payload,
            reason=reason,
            response_outbox=response_outbox,
        )
        session.commit()
        return terminated


def _lease_still_held(lease: RunLease) -> bool:
    """Return whether the worker lease can still write after a rejected terminal."""
    with session_factory.create_session() as session:
        refreshed = RunCoordinator(session).heartbeat(lease=lease)
        session.commit()
        return refreshed


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Agent event requires non-empty {key}")
    return value.strip()


def _delta_text(payload: dict[str, Any]) -> str:
    value = payload.get("delta", payload.get("text", payload.get("message")))
    if not isinstance(value, str):
        raise ValueError("delta requires text")
    return value


def persist_agent_events(
    *,
    lease: RunLease,
    events: Iterator[AgentEvent],
    should_stop: Callable[[], bool] = lambda: False,
    monotonic: Callable[[], float] = time.monotonic,
) -> WorkflowAssistRunStatus | AgentEventPumpOutcome | None:
    """Persist one Agent stream, stopping on a lost fence or terminal event.

    A terminal envelope may own the completed response snapshot that became
    observable only after the stream's final delta. Extra recovery rows around
    that snapshot (for example a following ``ask_user`` tool_call) are written
    as ordinary history instead of being forced into the one-message outbox.
    """
    deltas = _TimedMessageDeltaWriter(lease)
    reasoning_deltas = _TimedMessageDeltaWriter(
        lease,
        event_type=WorkflowAssistRunEventType.REASONING_DELTA,
        step_prefix="reasoning",
    )
    candidate_graph = _load_candidate_graph(lease)
    candidate_base_hash = _load_candidate_base_hash(lease)
    last_tool_call_id: str | None = None

    def _pumps_ok() -> bool:
        return deltas.check() and reasoning_deltas.check()

    def _flush_pumps() -> bool:
        return deltas.flush() and reasoning_deltas.flush()

    def _cancel_pumps() -> None:
        deltas.cancel()
        reasoning_deltas.cancel()

    event_iterator = iter(events)
    while True:
        if should_stop() or not _pumps_ok():
            _cancel_pumps()
            return AgentEventPumpOutcome.FENCED
        try:
            event_name, raw_payload = next(event_iterator)
        except StopIteration:
            break
        if should_stop() or not _pumps_ok():
            _cancel_pumps()
            return AgentEventPumpOutcome.FENCED
        payload = dict(raw_payload)
        if event_name in {"message", "message.delta", "reasoning.delta"}:
            recovery_messages = _recovery_messages(payload)
            checkpoint = _agent_checkpoint(payload)
            message_id = payload.get("message_id")
            delta_index = payload.get("delta_index")
            stream_mode = payload.get("stream_mode")
            writer = reasoning_deltas if event_name == "reasoning.delta" else deltas
            if not writer.push(
                _delta_text(payload),
                now=monotonic(),
                recovery_messages=recovery_messages,
                checkpoint=checkpoint,
                message_id=message_id if isinstance(message_id, str) and message_id.strip() else None,
                delta_index=delta_index if isinstance(delta_index, int) else None,
                stream_mode=stream_mode if isinstance(stream_mode, str) and stream_mode.strip() else None,
            ):
                _cancel_pumps()
                return AgentEventPumpOutcome.FENCED
            continue
        if not _flush_pumps():
            _cancel_pumps()
            return AgentEventPumpOutcome.FENCED

        if event_name in {"tool_call", "tool_result"}:
            recovery_messages = _recovery_messages(payload)
            checkpoint = _agent_checkpoint(payload)
            graph = payload.pop("graph", None)
            if "tool_call_id" not in payload and "id" in payload:
                payload["tool_call_id"] = payload.pop("id")
            tool_call_id = _required_text(payload, "tool_call_id")
            last_tool_call_id = tool_call_id
            suffix = "call" if event_name == "tool_call" else "result"
            event_type = (
                WorkflowAssistRunEventType.TOOL_CALL
                if event_name == "tool_call"
                else WorkflowAssistRunEventType.TOOL_RESULT
            )
            candidate_changed = isinstance(graph, dict) and graph != candidate_graph
            if not _commit_step(
                lease=lease,
                step_id=f"tool:{tool_call_id}:{suffix}",
                event=event_type,
                payload=payload,
                recovery_messages=[] if candidate_changed else recovery_messages,
                checkpoint=None if candidate_changed else checkpoint,
            ):
                _cancel_pumps()
                return AgentEventPumpOutcome.FENCED
            if candidate_changed:
                assert isinstance(graph, dict)
                if not _commit_step(
                    lease=lease,
                    step_id=f"candidate:{tool_call_id}",
                    event=WorkflowAssistRunEventType.CANDIDATE_UPDATED,
                    payload={"diff": _closed_graph_diff(candidate_graph, graph)},
                    candidate=CandidateMutation(graph=graph, base_hash=candidate_base_hash),
                    recovery_messages=recovery_messages,
                    checkpoint=checkpoint,
                ):
                    _cancel_pumps()
                    return AgentEventPumpOutcome.FENCED
                candidate_graph = graph
            continue

        if event_name == "candidate.updated":
            _recovery_messages(payload)
            checkpoint = _agent_checkpoint(payload)
            graph = payload.pop("graph", None)
            if not isinstance(graph, dict):
                raise ValueError("candidate.updated requires graph")
            step_id = _required_text(payload, "step_id")
            payload.pop("step_id")
            base_hash = payload.pop("base_hash", None)
            if isinstance(payload.get("diff"), dict) and "updated" in payload["diff"]:
                payload["diff"]["changed"] = payload["diff"].pop("updated")
            if set(payload) != {"diff"}:
                raise ValueError("candidate.updated exposes only diff in its RunEvent")
            if not _commit_step(
                lease=lease,
                step_id=f"candidate:{step_id}",
                event=WorkflowAssistRunEventType.CANDIDATE_UPDATED,
                payload=payload,
                candidate=CandidateMutation(graph=graph, base_hash=base_hash),
                checkpoint=checkpoint,
            ):
                _cancel_pumps()
                return AgentEventPumpOutcome.FENCED
            continue

        terminal_statuses = {
            "waiting_user": WorkflowAssistRunStatus.WAITING_USER,
            "done": WorkflowAssistRunStatus.DONE,
            "failed": WorkflowAssistRunStatus.FAILED,
            "error": WorkflowAssistRunStatus.ERROR,
            "aborted": WorkflowAssistRunStatus.ABORTED,
            "turn_complete": WorkflowAssistRunStatus.TURN_COMPLETE,
        }
        status = terminal_statuses.get(event_name)
        if status is None:
            raise ValueError(f"unsupported Agent event: {event_name}")
        recovery_messages = _recovery_messages(payload)
        checkpoint = _agent_checkpoint(payload)
        history_before, response_outbox, history_after = _partition_terminal_recovery(recovery_messages, checkpoint)
        graph = payload.pop("graph", payload.pop("candidate_graph", None))
        if isinstance(graph, dict) and graph != candidate_graph:
            if last_tool_call_id is None:
                raise ValueError("terminal candidate graph requires a preceding tool call")
            if not _commit_step(
                lease=lease,
                step_id=f"candidate:{last_tool_call_id}",
                event=WorkflowAssistRunEventType.CANDIDATE_UPDATED,
                payload={"diff": _closed_graph_diff(candidate_graph, graph)},
                candidate=CandidateMutation(graph=graph, base_hash=candidate_base_hash),
                checkpoint=checkpoint,
            ):
                _cancel_pumps()
                return AgentEventPumpOutcome.FENCED
            candidate_graph = graph
            checkpoint = None
        _append_recovery_messages(lease=lease, recovery_messages=history_before)
        if checkpoint is not None and response_outbox is None:
            raise ValueError("terminal Agent checkpoint requires a preceding durable step")
        reason_value = payload.get("reason", payload.get("termination_reason"))
        reason = reason_value if isinstance(reason_value, str) else None
        if not _terminate(
            lease=lease,
            status=status,
            payload=payload,
            reason=reason,
            response_outbox=response_outbox,
        ):
            _cancel_pumps()
            if status is WorkflowAssistRunStatus.DONE and _lease_still_held(lease):
                if _terminate(
                    lease=lease,
                    status=WorkflowAssistRunStatus.ERROR,
                    payload={"status": "error", "reason": "completion_rejected"},
                    reason="completion_rejected",
                    response_outbox=response_outbox,
                ):
                    return WorkflowAssistRunStatus.ERROR
            return AgentEventPumpOutcome.FENCED
        _append_recovery_messages(lease=lease, recovery_messages=history_after)
        _cancel_pumps()
        return status

    if not _flush_pumps():
        _cancel_pumps()
        return AgentEventPumpOutcome.FENCED
    _cancel_pumps()
    return None
