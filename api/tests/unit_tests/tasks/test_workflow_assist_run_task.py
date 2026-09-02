"""Durable Workflow Assist worker tests.

The real Agent loop is injected at the worker boundary so these tests exercise
database leases and event durability without replacing coordinator behavior.
"""

from __future__ import annotations

import builtins
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from libs.datetime_utils import naive_utc_now
from models import Account, App, TenantAccountJoin
from models.account import AccountStatus
from models.model import AppMode
from models.workflow_assist import (
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
    WorkflowAssistRunEventType,
    WorkflowAssistRunStatus,
)
from services.workflow_assist.chat import MessageDeltaAggregator, WorkflowAssistRunInitializationError
from services.workflow_assist.conversations import WorkflowAssistConversationService
from services.workflow_assist.run_coordinator import RunCoordinator
from services.workflow_assist.run_types import AgentResponseOutbox, RunOwner, UserAbortFence
from services.workflow_assist.service import WorkflowAssistService
from tasks import workflow_assist_run_reaper_task as reaper_module
from tasks import workflow_assist_run_task as task_module

TABLES = (
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
    App,
    Account,
    TenantAccountJoin,
)


def _is_first_message_delta_step(step_id: object) -> bool:
    if not isinstance(step_id, str) or not step_id.startswith("message:"):
        return False
    return step_id.rsplit(":", 1)[-1] == "0"


class _NoopHeartbeat:
    def __init__(self, *_args: object) -> None:
        pass

    def __enter__(self) -> _NoopHeartbeat:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def fenced(self) -> bool:
        return False


class _OnePulseStop:
    def __init__(self) -> None:
        self.calls = 0

    def wait(self, _seconds: float) -> bool:
        self.calls += 1
        return self.calls > 1


def _owner() -> RunOwner:
    return RunOwner(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
        conversation_id="conversation-1",
    )


def _queued_run(session: Session) -> WorkflowAssistRun:
    conversation = WorkflowAssistConversationService(session).create(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
    )
    conversation.id = "conversation-1"
    session.flush()
    run = RunCoordinator(session).start_turn(
        owner=_owner(),
        message="Build a support workflow",
        mode="workflow",
        model_config={"provider": "test"},
    )
    session.commit()
    return run


def _seed_real_runner_owner(session: Session, run: WorkflowAssistRun, *, graph: dict | None = None) -> None:
    app = App(
        id="app-1",
        tenant_id="tenant-1",
        name="Workflow",
        mode=AppMode.WORKFLOW,
        icon_type=None,
        icon=None,
        icon_background=None,
        enable_site=False,
        enable_api=False,
    )
    account = Account(name="Editor", email="editor@example.com", status=AccountStatus.ACTIVE)
    account.id = "account-1"
    membership = TenantAccountJoin(tenant_id="tenant-1", account_id="account-1")
    conversation = session.get(WorkflowAssistConversation, "conversation-1")
    assert conversation is not None
    conversation.candidate_graph = graph
    conversation.candidate_base_hash = "a" * 64
    run.model_config = {
        "provider": "test/provider",
        "name": "test-model",
        "mode": "chat",
        "completion_params": {},
    }
    session.add_all([app, account, membership])
    session.commit()


def _task_coordinates(run: WorkflowAssistRun) -> dict[str, object]:
    return {
        "tenant_id": "tenant-1",
        "app_id": "app-1",
        "account_id": "account-1",
        "conversation_id": "conversation-1",
        "run_id": run.id,
        "epoch": run.epoch,
    }


def _run_task_delivery(*, coordinates: dict[str, object], redelivered: bool = False) -> None:
    task_module.execute_workflow_assist_run.push_request(id="delivery-1", redelivered=redelivered)
    try:
        task_module.execute_workflow_assist_run.run(**coordinates)
    finally:
        task_module.execute_workflow_assist_run.pop_request()


