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


def _running(session: Session, *, contract_protocol_version: int | None = None):
    owner = RunOwner("tenant-1", "app-1", "account-1", "conversation-1")
    conversation = WorkflowAssistConversationService(session).create(
        tenant_id=owner.tenant_id,
        app_id=owner.app_id,
        account_id=owner.account_id,
    )
    conversation.id = owner.conversation_id
    conversation.contract_protocol_version = contract_protocol_version
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


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_tool_result_checkpoint_persists_workflow_contract_independently(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    _run, lease = _running(sqlite_session, contract_protocol_version=1)
    monkeypatch.setattr(
        chat_module.session_factory,
        "create_session",
        sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False),
    )
    contract_hash = "a" * 64
    contract = {
        "protocol_version": 1,
        "revision": 1,
        "contract_hash": contract_hash,
        "status": "draft",
    }

    outcome = chat_module.persist_agent_events(
        lease=lease,
        events=iter(
            [
                (
                    "tool_result",
                    {
                        "id": "plan-1",
                        "name": "submit_workflow_plan",
                        "ok": True,
                        "content": {"revision": 1, "contract_hash": contract_hash},
                        "_agent_checkpoint": {
                            "compacted_until_sequence": None,
                            "compacted_state": None,
                            "last_validation": None,
                            "workflow_contract": {
                                "protocol_version": 1,
                                "revision": 1,
                                "contract_hash": contract_hash,
                                "contract": contract,
                            },
                        },
                    },
                ),
                ("turn_complete", {}),
            ]
        ),
    )

    sqlite_session.expire_all()
    conversation = sqlite_session.get(WorkflowAssistConversation, lease.owner.conversation_id)
    assert outcome is WorkflowAssistRunStatus.TURN_COMPLETE
    assert conversation is not None
    assert conversation.workflow_contract == contract
    assert conversation.contract_revision == 1
    assert conversation.contract_hash == contract_hash
    assert conversation.candidate_revision == 0


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_reloaded_durable_run_enforces_persisted_contract(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    import services.workflow_assist.agent_initializer as initializer

    _run, lease = _running(sqlite_session, contract_protocol_version=1)
    monkeypatch.setattr(
        chat_module.session_factory,
        "create_session",
        sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False),
    )
    contract_hash = "a" * 64
    contract = {
        "schema_version": 1,
        "status": "complete",
        "operation": "rebuild",
        "requirements": [
            {
                "id": "req.workflow",
                "source_turn_id": "turn:1",
                "evidence": "Build a workflow",
                "text": "Build a workflow",
                "provenance": "explicit_user",
                "supersedes": [],
            }
        ],
        "assumptions": [],
        "edit_scope": None,
        "nodes": [
            {
                "id": "planned",
                "type": "start",
                "objective": "Start the workflow",
                "requirement_ids": ["req.workflow"],
                "inputs": [],
                "outputs": [{"name": "query", "type": "string"}],
                "structure_kind": "start",
                "unresolved": [],
            }
        ],
        "edges": [],
        "final_outputs": [{"name": "query", "source": ["planned", "query"], "type": "string"}],
        "resources": [],
        "checks": [
            {
                "id": "check.workflow",
                "description": "The workflow has its planned start",
                "level": "static",
                "requirement_ids": ["req.workflow"],
            }
        ],
        "unresolved": [],
        "protocol_version": 1,
        "revision": 1,
        "contract_hash": contract_hash,
    }
    assert (
        chat_module.persist_agent_events(
            lease=lease,
            events=iter(
                [
                    (
                        "tool_result",
                        {
                            "id": "plan-1",
                            "name": "submit_workflow_plan",
                            "ok": True,
                            "_agent_checkpoint": {
                                "compacted_until_sequence": None,
                                "compacted_state": None,
                                "last_validation": None,
                                "workflow_contract": {
                                    "protocol_version": 1,
                                    "revision": 1,
                                    "contract_hash": contract_hash,
                                    "contract": contract,
                                },
                            },
                        },
                    ),
                    ("turn_complete", {}),
                ]
            ),
        )
        is WorkflowAssistRunStatus.TURN_COMPLETE
    )
    sqlite_session.expire_all()
    snapshot = WorkflowAssistConversationService(sqlite_session).get(
        tenant_id=lease.owner.tenant_id,
        app_id=lease.owner.app_id,
        account_id=lease.owner.account_id,
        conversation_id=lease.owner.conversation_id,
    )

    class Invoker:
        def __init__(self) -> None:
            self.turns = [
                {
                    "tool_calls": [
                        {
                            "id": "build-extra",
                            "name": "build_node",
                            "arguments": {
                                "mode": "create",
                                "id": "extra",
                                "type": "template-transform",
                                "title": "Extra",
                                "intent": {"objective": "Unplanned work"},
                            },
                        }
                    ]
                },
                {"text": "Stopped after contract rejection"},
            ]

        def invoke(self, messages=None, **kwargs):
            return self.turns.pop(0)

    monkeypatch.setattr(initializer, "build_tool_catalogue", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(initializer, "build_knowledge_catalogue", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(initializer, "build_agent_model_catalogue", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(initializer, "_draft_namespace_names", lambda *_args, **_kwargs: (set(), set()))
    monkeypatch.setattr(initializer, "_draft_workflow_id", lambda *_args, **_kwargs: None)
    context = type("Context", (), {})()
    context.app_model = type("App", (), {"tenant_id": "tenant-1", "id": "app-1", "mode": "workflow"})()
    context.account = type("Account", (), {"id": "account-1"})()
    context.run = type(
        "Run",
        (),
        {
            "id": "run-2",
            "epoch": 2,
            "worker_id": "worker-2",
            "model_config": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
            "mode": "workflow",
            "selected_node": None,
            "references": [],
                "input": "Build a workflow",
                "contract_protocol_version": 1,
            },
    )()
    context.conversation = snapshot.conversation
    context.messages = tuple(snapshot.messages)
    context.should_stop = lambda: False

    events = list(
        chat_module.run_workflow_assist_agent(context, invoker=Invoker(), hydrate_graph=lambda graph: graph)
    )

    tool_results = [payload for name, payload in events if name == "tool_result"]
    rejection = next(payload for payload in tool_results if payload["id"] == "build-extra")
    assert rejection["ok"] is False
    assert "not declared" in rejection["summary"]


def _assistant_recovery(
    *,
    text: str,
    reasoning: str | None = None,
    message_id: str = "msg-1",
    sequence: int = 2,
) -> dict:
    payload: dict = {"text": text, "message_id": message_id}
    if reasoning:
        payload["reasoning"] = reasoning
    return {
        "sequence": sequence,
        "role": "assistant",
        "event_type": "message",
        "status": "completed",
        "payload": payload,
    }


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_message_delta_partitions_older_recovery_from_current_response(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    from sqlalchemy import select

    _run, lease = _running(sqlite_session)
    monkeypatch.setattr(
        chat_module.session_factory,
        "create_session",
        sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False),
    )
    earlier = _assistant_recovery(
        sequence=2,
        message_id="msg-invalid-turn",
        text="需要确认工作流节点所使用的模型。",
    )
    notice = _assistant_recovery(
        sequence=3,
        message_id="msg-protocol-notice",
        text="模型返回的工具调用格式无效，本次调用未执行，正在自动重试。",
    )

    outcome = chat_module.persist_agent_events(
        lease=lease,
        events=iter(
            [
                (
                    "message.delta",
                    {
                        "delta": notice["payload"]["text"],
                        "message_id": "msg-protocol-notice",
                        "delta_index": 0,
                        "stream_mode": "native",
                        "_recovery_messages": [earlier, notice],
                    },
                ),
                ("turn_complete", {}),
            ]
        ),
    )

    sqlite_session.expire_all()
    messages = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage)
            .where(WorkflowAssistMessage.conversation_id == lease.owner.conversation_id)
            .order_by(WorkflowAssistMessage.sequence)
        )
    )
    assistant = [message for message in messages if message.role == "assistant"]
    assert outcome is WorkflowAssistRunStatus.TURN_COMPLETE
    assert [(message.sequence, message.status, message.payload["message_id"]) for message in assistant] == [
        (2, "completed", "msg-invalid-turn"),
        (3, "completed", "msg-protocol-notice"),
    ]


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_message_delta_recovery_cannot_write_history_after_worker_fence_is_lost(
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
    run.attempt += 1
    sqlite_session.commit()
    earlier = _assistant_recovery(
        sequence=2,
        message_id="msg-invalid-turn",
        text="需要确认工作流节点所使用的模型。",
    )
    notice = _assistant_recovery(
        sequence=3,
        message_id="msg-protocol-notice",
        text="模型返回的工具调用格式无效，本次调用未执行，正在自动重试。",
    )

    outcome = chat_module.persist_agent_events(
        lease=lease,
        events=iter(
            [
                (
                    "message.delta",
                    {
                        "delta": notice["payload"]["text"],
                        "message_id": "msg-protocol-notice",
                        "delta_index": 0,
                        "_recovery_messages": [earlier, notice],
                    },
                )
            ]
        ),
    )

    sqlite_session.expire_all()
    assistant_messages = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage).where(
                WorkflowAssistMessage.conversation_id == lease.owner.conversation_id,
                WorkflowAssistMessage.role == "assistant",
            )
        )
    )
    assert outcome is chat_module.AgentEventPumpOutcome.FENCED
    assert assistant_messages == []


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_message_delta_recovery_rejects_a_mismatched_stream_identity(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    _run, lease = _running(sqlite_session)
    monkeypatch.setattr(
        chat_module.session_factory,
        "create_session",
        sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False),
    )
    recovery = _assistant_recovery(
        sequence=2,
        message_id="msg-durable",
        text="durable response",
    )

    with pytest.raises(ValueError, match="must match exactly one durable recovery message"):
        chat_module.persist_agent_events(
            lease=lease,
            events=iter(
                [
                    (
                        "message.delta",
                        {
                            "delta": "different stream",
                            "message_id": "msg-stream",
                            "delta_index": 0,
                            "_recovery_messages": [recovery],
                        },
                    )
                ]
            ),
        )


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
    assert [
        (event.event, event.step_id, event.payload.get("text"))
        for event in events
        if event.event
        in {
            WorkflowAssistRunEventType.REASONING_DELTA,
            WorkflowAssistRunEventType.MESSAGE_DELTA,
        }
    ] == [
        (WorkflowAssistRunEventType.REASONING_DELTA, "reasoning:msg-1:0", "先读图"),
        (WorkflowAssistRunEventType.MESSAGE_DELTA, "message:msg-1:0", "开始改"),
    ]
    assert messages
    assert messages[-1].payload.get("text") == "开始改"
    assert messages[-1].payload.get("reasoning") == "先读图"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_terminal_recovery_commits_the_completed_streaming_reply(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    from sqlalchemy import select

    _run, lease = _running(sqlite_session)
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
                    "message.delta",
                    {
                        "text": "当前工作流画布是空的。",
                        "delta": "当前工作流画布是空的。",
                        "message_id": "msg-final",
                        "delta_index": 0,
                    },
                ),
                (
                    "turn_complete",
                    {
                        "_recovery_messages": [
                            _assistant_recovery(text="当前工作流画布是空的。", message_id="msg-final")
                        ],
                    },
                ),
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
    assert [(message.status, message.payload.get("text")) for message in messages] == [
        ("completed", "当前工作流画布是空的。")
    ]


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


