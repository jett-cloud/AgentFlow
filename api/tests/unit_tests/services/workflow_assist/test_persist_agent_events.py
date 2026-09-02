"""Durable Agent-event persistence, including completion-policy failure recovery."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from models.workflow_assist import (
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
    WorkflowAssistRunStatus,
)
from services.workflow_assist import chat as chat_module
from services.workflow_assist.conversations import WorkflowAssistConversationService
from services.workflow_assist.run_coordinator import RunCoordinator
from services.workflow_assist.run_types import RunOwner

TABLES = (
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
)


def _running(session: Session):
    owner = RunOwner("tenant-1", "app-1", "account-1", "conversation-1")
    conversation = WorkflowAssistConversationService(session).create(
        tenant_id=owner.tenant_id,
        app_id=owner.app_id,
        account_id=owner.account_id,
    )
    conversation.id = owner.conversation_id
    session.flush()
    coordinator = RunCoordinator(session)
    run = coordinator.start_turn(
        owner=owner,
        message="Build a workflow",
        mode="workflow",
        model_config={"provider": "test"},
    )
    lease = coordinator.claim(owner=owner, run_id=run.id, epoch=run.epoch, worker_id="worker-1")
    assert lease is not None
    session.commit()
    return run, lease


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_persist_done_rejected_by_completion_policy_errors_instead_of_hanging(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    run, lease = _running(sqlite_session)
    conversation = sqlite_session.get(WorkflowAssistConversation, lease.owner.conversation_id)
    assert conversation is not None
    conversation.candidate_graph = {
        "nodes": [{"id": "start", "data": {"type": "start"}}],
        "edges": [],
    }
    conversation.candidate_revision = 1
    sqlite_session.commit()
    monkeypatch.setattr(
        chat_module.session_factory,
        "create_session",
        sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False),
    )

    outcome = chat_module.persist_agent_events(
        lease=lease,
        events=iter([("done", {})]),
    )

    sqlite_session.expire_all()
    persisted = sqlite_session.get(WorkflowAssistRun, run.id)
    assert outcome is WorkflowAssistRunStatus.ERROR
    assert persisted is not None
    assert persisted.status is WorkflowAssistRunStatus.ERROR
    assert persisted.termination_reason == "completion_rejected"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_persist_turn_complete_is_terminal_without_completion_evidence(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    run, lease = _running(sqlite_session)
    monkeypatch.setattr(
        chat_module.session_factory,
        "create_session",
        sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False),
    )

    outcome = chat_module.persist_agent_events(
        lease=lease,
        events=iter([("turn_complete", {})]),
    )

    sqlite_session.expire_all()
    persisted = sqlite_session.get(WorkflowAssistRun, run.id)
    conversation = sqlite_session.get(WorkflowAssistConversation, lease.owner.conversation_id)
    assert outcome is WorkflowAssistRunStatus.TURN_COMPLETE
    assert persisted is not None
    assert persisted.status is WorkflowAssistRunStatus.TURN_COMPLETE
    assert conversation is not None
    assert conversation.active_run_id is None
    assert conversation.completion_run_id is None


def _assistant_recovery(*, text: str, reasoning: str | None = None, message_id: str = "msg-1") -> dict:
    payload: dict = {"text": text, "message_id": message_id}
    if reasoning:
        payload["reasoning"] = reasoning
    return {
        "sequence": 2,
        "role": "assistant",
        "event_type": "message",
        "status": "completed",
        "payload": payload,
    }


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_reasoning_delta_commits_separate_step_and_recovery_payload(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    from sqlalchemy import select

    from models.workflow_assist import WorkflowAssistRunEvent, WorkflowAssistRunEventType

    run, lease = _running(sqlite_session)
    monkeypatch.setattr(
        chat_module.session_factory,
        "create_session",
        sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False),
    )

    outcome = chat_module.persist_agent_events(
        lease=lease,
        events=iter(
            [
                (
                    "reasoning.delta",
                    {
                        "text": "先读图",
                        "delta": "先读图",
                        "message_id": "msg-1",
                        "delta_index": 0,
                    },
                ),
                (
                    "message.delta",
                    {
                        "text": "开始改",
                        "delta": "开始改",
                        "message_id": "msg-1",
                        "delta_index": 0,
                        "_recovery_messages": [_assistant_recovery(text="开始改", reasoning="先读图")],
                    },
                ),
                ("turn_complete", {}),
            ]
        ),
    )

    sqlite_session.expire_all()
    events = list(
        sqlite_session.scalars(
            select(WorkflowAssistRunEvent)
            .where(WorkflowAssistRunEvent.run_id == run.id)
            .order_by(WorkflowAssistRunEvent.sequence)
        )
    )
    persisted = sqlite_session.get(WorkflowAssistRun, run.id)
    messages = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage).where(
                WorkflowAssistMessage.conversation_id == lease.owner.conversation_id,
                WorkflowAssistMessage.role == "assistant",
                WorkflowAssistMessage.event_type == "message",
            )
        )
    )
    assert outcome is WorkflowAssistRunStatus.TURN_COMPLETE
    assert persisted is not None
    assert persisted.status is WorkflowAssistRunStatus.TURN_COMPLETE
    assert [(event.event, event.step_id, event.payload.get("text")) for event in events if event.event in {
        WorkflowAssistRunEventType.REASONING_DELTA,
        WorkflowAssistRunEventType.MESSAGE_DELTA,
    }] == [
        (WorkflowAssistRunEventType.REASONING_DELTA, "reasoning:msg-1:0", "先读图"),
        (WorkflowAssistRunEventType.MESSAGE_DELTA, "message:msg-1:0", "开始改"),
    ]
    assert messages
    assert messages[-1].payload.get("text") == "开始改"
    assert messages[-1].payload.get("reasoning") == "先读图"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_empty_text_with_reasoning_is_accepted_for_recovery(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    from sqlalchemy import select

    run, lease = _running(sqlite_session)
    monkeypatch.setattr(
        chat_module.session_factory,
        "create_session",
        sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False),
    )

    outcome = chat_module.persist_agent_events(
        lease=lease,
        events=iter(
            [
                (
                    "reasoning.delta",
                    {
                        "text": "只规划",
                        "delta": "只规划",
                        "message_id": "msg-1",
                        "delta_index": 0,
                        "_recovery_messages": [_assistant_recovery(text="", reasoning="只规划")],
                    },
                ),
                ("turn_complete", {}),
            ]
        ),
    )

    sqlite_session.expire_all()
    messages = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage).where(
                WorkflowAssistMessage.conversation_id == lease.owner.conversation_id,
                WorkflowAssistMessage.role == "assistant",
                WorkflowAssistMessage.event_type == "message",
            )
        )
    )
    assert outcome is WorkflowAssistRunStatus.TURN_COMPLETE
    assert messages
    assert messages[-1].payload.get("text") == ""
    assert messages[-1].payload.get("reasoning") == "只规划"