def test_message_deltas_flush_at_time_or_utf8_byte_threshold() -> None:
    aggregator = MessageDeltaAggregator(interval_seconds=0.25, max_bytes=8)

    assert aggregator.push("你", now=0.0) == []
    assert aggregator.push("好", now=0.10) == []
    assert aggregator.push("!", now=0.25) == ["你好!"]

    assert aggregator.push("12345678", now=1.0) == ["12345678"]
    assert aggregator.push("x", now=1.1) == []
    assert aggregator.flush() == "x"


def test_message_delta_chunks_never_exceed_the_aggregation_limit() -> None:
    aggregator = MessageDeltaAggregator(interval_seconds=0.25, max_bytes=8)

    chunks = [*aggregator.push("你好世界", now=0.0), aggregator.flush()]

    assert chunks == ["你好", "世界"]
    assert all(len(chunk.encode("utf-8")) <= 8 for chunk in chunks)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_message_delta_step_ids_use_message_id_and_delta_index(sqlite_session: Session, monkeypatch) -> None:
    run = _queued_run(sqlite_session)
    lease = RunCoordinator(sqlite_session).claim(
        owner=_owner(),
        run_id=run.id,
        epoch=run.epoch,
        worker_id="worker-1",
    )
    assert lease is not None
    sqlite_session.commit()
    from services.workflow_assist import chat as chat_module

    monkeypatch.setattr(
        chat_module.session_factory,
        "create_session",
        sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False),
    )
    chat_module.persist_agent_events(
        lease=lease,
        events=iter(
            [
                (
                    "message.delta",
                    {
                        "text": "正在",
                        "delta": "正在",
                        "message_id": "msg-1",
                        "delta_index": 0,
                        "stream_mode": "native",
                    },
                ),
                (
                    "message.delta",
                    {
                        "text": "正在",
                        "delta": "正在",
                        "message_id": "msg-1",
                        "delta_index": 0,
                        "stream_mode": "native",
                    },
                ),
                (
                    "message.delta",
                    {
                        "text": "创建",
                        "delta": "创建",
                        "message_id": "msg-1",
                        "delta_index": 1,
                        "stream_mode": "native",
                    },
                ),
                ("turn_complete", {}),
            ]
        ),
    )
    sqlite_session.expire_all()
    deltas = list(
        sqlite_session.scalars(
            select(WorkflowAssistRunEvent)
            .where(
                WorkflowAssistRunEvent.run_id == run.id,
                WorkflowAssistRunEvent.event == WorkflowAssistRunEventType.MESSAGE_DELTA,
            )
            .order_by(WorkflowAssistRunEvent.sequence)
        )
    )
    assert [event.step_id for event in deltas] == ["message:msg-1:0", "message:msg-1:1"]
    assert deltas[0].payload["message_id"] == "msg-1"
    assert deltas[0].payload["delta_index"] == 0
    assert deltas[1].payload["message_id"] == "msg-1"
    assert deltas[1].payload["delta_index"] == 1
    assert deltas[0].payload.get("stream_mode") == "native"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_worker_claims_then_records_initialization_failure_when_app_is_missing(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    run = _queued_run(sqlite_session)
    maker = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(task_module.session_factory, "create_session", maker)
    invoked = False

    def runner(_context):
        nonlocal invoked
        invoked = True
        return iter(())

    task_module._execute_workflow_assist_run(
        owner=_owner(),
        run_id=run.id,
        epoch=run.epoch,
        worker_id="worker-1",
        agent_runner=runner,
        heartbeat_factory=_NoopHeartbeat,
    )

    sqlite_session.expire_all()
    persisted = sqlite_session.scalar(select(WorkflowAssistRun).where(WorkflowAssistRun.id == run.id))
    assert persisted is not None
    assert persisted.status is WorkflowAssistRunStatus.ERROR
    assert persisted.termination_reason == "run_initialization_failed"
    assert invoked is False
    terminal = sqlite_session.scalar(
        select(WorkflowAssistRunEvent).where(
            WorkflowAssistRunEvent.run_id == run.id,
            WorkflowAssistRunEvent.event == WorkflowAssistRunEventType.ERROR,
        )
    )
    assert terminal is not None
    assert terminal.payload == {"status": "error", "reason": "run_initialization_failed"}


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_worker_rejects_active_account_without_tenant_membership(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    run = _queued_run(sqlite_session)
    app = App(
        id="app-1",
        tenant_id="tenant-1",
        name="Workflow",
        mode=AppMode.WORKFLOW,
        icon_type=None,
        icon=None,
        icon_background=None,
        enable_site=False,
        enable_api=False,
    )
    account = Account(name="Editor", email="editor@example.com", status=AccountStatus.ACTIVE)
    account.id = "account-1"
    sqlite_session.add_all([app, account])
    sqlite_session.commit()
    maker = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(task_module.session_factory, "create_session", maker)
    invoked = False

    def runner(_context):
        nonlocal invoked
        invoked = True
        yield "waiting_user", {"tool_call_id": "ask", "questions": []}

    task_module._execute_workflow_assist_run(
        owner=_owner(),
        run_id=run.id,
        epoch=run.epoch,
        worker_id="worker-1",
        agent_runner=runner,
        heartbeat_factory=_NoopHeartbeat,
    )

    sqlite_session.expire_all()
    persisted = sqlite_session.get(WorkflowAssistRun, run.id)
    assert persisted is not None
    assert persisted.termination_reason == "run_initialization_failed"
    assert invoked is False


def test_celery_worker_is_pinned_to_conversation_queue() -> None:
    assert task_module.execute_workflow_assist_run.queue == "conversation"
    assert task_module.execute_workflow_assist_run.acks_late is True
    assert task_module.execute_workflow_assist_run.reject_on_worker_lost is True


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_task_entrypoint_redelivery_with_same_delivery_id_converges_after_crash_after_step(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    run = _queued_run(sqlite_session)
    maker = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(task_module.session_factory, "create_session", maker)
    monkeypatch.setattr(task_module, "_load_context", lambda **_kwargs: object())

    from services.workflow_assist import chat as chat_module

    class WorkerCrash(BaseException):
        pass

    delivery = 0
    text = "x" * 8192

    def runner(_context):
        nonlocal delivery
        delivery += 1
        yield (
            "message",
            {
                "delta": text,
                "_recovery_messages": [
                    {
                        "sequence": 2,
                        "role": "assistant",
                        "event_type": "message",
                        "status": "completed",
                        "payload": {"text": text},
                    }
                ],
            },
        )
        if delivery == 1:
            raise WorkerCrash()
        yield "error", {"message": "provider stopped", "errors": [], "termination_reason": "provider_error"}

    monkeypatch.setattr(chat_module, "run_workflow_assist_agent", runner)
    coordinates = {
        "tenant_id": "tenant-1",
        "app_id": "app-1",
        "account_id": "account-1",
        "conversation_id": "conversation-1",
        "run_id": run.id,
        "epoch": run.epoch,
    }

    task_module.execute_workflow_assist_run.push_request(id="delivery-1")
    try:
        with pytest.raises(WorkerCrash):
            task_module.execute_workflow_assist_run.run(**coordinates)
    finally:
        task_module.execute_workflow_assist_run.pop_request()
    task_module.execute_workflow_assist_run.push_request(id="delivery-1", redelivered=True)
    try:
        task_module.execute_workflow_assist_run.run(**coordinates)
    finally:
        task_module.execute_workflow_assist_run.pop_request()

    sqlite_session.expire_all()
    persisted = sqlite_session.get(WorkflowAssistRun, run.id)
    assert persisted is not None
    assert persisted.status is WorkflowAssistRunStatus.ERROR
    assert persisted.worker_id == "delivery-1"
    deltas = list(
        sqlite_session.scalars(
            select(WorkflowAssistRunEvent).where(
                WorkflowAssistRunEvent.run_id == run.id,
                WorkflowAssistRunEvent.event == WorkflowAssistRunEventType.MESSAGE_DELTA,
            )
        )
    )
    assert [(event.step_id, event.payload.get("text")) for event in deltas] == [("message:2:0", text)]
    assert deltas[0].payload["message_id"] == "2"
    assert deltas[0].payload["delta_index"] == 0
    messages = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage)
            .where(WorkflowAssistMessage.conversation_id == "conversation-1")
            .order_by(WorkflowAssistMessage.sequence)
        )
    )
    assert [(message.sequence, message.event_type) for message in messages] == [(1, "message"), (2, "message")]


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_real_runner_redelivery_replays_missing_suffix_after_crash_between_large_prose_chunks(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    run = _queued_run(sqlite_session)
    _seed_real_runner_owner(sqlite_session, run)
    maker = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(task_module.session_factory, "create_session", maker)

    from services.workflow_assist import agent_initializer as init_mod
    from services.workflow_assist import chat as chat_module

    monkeypatch.setattr(init_mod, "build_tool_catalogue", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(init_mod, "build_knowledge_catalogue", lambda *_args, **_kwargs: [])
    real_runner = chat_module.run_workflow_assist_agent
    from services.workflow_assist import chat_persistence as persist_mod

    real_commit_step = persist_mod._commit_step

    class WorkerCrash(BaseException):
        pass

    delivery = 0
    prose = "x" * (chat_module.MESSAGE_DELTA_MAX_BYTES * 2)

    class Invoker:
        def invoke(self, _messages):
            return {"text": prose}

    def runner(context):
        nonlocal delivery
        delivery += 1
        events = real_runner(context, invoker=Invoker(), hydrate_graph=lambda value: value)
        for event_name, payload in events:
            yield event_name, payload
            if event_name == "message":
                yield (
                    "error",
                    {
                        "message": "stop after durable prose",
                        "errors": [],
                        "termination_reason": "provider_error",
                    },
                )
                return

    def crash_after_first_chunk(**kwargs):
        committed = real_commit_step(**kwargs)
        if delivery == 1 and _is_first_message_delta_step(kwargs["step_id"]):
            raise WorkerCrash()
        return committed

    monkeypatch.setattr(chat_module, "run_workflow_assist_agent", runner)
    monkeypatch.setattr(persist_mod, "_commit_step", crash_after_first_chunk)
    coordinates = _task_coordinates(run)

    with pytest.raises(WorkerCrash):
        _run_task_delivery(coordinates=coordinates)
    sqlite_session.expire_all()
    after_crash = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage)
            .where(WorkflowAssistMessage.conversation_id == "conversation-1")
            .order_by(WorkflowAssistMessage.sequence)
        )
    )
    assert [(message.sequence, message.event_type, message.status) for message in after_crash] == [
        (1, "message", "completed"),
        (2, "message", "pending"),
    ]
    assert after_crash[1].payload["text"] == prose

    _run_task_delivery(coordinates=coordinates, redelivered=True)

    sqlite_session.expire_all()
    deltas = list(
        sqlite_session.scalars(
            select(WorkflowAssistRunEvent)
            .where(
                WorkflowAssistRunEvent.run_id == run.id,
                WorkflowAssistRunEvent.event == WorkflowAssistRunEventType.MESSAGE_DELTA,
            )
            .order_by(WorkflowAssistRunEvent.sequence)
        )
    )
    assert [len(event.payload["text"]) for event in deltas] == [
        chat_module.MESSAGE_DELTA_MAX_BYTES,
        chat_module.MESSAGE_DELTA_MAX_BYTES,
    ]
    assert deltas[0].step_id.startswith("message:")
    assert deltas[0].step_id.rsplit(":", 1)[-1] == "0"
    assert deltas[1].step_id.startswith("message:")
    assert deltas[1].step_id.rsplit(":", 1)[-1] == "1"
    assert deltas[0].payload["message_id"] == deltas[1].payload["message_id"]
    assert deltas[0].payload["delta_index"] == 0
    assert deltas[1].payload["delta_index"] == 1
    messages = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage)
            .where(WorkflowAssistMessage.conversation_id == "conversation-1")
            .order_by(WorkflowAssistMessage.sequence)
        )
    )
    assert [(message.sequence, message.event_type, message.payload) for message in messages] == [
        (1, "message", {"text": "Build a support workflow"}),
        (2, "message", {"text": prose}),
    ]


