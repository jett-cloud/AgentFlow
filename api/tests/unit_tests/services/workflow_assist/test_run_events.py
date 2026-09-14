from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from models.workflow_assist import (
    WorkflowAssistCompletionAssertion,
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistMode,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
    WorkflowAssistRunEventType,
    WorkflowAssistRunStatus,
)
from services.workflow_assist.conversations import (
    WorkflowAssistConversationNotFound,
)
from services.workflow_assist.run_events import (
    EventEnvelope,
    WorkflowAssistRunEventService,
    WorkflowAssistRunEventStream,
)
from services.workflow_assist.run_types import RunOwner

TABLES = (WorkflowAssistConversation, WorkflowAssistMessage, WorkflowAssistRun, WorkflowAssistRunEvent)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_compact_timeline_preserves_text_boundaries_and_exact_resume_cursor(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    run = _create_run(sqlite_session, epoch=1, message="request")
    facts = [
        ("reasoning.delta", "a", "先"),
        ("reasoning.delta", "a", "思考"),
        ("message.delta", "a", "你好"),
        ("message.delta", "a", "🌈"),
        ("message.delta", "b", "下一条"),
        ("tool_call", "", ""),
        ("message.delta", "b", "工具之后"),
    ]
    for sequence, (event, message_id, text) in enumerate(facts, start=1):
        _create_event(
            sqlite_session,
            run=run,
            sequence=sequence,
            event=WorkflowAssistRunEventType(event),
            payload={"message_id": message_id, "text": text, "delta_index": sequence},
        )
    sqlite_session.commit()
    service = WorkflowAssistRunEventService(sqlite_session)

    page = service.timeline(owner=_owner(), after_epoch=0, after_sequence=0, limit=3, compact=True)

    assert [(item.event, item.sequence, item.data.get("text")) for item in page.items] == [
        ("user.message", 0, "request"),
        ("reasoning.delta", 2, "先思考"),
        ("message.delta", 4, "你好🌈"),
    ]
    assert page.items[1].data["sequence_start"] == 1
    assert page.items[2].data["sequence_start"] == 3
    assert (page.cursor_epoch, page.cursor_sequence, page.has_more) == (1, 4, True)
    tail = service.timeline(owner=_owner(), after_epoch=1, after_sequence=4, limit=3, compact=True)
    assert [(item.event, item.sequence) for item in tail.items] == [
        ("message.delta", 5),
        ("tool_call", 6),
        ("message.delta", 7),
    ]
    assert not tail.has_more
    # Compaction is read-only: SSE and durable records retain their original identity.
    raw = service.list_events(owner=_owner(), run_id=run.id, after=0)
    assert len(raw) == 7
    assert raw[0].data["text"] == "先"
    assert "sequence_start" not in raw[0].data


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_compact_timeline_bounds_raw_scan_without_losing_page_tail(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    run = _create_run(sqlite_session, epoch=1, message="request")
    sqlite_session.add_all(
        [
            WorkflowAssistRunEvent(
                tenant_id=run.tenant_id,
                app_id=run.app_id,
                created_by=run.created_by,
                conversation_id=run.conversation_id,
                run_id=run.id,
                epoch=1,
                sequence=sequence,
                step_id=f"delta-{sequence}",
                event=WorkflowAssistRunEventType.REASONING_DELTA,
                payload={"message_id": "a", "text": "思", "delta_index": sequence},
            )
            for sequence in range(1, 10_006)
        ]
    )
    sqlite_session.commit()
    service = WorkflowAssistRunEventService(sqlite_session)

    page = service.timeline(owner=_owner(), after_epoch=0, after_sequence=0, limit=500, compact=True)
    assert page.has_more
    assert 0 < page.cursor_sequence <= 10_000
    tail = service.timeline(
        owner=_owner(),
        after_epoch=page.cursor_epoch,
        after_sequence=page.cursor_sequence,
        limit=500,
        compact=True,
    )
    assert not tail.has_more
    assert tail.cursor_sequence == 10_005
    chunks = [item.data["text"] for item in (*page.items, *tail.items) if item.event == "reasoning.delta"]
    assert "".join(chunks) == "思" * 10_005
    assert len(chunks) < 10


class _MaterializedEventResult:
    """Return the pre-commit event snapshot after the test injects a terminal commit."""

    rows: list[WorkflowAssistRunEvent]

    def __init__(self, rows: list[WorkflowAssistRunEvent]) -> None:
        self.rows = rows

    def all(self) -> list[WorkflowAssistRunEvent]:
        return self.rows


def _terminal_race_session_maker(sqlite_session: Session, control: dict[str, bool]):
    """Create sessions that deterministically commit terminal state after an event SELECT."""

    class TerminalRaceSession(Session):
        def scalars(self, statement, *args: Any, **kwargs: Any):
            result = super().scalars(statement, *args, **kwargs)
            entity = statement.column_descriptions[0].get("entity")
            if entity is not WorkflowAssistRunEvent or not control["armed"]:
                return result

            rows = list(result.all())
            control["armed"] = False
            run = self.scalar(select(WorkflowAssistRun).where(WorkflowAssistRun.conversation_id == "conversation-1"))
            assert run is not None
            run.status = WorkflowAssistRunStatus.DONE
            self.add(
                WorkflowAssistRunEvent(
                    tenant_id=run.tenant_id,
                    app_id=run.app_id,
                    created_by=run.created_by,
                    conversation_id=run.conversation_id,
                    run_id=run.id,
                    epoch=run.epoch,
                    sequence=1,
                    step_id="terminal-race",
                    event=WorkflowAssistRunEventType.DONE,
                    payload={"status": "done"},
                )
            )
            self.commit()
            return _MaterializedEventResult(rows)

    return sessionmaker(bind=sqlite_session.get_bind(), class_=TerminalRaceSession, expire_on_commit=False)


def _owner(**overrides: str) -> RunOwner:
    values = {
        "tenant_id": "tenant-1",
        "app_id": "app-1",
        "account_id": "account-1",
        "conversation_id": "conversation-1",
    }
    values.update(overrides)
    return RunOwner(**values)


def _create_conversation(session: Session, *, owner: RunOwner | None = None) -> WorkflowAssistConversation:
    scope = owner or _owner()
    conversation = WorkflowAssistConversation(
        id=scope.conversation_id,
        tenant_id=scope.tenant_id,
        app_id=scope.app_id,
        account_id=scope.account_id,
        title="Assist",
        state={},
    )
    session.add(conversation)
    session.flush()
    return conversation


def _create_run(
    session: Session,
    *,
    owner: RunOwner | None = None,
    epoch: int,
    message: str,
    status: WorkflowAssistRunStatus = WorkflowAssistRunStatus.RUNNING,
) -> WorkflowAssistRun:
    scope = owner or _owner()
    run = WorkflowAssistRun(
        tenant_id=scope.tenant_id,
        app_id=scope.app_id,
        created_by=scope.account_id,
        conversation_id=scope.conversation_id,
        epoch=epoch,
        status=status,
        input=message,
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={},
    )
    session.add(run)
    session.flush()
    return run


def _create_event(
    session: Session,
    *,
    run: WorkflowAssistRun,
    sequence: int,
    event: WorkflowAssistRunEventType,
    payload: dict[str, object],
) -> WorkflowAssistRunEvent:
    record = WorkflowAssistRunEvent(
        tenant_id=run.tenant_id,
        app_id=run.app_id,
        created_by=run.created_by,
        conversation_id=run.conversation_id,
        run_id=run.id,
        epoch=run.epoch,
        sequence=sequence,
        step_id=f"step-{run.epoch}-{sequence}",
        event=event,
        payload=payload,
    )
    session.add(record)
    session.flush()
    return record


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_runs_page_is_strictly_ascending_and_bounded_after_epoch(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    runs = [_create_run(sqlite_session, epoch=epoch, message=f"turn-{epoch}") for epoch in (3, 1, 4, 2)]
    sqlite_session.commit()

    page = WorkflowAssistRunEventService(sqlite_session).list_runs(owner=_owner(), after_epoch=1, limit=2)

    assert [item.epoch for item in page.items] == [2, 3]
    assert page.has_more
    assert page.next_after_epoch == 3
    assert {item.run_id for item in page.items} == {runs[3].id, runs[0].id}
    assert all(not hasattr(item, "events") for item in page.items)


@pytest.mark.parametrize(
    ("method", "kwargs", "message"),
    [
        ("list_runs", {"after_epoch": -1, "limit": 50}, "after_epoch"),
        ("list_runs", {"after_epoch": 0, "limit": 0}, "limit"),
        ("list_runs", {"after_epoch": 0, "limit": 101}, "limit"),
        ("timeline", {"after_epoch": -1, "after_sequence": 0, "limit": 200}, "after_epoch"),
        ("timeline", {"after_epoch": 0, "after_sequence": -1, "limit": 200}, "after_sequence"),
        ("timeline", {"after_epoch": 0, "after_sequence": 0, "limit": 501}, "limit"),
        ("list_events", {"run_id": "run-1", "after": -1}, "after"),
    ],
)
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_read_methods_reject_invalid_cursors_and_limits(
    sqlite_session: Session,
    method: str,
    kwargs: dict[str, object],
    message: str,
) -> None:
    service = WorkflowAssistRunEventService(sqlite_session)

    with pytest.raises(ValueError, match=message):
        getattr(service, method)(owner=_owner(), **kwargs)


@pytest.mark.parametrize(
    "unauthorized_owner",
    [
        _owner(tenant_id="tenant-2"),
        _owner(app_id="app-2"),
        _owner(account_id="account-2"),
        _owner(conversation_id="conversation-2"),
    ],
)
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_every_conversation_owner_dimension_is_required(
    sqlite_session: Session,
    unauthorized_owner: RunOwner,
) -> None:
    conversation = _create_conversation(sqlite_session)
    run = _create_run(sqlite_session, epoch=1, message="owned")
    conversation.latest_run_id = run.id
    sqlite_session.commit()
    service = WorkflowAssistRunEventService(sqlite_session)

    calls = (
        lambda: service.list_runs(owner=unauthorized_owner, after_epoch=0, limit=50),
        lambda: service.timeline(owner=unauthorized_owner, after_epoch=0, after_sequence=0, limit=200),
        lambda: service.get_candidate(owner=unauthorized_owner),
        lambda: service.list_events(owner=unauthorized_owner, run_id=run.id, after=0),
    )
    for call in calls:
        with pytest.raises(WorkflowAssistConversationNotFound):
            call()


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_run_lookup_rejects_a_run_from_another_owner(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    other_owner = _owner(account_id="account-2", conversation_id="conversation-2")
    _create_conversation(sqlite_session, owner=other_owner)
    other_run = _create_run(sqlite_session, owner=other_owner, epoch=1, message="hidden")
    sqlite_session.commit()

    with pytest.raises(WorkflowAssistConversationNotFound):
        WorkflowAssistRunEventService(sqlite_session).list_events(owner=_owner(), run_id=other_run.id, after=0)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_timeline_merges_user_messages_and_events_in_lexicographic_order(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    first = _create_run(sqlite_session, epoch=1, message="first turn")
    second = _create_run(sqlite_session, epoch=2, message="second turn")
    _create_event(
        sqlite_session,
        run=first,
        sequence=1,
        event=WorkflowAssistRunEventType.STATUS,
        payload={"status": "queued"},
    )
    _create_event(
        sqlite_session,
        run=first,
        sequence=2,
        event=WorkflowAssistRunEventType.MESSAGE_DELTA,
        payload={"delta": "hello"},
    )
    _create_event(
        sqlite_session,
        run=second,
        sequence=1,
        event=WorkflowAssistRunEventType.STATUS,
        payload={"status": "queued"},
    )
    sqlite_session.commit()
    service = WorkflowAssistRunEventService(sqlite_session)

    first_page = service.timeline(owner=_owner(), after_epoch=0, after_sequence=0, limit=3)
    second_page = service.timeline(
        owner=_owner(),
        after_epoch=first_page.cursor_epoch,
        after_sequence=first_page.cursor_sequence,
        limit=3,
    )

    assert [(item.epoch, item.sequence, item.event) for item in first_page.items] == [
        (1, 0, "user.message"),
        (1, 1, "status"),
        (1, 2, "message.delta"),
    ]
    assert [(item.epoch, item.sequence, item.event) for item in second_page.items] == [
        (2, 0, "user.message"),
        (2, 1, "status"),
    ]
    assert first_page.items[0].data == {"text": "first turn"}
    assert first_page.has_more
    assert not second_page.has_more


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_timeline_uses_run_input_not_legacy_llm_messages(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    _create_run(sqlite_session, epoch=1, message="durable input")
    sqlite_session.add(
        WorkflowAssistMessage(
            tenant_id="tenant-1",
            app_id="app-1",
            account_id="account-1",
            conversation_id=conversation.id,
            sequence=1,
            role="user",
            event_type="message",
            payload={"text": "legacy guess"},
        )
    )
    sqlite_session.commit()

    page = WorkflowAssistRunEventService(sqlite_session).timeline(
        owner=_owner(), after_epoch=0, after_sequence=0, limit=200
    )

    assert [(item.event, item.data) for item in page.items] == [("user.message", {"text": "durable input"})]


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_timeline_user_message_includes_run_references(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    run = _create_run(sqlite_session, epoch=1, message="把 知识库检索 接到 LLM")
    run.references = [{"kind": "node", "id": "n1", "label": "知识库检索"}]
    sqlite_session.commit()

    page = WorkflowAssistRunEventService(sqlite_session).timeline(
        owner=_owner(), after_epoch=0, after_sequence=0, limit=200
    )

    assert [(item.event, item.data) for item in page.items] == [
        (
            "user.message",
            {
                "text": "把 知识库检索 接到 LLM",
                "references": [{"kind": "node", "id": "n1", "label": "知识库检索"}],
            },
        )
    ]


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_event_serialization_is_exact_and_replay_is_strictly_after_cursor(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    run = _create_run(sqlite_session, epoch=7, message="build")
    _create_event(
        sqlite_session,
        run=run,
        sequence=1,
        event=WorkflowAssistRunEventType.TOOL_CALL,
        payload={"tool_call_id": "call-1", "name": "add_node", "args": {}},
    )
    second = _create_event(
        sqlite_session,
        run=run,
        sequence=2,
        event=WorkflowAssistRunEventType.TOOL_RESULT,
        payload={"tool_call_id": "call-1", "ok": True, "content": {}},
    )
    second.created_at = datetime(2026, 8, 25, 0, 0, 0)
    sqlite_session.commit()

    events = WorkflowAssistRunEventService(sqlite_session).list_events(owner=_owner(), run_id=run.id, after=1)

    assert len(events) == 1
    envelope = events[0].as_dict()
    assert set(envelope) == {"event", "run_id", "epoch", "sequence", "step_id", "created_at", "data"}
    assert envelope == {
        "event": "tool_result",
        "run_id": run.id,
        "epoch": 7,
        "sequence": 2,
        "step_id": "step-7-2",
        "created_at": "2026-08-25T00:00:00Z",
        "data": {"tool_call_id": "call-1", "ok": True, "summary": ""},
    }
    assert "graph" not in json.dumps(envelope)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_sse_envelope_strips_graph_from_persisted_payload(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    run = _create_run(sqlite_session, epoch=1, message="build")
    graph = {"nodes": [{"id": "n1", "data": {"type": "llm"}}], "edges": []}
    record = _create_event(
        sqlite_session,
        run=run,
        sequence=1,
        event=WorkflowAssistRunEventType.TOOL_RESULT,
        payload={
            "tool_call_id": "c1",
            "name": "build_node",
            "ok": True,
            "summary": "created n1",
            "graph": graph,
        },
    )
    sqlite_session.commit()

    events = WorkflowAssistRunEventService(sqlite_session).list_events(owner=_owner(), run_id=run.id, after=0)
    assert len(events) == 1
    envelope = events[0].as_dict()
    assert set(envelope) == {"event", "run_id", "epoch", "sequence", "step_id", "created_at", "data"}
    assert "graph" not in envelope["data"]
    assert envelope["data"]["summary"] == "created n1"
    sqlite_session.refresh(record)
    assert record.payload["graph"] == graph


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_sse_envelope_projects_tool_call_without_full_arguments(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    run = _create_run(sqlite_session, epoch=1, message="build")
    record = _create_event(
        sqlite_session,
        run=run,
        sequence=1,
        event=WorkflowAssistRunEventType.TOOL_CALL,
        payload={
            "tool_call_id": "c1",
            "name": "build_node",
            "arguments": {
                "id": "n1",
                "mode": "create",
                "type": "llm",
                "title": "检索",
                "config": {"prompt": "secret-system-prompt"},
            },
        },
    )
    sqlite_session.commit()

    events = WorkflowAssistRunEventService(sqlite_session).list_events(owner=_owner(), run_id=run.id, after=0)
    envelope = events[0].as_dict()
    assert set(envelope) == {"event", "run_id", "epoch", "sequence", "step_id", "created_at", "data"}
    data = envelope["data"]
    assert "config" not in json.dumps(data)
    assert "secret-system-prompt" not in json.dumps(data)
    assert data["summary"]
    assert set(data.get("arguments", {})) <= {"id", "mode", "type", "title", "purpose", "node_id"}
    assert data["arguments"]["id"] == "n1"
    sqlite_session.refresh(record)
    assert record.payload["arguments"]["config"] == {"prompt": "secret-system-prompt"}


def test_event_serialization_normalizes_aware_non_utc_time_to_rfc3339_utc() -> None:
    envelope = EventEnvelope(
        event="status",
        run_id="run-1",
        epoch=1,
        sequence=1,
        step_id="step-1",
        created_at=datetime(2026, 8, 25, 8, 0, 0, 123456, tzinfo=timezone(timedelta(hours=8))),
        data={"status": "queued"},
    )

    assert envelope.as_dict()["created_at"] == "2026-08-25T00:00:00.123456Z"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_run_replay_excludes_an_owner_shaped_event_with_the_wrong_epoch(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    run = _create_run(sqlite_session, epoch=7, message="build")
    event = _create_event(
        sqlite_session,
        run=run,
        sequence=1,
        event=WorkflowAssistRunEventType.STATUS,
        payload={"status": "queued"},
    )
    event.epoch = 8
    sqlite_session.commit()

    events = WorkflowAssistRunEventService(sqlite_session).list_events(owner=_owner(), run_id=run.id, after=0)

    assert events == ()


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_candidate_snapshot_returns_server_graph_evidence_and_owned_run_summaries(sqlite_session: Session) -> None:
    conversation = _create_conversation(sqlite_session)
    active = _create_run(sqlite_session, epoch=2, message="active")
    latest = _create_run(sqlite_session, epoch=1, message="latest", status=WorkflowAssistRunStatus.DONE)
    conversation.candidate_graph = {"nodes": [{"id": "start"}], "edges": []}
    conversation.candidate_revision = 4
    conversation.candidate_base_hash = "base-hash"
    conversation.active_run_id = active.id
    conversation.latest_run_id = latest.id
    conversation.completion_run_id = latest.id
    conversation.completion_epoch = 1
    conversation.completion_candidate_revision = 4
    conversation.completion_candidate_base_hash = "base-hash"
    conversation.completion_app_mode = WorkflowAssistMode.WORKFLOW
    conversation.completion_assertion = WorkflowAssistCompletionAssertion.WORKFLOW_STRUCTURE_REACHES_TERMINAL
    conversation.completion_contract_protocol_version = 1
    conversation.completion_contract_revision = 2
    conversation.completion_contract_hash = "a" * 64
    conversation.completion_graph_hash = "b" * 64
    conversation.completion_validation_version = 1
    conversation.contract_protocol_version = 1
    conversation.workflow_contract = {"invalid": True}
    sqlite_session.commit()

    snapshot = WorkflowAssistRunEventService(sqlite_session).get_candidate(owner=_owner())

    assert snapshot.graph == {"nodes": [{"id": "start"}], "edges": []}
    assert snapshot.revision == 4
    assert snapshot.base_hash == "base-hash"
    assert snapshot.active_run is not None
    assert snapshot.active_run.run_id == active.id
    assert snapshot.latest_run is not None
    assert snapshot.latest_run.run_id == latest.id
    assert snapshot.completion_evidence == {
        "run_id": latest.id,
        "epoch": 1,
        "candidate_revision": 4,
        "candidate_base_hash": "base-hash",
        "app_mode": "workflow",
        "assertion": "workflow_structure_reaches_terminal",
        "contract_protocol_version": 1,
        "contract_revision": 2,
        "contract_hash": "a" * 64,
        "graph_hash": "b" * 64,
        "validation_version": 1,
    }
    assert snapshot.contract_report is not None
    assert snapshot.contract_report["passed"] is False
    assert snapshot.contract_report["checks"][0]["id"] == "contract"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_stream_replays_then_emits_non_persisted_heartbeat_and_closes(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    run = _create_run(sqlite_session, epoch=1, message="build")
    _create_event(
        sqlite_session,
        run=run,
        sequence=1,
        event=WorkflowAssistRunEventType.STATUS,
        payload={"status": "queued"},
    )
    sqlite_session.commit()
    make_session = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    open_sessions = 0
    sleep_observations: list[int] = []

    @contextmanager
    def tracked_session() -> Iterator[Session]:
        nonlocal open_sessions
        open_sessions += 1
        try:
            with make_session() as session:
                yield session
        finally:
            open_sessions -= 1

    def observe_sleep(_seconds: float) -> None:
        sleep_observations.append(open_sessions)

    stream = WorkflowAssistRunEventStream(
        owner=_owner(),
        run_id=run.id,
        after=0,
        create_session=tracked_session,
        sleep=observe_sleep,
        max_empty_polls=1,
    )
    start = stream.start()
    chunks = list(stream.iter_chunks(start))

    assert chunks[0].startswith("id: 1\n")
    assert json.loads(chunks[0].split("data: ", 1)[1])["sequence"] == 1
    assert chunks[1] == ": heartbeat\n\n"
    assert sleep_observations == [0]
    assert sqlite_session.scalar(select(WorkflowAssistRunEvent).where(WorkflowAssistRunEvent.run_id == run.id))
    assert sqlite_session.query(WorkflowAssistRunEvent).count() == 1


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_request_start_terminal_race_replays_done_instead_of_selecting_empty_204(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    run = _create_run(sqlite_session, epoch=1, message="build")
    sqlite_session.commit()
    control = {"armed": True}
    stream = WorkflowAssistRunEventStream(
        owner=_owner(),
        run_id=run.id,
        after=0,
        create_session=_terminal_race_session_maker(sqlite_session, control),
        sleep=lambda _seconds: None,
    )

    start = stream.start()
    chunks = list(stream.iter_chunks(start))

    assert not start.terminal
    assert json.loads(chunks[-1].split("data: ", 1)[1])["event"] == "done"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_active_poll_terminal_race_replays_done_before_closing(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    run = _create_run(sqlite_session, epoch=1, message="build")
    sqlite_session.commit()
    control = {"armed": False}
    stream = WorkflowAssistRunEventStream(
        owner=_owner(),
        run_id=run.id,
        after=0,
        create_session=_terminal_race_session_maker(sqlite_session, control),
        sleep=lambda _seconds: None,
        max_empty_polls=2,
    )
    start = stream.start()
    control["armed"] = True

    chunks = list(stream.iter_chunks(start))

    assert chunks[0] == ": heartbeat\n\n"
    assert json.loads(chunks[-1].split("data: ", 1)[1])["event"] == "done"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_terminal_stream_with_no_increment_is_empty_at_request_start(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    run = _create_run(sqlite_session, epoch=1, message="done", status=WorkflowAssistRunStatus.DONE)
    _create_event(
        sqlite_session,
        run=run,
        sequence=1,
        event=WorkflowAssistRunEventType.DONE,
        payload={"status": "done"},
    )
    sqlite_session.commit()
    make_session = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    stream = WorkflowAssistRunEventStream(
        owner=_owner(), run_id=run.id, after=1, create_session=make_session, sleep=lambda _seconds: None
    )

    start = stream.start()

    assert start.terminal
    assert start.events == ()
    assert list(stream.iter_chunks(start)) == []


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_terminal_stream_drains_every_replay_batch_before_closing(sqlite_session: Session) -> None:
    _create_conversation(sqlite_session)
    run = _create_run(sqlite_session, epoch=1, message="done", status=WorkflowAssistRunStatus.DONE)
    for sequence in range(1, 202):
        event = WorkflowAssistRunEventType.DONE if sequence == 201 else WorkflowAssistRunEventType.MESSAGE_DELTA
        payload: dict[str, object] = {"status": "done"} if sequence == 201 else {"delta": str(sequence)}
        _create_event(sqlite_session, run=run, sequence=sequence, event=event, payload=payload)
    sqlite_session.commit()
    make_session = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    stream = WorkflowAssistRunEventStream(
        owner=_owner(), run_id=run.id, after=0, create_session=make_session, sleep=lambda _seconds: None
    )

    chunks = list(stream.iter_chunks(stream.start()))

    assert len(chunks) == 201
    assert chunks[-1].startswith("id: 201\n")
