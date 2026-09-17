"""Transactional state machine for durable Workflow Assist runs.

The coordinator owns run-event sequences and lifecycle changes. Every write is
fenced by full ownership, the active run and epoch, status, and worker lease.
No task dispatch, model invocation, or network work occurs in its transactions.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import exists, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from configs import dify_config
from core.workflow.generator.acceptance.evidence import canonical_graph_hash
from core.workflow.generator.agent.types import AgentMessage
from core.workflow.generator.contracts.workflow_reconciliation import WORKFLOW_RECONCILIATION_VERSION
from libs.datetime_utils import naive_utc_now
from models.workflow_assist import (
    WORKFLOW_ASSIST_RUN_ACTIVE_STATUSES,
    WorkflowAssistCompletionAssertion,
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistMode,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
    WorkflowAssistRunEventType,
    WorkflowAssistRunStatus,
)
from services.workflow_assist.completion_policy import CompletionPolicy
from services.workflow_assist.conversations import (
    WorkflowAssistConversationNotFound,
    WorkflowAssistConversationWriteConflictError,
)
from services.workflow_assist.run_types import (
    AGENT_RESPONSE_OUTBOX_KEY,
    AgentCheckpoint,
    AgentResponseOutbox,
    CandidateMutation,
    CommitStepOutcome,
    CommitStepResult,
    DispatchFailureFence,
    QueueTimeoutFence,
    RunLease,
    RunOwner,
    UserAbortFence,
    WorkerTimeoutFence,
    WorkflowContractCheckpoint,
)
from services.workflow_assist.run_values import (
    ensure_payload_size,
    prepare_candidate_graph,
    prepare_model_config,
    prepare_run_event_payload,
    prepare_run_input,
    sanitize_payload,
)

_TERMINAL_EVENT_TYPES = frozenset(
    {
        WorkflowAssistRunEventType.WAITING_USER,
        WorkflowAssistRunEventType.DONE,
        WorkflowAssistRunEventType.FAILED,
        WorkflowAssistRunEventType.ERROR,
        WorkflowAssistRunEventType.ABORTED,
        WorkflowAssistRunEventType.TURN_COMPLETE,
    }
)
_RESERVED_CONTROL_REASONS = frozenset({"dispatch_failed", "user_abort", "queue_timeout", "worker_lost"})
_MAX_AGENT_CHECKPOINT_BYTES = 1024 * 1024
_MAX_AGENT_RESPONSE_BYTES = 512 * 1024


class RunCoordinator:
    """Coordinate run lifecycle, leases, event ordering, and candidate writes.

    The supplied session is caller-owned. Each transition uses a savepoint so
    the caller may catch a transition error and safely commit its outer unit of
    work. Heartbeats remain compatible with a fresh short-lived session.
    """

    session: Session
    _completion_policy: CompletionPolicy

    def __init__(self, session: Session) -> None:
        self.session = session
        self._completion_policy = CompletionPolicy(session)

    def start_turn(
        self,
        *,
        owner: RunOwner,
        message: str,
        mode: WorkflowAssistMode | str,
        model_config: dict[str, Any],
        selected_node: str | None = None,
        references: list[dict[str, Any]] | None = None,
        live_acceptance_request_id: str | None = None,
    ) -> WorkflowAssistRun:
        """Atomically supersede an active run and create one queued user turn."""
        normalized_message = prepare_run_input(message)
        normalized_mode = self._normalize_mode(mode)
        prepared_model_config = prepare_model_config(model_config)
        normalized_selected_node = self._normalize_optional_text(
            selected_node, field_name="selected_node", max_length=255
        )
        queued_payload = self._prepare_event_payload({"status": "queued"})
        aborted_payload = self._prepare_event_payload({"status": "aborted", "reason": "superseded_by_new_turn"})

        try:
            with self.session.begin_nested():
                conversation = self._lock_conversation(owner)
                from services.workflow_assist.live_acceptance import resolve_live_approval

                live_acceptance = resolve_live_approval(self.session, conversation, live_acceptance_request_id)
                if conversation.active_run_id is not None:
                    active_run = self._lock_run(
                        owner,
                        run_id=conversation.active_run_id,
                        epoch=conversation.run_epoch,
                        statuses=WORKFLOW_ASSIST_RUN_ACTIVE_STATUSES,
                    )
                    if active_run is not None:
                        self._finish_locked_run(
                            conversation=conversation,
                            run=active_run,
                            status=WorkflowAssistRunStatus.ABORTED,
                            step_id=f"superseded:{conversation.run_epoch}",
                            payload=aborted_payload,
                            reason="superseded_by_new_turn",
                        )

                self._abandon_pending_agent_responses(conversation=conversation, reason="superseded_by_new_turn")
                conversation.run_epoch = (conversation.run_epoch or 0) + 1
                self._append_user_turn(
                    conversation=conversation,
                    message=normalized_message,
                    references=references,
                )
                run = WorkflowAssistRun(
                    tenant_id=owner.tenant_id,
                    app_id=owner.app_id,
                    created_by=owner.account_id,
                    conversation_id=owner.conversation_id,
                    epoch=conversation.run_epoch,
                    status=WorkflowAssistRunStatus.QUEUED,
                    input=normalized_message,
                    mode=normalized_mode,
                    model_config=prepared_model_config,
                    selected_node=normalized_selected_node,
                    references=list(references) if references else None,
                    contract_protocol_version=conversation.contract_protocol_version,
                    contract_rollout_stage=str(dify_config.WORKFLOW_ASSIST_CONTRACT_ROLLOUT),
                    live_acceptance=live_acceptance,
                    next_event_sequence=1,
                    candidate_revision=conversation.candidate_revision,
                )
                self.session.add(run)
                self.session.flush()
                self._append_run_step(
                    run=run,
                    step_id="status:queued",
                    event=WorkflowAssistRunEventType.STATUS,
                    payload=queued_payload,
                )
                conversation.active_run_id = run.id
                conversation.latest_run_id = run.id
                conversation.updated_at = naive_utc_now()
                self.session.flush()
            return run
        except IntegrityError as exc:
            raise self._write_conflict() from exc

    def consume_live_acceptance(self, *, lease: RunLease, revision: int, graph_hash: str) -> bool:
        """Reserve one graph-bound execution; consumed grants are never copied into retries."""
        with self.session.begin_nested():
            locked = self._lock_for_worker_write(lease)
            if locked is None:
                return False
            _, run = locked
            grant = run.live_acceptance
            if not isinstance(grant, dict) or grant.get("consumed") is not False:
                return False
            if grant.get("candidate_revision") != revision or grant.get("graph_hash") != graph_hash:
                return False
            run.live_acceptance = {**grant, "consumed": True}
            self.session.flush()
            return True

    def retry_failed_step(
        self,
        *,
        owner: RunOwner,
        run_id: str,
        epoch: int,
        failed_step_id: str,
    ) -> WorkflowAssistRun:
        """Queue a new Run from the last complete boundary before a retryable failure."""
        normalized_step_id = self._validate_step_id(failed_step_id)
        queued_payload = self._prepare_event_payload({"status": "queued"})

        try:
            with self.session.begin_nested():
                conversation = self._lock_conversation(owner)
                if conversation.run_epoch != epoch:
                    raise self._write_conflict()
                failed_run = self._lock_run(
                    owner,
                    run_id=run_id,
                    epoch=epoch,
                    statuses=frozenset({WorkflowAssistRunStatus.FAILED, WorkflowAssistRunStatus.ERROR}),
                )
                if failed_run is None:
                    raise ValueError("failed step is not retryable")
                if failed_run.termination_reason == "user_abort":
                    raise ValueError("failed step is not retryable")
                failed_event = self.session.scalar(
                    select(WorkflowAssistRunEvent).where(
                        *self._event_owner_predicates(owner),
                        WorkflowAssistRunEvent.run_id == failed_run.id,
                        WorkflowAssistRunEvent.epoch == failed_run.epoch,
                        WorkflowAssistRunEvent.step_id == normalized_step_id,
                    )
                )
                if failed_event is None:
                    raise ValueError("failed step not found")
                if not self._is_retryable_failed_step(failed_event):
                    raise ValueError("failed step is not retryable")
                self._drop_incomplete_tool_json_messages(conversation)
                conversation.run_epoch = (conversation.run_epoch or 0) + 1
                run = WorkflowAssistRun(
                    tenant_id=owner.tenant_id,
                    app_id=owner.app_id,
                    created_by=owner.account_id,
                    conversation_id=owner.conversation_id,
                    epoch=conversation.run_epoch,
                    status=WorkflowAssistRunStatus.QUEUED,
                    input=failed_run.input,
                    mode=failed_run.mode,
                    model_config=failed_run.model_config,
                    selected_node=failed_run.selected_node,
                    references=list(failed_run.references) if failed_run.references else None,
                    contract_protocol_version=failed_run.contract_protocol_version,
                    contract_rollout_stage=failed_run.contract_rollout_stage,
                    next_event_sequence=1,
                    candidate_revision=conversation.candidate_revision,
                )
                self.session.add(run)
                self.session.flush()
                self._append_run_step(
                    run=run,
                    step_id="status:queued",
                    event=WorkflowAssistRunEventType.STATUS,
                    payload=queued_payload,
                )
                conversation.active_run_id = run.id
                conversation.latest_run_id = run.id
                conversation.updated_at = naive_utc_now()
                self.session.flush()
            return run
        except IntegrityError as exc:
            raise self._write_conflict() from exc

    def claim(
        self,
        *,
        owner: RunOwner,
        run_id: str,
        epoch: int,
        worker_id: str,
    ) -> RunLease | None:
        """Claim a queued run or resume its lease for the same delivery identity."""
        normalized_worker_id = self._normalize_required_text(worker_id, field_name="worker_id", max_length=255)
        running_payload = self._prepare_event_payload({"status": "running"})
        try:
            with self.session.begin_nested():
                conversation = self._lock_current_conversation(owner, run_id=run_id, epoch=epoch)
                if conversation is None:
                    return None
                run = self._lock_run(
                    owner,
                    run_id=run_id,
                    epoch=epoch,
                    statuses=frozenset({WorkflowAssistRunStatus.QUEUED, WorkflowAssistRunStatus.RUNNING}),
                )
                if run is None:
                    return None

                now = naive_utc_now()
                if run.status is WorkflowAssistRunStatus.RUNNING:
                    if run.worker_id != normalized_worker_id:
                        return None
                    run.heartbeat_at = now
                    conversation.updated_at = now
                    self.session.flush()
                    return RunLease(
                        owner=owner,
                        run_id=run.id,
                        epoch=run.epoch,
                        worker_id=normalized_worker_id,
                        attempt=run.attempt,
                    )
                run.status = WorkflowAssistRunStatus.RUNNING
                run.attempt += 1
                run.worker_id = normalized_worker_id
                run.claimed_at = now
                run.started_at = now
                run.heartbeat_at = now
                self._append_run_step(
                    run=run,
                    step_id="status:running",
                    event=WorkflowAssistRunEventType.STATUS,
                    payload=running_payload,
                )
                conversation.updated_at = now
                self.session.flush()
                lease = RunLease(
                    owner=owner,
                    run_id=run.id,
                    epoch=run.epoch,
                    worker_id=normalized_worker_id,
                    attempt=run.attempt,
                )
            return lease
        except IntegrityError as exc:
            raise self._write_conflict() from exc

    def heartbeat(self, *, lease: RunLease) -> bool:
        """Refresh one running lease using a single short-session-compatible write."""
        if lease.worker_id is None:
            return False
        owner = lease.owner
        current_conversation = exists(
            select(WorkflowAssistConversation.id).where(
                WorkflowAssistConversation.id == owner.conversation_id,
                WorkflowAssistConversation.tenant_id == owner.tenant_id,
                WorkflowAssistConversation.app_id == owner.app_id,
                WorkflowAssistConversation.account_id == owner.account_id,
                WorkflowAssistConversation.is_deleted.is_(False),
                WorkflowAssistConversation.active_run_id == lease.run_id,
                WorkflowAssistConversation.run_epoch == lease.epoch,
            )
        )
        try:
            with self.session.begin_nested():
                result = cast(
                    "CursorResult[Any]",
                    self.session.execute(
                        update(WorkflowAssistRun)
                        .where(
                            *self._run_owner_predicates(owner),
                            WorkflowAssistRun.id == lease.run_id,
                            WorkflowAssistRun.epoch == lease.epoch,
                            WorkflowAssistRun.status == WorkflowAssistRunStatus.RUNNING,
                            WorkflowAssistRun.worker_id == lease.worker_id,
                            WorkflowAssistRun.attempt == lease.attempt,
                            current_conversation,
                        )
                        .values(heartbeat_at=naive_utc_now())
                        .execution_options(synchronize_session=False)
                    ),
                )
                self.session.flush()
                refreshed = result.rowcount == 1
            return refreshed
        except IntegrityError as exc:
            raise self._write_conflict() from exc

    def commit_step(
        self,
        *,
        lease: RunLease,
        step_id: str,
        event: WorkflowAssistRunEventType | str,
        payload: dict[str, Any],
        candidate: CandidateMutation | None = None,
        checkpoint: AgentCheckpoint | None = None,
        response_outbox: AgentResponseOutbox | None = None,
    ) -> CommitStepResult:
        """Commit one validated, idempotent ordinary run step."""
        normalized_step_id = self._validate_step_id(step_id)
        normalized_event = self._normalize_event(event)
        if normalized_event in _TERMINAL_EVENT_TYPES:
            raise ValueError("terminal events must be written with terminate")
        if normalized_event is WorkflowAssistRunEventType.STATUS:
            raise ValueError("status events are owned by run lifecycle transitions")
        prepared_payload = self._prepare_step_payload(event=normalized_event, payload=payload, candidate=candidate)
        prepared_candidate: dict[str, Any] | None = None
        prepared_base_hash: str | None = None
        if candidate is not None:
            prepared_candidate = prepare_candidate_graph(candidate.graph)
            prepared_base_hash = self._normalize_optional_text(
                candidate.base_hash, field_name="candidate base_hash", max_length=64
            )
        prepared_checkpoint = self._prepare_agent_checkpoint(checkpoint)
        prepared_response = self._prepare_agent_response(response_outbox)

        try:
            with self.session.begin_nested():
                result = self._commit_step_locked(
                    lease=lease,
                    step_id=normalized_step_id,
                    event=normalized_event,
                    payload=prepared_payload,
                    candidate_graph=prepared_candidate,
                    candidate_base_hash=prepared_base_hash,
                    checkpoint=prepared_checkpoint,
                    response_outbox=prepared_response,
                )
            return result
        except IntegrityError as exc:
            duplicate = self._recover_duplicate_after_conflict(
                lease=lease,
                step_id=normalized_step_id,
                event=normalized_event,
                payload=prepared_payload,
            )
            if duplicate is not None:
                return duplicate
            raise self._write_conflict() from exc

    def stage_agent_response(
        self,
        *,
        lease: RunLease,
        response: AgentResponseOutbox,
        history: Sequence[AgentMessage] = (),
    ) -> CommitStepOutcome:
        """Atomically append preceding history and freeze one response under a worker fence.

        History sequences must be strictly increasing and precede the response.
        Exact replays are idempotent; conflicting rows raise a write conflict.
        """
        prepared = self._prepare_agent_response(response)
        assert prepared is not None
        prepared_history = self._prepare_agent_history(history, response_sequence=prepared.sequence)
        try:
            with self.session.begin_nested():
                locked = self._lock_for_worker_write(lease)
                if locked is None:
                    return CommitStepOutcome.FENCED
                conversation, _run = locked
                latest_sequence = (
                    self.session.scalar(
                        select(func.coalesce(func.max(WorkflowAssistMessage.sequence), 0)).where(
                            WorkflowAssistMessage.tenant_id == lease.owner.tenant_id,
                            WorkflowAssistMessage.app_id == lease.owner.app_id,
                            WorkflowAssistMessage.account_id == lease.owner.account_id,
                            WorkflowAssistMessage.conversation_id == conversation.id,
                        )
                    )
                    or 0
                )
                for message in prepared_history:
                    existing_history = self._find_agent_message(lease=lease, sequence=message.sequence)
                    if existing_history is not None:
                        self._reject_mismatched_history(existing=existing_history, message=message)
                        continue
                    if message.sequence != latest_sequence + 1:
                        raise WorkflowAssistConversationWriteConflictError("Durable Agent history sequence mismatch")
                    self.session.add(
                        WorkflowAssistMessage(
                            tenant_id=lease.owner.tenant_id,
                            app_id=lease.owner.app_id,
                            account_id=lease.owner.account_id,
                            conversation_id=lease.owner.conversation_id,
                            sequence=message.sequence,
                            role=message.role,
                            event_type=message.event_type,
                            status=message.status,
                            retryable=False,
                            payload=message.payload,
                        )
                    )
                    latest_sequence = message.sequence
                existing = self._find_agent_message(lease=lease, sequence=prepared.sequence)
                if existing is not None:
                    self._reject_mismatched_response(existing=existing, response=prepared, lease=lease)
                    return CommitStepOutcome.DUPLICATE
                if prepared.sequence != latest_sequence + 1:
                    raise WorkflowAssistConversationWriteConflictError("Durable Agent response sequence mismatch")
                self.session.add(
                    WorkflowAssistMessage(
                        tenant_id=lease.owner.tenant_id,
                        app_id=lease.owner.app_id,
                        account_id=lease.owner.account_id,
                        conversation_id=lease.owner.conversation_id,
                        sequence=prepared.sequence,
                        role="assistant",
                        event_type="message",
                        status="pending",
                        retryable=False,
                        payload=self._staged_response_payload(prepared, lease=lease),
                    )
                )
                conversation.updated_at = naive_utc_now()
                self.session.flush()
            return CommitStepOutcome.COMMITTED
        except IntegrityError as exc:
            raise self._write_conflict() from exc

    def terminate(
        self,
        *,
        lease: RunLease | DispatchFailureFence | UserAbortFence | QueueTimeoutFence | WorkerTimeoutFence,
        status: WorkflowAssistRunStatus | str,
        step_id: str,
        payload: dict[str, Any],
        reason: str | None = None,
        response_outbox: AgentResponseOutbox | None = None,
    ) -> bool:
        """Atomically finish one running worker lease and append its terminal event.

        ``done`` is authorized only after deterministic, mode-specific
        verification of the exact candidate held by the locked conversation.
        A completed response supplied by a worker is persisted in the same
        transaction so the terminal event cannot outrun conversation history.
        """
        normalized_status = self._normalize_status(status)
        if not normalized_status.is_terminal:
            raise ValueError("terminate requires a terminal run status")
        normalized_step_id = self._validate_step_id(step_id)
        normalized_reason = self._normalize_optional_text(reason, field_name="reason", max_length=64)
        control_statuses = self._validate_terminal_authority(
            lease=lease,
            status=normalized_status,
            reason=normalized_reason,
        )
        prepared_payload = self._prepare_terminal_payload(status=normalized_status, payload=payload)
        prepared_response = self._prepare_agent_response(response_outbox)
        if prepared_response is not None and not isinstance(lease, RunLease):
            raise ValueError("terminal Agent response requires a worker lease")

        try:
            with self.session.begin_nested():
                if not isinstance(lease, RunLease):
                    assert control_statuses is not None
                    locked = self._lock_for_control_write(lease, statuses=control_statuses)
                else:
                    locked = self._lock_for_worker_write(lease)
                if locked is None:
                    return False
                conversation, run = locked
                if not self._timeout_observation_is_current(lease=lease, run=run):
                    return False
                if normalized_status is WorkflowAssistRunStatus.DONE:
                    if not self._candidate_is_complete(owner=lease.owner, conversation=conversation, run=run):
                        return False
                    self._write_completion_evidence(conversation=conversation, run=run)
                if prepared_response is not None:
                    assert isinstance(lease, RunLease)
                    self._persist_terminal_agent_response(
                        lease=lease,
                        conversation=conversation,
                        run=run,
                        response=prepared_response,
                    )
                self._finish_locked_run(
                    conversation=conversation,
                    run=run,
                    status=normalized_status,
                    step_id=normalized_step_id,
                    payload=prepared_payload,
                    reason=normalized_reason,
                )
                self.session.flush()
            return True
        except IntegrityError as exc:
            raise self._write_conflict() from exc

    def _commit_step_locked(
        self,
        *,
        lease: RunLease,
        step_id: str,
        event: WorkflowAssistRunEventType,
        payload: dict[str, Any],
        candidate_graph: dict[str, Any] | None,
        candidate_base_hash: str | None,
        checkpoint: AgentCheckpoint | None,
        response_outbox: AgentResponseOutbox | None,
    ) -> CommitStepResult:
        locked = self._lock_for_worker_write(lease)
        if locked is None:
            return CommitStepResult(outcome=CommitStepOutcome.FENCED)
        conversation, run = locked
        duplicate = self._find_existing_step(lease=lease, step_id=step_id)
        if duplicate is not None:
            self._reject_mismatched_step_replay(existing=duplicate, event=event, payload=payload)
            return CommitStepResult(
                outcome=CommitStepOutcome.DUPLICATE,
                sequence=duplicate.sequence,
                candidate_revision=run.candidate_revision,
            )

        if candidate_graph is not None:
            next_revision = conversation.candidate_revision + 1
            payload = self._prepare_event_payload({"revision": next_revision, "diff": payload["diff"]})
            conversation.candidate_graph = candidate_graph
            conversation.candidate_revision = next_revision
            if candidate_base_hash is not None:
                conversation.candidate_base_hash = candidate_base_hash
            self._clear_completion_evidence(conversation)
            run.candidate_revision = next_revision

        if checkpoint is not None:
            self._apply_agent_checkpoint(
                conversation=conversation,
                checkpoint=checkpoint,
                contract_protocol_version=run.contract_protocol_version,
            )

        if response_outbox is not None:
            self._complete_agent_response(lease=lease, response=response_outbox)

        committed_event = self._append_run_step(run=run, step_id=step_id, event=event, payload=payload)
        conversation.updated_at = naive_utc_now()
        self.session.flush()
        return CommitStepResult(
            outcome=CommitStepOutcome.COMMITTED,
            sequence=committed_event.sequence,
            candidate_revision=run.candidate_revision,
        )

    @staticmethod
    def _prepare_agent_checkpoint(checkpoint: AgentCheckpoint | None) -> AgentCheckpoint | None:
        if checkpoint is None:
            return None
        watermark = checkpoint.compacted_until_sequence
        compacted_state = checkpoint.compacted_state
        if (watermark is None) != (compacted_state is None):
            raise ValueError("Agent compaction watermark and state must be present together")
        if watermark is not None and watermark < 1:
            raise ValueError("Agent compaction watermark must be positive")
        prepared_compacted = sanitize_payload(compacted_state) if compacted_state is not None else None
        if prepared_compacted is not None:
            ensure_payload_size(prepared_compacted, max_bytes=_MAX_AGENT_CHECKPOINT_BYTES)
        prepared_validation = (
            sanitize_payload(checkpoint.last_validation) if checkpoint.last_validation is not None else None
        )
        if prepared_validation is not None:
            ensure_payload_size(prepared_validation, max_bytes=_MAX_AGENT_CHECKPOINT_BYTES)
        prepared_contract = RunCoordinator._prepare_contract_checkpoint(checkpoint.workflow_contract)
        return AgentCheckpoint(
            compacted_until_sequence=watermark,
            compacted_state=prepared_compacted,
            last_validation=prepared_validation,
            workflow_contract=prepared_contract,
        )

    @staticmethod
    def _prepare_contract_checkpoint(
        checkpoint: WorkflowContractCheckpoint | None,
    ) -> WorkflowContractCheckpoint | None:
        if checkpoint is None:
            return None
        if checkpoint.protocol_version != 1:
            raise ValueError("Workflow contract protocol version is unsupported")
        if checkpoint.revision < 1:
            raise ValueError("Workflow contract revision must be positive")
        if re.fullmatch(r"[0-9a-f]{64}", checkpoint.contract_hash) is None:
            raise ValueError("Workflow contract hash must be SHA256 hex")
        prepared = sanitize_payload(checkpoint.contract)
        ensure_payload_size(prepared, max_bytes=_MAX_AGENT_CHECKPOINT_BYTES)
        if (
            prepared.get("protocol_version") != checkpoint.protocol_version
            or prepared.get("revision") != checkpoint.revision
            or prepared.get("contract_hash") != checkpoint.contract_hash
        ):
            raise ValueError("Workflow contract checkpoint metadata does not match its body")
        return WorkflowContractCheckpoint(
            protocol_version=checkpoint.protocol_version,
            revision=checkpoint.revision,
            contract_hash=checkpoint.contract_hash,
            contract=cast(dict[str, object], prepared),
        )

    @classmethod
    def _prepare_agent_response(cls, response: AgentResponseOutbox | None) -> AgentResponseOutbox | None:
        if response is None:
            return None
        if response.sequence < 1:
            raise ValueError("Agent response sequence must be positive")
        prepared_payload = sanitize_payload(response.payload)
        ensure_payload_size(prepared_payload, max_bytes=_MAX_AGENT_RESPONSE_BYTES)
        return AgentResponseOutbox(
            sequence=response.sequence,
            payload=prepared_payload,
            checkpoint=cls._prepare_agent_checkpoint(response.checkpoint),
        )

    @staticmethod
    def _prepare_agent_history(
        history: Sequence[AgentMessage],
        *,
        response_sequence: int,
    ) -> tuple[AgentMessage, ...]:
        prepared: list[AgentMessage] = []
        previous_sequence = 0
        for message in history:
            if message.sequence < 1 or message.sequence >= response_sequence:
                raise ValueError("Agent history sequence must be positive and precede the response")
            if message.sequence <= previous_sequence:
                raise ValueError("Agent history sequences must be strictly increasing")
            if message.role not in {"user", "assistant"}:
                raise ValueError("Agent history role is invalid")
            if message.event_type not in {"message", "tool_call", "tool_result"}:
                raise ValueError("Agent history event type is invalid")
            if not message.status or len(message.status) > 32:
                raise ValueError("Agent history status is invalid")
            payload = sanitize_payload(message.payload)
            ensure_payload_size(payload, max_bytes=_MAX_AGENT_RESPONSE_BYTES)
            prepared.append(
                AgentMessage(
                    sequence=message.sequence,
                    role=message.role,
                    event_type=message.event_type,
                    status=message.status,
                    payload=payload,
                )
            )
            previous_sequence = message.sequence
        return tuple(prepared)

    @staticmethod
    def _checkpoint_payload(checkpoint: AgentCheckpoint | None) -> dict[str, Any] | None:
        if checkpoint is None:
            return None
        return {
            "compacted_until_sequence": checkpoint.compacted_until_sequence,
            "compacted_state": checkpoint.compacted_state,
            "last_validation": checkpoint.last_validation,
            "workflow_contract": (
                {
                    "protocol_version": checkpoint.workflow_contract.protocol_version,
                    "revision": checkpoint.workflow_contract.revision,
                    "contract_hash": checkpoint.workflow_contract.contract_hash,
                    "contract": checkpoint.workflow_contract.contract,
                }
                if checkpoint.workflow_contract is not None
                else None
            ),
        }

    @classmethod
    def _staged_response_payload(cls, response: AgentResponseOutbox, *, lease: RunLease) -> dict[str, Any]:
        payload = dict(response.payload)
        payload[AGENT_RESPONSE_OUTBOX_KEY] = {
            "run_id": lease.run_id,
            "epoch": lease.epoch,
            "worker_id": lease.worker_id,
            "checkpoint": cls._checkpoint_payload(response.checkpoint),
        }
        ensure_payload_size(payload, max_bytes=_MAX_AGENT_RESPONSE_BYTES)
        return payload

    def _find_agent_message(self, *, lease: RunLease, sequence: int) -> WorkflowAssistMessage | None:
        owner = lease.owner
        return self.session.scalar(
            select(WorkflowAssistMessage)
            .where(
                WorkflowAssistMessage.tenant_id == owner.tenant_id,
                WorkflowAssistMessage.app_id == owner.app_id,
                WorkflowAssistMessage.account_id == owner.account_id,
                WorkflowAssistMessage.conversation_id == owner.conversation_id,
                WorkflowAssistMessage.sequence == sequence,
            )
            .with_for_update()
        )

    @staticmethod
    def _reject_mismatched_history(*, existing: WorkflowAssistMessage, message: AgentMessage) -> None:
        if (
            existing.role != message.role
            or existing.event_type != message.event_type
            or existing.status != message.status
            or existing.retryable
            or existing.payload != message.payload
        ):
            raise WorkflowAssistConversationWriteConflictError("Durable Agent history replay payload mismatch")

    @classmethod
    def _reject_mismatched_response(
        cls,
        *,
        existing: WorkflowAssistMessage,
        response: AgentResponseOutbox,
        lease: RunLease,
    ) -> None:
        expected_payload = cls._staged_response_payload(response, lease=lease)
        completed_match = existing.status == "completed" and existing.payload == response.payload
        pending_match = existing.status == "pending" and existing.payload == expected_payload
        identity_matches = existing.role == "assistant" and existing.event_type == "message"
        if not identity_matches or not (completed_match or pending_match):
            raise WorkflowAssistConversationWriteConflictError("Durable Agent response replay payload mismatch")

    def _complete_agent_response(self, *, lease: RunLease, response: AgentResponseOutbox) -> None:
        existing = self._find_agent_message(lease=lease, sequence=response.sequence)
        if existing is None:
            raise WorkflowAssistConversationWriteConflictError("Durable Agent response outbox is missing")
        self._reject_mismatched_response(existing=existing, response=response, lease=lease)
        existing.payload = response.payload
        existing.status = "completed"

    def _persist_terminal_agent_response(
        self,
        *,
        lease: RunLease,
        conversation: WorkflowAssistConversation,
        run: WorkflowAssistRun,
        response: AgentResponseOutbox,
    ) -> None:
        existing = self._find_agent_message(lease=lease, sequence=response.sequence)
        if existing is not None:
            self._reject_mismatched_response(existing=existing, response=response, lease=lease)
            existing.payload = response.payload
            existing.status = "completed"
        else:
            latest_sequence = (
                self.session.scalar(
                    select(func.coalesce(func.max(WorkflowAssistMessage.sequence), 0)).where(
                        WorkflowAssistMessage.tenant_id == lease.owner.tenant_id,
                        WorkflowAssistMessage.app_id == lease.owner.app_id,
                        WorkflowAssistMessage.account_id == lease.owner.account_id,
                        WorkflowAssistMessage.conversation_id == conversation.id,
                    )
                )
                or 0
            )
            if response.sequence != latest_sequence + 1:
                raise WorkflowAssistConversationWriteConflictError("Durable Agent response sequence mismatch")
            self.session.add(
                WorkflowAssistMessage(
                    tenant_id=lease.owner.tenant_id,
                    app_id=lease.owner.app_id,
                    account_id=lease.owner.account_id,
                    conversation_id=lease.owner.conversation_id,
                    sequence=response.sequence,
                    role="assistant",
                    event_type="message",
                    status="completed",
                    retryable=False,
                    payload=response.payload,
                )
            )
        if response.checkpoint is not None:
            self._apply_agent_checkpoint(
                conversation=conversation,
                checkpoint=response.checkpoint,
                contract_protocol_version=run.contract_protocol_version,
            )

    @classmethod
    def _apply_agent_checkpoint(
        cls,
        *,
        conversation: WorkflowAssistConversation,
        checkpoint: AgentCheckpoint,
        contract_protocol_version: int | None,
    ) -> None:
        watermark = checkpoint.compacted_until_sequence
        current = conversation.compacted_until_sequence
        if watermark is not None and current is not None and watermark < current:
            raise ValueError("Agent compaction checkpoint cannot regress")
        if watermark is not None:
            conversation.compacted_until_sequence = watermark
            conversation.compacted_state = checkpoint.compacted_state
        state = sanitize_payload(conversation.state if isinstance(conversation.state, dict) else {})
        if checkpoint.last_validation is None:
            state.pop("last_validation", None)
        else:
            state["last_validation"] = checkpoint.last_validation
        ensure_payload_size(state, max_bytes=_MAX_AGENT_CHECKPOINT_BYTES)
        conversation.state = state
        contract = checkpoint.workflow_contract
        if contract is None:
            return
        if contract_protocol_version != contract.protocol_version:
            raise ValueError("Workflow contract protocol does not match the frozen Run")
        if conversation.contract_protocol_version != contract_protocol_version:
            raise ValueError("Conversation protocol changed during an active Run")
        current_revision = conversation.contract_revision or 0
        if contract.revision < current_revision:
            raise ValueError("Workflow contract revision cannot regress")
        if contract.revision == current_revision:
            hash_changed = conversation.contract_hash != contract.contract_hash
            body_changed = conversation.workflow_contract != contract.contract
            if hash_changed or body_changed:
                raise ValueError("Workflow contract revision replay does not match persisted state")
            return
        if contract.revision != current_revision + 1:
            raise ValueError("Workflow contract revision must advance by one")
        conversation.workflow_contract = contract.contract
        conversation.contract_revision = contract.revision
        conversation.contract_hash = contract.contract_hash
        cls._clear_completion_evidence(conversation)

    @staticmethod
    def _reject_mismatched_step_replay(
        *,
        existing: WorkflowAssistRunEvent,
        event: WorkflowAssistRunEventType,
        payload: dict[str, Any],
    ) -> None:
        if event not in {
            WorkflowAssistRunEventType.MESSAGE_DELTA,
            WorkflowAssistRunEventType.REASONING_DELTA,
            WorkflowAssistRunEventType.TOOL_CALL,
            WorkflowAssistRunEventType.TOOL_RESULT,
        }:
            return
        if existing.event != event or existing.payload != payload:
            raise WorkflowAssistConversationWriteConflictError("Durable run step replay payload mismatch")

    def _recover_duplicate_after_conflict(
        self,
        *,
        lease: RunLease,
        step_id: str,
        event: WorkflowAssistRunEventType,
        payload: dict[str, Any],
    ) -> CommitStepResult | None:
        """Re-read a same-step winner after a rolled-back unique-key race."""
        try:
            with self.session.begin_nested():
                locked = self._lock_for_worker_write(lease)
                if locked is None:
                    return None
                _conversation, run = locked
                duplicate = self._find_existing_step(lease=lease, step_id=step_id)
                if duplicate is None:
                    return None
                self._reject_mismatched_step_replay(existing=duplicate, event=event, payload=payload)
                return CommitStepResult(
                    outcome=CommitStepOutcome.DUPLICATE,
                    sequence=duplicate.sequence,
                    candidate_revision=run.candidate_revision,
                )
        except IntegrityError:
            return None

    def _lock_conversation(self, owner: RunOwner) -> WorkflowAssistConversation:
        conversation = self.session.scalar(
            select(WorkflowAssistConversation)
            .where(
                WorkflowAssistConversation.id == owner.conversation_id,
                WorkflowAssistConversation.tenant_id == owner.tenant_id,
                WorkflowAssistConversation.app_id == owner.app_id,
                WorkflowAssistConversation.account_id == owner.account_id,
                WorkflowAssistConversation.is_deleted.is_(False),
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if conversation is None:
            raise WorkflowAssistConversationNotFound()
        return conversation

    def _lock_current_conversation(
        self, owner: RunOwner, *, run_id: str, epoch: int
    ) -> WorkflowAssistConversation | None:
        return self.session.scalar(
            select(WorkflowAssistConversation)
            .where(
                WorkflowAssistConversation.id == owner.conversation_id,
                WorkflowAssistConversation.tenant_id == owner.tenant_id,
                WorkflowAssistConversation.app_id == owner.app_id,
                WorkflowAssistConversation.account_id == owner.account_id,
                WorkflowAssistConversation.is_deleted.is_(False),
                WorkflowAssistConversation.active_run_id == run_id,
                WorkflowAssistConversation.run_epoch == epoch,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )

    def _lock_run(
        self,
        owner: RunOwner,
        *,
        run_id: str,
        epoch: int,
        statuses: frozenset[WorkflowAssistRunStatus],
    ) -> WorkflowAssistRun | None:
        return self.session.scalar(
            select(WorkflowAssistRun)
            .where(
                *self._run_owner_predicates(owner),
                WorkflowAssistRun.id == run_id,
                WorkflowAssistRun.epoch == epoch,
                WorkflowAssistRun.status.in_(statuses),
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )

    def _find_existing_step(self, *, lease: RunLease, step_id: str) -> WorkflowAssistRunEvent | None:
        return self.session.scalar(
            select(WorkflowAssistRunEvent)
            .where(
                *self._event_owner_predicates(lease.owner),
                WorkflowAssistRunEvent.run_id == lease.run_id,
                WorkflowAssistRunEvent.epoch == lease.epoch,
                WorkflowAssistRunEvent.step_id == step_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )

    def _lock_for_worker_write(self, lease: RunLease) -> tuple[WorkflowAssistConversation, WorkflowAssistRun] | None:
        if lease.worker_id is None:
            return None
        conversation = self._lock_current_conversation(lease.owner, run_id=lease.run_id, epoch=lease.epoch)
        if conversation is None:
            return None
        run = self._lock_run(
            lease.owner,
            run_id=lease.run_id,
            epoch=lease.epoch,
            statuses=frozenset({WorkflowAssistRunStatus.RUNNING}),
        )
        if run is None or run.worker_id != lease.worker_id or run.attempt != lease.attempt:
            return None
        return conversation, run

    def _lock_for_control_write(
        self,
        fence: DispatchFailureFence | UserAbortFence | QueueTimeoutFence | WorkerTimeoutFence,
        *,
        statuses: frozenset[WorkflowAssistRunStatus],
    ) -> tuple[WorkflowAssistConversation, WorkflowAssistRun] | None:
        conversation = self._lock_current_conversation(fence.owner, run_id=fence.run_id, epoch=fence.epoch)
        if conversation is None:
            return None
        run = self._lock_run(
            fence.owner,
            run_id=fence.run_id,
            epoch=fence.epoch,
            statuses=statuses,
        )
        if run is None:
            return None
        return conversation, run

    @staticmethod
    def _timeout_observation_is_current(
        *,
        lease: RunLease | DispatchFailureFence | UserAbortFence | QueueTimeoutFence | WorkerTimeoutFence,
        run: WorkflowAssistRun,
    ) -> bool:
        now = naive_utc_now()
        if isinstance(lease, QueueTimeoutFence):
            return lease.observed_queued_at <= lease.cutoff <= now and run.queued_at == lease.observed_queued_at
        if isinstance(lease, WorkerTimeoutFence):
            return (
                run.heartbeat_at is not None
                and lease.observed_heartbeat_at <= lease.cutoff <= now
                and run.heartbeat_at <= lease.observed_heartbeat_at
            )
        return True

    def _append_user_turn(
        self,
        *,
        conversation: WorkflowAssistConversation,
        message: str,
        references: list[dict[str, Any]] | None = None,
    ) -> None:
        latest = self.session.scalar(
            select(WorkflowAssistMessage)
            .where(
                WorkflowAssistMessage.tenant_id == conversation.tenant_id,
                WorkflowAssistMessage.app_id == conversation.app_id,
                WorkflowAssistMessage.account_id == conversation.account_id,
                WorkflowAssistMessage.conversation_id == conversation.id,
            )
            .order_by(WorkflowAssistMessage.sequence.desc())
            .limit(1)
        )
        if (
            isinstance(latest, WorkflowAssistMessage)
            and latest.event_type == "tool_call"
            and latest.status == "pending"
            and latest.payload.get("name") == "ask_user"
            and isinstance(latest.payload.get("id"), str)
            and latest.payload["id"]
        ):
            latest.status = "completed"
            self.session.add(
                WorkflowAssistMessage(
                    tenant_id=conversation.tenant_id,
                    app_id=conversation.app_id,
                    account_id=conversation.account_id,
                    conversation_id=conversation.id,
                    sequence=latest.sequence + 1,
                    role="assistant",
                    event_type="tool_result",
                    payload={
                        "tool_call_id": latest.payload["id"],
                        "name": "ask_user",
                        "content": message,
                    },
                )
            )
            return

        sequence = latest.sequence + 1 if isinstance(latest, WorkflowAssistMessage) else 1
        self.session.add(
            WorkflowAssistMessage(
                tenant_id=conversation.tenant_id,
                app_id=conversation.app_id,
                account_id=conversation.account_id,
                conversation_id=conversation.id,
                sequence=sequence,
                role="user",
                event_type="message",
                payload={"text": message, **({"references": list(references)} if references else {})},
            )
        )

    def _append_run_step(
        self,
        *,
        run: WorkflowAssistRun,
        step_id: str,
        event: WorkflowAssistRunEventType,
        payload: dict[str, Any],
    ) -> WorkflowAssistRunEvent:
        run_event = WorkflowAssistRunEvent(
            tenant_id=run.tenant_id,
            app_id=run.app_id,
            created_by=run.created_by,
            conversation_id=run.conversation_id,
            run_id=run.id,
            epoch=run.epoch,
            sequence=run.next_event_sequence,
            step_id=step_id,
            event=event,
            payload=payload,
        )
        self.session.add(run_event)
        run.next_event_sequence += 1
        return run_event

    def _finish_locked_run(
        self,
        *,
        conversation: WorkflowAssistConversation,
        run: WorkflowAssistRun,
        status: WorkflowAssistRunStatus,
        step_id: str,
        payload: dict[str, Any],
        reason: str | None,
    ) -> None:
        now = naive_utc_now()
        self._abandon_pending_agent_responses(conversation=conversation, run=run, reason=reason)
        self._append_run_step(
            run=run,
            step_id=step_id,
            event=WorkflowAssistRunEventType(status.value),
            payload=payload,
        )
        run.status = status
        run.finished_at = now
        run.termination_reason = reason
        conversation.last_run_termination_reason = reason
        if conversation.active_run_id == run.id:
            conversation.active_run_id = None
        conversation.updated_at = now

    def _abandon_pending_agent_responses(
        self,
        *,
        conversation: WorkflowAssistConversation,
        run: WorkflowAssistRun | None = None,
        reason: str | None = None,
    ) -> None:
        pending = self.session.scalars(
            select(WorkflowAssistMessage)
            .where(
                WorkflowAssistMessage.tenant_id == conversation.tenant_id,
                WorkflowAssistMessage.app_id == conversation.app_id,
                WorkflowAssistMessage.account_id == conversation.account_id,
                WorkflowAssistMessage.conversation_id == conversation.id,
                WorkflowAssistMessage.role == "assistant",
                WorkflowAssistMessage.event_type == "message",
                WorkflowAssistMessage.status == "pending",
            )
            .with_for_update()
        ).all()
        changed = False
        for message in pending:
            if run is not None and not self._pending_response_belongs_to_run(message=message, run=run):
                continue
            if reason == "superseded_by_new_turn" or not self._pending_response_has_visible_text(message):
                self.session.delete(message)
                changed = True
                continue
            payload = dict(message.payload) if isinstance(message.payload, dict) else {}
            payload.pop(AGENT_RESPONSE_OUTBOX_KEY, None)
            message.payload = payload
            message.status = "partial"
            message.retryable = reason != "user_abort"
            changed = True
        if changed:
            self.session.flush()

    @staticmethod
    def _pending_response_has_visible_text(message: WorkflowAssistMessage) -> bool:
        payload = message.payload
        if not isinstance(payload, dict):
            return False
        text = payload.get("text")
        reasoning = payload.get("reasoning")
        return (isinstance(text, str) and bool(text.strip())) or (
            isinstance(reasoning, str) and bool(reasoning.strip())
        )

    @staticmethod
    def _pending_response_belongs_to_run(*, message: WorkflowAssistMessage, run: WorkflowAssistRun) -> bool:
        payload = message.payload
        if not isinstance(payload, dict):
            return False
        owner = payload.get(AGENT_RESPONSE_OUTBOX_KEY)
        return (
            isinstance(owner, dict)
            and owner.get("run_id") == run.id
            and owner.get("epoch") == run.epoch
            and owner.get("worker_id") == run.worker_id
        )

    @staticmethod
    def _clear_completion_evidence(conversation: WorkflowAssistConversation) -> None:
        conversation.completion_run_id = None
        conversation.completion_epoch = None
        conversation.completion_candidate_revision = None
        conversation.completion_candidate_base_hash = None
        conversation.completion_app_mode = None
        conversation.completion_assertion = None
        conversation.completion_contract_protocol_version = None
        conversation.completion_contract_revision = None
        conversation.completion_contract_hash = None
        conversation.completion_graph_hash = None
        conversation.completion_validation_version = None

    def _candidate_is_complete(
        self,
        *,
        owner: RunOwner,
        conversation: WorkflowAssistConversation,
        run: WorkflowAssistRun,
    ) -> bool:
        graph = conversation.candidate_graph
        if not isinstance(graph, dict) or not conversation.candidate_base_hash:
            return False
        if run.candidate_revision != conversation.candidate_revision:
            return False
        try:
            mode = WorkflowAssistMode(run.mode)
        except (TypeError, ValueError):
            return False
        return self._completion_policy.candidate_is_complete(
            owner=owner,
            graph=graph,
            mode=mode,
            contract_protocol_version=run.contract_protocol_version,
            contract=conversation.workflow_contract,
            candidate_base_hash=conversation.candidate_base_hash,
        )

    @staticmethod
    def _write_completion_evidence(*, conversation: WorkflowAssistConversation, run: WorkflowAssistRun) -> None:
        conversation.completion_run_id = run.id
        conversation.completion_epoch = run.epoch
        conversation.completion_candidate_revision = conversation.candidate_revision
        conversation.completion_candidate_base_hash = conversation.candidate_base_hash
        conversation.completion_app_mode = run.mode
        conversation.completion_assertion = WorkflowAssistCompletionAssertion.WORKFLOW_STRUCTURE_REACHES_TERMINAL
        conversation.completion_contract_protocol_version = run.contract_protocol_version
        conversation.completion_contract_revision = conversation.contract_revision
        conversation.completion_contract_hash = conversation.contract_hash
        graph = conversation.candidate_graph
        conversation.completion_graph_hash = canonical_graph_hash(graph) if isinstance(graph, dict) else None
        conversation.completion_validation_version = WORKFLOW_RECONCILIATION_VERSION

    def _prepare_step_payload(
        self,
        *,
        event: WorkflowAssistRunEventType,
        payload: dict[str, Any],
        candidate: CandidateMutation | None,
    ) -> dict[str, Any]:
        prepared_payload = self._prepare_event_payload(payload)
        self._reject_graph_payload(prepared_payload)
        is_candidate_event = event is WorkflowAssistRunEventType.CANDIDATE_UPDATED
        if is_candidate_event != (candidate is not None):
            raise ValueError("candidate.updated requires exactly one candidate mutation")
        if is_candidate_event:
            if set(prepared_payload) != {"diff"} or not isinstance(prepared_payload["diff"], dict):
                raise ValueError("candidate.updated payload must contain only a diff summary")
            diff = prepared_payload["diff"]
            if not set(diff).issubset({"added", "removed", "changed"}) or any(
                not isinstance(items, list) or not all(isinstance(item, str) for item in items)
                for items in diff.values()
            ):
                raise ValueError("candidate.updated diff must contain only node id lists")
        if event in {WorkflowAssistRunEventType.TOOL_CALL, WorkflowAssistRunEventType.TOOL_RESULT}:
            tool_call_id = prepared_payload.get("tool_call_id")
            if not isinstance(tool_call_id, str) or not tool_call_id.strip():
                raise ValueError(f"{event.value} requires a non-empty tool_call_id")
            prepared_payload["tool_call_id"] = tool_call_id.strip()
            prepared_payload = self._prepare_event_payload(prepared_payload)
        return prepared_payload

    def _prepare_terminal_payload(self, *, status: WorkflowAssistRunStatus, payload: dict[str, Any]) -> dict[str, Any]:
        prepared_payload = self._prepare_event_payload(payload)
        self._reject_graph_payload(prepared_payload)
        payload_status = prepared_payload.get("status")
        if payload_status is not None and payload_status != status.value:
            raise ValueError("terminal payload status does not match run status")
        prepared_payload["status"] = status.value
        return self._prepare_event_payload(prepared_payload)

    def _prepare_event_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return prepare_run_event_payload(payload, dialect=self.session.get_bind().dialect)

    @classmethod
    def _reject_graph_payload(cls, value: object) -> None:
        if isinstance(value, dict):
            normalized_keys = {str(key).lower().replace("-", "_") for key in value}
            if {"nodes", "edges"}.issubset(normalized_keys):
                raise ValueError("run events must not contain a graph structure")
            for key, item in value.items():
                normalized_key = str(key).lower().replace("-", "_")
                if normalized_key in {"graph", "candidate_graph", "candidategraph", "current_graph", "currentgraph"}:
                    raise ValueError("run events must not contain a graph")
                cls._reject_graph_payload(item)
        elif isinstance(value, list | tuple):
            for item in value:
                cls._reject_graph_payload(item)

    @staticmethod
    def _normalize_mode(mode: WorkflowAssistMode | str) -> WorkflowAssistMode:
        try:
            return WorkflowAssistMode(mode)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported Workflow Assist mode") from exc

    @staticmethod
    def _normalize_event(event: WorkflowAssistRunEventType | str) -> WorkflowAssistRunEventType:
        try:
            return WorkflowAssistRunEventType(event)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported Workflow Assist run event") from exc

    @staticmethod
    def _normalize_status(status: WorkflowAssistRunStatus | str) -> WorkflowAssistRunStatus:
        try:
            return WorkflowAssistRunStatus(status)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported Workflow Assist run status") from exc

    @staticmethod
    def _validate_terminal_authority(
        *,
        lease: RunLease | DispatchFailureFence | UserAbortFence | QueueTimeoutFence | WorkerTimeoutFence,
        status: WorkflowAssistRunStatus,
        reason: str | None,
    ) -> frozenset[WorkflowAssistRunStatus] | None:
        if isinstance(lease, UserAbortFence):
            if (status, reason) != (WorkflowAssistRunStatus.ABORTED, "user_abort"):
                raise ValueError("user-abort control fence requires aborted/user_abort")
            return WORKFLOW_ASSIST_RUN_ACTIVE_STATUSES
        if isinstance(lease, DispatchFailureFence):
            if (status, reason) != (WorkflowAssistRunStatus.ERROR, "dispatch_failed"):
                raise ValueError("dispatch-failure control fence requires error/dispatch_failed")
            return frozenset({WorkflowAssistRunStatus.QUEUED})
        if isinstance(lease, QueueTimeoutFence):
            if (status, reason) != (WorkflowAssistRunStatus.ERROR, "queue_timeout"):
                raise ValueError("queue-timeout control fence requires error/queue_timeout")
            return frozenset({WorkflowAssistRunStatus.QUEUED})
        if isinstance(lease, WorkerTimeoutFence):
            if (status, reason) != (WorkflowAssistRunStatus.ERROR, "worker_lost"):
                raise ValueError("worker-timeout control fence requires error/worker_lost")
            return frozenset({WorkflowAssistRunStatus.RUNNING})
        if not isinstance(lease, RunLease):
            raise ValueError("terminate requires a worker lease or typed control fence")
        if reason in _RESERVED_CONTROL_REASONS:
            raise ValueError("reserved control terminal reason requires a control fence")
        return None

    @staticmethod
    def _is_retryable_failed_step(event: WorkflowAssistRunEvent) -> bool:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if event.event in {WorkflowAssistRunEventType.FAILED, WorkflowAssistRunEventType.ERROR}:
            if payload.get("reason") == "user_abort":
                return False
            return payload.get("retryable") is not False
        if event.event is WorkflowAssistRunEventType.TOOL_RESULT:
            return payload.get("ok") is False and payload.get("retryable") is True
        return False

    def _drop_incomplete_tool_json_messages(self, conversation: WorkflowAssistConversation) -> None:
        rows = list(
            self.session.scalars(
                select(WorkflowAssistMessage)
                .where(
                    WorkflowAssistMessage.tenant_id == conversation.tenant_id,
                    WorkflowAssistMessage.app_id == conversation.app_id,
                    WorkflowAssistMessage.account_id == conversation.account_id,
                    WorkflowAssistMessage.conversation_id == conversation.id,
                )
                .order_by(WorkflowAssistMessage.sequence)
                .with_for_update()
            )
        )
        completed_tool_call_ids: set[str] = set()
        for message in rows:
            payload = message.payload if isinstance(message.payload, dict) else {}
            tool_call_id = payload.get("tool_call_id")
            if (
                message.event_type == "tool_result"
                and message.status == "completed"
                and isinstance(tool_call_id, str)
                and tool_call_id
            ):
                completed_tool_call_ids.add(tool_call_id)
        changed = False
        for message in rows:
            if message.event_type != "tool_call":
                continue
            payload = message.payload if isinstance(message.payload, dict) else {}
            call_id = payload.get("id")
            if payload.get("name") == "ask_user" and message.status == "pending":
                continue
            if not isinstance(call_id, str) or call_id not in completed_tool_call_ids:
                self.session.delete(message)
                changed = True
        if changed:
            self.session.flush()

    @classmethod
    def _validate_step_id(cls, step_id: str) -> str:
        return cls._normalize_required_text(step_id, field_name="step_id", max_length=255)

    @staticmethod
    def _normalize_required_text(value: str, *, field_name: str, max_length: int) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be text")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must be non-empty")
        if len(normalized) > max_length:
            raise ValueError(f"{field_name} must not exceed {max_length} characters")
        return normalized

    @classmethod
    def _normalize_optional_text(cls, value: str | None, *, field_name: str, max_length: int) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be text")
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > max_length:
            raise ValueError(f"{field_name} must not exceed {max_length} characters")
        return normalized

    @staticmethod
    def _write_conflict() -> WorkflowAssistConversationWriteConflictError:
        return WorkflowAssistConversationWriteConflictError(
            "Concurrent Workflow Assist run write could not be serialized"
        )

    @staticmethod
    def _run_owner_predicates(owner: RunOwner) -> tuple[ColumnElement[bool], ...]:
        return (
            WorkflowAssistRun.tenant_id == owner.tenant_id,
            WorkflowAssistRun.app_id == owner.app_id,
            WorkflowAssistRun.created_by == owner.account_id,
            WorkflowAssistRun.conversation_id == owner.conversation_id,
        )

    @staticmethod
    def _event_owner_predicates(owner: RunOwner) -> tuple[ColumnElement[bool], ...]:
        return (
            WorkflowAssistRunEvent.tenant_id == owner.tenant_id,
            WorkflowAssistRunEvent.app_id == owner.app_id,
            WorkflowAssistRunEvent.created_by == owner.account_id,
            WorkflowAssistRunEvent.conversation_id == owner.conversation_id,
        )