@pytest.mark.parametrize("replayed_prose", ["y" * (8192 * 2), "short replay"])
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_real_task_redelivery_freezes_large_prose_before_first_chunk(
    sqlite_session: Session,
    monkeypatch,
    replayed_prose: str,
) -> None:
    run = _queued_run(sqlite_session)
    _seed_real_runner_owner(sqlite_session, run)
    maker = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(task_module.session_factory, "create_session", maker)

    from services.workflow_assist import agent_initializer as init_mod
    from services.workflow_assist import chat as chat_module

    monkeypatch.setattr(init_mod, "build_tool_catalogue", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(init_mod, "build_knowledge_catalogue", lambda *_args, **_kwargs: [])
    real_runner = chat_module.run_workflow_assist_agent
    from services.workflow_assist import chat_persistence as persist_mod

    real_commit_step = persist_mod._commit_step

    class WorkerCrash(BaseException):
        pass

    original_prose = "x" * (chat_module.MESSAGE_DELTA_MAX_BYTES * 2)
    delivery = 0
    invocations = [0, 0]

    class Invoker:
        def invoke(self, _messages):
            invocations[delivery - 1] += 1
            return {"text": original_prose if delivery == 1 else replayed_prose}

    def runner(context):
        nonlocal delivery
        delivery += 1
        events = real_runner(context, invoker=Invoker(), hydrate_graph=lambda value: value)
        for event_name, payload in events:
            yield event_name, payload
            if event_name == "message":
                yield (
                    "error",
                    {
                        "message": "stop after durable prose",
                        "errors": [],
                        "termination_reason": "provider_error",
                    },
                )
                return

    def crash_after_first_chunk(**kwargs):
        committed = real_commit_step(**kwargs)
        if delivery == 1 and _is_first_message_delta_step(kwargs["step_id"]):
            raise WorkerCrash()
        return committed

    monkeypatch.setattr(chat_module, "run_workflow_assist_agent", runner)
    monkeypatch.setattr(persist_mod, "_commit_step", crash_after_first_chunk)
    coordinates = _task_coordinates(run)

    with pytest.raises(WorkerCrash):
        _run_task_delivery(coordinates=coordinates)
    _run_task_delivery(coordinates=coordinates, redelivered=True)

    sqlite_session.expire_all()
    deltas = list(
        sqlite_session.scalars(
            select(WorkflowAssistRunEvent)
            .where(
                WorkflowAssistRunEvent.run_id == run.id,
                WorkflowAssistRunEvent.event == WorkflowAssistRunEventType.MESSAGE_DELTA,
            )
            .order_by(WorkflowAssistRunEvent.sequence)
        )
    )
    assert "".join(str(event.payload["text"]) for event in deltas) == original_prose
    messages = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage)
            .where(WorkflowAssistMessage.conversation_id == "conversation-1")
            .order_by(WorkflowAssistMessage.sequence)
        )
    )
    assert [(message.sequence, message.status, message.payload) for message in messages] == [
        (1, "completed", {"text": "Build a support workflow"}),
        (2, "completed", {"text": original_prose}),
    ]
    assert invocations == [1, 0]


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_provider_failure_after_staged_prose_does_not_poison_the_next_turn(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    old_run = _queued_run(sqlite_session)
    _seed_real_runner_owner(sqlite_session, old_run)
    maker = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(task_module.session_factory, "create_session", maker)

    from services.workflow_assist import agent_initializer as init_mod
    from services.workflow_assist import chat as chat_module

    monkeypatch.setattr(init_mod, "build_tool_catalogue", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(init_mod, "build_knowledge_catalogue", lambda *_args, **_kwargs: [])
    real_runner = chat_module.run_workflow_assist_agent
    from services.workflow_assist import chat_persistence as persist_mod

    real_commit_step = persist_mod._commit_step
    old_prose = "old-response" * chat_module.MESSAGE_DELTA_MAX_BYTES
    fail_commit_once = True
    new_model_calls = 0

    class OldInvoker:
        def invoke(self, _messages):
            return {"text": old_prose}

    class NewInvoker:
        def invoke(self, _messages):
            nonlocal new_model_calls
            new_model_calls += 1
            return {"tool_calls": [{"name": "fail", "arguments": {"reason": "new turn reached model"}}]}

    def runner(context):
        invoker = OldInvoker() if context.run.id == old_run.id else NewInvoker()
        return real_runner(context, invoker=invoker, hydrate_graph=lambda value: value)

    def provider_failure_after_first_delta(**kwargs):
        nonlocal fail_commit_once
        committed = real_commit_step(**kwargs)
        if fail_commit_once and _is_first_message_delta_step(kwargs["step_id"]):
            fail_commit_once = False
            raise RuntimeError("provider stream failed after first durable delta")
        return committed

    monkeypatch.setattr(chat_module, "run_workflow_assist_agent", runner)
    monkeypatch.setattr(persist_mod, "_commit_step", provider_failure_after_first_delta)

    _run_task_delivery(coordinates=_task_coordinates(old_run))
    sqlite_session.expire_all()
    terminated = sqlite_session.get(WorkflowAssistRun, old_run.id)
    assert terminated is not None
    assert terminated.status is WorkflowAssistRunStatus.ERROR
    assert terminated.termination_reason == "provider_error"

    new_run = RunCoordinator(sqlite_session).start_turn(
        owner=_owner(),
        message="Build the replacement workflow",
        mode="workflow",
        model_config={"provider": "test/provider", "name": "test-model", "mode": "chat", "completion_params": {}},
    )
    sqlite_session.commit()
    _run_task_delivery(coordinates=_task_coordinates(new_run))

    sqlite_session.expire_all()
    new_persisted = sqlite_session.get(WorkflowAssistRun, new_run.id)
    assert new_persisted is not None
    assert new_persisted.status is WorkflowAssistRunStatus.FAILED
    assert new_model_calls == 1
    messages = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage)
            .where(WorkflowAssistMessage.conversation_id == "conversation-1")
            .order_by(WorkflowAssistMessage.sequence)
        )
    )
    assert not any(message.status == "pending" for message in messages)
    assert not any(
        message.status == "completed" and old_prose in str(message.payload) for message in messages
    )
    new_events = list(
        sqlite_session.scalars(select(WorkflowAssistRunEvent).where(WorkflowAssistRunEvent.run_id == new_run.id))
    )
    assert old_prose not in str([event.payload for event in new_events])