def _pending_ask_user_recovery(*, sequence: int = 3) -> dict:
    return {
        "sequence": sequence,
        "role": "assistant",
        "event_type": "tool_call",
        "status": "pending",
        "payload": {
            "id": "ask-1",
            "name": "ask_user",
            "arguments": {"questions": [{"id": "q1", "prompt": "要我改吗？"}]},
        },
    }


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_waiting_user_keeps_streamed_prose_and_pending_ask_user(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    from sqlalchemy import select

    _run, lease = _running(sqlite_session)
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
                    "message.delta",
                    {
                        "text": "当前工作流是 start → retrieval → agent。",
                        "delta": "当前工作流是 start → retrieval → agent。",
                        "message_id": "msg-final",
                        "delta_index": 0,
                    },
                ),
                (
                    "waiting_user",
                    {
                        "tool_call_id": "ask-1",
                        "questions": [{"id": "q1", "prompt": "要我改吗？"}],
                        "_recovery_messages": [
                            _assistant_recovery(
                                text="当前工作流是 start → retrieval → agent。",
                                message_id="msg-final",
                            ),
                            _pending_ask_user_recovery(),
                        ],
                    },
                ),
            ]
        ),
    )

    sqlite_session.expire_all()
    messages = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage)
            .where(WorkflowAssistMessage.conversation_id == lease.owner.conversation_id)
            .order_by(WorkflowAssistMessage.sequence)
        )
    )
    persisted = sqlite_session.get(WorkflowAssistRun, _run.id)
    assert outcome is WorkflowAssistRunStatus.WAITING_USER
    assert persisted is not None
    assert persisted.status is WorkflowAssistRunStatus.WAITING_USER
    assert [
        (
            message.sequence,
            message.event_type,
            message.status,
            message.payload.get("text") or message.payload.get("name"),
        )
        for message in messages
        if message.role == "assistant"
    ] == [
        (2, "message", "completed", "当前工作流是 start → retrieval → agent。"),
        (3, "tool_call", "pending", "ask_user"),
    ]
