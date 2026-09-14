"""RunCoordinator state-machine tests.

These tests use real SQLAlchemy sessions and rows. SQLite does not enforce
``SELECT FOR UPDATE`` or reproduce PostgreSQL writer interleavings, so the
atomic-supersede test verifies the complete transactional state transition and
the lock test separately verifies that the coordinator emits the row lock.
Owner, epoch, status, and worker-lease predicates are exercised through public
operations so a missing fence produces an observable unauthorized write.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from core.workflow.generator.acceptance.evidence import canonical_graph_hash
from core.workflow.generator.agent.types import AgentMessage
from core.workflow.generator.contracts.workflow_contract import canonical_workflow_contract_hash
from core.workflow.generator.contracts.workflow_reconciliation import WORKFLOW_RECONCILIATION_VERSION
from libs.datetime_utils import naive_utc_now
from models.agent import Agent, AgentConfigSnapshot, AgentScope, AgentSource, AgentStatus
from models.agent_config_entities import AgentSoulConfig
from models.workflow import Workflow, WorkflowType
from models.workflow_assist import (
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistMode,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
    WorkflowAssistRunEventType,
    WorkflowAssistRunStatus,
)
from services.workflow_assist.conversations import (
    WorkflowAssistConversationService,
    WorkflowAssistConversationWriteConflictError,
)
from services.workflow_assist.run_coordinator import RunCoordinator
from services.workflow_assist.run_types import (
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

TABLES = (
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
    Workflow,
    Agent,
    AgentConfigSnapshot,
)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_live_approval_is_bound_to_pending_graph_and_consumed_once(sqlite_session: Session) -> None:
    from dataclasses import replace

    from core.workflow.generator.acceptance.authorization import build_live_acceptance_request
    from services.workflow_assist.run_values import sanitize_payload

    conversation = _create_conversation(sqlite_session)
    graph = {"nodes": [{"id": "llm", "data": {"type": "llm"}}], "edges": []}
    conversation.candidate_graph = graph
    conversation.candidate_revision = 2
    request = build_live_acceptance_request(graph, revision=2)
    payload = sanitize_payload(
        {
            "id": "consent-1",
            "name": "ask_user",
            "arguments": {
                "questions": [
                    {
                        "id": "live_run_consent",
                        "kind": "live_acceptance",
                        "execution_request": request.model_dump(mode="json"),
                    }
                ]
            },
        }
    )
    sqlite_session.add(
        WorkflowAssistMessage(
            tenant_id=conversation.tenant_id,
            app_id=conversation.app_id,
            account_id=conversation.account_id,
            conversation_id=conversation.id,
            sequence=1,
            event_type="tool_call",
            role="assistant",
            status="pending",
            payload=payload,
        )
    )
    sqlite_session.flush()
    coordinator = RunCoordinator(sqlite_session)
    with pytest.raises(ValueError, match="stale"):
        coordinator.start_turn(
            owner=_owner(), message="approve", mode="workflow", model_config={}, live_acceptance_request_id="0" * 32
        )
    run = coordinator.start_turn(
        owner=_owner(),
        message="approve",
        mode="workflow",
        model_config={},
        live_acceptance_request_id=request.request_id,
    )
    lease = coordinator.claim(owner=_owner(), run_id=run.id, epoch=run.epoch, worker_id="worker-1")
    assert lease is not None
    assert not coordinator.consume_live_acceptance(lease=lease, revision=3, graph_hash=request.graph_hash)
    assert not coordinator.consume_live_acceptance(lease=lease, revision=2, graph_hash="f" * 64)
    assert not coordinator.consume_live_acceptance(
        lease=replace(lease, worker_id="other"), revision=2, graph_hash=request.graph_hash
    )
    assert coordinator.consume_live_acceptance(lease=lease, revision=2, graph_hash=request.graph_hash)
    assert not coordinator.consume_live_acceptance(lease=lease, revision=2, graph_hash=request.graph_hash)
    _terminate_error(coordinator, lease)
    retried = coordinator.retry_failed_step(
        owner=_owner(), run_id=run.id, epoch=run.epoch, failed_step_id="error:provider"
    )
    assert retried.live_acceptance is None
    with pytest.raises(ValueError, match="No pending"):
        coordinator.start_turn(
            owner=_owner(),
            message="approve again",
            mode="workflow",
            model_config={},
            live_acceptance_request_id=request.request_id,
        )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_ordinary_turn_never_receives_a_live_grant(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    run, _ = _start_and_claim(sqlite_session)
    assert run.live_acceptance is None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_terminal_response_persists_its_checkpoint(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    _run, lease = _start_and_claim(sqlite_session)
    response = AgentResponseOutbox(
        sequence=2,
        payload={"text": "Need confirmation"},
        checkpoint=AgentCheckpoint(
            compacted_until_sequence=1, compacted_state={"summary": "ready"}, last_validation=None
        ),
    )
    assert coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.TURN_COMPLETE,
        step_id="turn:complete",
        payload={"status": "turn_complete"},
        response_outbox=response,
    )
    assert conversation.compacted_until_sequence == 1
    assert conversation.compacted_state == {"summary": "ready"}


def _owner(*, account_id: str = "account-1") -> RunOwner:
    return RunOwner(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id=account_id,
        conversation_id="conversation-1",
    )


def _create_conversation(session: Session, *, account_id: str = "account-1") -> WorkflowAssistConversation:
    conversation = WorkflowAssistConversationService(session).create(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id=account_id,
    )
    conversation.id = "conversation-1"
    conversation.contract_protocol_version = None
    session.flush()
    return conversation


def _start_and_claim(
    session: Session,
    *,
    worker_id: str = "worker-1",
    mode: WorkflowAssistMode = WorkflowAssistMode.WORKFLOW,
) -> tuple[WorkflowAssistRun, RunLease]:
    coordinator = RunCoordinator(session)
    run = coordinator.start_turn(
        owner=_owner(),
        message="Build a support workflow",
        mode=mode,
        model_config={"provider": "test"},
    )
    lease = coordinator.claim(owner=_owner(), run_id=run.id, epoch=run.epoch, worker_id=worker_id)
    assert lease is not None
    assert lease.attempt == 1
    return run, lease


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_start_turn_freezes_contract_protocol_on_the_run(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "services.workflow_assist.run_coordinator.dify_config.WORKFLOW_ASSIST_CONTRACT_ROLLOUT",
        "new_conversations",
    )
    conversation = _create_conversation(sqlite_session)
    conversation.contract_protocol_version = 1
    sqlite_session.flush()

    run = RunCoordinator(sqlite_session).start_turn(
        owner=_owner(),
        message="Build it",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={"provider": "test"},
    )
    conversation.contract_protocol_version = None
    sqlite_session.flush()

    assert run.contract_protocol_version == 1
    assert run.contract_rollout_stage == "new_conversations"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_message_sequences_ignore_foreign_owner_rows_with_the_same_conversation_id(
    sqlite_session: Session,
) -> None:
    conversation = _create_conversation(sqlite_session)
    sqlite_session.add(
        WorkflowAssistMessage(
            tenant_id="tenant-foreign",
            app_id="app-foreign",
            account_id="account-foreign",
            conversation_id=conversation.id,
            sequence=999,
            role="assistant",
            event_type="message",
            payload={"text": "foreign corrupt row"},
        )
    )
    sqlite_session.flush()
    coordinator = RunCoordinator(sqlite_session)

    run = coordinator.start_turn(
        owner=_owner(),
        message="Build a support workflow",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={"provider": "test"},
    )
    lease = coordinator.claim(owner=_owner(), run_id=run.id, epoch=run.epoch, worker_id="worker-1")
    assert lease is not None
    response = AgentResponseOutbox(sequence=2, payload={"text": "owner response"}, checkpoint=None)

    assert coordinator.stage_agent_response(lease=lease, response=response) is CommitStepOutcome.COMMITTED
    owner_sequences = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage.sequence)
            .where(
                WorkflowAssistMessage.tenant_id == "tenant-1",
                WorkflowAssistMessage.app_id == "app-1",
                WorkflowAssistMessage.account_id == "account-1",
                WorkflowAssistMessage.conversation_id == conversation.id,
            )
            .order_by(WorkflowAssistMessage.sequence)
        )
    )
    assert owner_sequences == [1, 2]


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_stage_agent_response_with_history_rejects_a_stale_worker_without_writes(
    sqlite_session: Session,
) -> None:
    _create_conversation(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    run.attempt = 2
    sqlite_session.flush()
    history = (
        AgentMessage(
            sequence=2,
            role="assistant",
            event_type="message",
            status="completed",
            payload={"text": "earlier", "message_id": "msg-earlier"},
        ),
    )
    response = AgentResponseOutbox(
        sequence=3,
        payload={"text": "retry", "message_id": "msg-retry"},
        checkpoint=None,
    )

    outcome = RunCoordinator(sqlite_session).stage_agent_response(
        lease=lease,
        history=history,
        response=response,
    )

    assert outcome is CommitStepOutcome.FENCED
    assert _assistant_messages(sqlite_session) == []


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_stage_agent_response_rolls_back_history_when_response_sequence_is_invalid(
    sqlite_session: Session,
) -> None:
    _create_conversation(sqlite_session)
    _run, lease = _start_and_claim(sqlite_session)
    history = (
        AgentMessage(
            sequence=2,
            role="assistant",
            event_type="message",
            status="completed",
            payload={"text": "earlier", "message_id": "msg-earlier"},
        ),
    )
    response = AgentResponseOutbox(
        sequence=4,
        payload={"text": "retry", "message_id": "msg-retry"},
        checkpoint=None,
    )

    with pytest.raises(WorkflowAssistConversationWriteConflictError, match="sequence mismatch"):
        RunCoordinator(sqlite_session).stage_agent_response(
            lease=lease,
            history=history,
            response=response,
        )

    assert _assistant_messages(sqlite_session) == []


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_stage_agent_response_with_history_is_idempotent_on_replay(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    _run, lease = _start_and_claim(sqlite_session)
    history = (
        AgentMessage(
            sequence=2,
            role="assistant",
            event_type="message",
            status="completed",
            payload={"text": "earlier", "message_id": "msg-earlier"},
        ),
    )
    response = AgentResponseOutbox(
        sequence=3,
        payload={"text": "retry", "message_id": "msg-retry"},
        checkpoint=None,
    )
    coordinator = RunCoordinator(sqlite_session)

    first = coordinator.stage_agent_response(lease=lease, history=history, response=response)
    replay = coordinator.stage_agent_response(lease=lease, history=history, response=response)

    assert first is CommitStepOutcome.COMMITTED
    assert replay is CommitStepOutcome.DUPLICATE
    assert [(message.sequence, message.status) for message in _assistant_messages(sqlite_session)] == [
        (2, "completed"),
        (3, "pending"),
    ]


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_start_turn_abandons_only_pending_response_outboxes(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    _run, lease = _start_and_claim(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    completed = AgentResponseOutbox(sequence=2, payload={"text": "durable history"}, checkpoint=None)
    assert coordinator.stage_agent_response(lease=lease, response=completed) is CommitStepOutcome.COMMITTED
    result = coordinator.commit_step(
        lease=lease,
        step_id="message:2:0",
        event=WorkflowAssistRunEventType.MESSAGE_DELTA,
        payload={"delta": "durable history"},
        response_outbox=completed,
    )
    assert result.outcome is CommitStepOutcome.COMMITTED
    pending = AgentResponseOutbox(sequence=3, payload={"text": "abandoned response"}, checkpoint=None)
    assert coordinator.stage_agent_response(lease=lease, response=pending) is CommitStepOutcome.COMMITTED

    coordinator.start_turn(
        owner=_owner(),
        message="Start cleanly",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={"provider": "test"},
    )

    messages = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage)
            .where(WorkflowAssistMessage.conversation_id == "conversation-1")
            .order_by(WorkflowAssistMessage.sequence)
        )
    )
    assert [(message.sequence, message.status, message.payload) for message in messages] == [
        (1, "completed", {"text": "Build a support workflow"}),
        (2, "completed", {"text": "durable history"}),
        (3, "completed", {"text": "Start cleanly"}),
    ]


def _stage_pending_response(coordinator: RunCoordinator, lease: RunLease, *, text: str, sequence: int = 2) -> None:
    pending = AgentResponseOutbox(sequence=sequence, payload={"text": text}, checkpoint=None)
    assert coordinator.stage_agent_response(lease=lease, response=pending) is CommitStepOutcome.COMMITTED


def _assistant_messages(session: Session) -> list[WorkflowAssistMessage]:
    return list(
        session.scalars(
            select(WorkflowAssistMessage)
            .where(
                WorkflowAssistMessage.conversation_id == "conversation-1",
                WorkflowAssistMessage.role == "assistant",
                WorkflowAssistMessage.event_type == "message",
            )
            .order_by(WorkflowAssistMessage.sequence)
        )
    )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_abandon_empty_pending_response_is_deleted(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    _stage_pending_response(coordinator, lease, text="   ")
    assert coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.ERROR,
        step_id="terminal-empty",
        payload={},
        reason="provider_error",
    )
    assert _assistant_messages(sqlite_session) == []


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_abandon_superseded_pending_response_is_deleted(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    _run, lease = _start_and_claim(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    _stage_pending_response(coordinator, lease, text="正在创建")
    coordinator.start_turn(
        owner=_owner(),
        message="Start cleanly",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={"provider": "test"},
    )
    assert [message.payload.get("text") for message in _assistant_messages(sqlite_session)] == []


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_abandon_user_abort_keeps_visible_text_as_partial_not_retryable(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    _stage_pending_response(coordinator, lease, text="正在创建")
    assert coordinator.terminate(
        lease=UserAbortFence(owner=_owner(), run_id=run.id, epoch=run.epoch),
        status=WorkflowAssistRunStatus.ABORTED,
        step_id="terminal:user-abort",
        payload={"status": "aborted", "reason": "user_abort"},
        reason="user_abort",
    )
    messages = _assistant_messages(sqlite_session)
    assert len(messages) == 1
    assert messages[0].status == "partial"
    assert messages[0].retryable is False
    assert messages[0].payload["text"] == "正在创建"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_abandon_provider_error_keeps_visible_text_as_partial_retryable(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    _run, lease = _start_and_claim(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    _stage_pending_response(coordinator, lease, text="正在创建")
    assert coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.ERROR,
        step_id="terminal-provider",
        payload={},
        reason="provider_error",
    )
    messages = _assistant_messages(sqlite_session)
    assert len(messages) == 1
    assert messages[0].status == "partial"
    assert messages[0].retryable is True
    assert messages[0].payload["text"] == "正在创建"


def _commit_candidate(
    coordinator: RunCoordinator,
    lease: RunLease,
    *,
    base_hash: str = "draft-1",
    mode: WorkflowAssistMode = WorkflowAssistMode.WORKFLOW,
    graph: dict[str, Any] | None = None,
) -> None:
    terminal_type = "end" if mode is WorkflowAssistMode.WORKFLOW else "answer"
    candidate_graph = graph or {
        "nodes": [
            {"id": "start", "data": {"type": "start"}},
            {"id": "terminal", "data": {"type": terminal_type}},
        ],
        "edges": [{"source": "start", "target": "terminal"}],
    }
    result = coordinator.commit_step(
        lease=lease,
        step_id="candidate-1",
        event=WorkflowAssistRunEventType.CANDIDATE_UPDATED,
        payload={"diff": {"added": ["terminal"], "removed": [], "changed": []}},
        candidate=CandidateMutation(
            graph=candidate_graph,
            base_hash=base_hash,
        ),
    )
    assert result.outcome is CommitStepOutcome.COMMITTED


def _agent_candidate_graph(*, binding: dict[str, str], connect_agent: bool = True) -> dict[str, Any]:
    edges = (
        [
            {"source": "start", "target": "agent"},
            {"source": "agent", "target": "terminal"},
        ]
        if connect_agent
        else [{"source": "start", "target": "terminal"}]
    )
    return {
        "nodes": [
            {"id": "start", "data": {"type": "start"}},
            {
                "id": "agent",
                "data": {
                    "type": "agent",
                    "version": "2",
                    "agent_node_kind": "dify_agent",
                    "agent_task": "Resolve the request",
                    "agent_binding": binding,
                },
            },
            {"id": "terminal", "data": {"type": "end"}},
        ],
        "edges": edges,
    }


def _create_draft_workflow(session: Session) -> Workflow:
    workflow = Workflow(
        id="workflow-1",
        tenant_id="tenant-1",
        app_id="app-1",
        type=WorkflowType.WORKFLOW,
        version=Workflow.VERSION_DRAFT,
        graph="{}",
        _features="{}",
        created_by="account-1",
        _environment_variables="[]",
        _conversation_variables="[]",
        _rag_pipeline_variables="[]",
    )
    session.add(workflow)
    session.flush()
    return workflow


def _create_inline_agent_records(
    session: Session,
    *,
    agent_id: str = "agent-1",
    snapshot_id: str = "snapshot-1",
    agent_tenant_id: str = "tenant-1",
    agent_app_id: str = "app-1",
    agent_workflow_id: str = "workflow-1",
    agent_node_id: str = "agent",
    agent_created_by: str = "account-1",
    snapshot_tenant_id: str | None = None,
    snapshot_agent_id: str | None = None,
    snapshot_created_by: str = "account-1",
) -> None:
    agent = Agent(
        id=agent_id,
        tenant_id=agent_tenant_id,
        name="Workflow Agent",
        scope=AgentScope.WORKFLOW_ONLY,
        source=AgentSource.WORKFLOW,
        app_id=agent_app_id,
        workflow_id=agent_workflow_id,
        workflow_node_id=agent_node_id,
        active_config_snapshot_id=snapshot_id,
        status=AgentStatus.ACTIVE,
        created_by=agent_created_by,
    )
    snapshot = AgentConfigSnapshot(
        id=snapshot_id,
        tenant_id=snapshot_tenant_id or agent_tenant_id,
        agent_id=snapshot_agent_id or agent_id,
        version=1,
        config_snapshot=AgentSoulConfig(),
        created_by=snapshot_created_by,
    )
    session.add_all([agent, snapshot])
    session.flush()


def _control_fence(
    run: WorkflowAssistRun, *, reason: str
) -> DispatchFailureFence | UserAbortFence | QueueTimeoutFence | WorkerTimeoutFence:
    if reason == "user_abort":
        return UserAbortFence(owner=_owner(), run_id=run.id, epoch=run.epoch)
    if reason == "dispatch_failed":
        return DispatchFailureFence(owner=_owner(), run_id=run.id, epoch=run.epoch)
    if reason == "queue_timeout":
        return QueueTimeoutFence(
            owner=_owner(),
            run_id=run.id,
            epoch=run.epoch,
            cutoff=run.queued_at,
            observed_queued_at=run.queued_at,
        )
    assert reason == "worker_lost"
    assert run.heartbeat_at is not None
    return WorkerTimeoutFence(
        owner=_owner(),
        run_id=run.id,
        epoch=run.epoch,
        cutoff=run.heartbeat_at,
        observed_heartbeat_at=run.heartbeat_at,
    )


def _assert_done_rejected_without_side_effects(
    session: Session,
    *,
    conversation: WorkflowAssistConversation,
    run: WorkflowAssistRun,
    sequence: int,
    step_id: str,
) -> None:
    assert run.status is WorkflowAssistRunStatus.RUNNING
    assert run.next_event_sequence == sequence
    assert conversation.active_run_id == run.id
    assert conversation.completion_run_id is None
    assert conversation.completion_epoch is None
    assert conversation.completion_candidate_revision is None
    assert conversation.completion_candidate_base_hash is None
    assert conversation.completion_app_mode is None
    assert conversation.completion_assertion is None
    assert session.scalar(select(WorkflowAssistRunEvent).where(WorkflowAssistRunEvent.step_id == step_id)) is None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_start_turn_atomically_supersedes_the_active_run(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    old_run, _old_lease = _start_and_claim(sqlite_session)

    new_run = coordinator.start_turn(
        owner=_owner(),
        message="Use the newest requirements",
        mode=WorkflowAssistMode.ADVANCED_CHAT,
        model_config={"model": "test-model"},
        selected_node="node-1",
    )
    sqlite_session.flush()

    messages = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage)
            .where(WorkflowAssistMessage.conversation_id == conversation.id)
            .order_by(WorkflowAssistMessage.sequence)
        )
    )
    old_events = list(
        sqlite_session.scalars(
            select(WorkflowAssistRunEvent)
            .where(WorkflowAssistRunEvent.run_id == old_run.id)
            .order_by(WorkflowAssistRunEvent.sequence)
        )
    )
    new_events = list(
        sqlite_session.scalars(
            select(WorkflowAssistRunEvent)
            .where(WorkflowAssistRunEvent.run_id == new_run.id)
            .order_by(WorkflowAssistRunEvent.sequence)
        )
    )

    assert old_run.status is WorkflowAssistRunStatus.ABORTED
    assert old_run.termination_reason == "superseded_by_new_turn"
    assert [event.sequence for event in old_events] == [1, 2, 3]
    assert old_events[-1].event is WorkflowAssistRunEventType.ABORTED
    assert old_events[-1].payload == {"status": "aborted", "reason": "superseded_by_new_turn"}
    assert new_run.status is WorkflowAssistRunStatus.QUEUED
    assert new_run.epoch == old_run.epoch + 1
    assert new_run.next_event_sequence == 2
    assert new_run.candidate_revision == conversation.candidate_revision
    assert [(message.role, message.event_type, message.payload) for message in messages] == [
        ("user", "message", {"text": "Build a support workflow"}),
        ("user", "message", {"text": "Use the newest requirements"}),
    ]
    assert [(event.sequence, event.event, event.payload) for event in new_events] == [
        (1, WorkflowAssistRunEventType.STATUS, {"status": "queued"})
    ]
    assert conversation.active_run_id == new_run.id
    assert conversation.latest_run_id == new_run.id
    assert conversation.run_epoch == new_run.epoch
    assert new_run.selected_node == "node-1"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_start_turn_persists_references_on_run_and_user_payload(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    references = [
        {"kind": "node", "id": "n1", "label": "知识库检索"},
        {
            "kind": "tool",
            "id": "time/current_time",
            "label": "当前时间",
            "provider": "time",
            "tool_name": "current_time",
        },
    ]

    run = coordinator.start_turn(
        owner=_owner(),
        message="把 知识库检索 接到当前时间",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={"provider": "test"},
        selected_node="node-1",
        references=references,
    )
    sqlite_session.flush()

    messages = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage)
            .where(WorkflowAssistMessage.conversation_id == conversation.id)
            .order_by(WorkflowAssistMessage.sequence)
        )
    )

    assert run.selected_node == "node-1"
    assert run.references == references
    assert run.model_config == {"provider": "test"}
    assert "references" not in run.model_config
    assert [(message.role, message.event_type, message.payload) for message in messages] == [
        (
            "user",
            "message",
            {"text": "把 知识库检索 接到当前时间", "references": references},
        )
    ]


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_start_turn_resolves_pending_ask_user_without_appending_a_duplicate_user_message(
    sqlite_session: Session,
) -> None:
    conversation = _create_conversation(sqlite_session)
    sqlite_session.add(
        WorkflowAssistMessage(
            tenant_id=conversation.tenant_id,
            app_id=conversation.app_id,
            account_id=conversation.account_id,
            conversation_id=conversation.id,
            sequence=1,
            role="assistant",
            event_type="tool_call",
            status="pending",
            payload={"id": "ask-1", "name": "ask_user", "arguments": {"questions": ["Which channel?"]}},
        )
    )
    sqlite_session.flush()

    RunCoordinator(sqlite_session).start_turn(
        owner=_owner(),
        message="Use email",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={"model": "test-model"},
    )
    sqlite_session.flush()

    messages = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage)
            .where(WorkflowAssistMessage.conversation_id == conversation.id)
            .order_by(WorkflowAssistMessage.sequence)
        )
    )
    assert [(message.role, message.event_type, message.status, message.payload) for message in messages] == [
        (
            "assistant",
            "tool_call",
            "completed",
            {"id": "ask-1", "name": "ask_user", "arguments": {"questions": ["Which channel?"]}},
        ),
        (
            "assistant",
            "tool_result",
            "completed",
            {"tool_call_id": "ask-1", "name": "ask_user", "content": "Use email"},
        ),
    ]


def test_start_turn_requests_a_conversation_row_lock() -> None:
    session = MagicMock(spec=Session)
    session.get_bind.return_value.dialect = sqlite.dialect()
    conversation = WorkflowAssistConversation(
        id="conversation-1",
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
    )
    session.scalar.side_effect = [conversation, 0]

    RunCoordinator(session).start_turn(
        owner=_owner(),
        message="Build a workflow",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={},
    )

    lock_statement = session.scalar.call_args_list[0].args[0]
    assert lock_statement._for_update_arg is not None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_superseded_epoch_cannot_append_an_event_or_mutate_candidate(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    old_run, old_lease = _start_and_claim(sqlite_session)
    coordinator.start_turn(
        owner=_owner(),
        message="Replace the old turn",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={},
    )

    result = coordinator.commit_step(
        lease=old_lease,
        step_id="old-worker-step",
        event=WorkflowAssistRunEventType.CANDIDATE_UPDATED,
        payload={"diff": {"added": ["stale"], "removed": [], "changed": []}},
        candidate=CandidateMutation(graph={"nodes": [{"id": "stale"}], "edges": []}, base_hash="stale"),
    )

    stale_event = sqlite_session.scalar(
        select(WorkflowAssistRunEvent).where(
            WorkflowAssistRunEvent.run_id == old_run.id,
            WorkflowAssistRunEvent.step_id == "old-worker-step",
        )
    )
    assert result.outcome is CommitStepOutcome.FENCED
    assert stale_event is None
    assert conversation.candidate_graph is None
    assert conversation.candidate_revision == 0


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_commit_step_is_idempotent_for_a_stable_step_id(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)

    first = coordinator.commit_step(
        lease=lease,
        step_id="tool-1:result",
        event=WorkflowAssistRunEventType.CANDIDATE_UPDATED,
        payload={"diff": {"added": ["current"], "removed": [], "changed": []}},
        candidate=CandidateMutation(graph={"nodes": [{"id": "current"}], "edges": []}, base_hash="draft-1"),
    )
    duplicate = coordinator.commit_step(
        lease=lease,
        step_id="tool-1:result",
        event=WorkflowAssistRunEventType.CANDIDATE_UPDATED,
        payload={"diff": {"added": ["duplicate"], "removed": [], "changed": []}},
        candidate=CandidateMutation(graph={"nodes": [{"id": "duplicate"}], "edges": []}, base_hash="draft-2"),
    )

    events = list(
        sqlite_session.scalars(
            select(WorkflowAssistRunEvent)
            .where(WorkflowAssistRunEvent.run_id == run.id)
            .order_by(WorkflowAssistRunEvent.sequence)
        )
    )
    assert first.outcome is CommitStepOutcome.COMMITTED
    assert first.sequence == 3
    assert duplicate.outcome is CommitStepOutcome.DUPLICATE
    assert duplicate.sequence == 3
    assert [event.sequence for event in events] == [1, 2, 3]
    assert conversation.candidate_graph == {"nodes": [{"id": "current"}], "edges": []}
    assert conversation.candidate_revision == 1
    assert conversation.candidate_base_hash == "draft-1"
    assert run.candidate_revision == 1
    assert run.next_event_sequence == 4
    assert events[-1].payload == {
        "revision": conversation.candidate_revision,
        "diff": {"added": ["current"], "removed": [], "changed": []},
    }


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_committed_tool_slot_rejects_a_payload_mismatch(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    _run, lease = _start_and_claim(sqlite_session)
    step_id = "tool:call-2-0:call"
    coordinator.commit_step(
        lease=lease,
        step_id=step_id,
        event=WorkflowAssistRunEventType.TOOL_CALL,
        payload={
            "tool_call_id": "call-2-0",
            "name": "connect",
            "arguments": {"source": "start", "target": "middle"},
        },
    )

    with pytest.raises(WorkflowAssistConversationWriteConflictError, match="payload"):
        coordinator.commit_step(
            lease=lease,
            step_id=step_id,
            event=WorkflowAssistRunEventType.TOOL_CALL,
            payload={
                "tool_call_id": "call-2-0",
                "name": "disconnect",
                "arguments": {"source": "middle", "target": "end"},
            },
        )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_committed_message_delta_slot_rejects_a_payload_mismatch(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    _run, lease = _start_and_claim(sqlite_session)
    coordinator.commit_step(
        lease=lease,
        step_id="message:2:1",
        event=WorkflowAssistRunEventType.MESSAGE_DELTA,
        payload={"text": "first model response"},
    )

    with pytest.raises(WorkflowAssistConversationWriteConflictError, match="payload"):
        coordinator.commit_step(
            lease=lease,
            step_id="message:2:1",
            event=WorkflowAssistRunEventType.MESSAGE_DELTA,
            payload={"text": "different model response"},
        )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_candidate_mutation_clears_completion_evidence_in_the_step_transaction(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    conversation.completion_run_id = run.id
    conversation.completion_epoch = run.epoch
    conversation.completion_candidate_revision = 0
    conversation.completion_candidate_base_hash = "draft-1"
    conversation.completion_app_mode = WorkflowAssistMode.WORKFLOW
    conversation.completion_assertion = "workflow_structure_reaches_terminal"
    conversation.completion_contract_protocol_version = 1
    conversation.completion_contract_revision = 1
    conversation.completion_contract_hash = "a" * 64

    result = coordinator.commit_step(
        lease=lease,
        step_id="candidate-1",
        event=WorkflowAssistRunEventType.CANDIDATE_UPDATED,
        payload={"diff": {"added": ["new"], "removed": [], "changed": []}},
        candidate=CandidateMutation(graph={"nodes": [{"id": "new"}], "edges": []}, base_hash="draft-1"),
    )

    assert result.outcome is CommitStepOutcome.COMMITTED
    assert conversation.candidate_revision == 1
    assert all(
        getattr(conversation, field) is None
        for field in (
            "completion_run_id",
            "completion_epoch",
            "completion_candidate_revision",
            "completion_candidate_base_hash",
            "completion_app_mode",
            "completion_assertion",
            "completion_contract_protocol_version",
            "completion_contract_revision",
            "completion_contract_hash",
            "completion_graph_hash",
            "completion_validation_version",
        )
    )


@pytest.mark.parametrize("mode", [WorkflowAssistMode.WORKFLOW, WorkflowAssistMode.ADVANCED_CHAT])
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_done_atomically_persists_typed_completion_evidence(
    sqlite_session: Session,
    mode: WorkflowAssistMode,
) -> None:
    conversation = _create_conversation(sqlite_session)
    conversation.contract_protocol_version = 1
    sqlite_session.flush()
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session, mode=mode)
    terminal_type = "end" if mode is WorkflowAssistMode.WORKFLOW else "answer"
    terminal_output = "result" if terminal_type == "end" else "answer"
    graph = {
        "nodes": [
            {
                "id": "start",
                "data": {
                    "type": "start",
                    "variables": [{"variable": "query", "type": "paragraph"}],
                },
            },
            {
                "id": "terminal",
                "data": {
                    "type": terminal_type,
                    **(
                        {
                            "outputs": [
                                {
                                    "variable": "result",
                                    "value_selector": ["start", "query"],
                                    "value_type": "string",
                                }
                            ]
                        }
                        if terminal_type == "end"
                        else {"answer": "{{#start.query#}}"}
                    ),
                },
            },
        ],
        "edges": [{"source": "start", "target": "terminal"}],
    }
    _commit_candidate(coordinator, lease, mode=mode, graph=graph)
    contract_body = {
        "schema_version": 1,
        "status": "complete",
        "operation": "rebuild",
        "requirements": [
            {
                "id": "req.result",
                "source_turn_id": "turn:1",
                "evidence": "Build a support workflow",
                "text": "Build a support workflow",
                "provenance": "explicit_user",
                "supersedes": [],
            }
        ],
        "assumptions": [],
        "edit_scope": None,
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "objective": "Collect query",
                "requirement_ids": ["req.result"],
                "inputs": [],
                "outputs": [{"name": "query", "type": "string"}],
                "structure_kind": "start",
                "unresolved": [],
            },
            {
                "id": "terminal",
                "type": terminal_type,
                "objective": "Return result",
                "requirement_ids": ["req.result"],
                "inputs": [{"source": ["start", "query"], "role": "result"}],
                "outputs": [{"name": terminal_output, "type": "string"}],
                "structure_kind": terminal_type,
                "unresolved": [],
            },
        ],
        "edges": [{"source": "start", "target": "terminal", "source_handle": None}],
        "final_outputs": [{"name": "result", "source": ["terminal", terminal_output], "type": "string"}],
        "resources": [],
        "checks": [
            {
                "id": "check.result",
                "description": "Terminal returns result",
                "level": "static",
                "requirement_ids": ["req.result"],
            }
        ],
        "unresolved": [],
    }
    contract_hash = canonical_workflow_contract_hash(contract_body, revision=1)
    conversation.workflow_contract = {
        **contract_body,
        "protocol_version": 1,
        "revision": 1,
        "contract_hash": contract_hash,
    }
    conversation.contract_revision = 1
    conversation.contract_hash = contract_hash

    assert coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.DONE,
        step_id="terminal-done",
        payload={},
        reason="completed",
    )

    terminal = sqlite_session.scalar(
        select(WorkflowAssistRunEvent).where(
            WorkflowAssistRunEvent.run_id == run.id,
            WorkflowAssistRunEvent.step_id == "terminal-done",
        )
    )
    assert terminal is not None
    assert terminal.event is WorkflowAssistRunEventType.DONE
    assert terminal.payload == {"status": "done"}
    assert run.status is WorkflowAssistRunStatus.DONE
    assert conversation.active_run_id is None
    assert conversation.completion_run_id == run.id
    assert conversation.completion_epoch == run.epoch
    assert conversation.completion_candidate_revision == conversation.candidate_revision
    assert conversation.completion_candidate_base_hash == "draft-1"
    assert conversation.completion_app_mode is mode
    assert conversation.completion_assertion == "workflow_structure_reaches_terminal"
    assert conversation.completion_contract_protocol_version == 1
    assert conversation.completion_contract_revision == 1
    assert conversation.completion_contract_hash == contract_hash
    assert conversation.completion_graph_hash == canonical_graph_hash(graph)
    assert conversation.completion_validation_version == WORKFLOW_RECONCILIATION_VERSION


@pytest.mark.parametrize("mode", [WorkflowAssistMode.WORKFLOW, WorkflowAssistMode.ADVANCED_CHAT])
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_done_rejects_candidate_without_a_mode_specific_terminal_path(
    sqlite_session: Session,
    mode: WorkflowAssistMode,
) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session, mode=mode)
    wrong_terminal = "answer" if mode is WorkflowAssistMode.WORKFLOW else "end"
    invalid_graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start"}},
            {"id": "terminal", "data": {"type": wrong_terminal}},
        ],
        "edges": [{"source": "start", "target": "terminal"}],
    }
    _commit_candidate(coordinator, lease, mode=mode, graph=invalid_graph)
    sequence = run.next_event_sequence

    assert not coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.DONE,
        step_id="invalid-done",
        payload={},
    )

    assert run.status is WorkflowAssistRunStatus.RUNNING
    assert run.next_event_sequence == sequence
    assert conversation.active_run_id == run.id
    assert conversation.completion_run_id is None
    assert (
        sqlite_session.scalar(select(WorkflowAssistRunEvent).where(WorkflowAssistRunEvent.step_id == "invalid-done"))
        is None
    )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_caller_cannot_supply_a_fabricated_completion_proof(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    _commit_candidate(coordinator, lease)
    sequence = run.next_event_sequence

    with pytest.raises(TypeError):
        coordinator.terminate(
            lease=lease,
            status=WorkflowAssistRunStatus.DONE,
            step_id="fabricated-proof",
            payload={},
            completion=object(),  # type: ignore[call-arg]
        )

    assert run.status is WorkflowAssistRunStatus.RUNNING
    assert run.next_event_sequence == sequence
    assert conversation.active_run_id == run.id
    assert conversation.completion_run_id is None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_queued_run_cannot_be_completed_even_with_a_valid_candidate(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run = coordinator.start_turn(
        owner=_owner(),
        message="Build a workflow",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={},
    )
    conversation.candidate_graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start"}},
            {"id": "end", "data": {"type": "end"}},
        ],
        "edges": [{"source": "start", "target": "end"}],
    }
    conversation.candidate_revision = 1
    conversation.candidate_base_hash = "draft-1"
    run.candidate_revision = 1
    sqlite_session.flush()
    sequence = run.next_event_sequence

    assert not coordinator.terminate(
        lease=RunLease(owner=_owner(), run_id=run.id, epoch=run.epoch, attempt=run.attempt, worker_id=None),
        status=WorkflowAssistRunStatus.DONE,
        step_id="queued-done",
        payload={},
    )

    assert run.status is WorkflowAssistRunStatus.QUEUED
    assert run.next_event_sequence == sequence
    assert conversation.active_run_id == run.id
    assert conversation.completion_run_id is None


@pytest.mark.parametrize(
    ("running", "status", "reason"),
    [
        (False, WorkflowAssistRunStatus.ERROR, "dispatch_failed"),
        (False, WorkflowAssistRunStatus.ERROR, "queue_timeout"),
        (False, WorkflowAssistRunStatus.ABORTED, "user_abort"),
        (True, WorkflowAssistRunStatus.ABORTED, "user_abort"),
        (True, WorkflowAssistRunStatus.ERROR, "worker_lost"),
    ],
)
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_control_fence_permits_only_exact_system_terminal_transitions(
    sqlite_session: Session,
    running: bool,
    status: WorkflowAssistRunStatus,
    reason: str,
) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run = coordinator.start_turn(
        owner=_owner(),
        message="Build a workflow",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={},
    )
    if running:
        assert coordinator.claim(owner=_owner(), run_id=run.id, epoch=run.epoch, worker_id="worker-1") is not None
    initial_sequence = run.next_event_sequence
    fence = _control_fence(run, reason=reason)

    assert coordinator.terminate(
        lease=fence,
        status=status,
        step_id=f"control:{reason}",
        payload={},
        reason=reason,
    )

    terminal = sqlite_session.scalar(
        select(WorkflowAssistRunEvent).where(
            WorkflowAssistRunEvent.run_id == run.id,
            WorkflowAssistRunEvent.step_id == f"control:{reason}",
        )
    )
    assert terminal is not None
    assert terminal.sequence == initial_sequence
    assert terminal.event is WorkflowAssistRunEventType(status.value)
    assert terminal.payload == {"status": status.value}
    assert run.status is status
    assert run.termination_reason == reason
    assert run.next_event_sequence == initial_sequence + 1
    assert conversation.last_run_termination_reason == reason
    assert conversation.active_run_id is None


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (WorkflowAssistRunStatus.DONE, None),
        (WorkflowAssistRunStatus.WAITING_USER, "user_abort"),
        (WorkflowAssistRunStatus.FAILED, "user_abort"),
        (WorkflowAssistRunStatus.ERROR, "user_abort"),
    ],
)
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_control_fence_rejects_unapproved_terminal_reason_pairs_without_side_effects(
    sqlite_session: Session,
    status: WorkflowAssistRunStatus,
    reason: str | None,
) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run = coordinator.start_turn(
        owner=_owner(),
        message="Build a workflow",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={},
    )
    sequence = run.next_event_sequence

    with pytest.raises(ValueError, match="control"):
        coordinator.terminate(
            lease=UserAbortFence(owner=_owner(), run_id=run.id, epoch=run.epoch),
            status=status,
            step_id="invalid-control",
            payload={},
            reason=reason,
        )

    assert run.status is WorkflowAssistRunStatus.QUEUED
    assert run.next_event_sequence == sequence
    assert conversation.active_run_id == run.id
    assert conversation.last_run_termination_reason is None
    assert (
        sqlite_session.scalar(select(WorkflowAssistRunEvent).where(WorkflowAssistRunEvent.step_id == "invalid-control"))
        is None
    )


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_control_fence_rejects_a_status_state_mismatch_without_side_effects(
    sqlite_session: Session,
    running: bool,
) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run = coordinator.start_turn(
        owner=_owner(),
        message="Build a workflow",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={},
    )
    if running:
        assert coordinator.claim(owner=_owner(), run_id=run.id, epoch=run.epoch, worker_id="worker-1") is not None
    sequence = run.next_event_sequence
    if running:
        fence: QueueTimeoutFence | WorkerTimeoutFence = QueueTimeoutFence(
            owner=_owner(),
            run_id=run.id,
            epoch=run.epoch,
            cutoff=run.queued_at,
            observed_queued_at=run.queued_at,
        )
        reason = "queue_timeout"
    else:
        observed = naive_utc_now()
        fence = WorkerTimeoutFence(
            owner=_owner(),
            run_id=run.id,
            epoch=run.epoch,
            cutoff=observed,
            observed_heartbeat_at=observed,
        )
        reason = "worker_lost"

    assert not coordinator.terminate(
        lease=fence,
        status=WorkflowAssistRunStatus.ERROR,
        step_id="wrong-state-control",
        payload={},
        reason=reason,
    )

    assert run.status is (WorkflowAssistRunStatus.RUNNING if running else WorkflowAssistRunStatus.QUEUED)
    assert run.next_event_sequence == sequence
    assert conversation.active_run_id == run.id
    assert conversation.last_run_termination_reason is None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_control_fence_rejects_stale_or_wrong_owner_scope_without_side_effects(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run = coordinator.start_turn(
        owner=_owner(),
        message="Build a workflow",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={},
    )
    sequence = run.next_event_sequence
    invalid_fences = (
        QueueTimeoutFence(
            owner=_owner(account_id="account-2"),
            run_id=run.id,
            epoch=run.epoch,
            cutoff=run.queued_at,
            observed_queued_at=run.queued_at,
        ),
        QueueTimeoutFence(
            owner=_owner(),
            run_id=run.id,
            epoch=run.epoch + 1,
            cutoff=run.queued_at,
            observed_queued_at=run.queued_at,
        ),
    )

    for index, fence in enumerate(invalid_fences):
        assert not coordinator.terminate(
            lease=fence,
            status=WorkflowAssistRunStatus.ERROR,
            step_id=f"invalid-fence-{index}",
            payload={},
            reason="queue_timeout",
        )

    assert run.status is WorkflowAssistRunStatus.QUEUED
    assert run.next_event_sequence == sequence
    assert conversation.active_run_id == run.id
    assert conversation.last_run_termination_reason is None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_queue_timeout_fence_rejects_a_run_claimed_after_timeout_observation(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run = coordinator.start_turn(
        owner=_owner(),
        message="Build a workflow",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={},
    )
    timeout = QueueTimeoutFence(
        owner=_owner(),
        run_id=run.id,
        epoch=run.epoch,
        cutoff=run.queued_at,
        observed_queued_at=run.queued_at,
    )
    lease = coordinator.claim(owner=_owner(), run_id=run.id, epoch=run.epoch, worker_id="worker-1")
    assert lease is not None
    sequence = run.next_event_sequence

    assert not coordinator.terminate(
        lease=timeout,
        status=WorkflowAssistRunStatus.ERROR,
        step_id="stale-queue-timeout",
        payload={},
        reason="queue_timeout",
    )

    assert run.status is WorkflowAssistRunStatus.RUNNING
    assert run.next_event_sequence == sequence
    assert conversation.active_run_id == run.id
    assert conversation.last_run_termination_reason is None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_worker_timeout_fence_rejects_a_heartbeat_after_timeout_observation(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    observed = naive_utc_now() - timedelta(minutes=10)
    run.heartbeat_at = observed
    sqlite_session.flush()
    timeout = WorkerTimeoutFence(
        owner=_owner(),
        run_id=run.id,
        epoch=run.epoch,
        cutoff=observed,
        observed_heartbeat_at=observed,
    )

    assert coordinator.heartbeat(lease=lease)
    sequence = run.next_event_sequence

    assert not coordinator.terminate(
        lease=timeout,
        status=WorkflowAssistRunStatus.ERROR,
        step_id="stale-worker-timeout",
        payload={},
        reason="worker_lost",
    )

    assert run.status is WorkflowAssistRunStatus.RUNNING
    assert run.heartbeat_at is not None
    assert run.heartbeat_at > observed
    assert run.next_event_sequence == sequence
    assert conversation.active_run_id == run.id
    assert conversation.last_run_termination_reason is None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_timeout_fences_reject_runs_newer_than_their_cutoff(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    queued = coordinator.start_turn(
        owner=_owner(),
        message="Build a workflow",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={},
    )
    sequence = queued.next_event_sequence
    too_early = queued.queued_at - timedelta(seconds=1)

    assert not coordinator.terminate(
        lease=QueueTimeoutFence(
            owner=_owner(),
            run_id=queued.id,
            epoch=queued.epoch,
            cutoff=too_early,
            observed_queued_at=queued.queued_at,
        ),
        status=WorkflowAssistRunStatus.ERROR,
        step_id="premature-queue-timeout",
        payload={},
        reason="queue_timeout",
    )

    assert queued.status is WorkflowAssistRunStatus.QUEUED
    assert queued.next_event_sequence == sequence
    assert conversation.active_run_id == queued.id


@pytest.mark.parametrize("reason", ["dispatch_failed", "worker_lost"])
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_worker_lease_cannot_forge_a_reserved_control_reason(sqlite_session: Session, reason: str) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    sequence = run.next_event_sequence

    with pytest.raises(ValueError, match="control"):
        coordinator.terminate(
            lease=lease,
            status=WorkflowAssistRunStatus.ERROR,
            step_id=f"forged-{reason}",
            payload={},
            reason=reason,
        )

    assert run.status is WorkflowAssistRunStatus.RUNNING
    assert run.next_event_sequence == sequence
    assert conversation.active_run_id == run.id


@pytest.mark.parametrize(
    "binding",
    [
        {"binding_type": "inline_agent"},
        {"binding_type": "inline_agent", "agent_id": "agent-1"},
        {"binding_type": "inline_agent", "current_snapshot_id": "snapshot-1"},
        {
            "binding_type": "inline_agent",
            "agent_id": " ",
            "current_snapshot_id": " ",
        },
    ],
)
@pytest.mark.parametrize("connect_agent", [True, False])
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_done_rejects_an_unhydrated_inline_agent_candidate(
    sqlite_session: Session,
    binding: dict[str, str],
    connect_agent: bool,
) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    unhydrated_graph = _agent_candidate_graph(binding=binding, connect_agent=connect_agent)
    unhydrated_graph["nodes"][1]["data"].update(
        {"agent_id": "misplaced-agent", "current_snapshot_id": "misplaced-snapshot"}
    )
    _commit_candidate(
        coordinator,
        lease,
        graph=unhydrated_graph,
    )
    sequence = run.next_event_sequence

    assert not coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.DONE,
        step_id="unhydrated-done",
        payload={},
    )

    _assert_done_rejected_without_side_effects(
        sqlite_session,
        conversation=conversation,
        run=run,
        sequence=sequence,
        step_id="unhydrated-done",
    )


@pytest.mark.parametrize(
    "graph",
    [
        {
            "nodes": [
                {"id": "start", "data": {"type": "start"}},
                {
                    "id": 7,
                    "data": {
                        "type": "agent",
                        "version": "2",
                        "agent_binding": {"binding_type": "inline_agent"},
                    },
                },
                {"id": "terminal", "data": {"type": "end"}},
            ],
            "edges": [{"source": "start", "target": 7}, {"source": 7, "target": "terminal"}],
        },
        {
            "nodes": [
                {"id": "start", "data": {"type": "start"}},
                {"id": " ", "data": {"type": "end"}},
            ],
            "edges": [{"source": "start", "target": " "}],
        },
        {
            "nodes": [
                {"id": "same", "data": {"type": "start"}},
                {"id": "same", "data": {"type": "end"}},
            ],
            "edges": [{"source": "same", "target": "same"}],
        },
        {
            "nodes": [
                {"id": "start", "data": {"type": "start"}},
                {"id": "terminal", "data": {"type": "end"}},
            ],
            "edges": [{"source": 1, "target": "terminal"}],
        },
        {
            "nodes": [
                {"id": "start", "data": {"type": "start"}},
                {"id": "terminal", "data": {"type": "end"}},
            ],
            "edges": [{"source": "start", "target": "missing"}],
        },
    ],
)
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_done_rejects_malformed_or_inconsistently_identified_graphs_without_side_effects(
    sqlite_session: Session,
    graph: dict[str, Any],
) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    _commit_candidate(coordinator, lease, graph=graph)
    sequence = run.next_event_sequence

    assert not coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.DONE,
        step_id="malformed-graph-done",
        payload={},
    )

    assert run.status is WorkflowAssistRunStatus.RUNNING
    assert run.next_event_sequence == sequence
    assert conversation.active_run_id == run.id
    assert conversation.completion_run_id is None
    assert (
        sqlite_session.scalar(
            select(WorkflowAssistRunEvent).where(WorkflowAssistRunEvent.step_id == "malformed-graph-done")
        )
        is None
    )


@pytest.mark.parametrize("connect_agent", [True, False])
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_done_rejects_nonexistent_inline_agent_records(sqlite_session: Session, connect_agent: bool) -> None:
    conversation = _create_conversation(sqlite_session)
    _create_draft_workflow(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    _commit_candidate(
        coordinator,
        lease,
        graph=_agent_candidate_graph(
            binding={
                "binding_type": "inline_agent",
                "agent_id": "missing-agent",
                "current_snapshot_id": "missing-snapshot",
            },
            connect_agent=connect_agent,
        ),
    )
    sequence = run.next_event_sequence

    assert not coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.DONE,
        step_id="missing-agent-done",
        payload={},
    )

    _assert_done_rejected_without_side_effects(
        sqlite_session,
        conversation=conversation,
        run=run,
        sequence=sequence,
        step_id="missing-agent-done",
    )


@pytest.mark.parametrize("connect_agent", [True, False])
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_done_rejects_a_snapshot_owned_by_another_agent(sqlite_session: Session, connect_agent: bool) -> None:
    conversation = _create_conversation(sqlite_session)
    _create_draft_workflow(sqlite_session)
    _create_inline_agent_records(sqlite_session, snapshot_agent_id="agent-2")
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    _commit_candidate(
        coordinator,
        lease,
        graph=_agent_candidate_graph(
            binding={
                "binding_type": "inline_agent",
                "agent_id": "agent-1",
                "current_snapshot_id": "snapshot-1",
            },
            connect_agent=connect_agent,
        ),
    )
    sequence = run.next_event_sequence

    assert not coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.DONE,
        step_id="mismatched-snapshot-done",
        payload={},
    )

    _assert_done_rejected_without_side_effects(
        sqlite_session,
        conversation=conversation,
        run=run,
        sequence=sequence,
        step_id="mismatched-snapshot-done",
    )


@pytest.mark.parametrize(
    "owner_override",
    [
        {"agent_tenant_id": "tenant-2", "snapshot_tenant_id": "tenant-2"},
        {"agent_app_id": "app-2"},
        {"agent_created_by": "account-2", "snapshot_created_by": "account-2"},
    ],
)
@pytest.mark.parametrize("connect_agent", [True, False])
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_done_rejects_cross_owner_inline_agent_records(
    sqlite_session: Session,
    owner_override: dict[str, str],
    connect_agent: bool,
) -> None:
    conversation = _create_conversation(sqlite_session)
    _create_draft_workflow(sqlite_session)
    _create_inline_agent_records(sqlite_session, **owner_override)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    _commit_candidate(
        coordinator,
        lease,
        graph=_agent_candidate_graph(
            binding={
                "binding_type": "inline_agent",
                "agent_id": "agent-1",
                "current_snapshot_id": "snapshot-1",
            },
            connect_agent=connect_agent,
        ),
    )
    sequence = run.next_event_sequence

    assert not coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.DONE,
        step_id="cross-owner-agent-done",
        payload={},
    )

    _assert_done_rejected_without_side_effects(
        sqlite_session,
        conversation=conversation,
        run=run,
        sequence=sequence,
        step_id="cross-owner-agent-done",
    )


@pytest.mark.parametrize("connect_agent", [True, False])
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_done_accepts_a_hydrated_inline_agent_candidate(
    sqlite_session: Session,
    connect_agent: bool,
) -> None:
    conversation = _create_conversation(sqlite_session)
    _create_draft_workflow(sqlite_session)
    _create_inline_agent_records(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    _commit_candidate(
        coordinator,
        lease,
        graph=_agent_candidate_graph(
            binding={
                "binding_type": "inline_agent",
                "agent_id": "agent-1",
                "current_snapshot_id": "snapshot-1",
            },
            connect_agent=connect_agent,
        ),
    )

    assert coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.DONE,
        step_id="hydrated-done",
        payload={},
    )

    assert run.status is WorkflowAssistRunStatus.DONE
    assert conversation.active_run_id is None
    assert conversation.completion_run_id == run.id


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_failed_finish_is_a_tool_result_and_run_remains_running(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)

    result = coordinator.commit_step(
        lease=lease,
        step_id="finish-validation-failed",
        event=WorkflowAssistRunEventType.TOOL_RESULT,
        payload={"tool_call_id": "finish-call", "ok": False, "content": "No path reaches end"},
    )

    event = sqlite_session.scalar(
        select(WorkflowAssistRunEvent).where(WorkflowAssistRunEvent.step_id == "finish-validation-failed")
    )
    assert result.outcome is CommitStepOutcome.COMMITTED
    assert event is not None
    assert event.payload["ok"] is False
    assert run.status is WorkflowAssistRunStatus.RUNNING
    assert conversation.active_run_id == run.id
    assert conversation.completion_run_id is None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_contract_checkpoint_is_idempotent_and_does_not_advance_graph_revision(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    conversation.contract_protocol_version = 1
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    contract = {"protocol_version": 1, "revision": 1, "contract_hash": "a" * 64, "status": "draft"}
    checkpoint = AgentCheckpoint(
        compacted_until_sequence=None,
        compacted_state=None,
        last_validation=None,
        workflow_contract=WorkflowContractCheckpoint(
            protocol_version=1,
            revision=1,
            contract_hash="a" * 64,
            contract=contract,
        ),
    )
    conversation.completion_run_id = run.id
    conversation.completion_contract_revision = 0

    first = coordinator.commit_step(
        lease=lease,
        step_id="contract-1",
        event=WorkflowAssistRunEventType.TOOL_RESULT,
        payload={"tool_call_id": "plan-1", "ok": True},
        checkpoint=checkpoint,
    )
    replay = coordinator.commit_step(
        lease=lease,
        step_id="contract-1",
        event=WorkflowAssistRunEventType.TOOL_RESULT,
        payload={"tool_call_id": "plan-1", "ok": True},
        checkpoint=checkpoint,
    )

    assert first.outcome is CommitStepOutcome.COMMITTED
    assert replay.outcome is CommitStepOutcome.DUPLICATE
    assert conversation.workflow_contract == contract
    assert conversation.contract_protocol_version == 1
    assert conversation.contract_revision == 1
    assert conversation.contract_hash == "a" * 64
    assert conversation.candidate_revision == 0
    assert run.candidate_revision == 0
    assert conversation.completion_run_id is None
    assert conversation.completion_contract_revision is None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_contract_checkpoint_rejects_revision_regression(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    conversation.contract_protocol_version = 1
    coordinator = RunCoordinator(sqlite_session)
    _run, lease = _start_and_claim(sqlite_session)

    def checkpoint(revision: int, marker: str) -> AgentCheckpoint:
        contract_hash = marker * 64
        contract = {
            "protocol_version": 1,
            "revision": revision,
            "contract_hash": contract_hash,
            "status": "draft",
        }
        return AgentCheckpoint(
            compacted_until_sequence=None,
            compacted_state=None,
            last_validation=None,
            workflow_contract=WorkflowContractCheckpoint(
                protocol_version=1,
                revision=revision,
                contract_hash=contract_hash,
                contract=contract,
            ),
        )

    coordinator.commit_step(
        lease=lease,
        step_id="contract-1",
        event=WorkflowAssistRunEventType.TOOL_RESULT,
        payload={"tool_call_id": "plan-1", "ok": True},
        checkpoint=checkpoint(1, "a"),
    )
    coordinator.commit_step(
        lease=lease,
        step_id="contract-2",
        event=WorkflowAssistRunEventType.TOOL_RESULT,
        payload={"tool_call_id": "plan-2", "ok": True},
        checkpoint=checkpoint(2, "b"),
    )

    with pytest.raises(ValueError, match="contract revision cannot regress"):
        coordinator.commit_step(
            lease=lease,
            step_id="contract-stale",
            event=WorkflowAssistRunEventType.TOOL_RESULT,
            payload={"tool_call_id": "plan-stale", "ok": True},
            checkpoint=checkpoint(1, "a"),
        )

    assert conversation.contract_revision == 2
    assert conversation.contract_hash == "b" * 64


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_sequences_remain_continuous_through_terminal_state(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    for index in range(2):
        result = coordinator.commit_step(
            lease=lease,
            step_id=f"message-{index}",
            event=WorkflowAssistRunEventType.MESSAGE_DELTA,
            payload={"delta": str(index)},
        )
        assert result.outcome is CommitStepOutcome.COMMITTED

    assert coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.WAITING_USER,
        step_id="terminal-waiting",
        payload={"questions": []},
        reason="clarification_required",
    )

    events = list(
        sqlite_session.scalars(
            select(WorkflowAssistRunEvent)
            .where(WorkflowAssistRunEvent.run_id == run.id)
            .order_by(WorkflowAssistRunEvent.sequence)
        )
    )
    assert [event.sequence for event in events] == [1, 2, 3, 4, 5]
    assert events[-1].event is WorkflowAssistRunEventType.WAITING_USER
    assert events[-1].payload["status"] == "waiting_user"
    assert run.next_event_sequence == 6
    assert conversation.completion_run_id is None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_terminal_run_rejects_ordinary_writes_and_heartbeat(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    assert coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.WAITING_USER,
        step_id="waiting-for-answer",
        payload={"status": "waiting_user", "questions": []},
        reason="clarification_required",
    )

    result = coordinator.commit_step(
        lease=lease,
        step_id="too-late",
        event=WorkflowAssistRunEventType.MESSAGE_DELTA,
        payload={"delta": "late"},
    )

    assert result.outcome is CommitStepOutcome.FENCED
    assert not coordinator.heartbeat(lease=lease)
    assert not coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.DONE,
        step_id="second-terminal",
        payload={"status": "done"},
    )
    assert run.status is WorkflowAssistRunStatus.WAITING_USER
    assert conversation.active_run_id is None
    assert (
        sqlite_session.scalar(select(WorkflowAssistRunEvent).where(WorkflowAssistRunEvent.step_id == "too-late"))
        is None
    )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_wrong_owner_epoch_worker_or_status_cannot_write(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    queued = coordinator.start_turn(
        owner=_owner(),
        message="Build a workflow",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={},
    )
    assert (
        coordinator.claim(
            owner=_owner(account_id="account-2"),
            run_id=queued.id,
            epoch=queued.epoch,
            worker_id="worker-1",
        )
        is None
    )
    queued_lease = RunLease(
        owner=_owner(), run_id=queued.id, epoch=queued.epoch, attempt=queued.attempt, worker_id=None
    )
    assert (
        coordinator.commit_step(
            lease=queued_lease,
            step_id="queued-write",
            event=WorkflowAssistRunEventType.MESSAGE_DELTA,
            payload={},
        ).outcome
        is CommitStepOutcome.FENCED
    )

    lease = coordinator.claim(owner=_owner(), run_id=queued.id, epoch=queued.epoch, worker_id="worker-1")
    assert lease is not None
    wrong_owner = RunLease(
        owner=_owner(account_id="account-2"),
        run_id=lease.run_id,
        epoch=lease.epoch,
        attempt=lease.attempt,
        worker_id=lease.worker_id,
    )
    wrong_epoch = RunLease(
        owner=lease.owner,
        run_id=lease.run_id,
        epoch=lease.epoch + 1,
        attempt=lease.attempt,
        worker_id=lease.worker_id,
    )
    wrong_worker = RunLease(
        owner=lease.owner,
        run_id=lease.run_id,
        epoch=lease.epoch,
        attempt=lease.attempt,
        worker_id="worker-2",
    )

    for invalid_lease in (wrong_owner, wrong_epoch, wrong_worker):
        assert not coordinator.heartbeat(lease=invalid_lease)
        assert (
            coordinator.commit_step(
                lease=invalid_lease,
                step_id=f"invalid-{invalid_lease.owner.account_id}-{invalid_lease.epoch}-{invalid_lease.worker_id}",
                event=WorkflowAssistRunEventType.MESSAGE_DELTA,
                payload={},
            ).outcome
            is CommitStepOutcome.FENCED
        )
        assert not coordinator.terminate(
            lease=invalid_lease,
            status=WorkflowAssistRunStatus.ERROR,
            step_id="invalid-terminal",
            payload={"status": "error"},
        )

    assert coordinator.heartbeat(lease=lease)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_same_delivery_identity_can_resume_but_different_worker_cannot_steal_running_lease(
    sqlite_session: Session,
) -> None:
    _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run = coordinator.start_turn(
        owner=_owner(),
        message="Build a workflow",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={},
    )
    first = coordinator.claim(owner=_owner(), run_id=run.id, epoch=run.epoch, worker_id="delivery-1")
    assert first is not None
    first_heartbeat = run.heartbeat_at

    assert coordinator.claim(owner=_owner(), run_id=run.id, epoch=run.epoch, worker_id="delivery-2") is None
    resumed = coordinator.claim(owner=_owner(), run_id=run.id, epoch=run.epoch, worker_id="delivery-1")

    assert resumed == first
    assert first.attempt == 1
    assert resumed.attempt == 1
    assert run.attempt == 1
    assert run.heartbeat_at is not None
    assert first_heartbeat is not None
    assert run.heartbeat_at >= first_heartbeat
    running_events = list(
        sqlite_session.scalars(
            select(WorkflowAssistRunEvent).where(
                WorkflowAssistRunEvent.run_id == run.id,
                WorkflowAssistRunEvent.step_id == "status:running",
            )
        )
    )
    assert len(running_events) == 1


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_stale_lease_attempt_cannot_write_after_attempt_advances(sqlite_session: Session) -> None:
    coordinator = RunCoordinator(sqlite_session)
    _create_conversation(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    run.attempt = 2
    sqlite_session.flush()

    assert not coordinator.heartbeat(lease=lease)
    assert (
        coordinator.commit_step(
            lease=lease,
            step_id="stale-attempt",
            event=WorkflowAssistRunEventType.MESSAGE_DELTA,
            payload={},
        ).outcome
        is CommitStepOutcome.FENCED
    )
    assert not coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.ERROR,
        step_id="stale-attempt-terminal",
        payload={"status": "error"},
    )
    assert run.status is WorkflowAssistRunStatus.RUNNING


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_deleting_conversation_fences_all_later_lease_writes(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)

    WorkflowAssistConversationService(sqlite_session).delete(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
        conversation_id=conversation.id,
    )

    assert not coordinator.heartbeat(lease=lease)
    assert (
        coordinator.commit_step(
            lease=lease,
            step_id="after-delete",
            event=WorkflowAssistRunEventType.MESSAGE_DELTA,
            payload={},
        ).outcome
        is CommitStepOutcome.FENCED
    )
    assert not coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.ERROR,
        step_id="after-delete-terminal",
        payload={"status": "error"},
    )
    assert sqlite_session.get(WorkflowAssistRun, run.id) is None


def test_terminate_rejects_non_terminal_status() -> None:
    with pytest.raises(ValueError, match="terminal"):
        RunCoordinator(MagicMock(spec=Session)).terminate(
            lease=RunLease(owner=_owner(), run_id="run-1", epoch=1, attempt=1, worker_id="worker-1"),
            status=WorkflowAssistRunStatus.RUNNING,
            step_id="invalid-terminal",
            payload={"status": "running"},
        )


@pytest.mark.parametrize(
    ("event", "payload", "candidate"),
    [
        (WorkflowAssistRunEventType.STATUS, {"status": "queued"}, None),
        (WorkflowAssistRunEventType.CANDIDATE_UPDATED, {"diff": {}}, None),
        (
            WorkflowAssistRunEventType.MESSAGE_DELTA,
            {"delta": "hidden mutation"},
            CandidateMutation(graph={"nodes": [], "edges": []}),
        ),
        (
            WorkflowAssistRunEventType.CANDIDATE_UPDATED,
            {"revision": 10, "diff": {}},
            CandidateMutation(graph={"nodes": [], "edges": []}),
        ),
        (
            WorkflowAssistRunEventType.CANDIDATE_UPDATED,
            {"diff": {}, "message": "extra"},
            CandidateMutation(graph={"nodes": [], "edges": []}),
        ),
        (
            WorkflowAssistRunEventType.CANDIDATE_UPDATED,
            {"diff": {"nodes": [{"id": "leaked"}], "edges": []}},
            CandidateMutation(graph={"nodes": [{"id": "current"}], "edges": []}),
        ),
        (WorkflowAssistRunEventType.TOOL_CALL, {"name": "finish"}, None),
        (WorkflowAssistRunEventType.TOOL_RESULT, {"tool_call_id": "", "ok": False}, None),
        (WorkflowAssistRunEventType.MESSAGE_DELTA, {"nested": {"candidate_graph": {"nodes": []}}}, None),
        (WorkflowAssistRunEventType.MESSAGE_DELTA, {"items": [{"graph": {"nodes": []}}]}, None),
    ],
)
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_invalid_event_inputs_have_no_database_or_sequence_side_effects(
    sqlite_session: Session,
    event: WorkflowAssistRunEventType,
    payload: dict[str, object],
    candidate: CandidateMutation | None,
) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    sequence = run.next_event_sequence
    revision = conversation.candidate_revision

    with pytest.raises(ValueError):
        coordinator.commit_step(
            lease=lease,
            step_id="invalid-event",
            event=event,
            payload=payload,
            candidate=candidate,
        )

    assert run.next_event_sequence == sequence
    assert conversation.candidate_revision == revision
    assert (
        sqlite_session.scalar(select(WorkflowAssistRunEvent).where(WorkflowAssistRunEvent.step_id == "invalid-event"))
        is None
    )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_terminal_status_payload_mismatch_has_no_side_effects(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    sequence = run.next_event_sequence

    with pytest.raises(ValueError, match="status"):
        coordinator.terminate(
            lease=lease,
            status=WorkflowAssistRunStatus.ERROR,
            step_id="mismatched-terminal",
            payload={"status": "done"},
            reason="failed",
        )

    assert run.status is WorkflowAssistRunStatus.RUNNING
    assert run.next_event_sequence == sequence
    assert conversation.active_run_id == run.id
    assert (
        sqlite_session.scalar(
            select(WorkflowAssistRunEvent).where(WorkflowAssistRunEvent.step_id == "mismatched-terminal")
        )
        is None
    )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_start_turn_refreshes_a_stale_preloaded_conversation_before_superseding(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    sqlite_session.commit()
    make_session = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)

    with make_session() as stale_session:
        stale_conversation = stale_session.get(WorkflowAssistConversation, conversation.id)
        assert stale_conversation is not None
        assert stale_conversation.active_run_id is None

        with make_session() as current_session:
            current_coordinator = RunCoordinator(current_session)
            current_run = current_coordinator.start_turn(
                owner=_owner(),
                message="First turn",
                mode=WorkflowAssistMode.WORKFLOW,
                model_config={},
            )
            current_lease = current_coordinator.claim(
                owner=_owner(), run_id=current_run.id, epoch=current_run.epoch, worker_id="worker-1"
            )
            assert current_lease is not None
            current_session.commit()
            current_run_id = current_run.id

        replacement = RunCoordinator(stale_session).start_turn(
            owner=_owner(),
            message="Replacement turn",
            mode=WorkflowAssistMode.WORKFLOW,
            model_config={},
        )
        stale_session.commit()
        replacement_id = replacement.id

    with make_session() as verify_session:
        old_run = verify_session.get(WorkflowAssistRun, current_run_id)
        new_run = verify_session.get(WorkflowAssistRun, replacement_id)
        restored = verify_session.get(WorkflowAssistConversation, conversation.id)
        assert old_run is not None
        assert old_run.status is WorkflowAssistRunStatus.ABORTED
        assert new_run is not None
        assert new_run.epoch == 2
        assert restored is not None
        assert restored.active_run_id == new_run.id
        assert restored.run_epoch == 2


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_commit_step_refreshes_stale_run_sequence_and_duplicate_state(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    sqlite_session.commit()
    make_session = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)

    with make_session() as stale_session:
        stale_run = stale_session.get(WorkflowAssistRun, run.id)
        stale_conversation = stale_session.get(WorkflowAssistConversation, lease.owner.conversation_id)
        assert stale_run is not None
        assert stale_run.next_event_sequence == 3
        assert stale_conversation is not None

        with make_session() as current_session:
            first = RunCoordinator(current_session).commit_step(
                lease=lease,
                step_id="concurrent-step",
                event=WorkflowAssistRunEventType.MESSAGE_DELTA,
                payload={"delta": "first"},
            )
            assert first.outcome is CommitStepOutcome.COMMITTED
            current_session.commit()

        second = RunCoordinator(stale_session).commit_step(
            lease=lease,
            step_id="next-step",
            event=WorkflowAssistRunEventType.MESSAGE_DELTA,
            payload={"delta": "second"},
        )
        duplicate = RunCoordinator(stale_session).commit_step(
            lease=lease,
            step_id="concurrent-step",
            event=WorkflowAssistRunEventType.MESSAGE_DELTA,
            payload={"delta": "first"},
        )
        stale_session.commit()

    assert second.sequence == 4
    assert duplicate.outcome is CommitStepOutcome.DUPLICATE
    assert duplicate.sequence == 3


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_commit_step_rereads_a_duplicate_after_a_unique_race(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    winner = coordinator.commit_step(
        lease=lease,
        step_id="raced-step",
        event=WorkflowAssistRunEventType.MESSAGE_DELTA,
        payload={"delta": "winner"},
    )
    sequence = run.next_event_sequence

    def raise_unique_conflict(**_kwargs: object) -> CommitStepResult:
        raise IntegrityError("INSERT", {}, RuntimeError("duplicate"))

    monkeypatch.setattr(coordinator, "_commit_step_locked", raise_unique_conflict)

    duplicate = coordinator.commit_step(
        lease=lease,
        step_id="raced-step",
        event=WorkflowAssistRunEventType.MESSAGE_DELTA,
        payload={"delta": "winner"},
    )

    assert winner.sequence == 3
    assert duplicate.outcome is CommitStepOutcome.DUPLICATE
    assert duplicate.sequence == 3
    assert run.next_event_sequence == sequence


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_commit_step_translates_a_residual_unique_conflict(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    sequence = run.next_event_sequence

    def raise_unique_conflict(**_kwargs: object) -> CommitStepResult:
        raise IntegrityError("INSERT", {}, RuntimeError("duplicate"))

    monkeypatch.setattr(coordinator, "_commit_step_locked", raise_unique_conflict)

    with pytest.raises(WorkflowAssistConversationWriteConflictError):
        coordinator.commit_step(
            lease=lease,
            step_id="losing-step",
            event=WorkflowAssistRunEventType.MESSAGE_DELTA,
            payload={"delta": "loser"},
        )
    sqlite_session.commit()

    assert run.next_event_sequence == sequence
    assert (
        sqlite_session.scalar(select(WorkflowAssistRunEvent).where(WorkflowAssistRunEvent.step_id == "losing-step"))
        is None
    )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_oversized_start_turn_can_be_caught_without_committing_partial_supersede(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, _lease = _start_and_claim(sqlite_session)
    sqlite_session.commit()
    message_count = sqlite_session.query(WorkflowAssistMessage).count()
    event_count = sqlite_session.query(WorkflowAssistRunEvent).count()

    with pytest.raises(ValueError, match="65536"):
        coordinator.start_turn(
            owner=_owner(),
            message=("é" * 32_768) + "x",
            mode=WorkflowAssistMode.WORKFLOW,
            model_config={},
        )
    sqlite_session.commit()
    sqlite_session.expire_all()

    restored_run = sqlite_session.get(WorkflowAssistRun, run.id)
    restored_conversation = sqlite_session.get(WorkflowAssistConversation, conversation.id)
    assert restored_run is not None
    assert restored_run.status is WorkflowAssistRunStatus.RUNNING
    assert restored_conversation is not None
    assert restored_conversation.run_epoch == 1
    assert restored_conversation.active_run_id == run.id
    assert sqlite_session.query(WorkflowAssistMessage).count() == message_count
    assert sqlite_session.query(WorkflowAssistRunEvent).count() == event_count


@pytest.mark.parametrize(
    "payload",
    [
        {"bad": object()},
        {"data": "x" * 262_144},
    ],
)
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_invalid_terminal_payload_can_be_caught_without_partial_completion(
    sqlite_session: Session,
    payload: dict[str, Any],
) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    _commit_candidate(coordinator, lease)
    sqlite_session.commit()
    sequence = run.next_event_sequence

    with pytest.raises(ValueError):
        coordinator.terminate(
            lease=lease,
            status=WorkflowAssistRunStatus.DONE,
            step_id="invalid-terminal-payload",
            payload=payload,
        )
    sqlite_session.commit()
    sqlite_session.expire_all()

    restored_run = sqlite_session.get(WorkflowAssistRun, run.id)
    restored_conversation = sqlite_session.get(WorkflowAssistConversation, conversation.id)
    assert restored_run is not None
    assert restored_run.status is WorkflowAssistRunStatus.RUNNING
    assert restored_run.next_event_sequence == sequence
    assert restored_conversation is not None
    assert restored_conversation.active_run_id == run.id
    assert restored_conversation.completion_run_id is None
    assert (
        sqlite_session.scalar(
            select(WorkflowAssistRunEvent).where(WorkflowAssistRunEvent.step_id == "invalid-terminal-payload")
        )
        is None
    )


@pytest.mark.parametrize("raw_event", ["status", "candidate.updated", "not-an-event"])
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_raw_event_strings_cannot_bypass_event_invariants(
    sqlite_session: Session,
    raw_event: str,
) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    sequence = run.next_event_sequence

    with pytest.raises(ValueError):
        coordinator.commit_step(
            lease=lease,
            step_id="raw-event",
            event=raw_event,  # type: ignore[arg-type]
            payload={"status": "done"},
        )

    assert run.next_event_sequence == sequence
    assert conversation.candidate_revision == 0
    assert (
        sqlite_session.scalar(select(WorkflowAssistRunEvent).where(WorkflowAssistRunEvent.step_id == "raw-event"))
        is None
    )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_mode_and_terminal_status_strings_are_normalized_or_rejected(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run = coordinator.start_turn(
        owner=_owner(),
        message="Build a workflow",
        mode="workflow",  # type: ignore[arg-type]
        model_config={},
    )
    assert run.mode is WorkflowAssistMode.WORKFLOW
    lease = coordinator.claim(owner=_owner(), run_id=run.id, epoch=run.epoch, worker_id="worker-1")
    assert lease is not None

    with pytest.raises(ValueError):
        coordinator.terminate(
            lease=lease,
            status="not-a-status",  # type: ignore[arg-type]
            step_id="invalid-status",
            payload={},
        )

    assert run.status is WorkflowAssistRunStatus.RUNNING
    assert conversation.active_run_id == run.id


def _terminate_error(
    coordinator: RunCoordinator,
    lease: RunLease,
    *,
    step_id: str = "error:provider",
    retryable: bool = True,
) -> None:
    assert coordinator.terminate(
        lease=lease,
        status=WorkflowAssistRunStatus.ERROR,
        step_id=step_id,
        payload={"status": "error", "reason": "provider_error", "retryable": retryable},
        reason="provider_error",
    )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_retry_failed_step_queues_a_new_run_without_a_new_user_message(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    conversation.contract_protocol_version = 1
    sqlite_session.flush()
    coordinator = RunCoordinator(sqlite_session)
    failed_run, lease = _start_and_claim(sqlite_session)
    coordinator.commit_step(
        lease=lease,
        step_id="tool:call-1:result",
        event=WorkflowAssistRunEventType.TOOL_RESULT,
        payload={"tool_call_id": "call-1", "name": "read_graph", "ok": True},
    )
    sqlite_session.add(
        WorkflowAssistMessage(
            tenant_id=conversation.tenant_id,
            app_id=conversation.app_id,
            account_id=conversation.account_id,
            conversation_id=conversation.id,
            sequence=2,
            role="assistant",
            event_type="tool_call",
            status="pending",
            payload={"id": "call-incomplete", "name": "build_node", "arguments": {"title": "{"}},
        )
    )
    sqlite_session.flush()
    _terminate_error(coordinator, lease, step_id="error:provider")

    retried = coordinator.retry_failed_step(
        owner=_owner(),
        run_id=failed_run.id,
        epoch=failed_run.epoch,
        failed_step_id="error:provider",
    )

    messages = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage)
            .where(WorkflowAssistMessage.conversation_id == conversation.id)
            .order_by(WorkflowAssistMessage.sequence)
        )
    )
    events = list(
        sqlite_session.scalars(
            select(WorkflowAssistRunEvent)
            .where(WorkflowAssistRunEvent.run_id == retried.id)
            .order_by(WorkflowAssistRunEvent.sequence)
        )
    )
    assert retried.id != failed_run.id
    assert retried.epoch == failed_run.epoch + 1
    assert retried.status is WorkflowAssistRunStatus.QUEUED
    assert retried.input == failed_run.input
    assert failed_run.contract_protocol_version == 1
    assert retried.contract_protocol_version == 1
    assert retried.contract_rollout_stage == failed_run.contract_rollout_stage
    assert conversation.active_run_id == retried.id
    assert conversation.run_epoch == retried.epoch
    assert [(message.role, message.event_type, message.payload.get("id")) for message in messages] == [
        ("user", "message", None),
    ]
    assert [event.event for event in events] == [WorkflowAssistRunEventType.STATUS]


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_retry_failed_step_rejects_a_non_retryable_or_incomplete_step(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    coordinator.commit_step(
        lease=lease,
        step_id="tool:call-open:call",
        event=WorkflowAssistRunEventType.TOOL_CALL,
        payload={"tool_call_id": "call-open", "name": "build_node"},
    )
    coordinator.commit_step(
        lease=lease,
        step_id="message:msg-1:0",
        event=WorkflowAssistRunEventType.MESSAGE_DELTA,
        payload={"text": "half"},
    )
    _terminate_error(coordinator, lease, step_id="error:not-retryable", retryable=False)

    with pytest.raises(ValueError, match="not retryable"):
        coordinator.retry_failed_step(
            owner=_owner(),
            run_id=run.id,
            epoch=run.epoch,
            failed_step_id="error:not-retryable",
        )
    with pytest.raises(ValueError, match="not retryable"):
        coordinator.retry_failed_step(
            owner=_owner(),
            run_id=run.id,
            epoch=run.epoch,
            failed_step_id="tool:call-open:call",
        )
    with pytest.raises(ValueError, match="not retryable"):
        coordinator.retry_failed_step(
            owner=_owner(),
            run_id=run.id,
            epoch=run.epoch,
            failed_step_id="message:msg-1:0",
        )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_retry_failed_step_rejects_a_stale_epoch(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    _terminate_error(coordinator, lease)
    coordinator.start_turn(
        owner=_owner(),
        message="A newer turn",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={"provider": "test"},
    )

    with pytest.raises(WorkflowAssistConversationWriteConflictError):
        coordinator.retry_failed_step(
            owner=_owner(),
            run_id=run.id,
            epoch=run.epoch,
            failed_step_id="error:provider",
        )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_retry_failed_step_rejects_a_user_abort(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    coordinator = RunCoordinator(sqlite_session)
    run, lease = _start_and_claim(sqlite_session)
    assert coordinator.terminate(
        lease=UserAbortFence(owner=_owner(), run_id=run.id, epoch=run.epoch),
        status=WorkflowAssistRunStatus.ABORTED,
        step_id="aborted:user_abort",
        payload={"status": "aborted", "reason": "user_abort"},
        reason="user_abort",
    )

    with pytest.raises(ValueError, match="not retryable"):
        coordinator.retry_failed_step(
            owner=_owner(),
            run_id=run.id,
            epoch=run.epoch,
            failed_step_id="aborted:user_abort",
        )