@pytest.mark.parametrize("lifecycle", ["fence", "reaper", "supersede"])
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_abandoned_response_lifecycles_isolate_the_next_run_owner(
    sqlite_session: Session,
    monkeypatch,
    lifecycle: str,
) -> None:
    old_run = _queued_run(sqlite_session)
    _seed_real_runner_owner(sqlite_session, old_run)
    coordinator = RunCoordinator(sqlite_session)
    lease = coordinator.claim(
        owner=_owner(),
        run_id=old_run.id,
        epoch=old_run.epoch,
        worker_id="delivery-old",
    )
    assert lease is not None
    assert (
        coordinator.stage_agent_response(
            lease=lease,
            response=AgentResponseOutbox(sequence=2, payload={"text": "stale full response"}, checkpoint=None),
        )
        is not None
    )
    staged = sqlite_session.scalar(
        select(WorkflowAssistMessage).where(
            WorkflowAssistMessage.conversation_id == "conversation-1",
            WorkflowAssistMessage.sequence == 2,
        )
    )
    assert staged is not None
    assert staged.payload["__agent_response_outbox"] == {
        "run_id": old_run.id,
        "epoch": old_run.epoch,
        "worker_id": "delivery-old",
        "checkpoint": None,
    }
    sqlite_session.commit()
    maker = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(task_module.session_factory, "create_session", maker)
    monkeypatch.setattr(reaper_module.session_factory, "create_session", maker)

    if lifecycle == "fence":
        assert coordinator.terminate(
            lease=UserAbortFence(owner=_owner(), run_id=old_run.id, epoch=old_run.epoch),
            status=WorkflowAssistRunStatus.ABORTED,
            step_id="terminal:user-abort",
            payload={"status": "aborted", "reason": "user_abort"},
            reason="user_abort",
        )
        sqlite_session.commit()
    elif lifecycle == "reaper":
        now = naive_utc_now()
        old_run.heartbeat_at = now - timedelta(seconds=61)
        sqlite_session.commit()
        assert (
            reaper_module.reap_stale_workflow_assist_runs(
                now=now,
                queue_timeout_seconds=120,
                heartbeat_timeout_seconds=60,
                batch_size=100,
            )
            == 1
        )

    if lifecycle == "supersede":
        new_run = coordinator.start_turn(
            owner=_owner(),
            message="New owner turn",
            mode="workflow",
            model_config={"provider": "test/provider", "name": "test-model", "mode": "chat"},
        )
    else:
        sqlite_session.expire_all()
        new_run = RunCoordinator(sqlite_session).start_turn(
            owner=_owner(),
            message="New owner turn",
            mode="workflow",
            model_config={"provider": "test/provider", "name": "test-model", "mode": "chat"},
        )
    sqlite_session.commit()

    from services.workflow_assist import agent_initializer as init_mod
    from services.workflow_assist import chat as chat_module

    monkeypatch.setattr(init_mod, "build_tool_catalogue", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(init_mod, "build_knowledge_catalogue", lambda *_args, **_kwargs: [])
    real_runner = chat_module.run_workflow_assist_agent
    model_calls = 0

    class Invoker:
        def invoke(self, _messages):
            nonlocal model_calls
            model_calls += 1
            return {"tool_calls": [{"name": "fail", "arguments": {"reason": "new owner executed"}}]}

    monkeypatch.setattr(
        chat_module,
        "run_workflow_assist_agent",
        lambda context: real_runner(context, invoker=Invoker(), hydrate_graph=lambda value: value),
    )
    _run_task_delivery(coordinates=_task_coordinates(new_run))

    sqlite_session.expire_all()
    persisted = sqlite_session.get(WorkflowAssistRun, new_run.id)
    assert persisted is not None
    assert persisted.status is WorkflowAssistRunStatus.FAILED
    assert model_calls == 1
    messages = list(
        sqlite_session.scalars(
            select(WorkflowAssistMessage)
            .where(WorkflowAssistMessage.conversation_id == "conversation-1")
            .order_by(WorkflowAssistMessage.sequence)
        )
    )
    assert not any(message.status == "pending" for message in messages)
    assert not any(
        message.status == "completed"
        and message.event_type == "message"
        and isinstance(message.payload, dict)
        and message.payload.get("text") == "stale full response"
        for message in messages
    )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_worker_terminates_when_agent_adapter_import_fails(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    run = _queued_run(sqlite_session)
    maker = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(task_module.session_factory, "create_session", maker)
    monkeypatch.setattr(task_module, "_load_context", lambda **_kwargs: object())
    real_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "services.workflow_assist.chat":
            raise ImportError("cannot import name 'PROMPT_SKIP_RANGES_KEY'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    task_module._execute_workflow_assist_run(
        owner=_owner(),
        run_id=run.id,
        epoch=run.epoch,
        worker_id="worker-1",
        heartbeat_factory=_NoopHeartbeat,
    )

    sqlite_session.expire_all()
    persisted = sqlite_session.get(WorkflowAssistRun, run.id)
    assert persisted is not None
    assert persisted.status is WorkflowAssistRunStatus.ERROR
    assert persisted.termination_reason == "run_initialization_failed"


@pytest.mark.parametrize(
    ("exception", "expected_reason"),
    [
        (WorkflowAssistRunInitializationError("catalog unavailable"), "run_initialization_failed"),
        (RuntimeError("provider unavailable"), "provider_error"),
    ],
)
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_worker_maps_initialization_and_provider_failures_to_distinct_terminal_reasons(
    sqlite_session: Session,
    monkeypatch,
    exception: Exception,
    expected_reason: str,
) -> None:
    run = _queued_run(sqlite_session)
    maker = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(task_module.session_factory, "create_session", maker)
    monkeypatch.setattr(task_module, "_load_context", lambda **_kwargs: object())

    def runner(_context):
        raise exception
        yield  # pragma: no cover

    task_module._execute_workflow_assist_run(
        owner=_owner(),
        run_id=run.id,
        epoch=run.epoch,
        worker_id="worker-1",
        agent_runner=runner,
        heartbeat_factory=_NoopHeartbeat,
    )

    sqlite_session.expire_all()
    persisted = sqlite_session.get(WorkflowAssistRun, run.id)
    assert persisted is not None
    assert persisted.status is WorkflowAssistRunStatus.ERROR
    assert persisted.termination_reason == expected_reason


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_worker_provider_crash_persists_exception_text(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    run = _queued_run(sqlite_session)
    maker = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(task_module.session_factory, "create_session", maker)
    monkeypatch.setattr(task_module, "_load_context", lambda **_kwargs: object())

    def runner(_context):
        raise RuntimeError("Connection to api.deepseek.com timed out. (connect timeout=10)")
        yield  # pragma: no cover

    task_module._execute_workflow_assist_run(
        owner=_owner(),
        run_id=run.id,
        epoch=run.epoch,
        worker_id="worker-1",
        agent_runner=runner,
        heartbeat_factory=_NoopHeartbeat,
    )

    sqlite_session.expire_all()
    event = sqlite_session.scalar(
        select(WorkflowAssistRunEvent).where(
            WorkflowAssistRunEvent.run_id == run.id,
            WorkflowAssistRunEvent.event == WorkflowAssistRunEventType.ERROR,
        )
    )
    assert event is not None
    assert "deepseek.com" in str(event.payload.get("message"))
    errors = event.payload.get("errors")
    assert isinstance(errors, list)
    assert errors
    assert "deepseek.com" in str(errors[0].get("detail"))


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_heartbeat_uses_a_short_session_and_refreshes_the_claim(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    run = _queued_run(sqlite_session)
    lease = RunCoordinator(sqlite_session).claim(owner=_owner(), run_id=run.id, epoch=run.epoch, worker_id="worker-1")
    assert lease is not None
    sqlite_session.commit()
    previous = run.heartbeat_at
    maker = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(task_module.session_factory, "create_session", maker)
    heartbeat = task_module.LeaseHeartbeat(lease, interval_seconds=10)
    heartbeat._stop = _OnePulseStop()  # type: ignore[assignment]

    heartbeat._run()

    sqlite_session.expire_all()
    persisted = sqlite_session.get(WorkflowAssistRun, run.id)
    assert persisted is not None
    assert persisted.heartbeat_at is not None
    assert previous is not None
    assert persisted.heartbeat_at >= previous
    assert heartbeat.fenced() is False


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_service_dispatches_only_durable_run_coordinates(sqlite_session: Session, monkeypatch) -> None:
    run = _queued_run(sqlite_session)
    dispatched: list[dict[str, object]] = []
    monkeypatch.setattr(task_module.execute_workflow_assist_run, "delay", lambda **kwargs: dispatched.append(kwargs))

    WorkflowAssistService.dispatch_run(run)

    assert dispatched == [
        {
            "tenant_id": "tenant-1",
            "app_id": "app-1",
            "account_id": "account-1",
            "conversation_id": "conversation-1",
            "run_id": run.id,
            "epoch": run.epoch,
        }
    ]
