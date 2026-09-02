from __future__ import annotations

import pytest
from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from models.workflow_assist import (
    WorkflowAssistConversation,
    WorkflowAssistMode,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
    WorkflowAssistRunEventType,
    WorkflowAssistRunStatus,
)

TABLES = (WorkflowAssistConversation, WorkflowAssistRun, WorkflowAssistRunEvent)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_run_defaults_to_queued_before_the_first_worker_attempt(sqlite_session: Session) -> None:
    run = WorkflowAssistRun(
        tenant_id="tenant-1",
        app_id="app-1",
        created_by="account-1",
        conversation_id="conversation-1",
        epoch=1,
        input="Build a support workflow",
        mode=WorkflowAssistMode.WORKFLOW,
    )

    sqlite_session.add(run)
    sqlite_session.flush()

    assert run.status is WorkflowAssistRunStatus.QUEUED
    assert run.attempt == 0
    assert run.next_event_sequence == 1
    assert run.candidate_revision == 0
    assert run.model_config == {}
    assert run.queued_at is not None
    assert run.started_at is None
    assert run.finished_at is None


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("queued", False),
        ("running", False),
        ("waiting_user", True),
        ("done", True),
        ("failed", True),
        ("error", True),
        ("aborted", True),
        ("turn_complete", True),
    ],
)
def test_run_status_reports_whether_it_is_terminal(status: str, expected: bool) -> None:
    assert WorkflowAssistRunStatus(status).is_terminal is expected


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_run_input_enforces_the_utf8_64_kib_limit(sqlite_session: Session) -> None:
    accepted = WorkflowAssistRun(
        tenant_id="tenant-1",
        app_id="app-1",
        created_by="account-1",
        conversation_id="conversation-1",
        epoch=1,
        input="é" * 32_768,
        mode=WorkflowAssistMode.WORKFLOW,
    )
    sqlite_session.add(accepted)
    sqlite_session.flush()
    assert accepted.input == "é" * 32_768

    with pytest.raises(ValueError, match="input exceeds 65536 bytes"):
        WorkflowAssistRun(
            tenant_id="tenant-1",
            app_id="app-1",
            created_by="account-1",
            conversation_id="conversation-1",
            epoch=1,
            input=("é" * 32_768) + "x",
            mode=WorkflowAssistMode.WORKFLOW,
        )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_run_event_payload_enforces_the_serialized_256_kib_limit(sqlite_session: Session) -> None:
    accepted = WorkflowAssistRunEvent(
        tenant_id="tenant-1",
        app_id="app-1",
        created_by="account-1",
        conversation_id="conversation-1",
        run_id="run-1",
        epoch=1,
        sequence=1,
        step_id="step-1",
        event=WorkflowAssistRunEventType.STATUS,
        payload={"data": "x" * 262_132},
    )
    sqlite_session.add(accepted)
    sqlite_session.flush()
    assert accepted.payload["data"].endswith("x")

    rejected = WorkflowAssistRunEvent(
        tenant_id="tenant-1",
        app_id="app-1",
        created_by="account-1",
        conversation_id="conversation-1",
        run_id="run-1",
        epoch=1,
        sequence=2,
        step_id="step-2",
        event=WorkflowAssistRunEventType.STATUS,
        payload={"data": "x" * 262_133},
    )
    sqlite_session.add(rejected)
    with pytest.raises(StatementError, match="event payload exceeds 262144 bytes"):
        sqlite_session.flush()


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_mutating_event_payload_before_flush_cannot_bypass_the_limit(sqlite_session: Session) -> None:
    payload = {"data": "small"}
    event = WorkflowAssistRunEvent(
        tenant_id="tenant-1",
        app_id="app-1",
        created_by="account-1",
        conversation_id="conversation-1",
        run_id="run-1",
        epoch=1,
        sequence=1,
        step_id="step-1",
        event=WorkflowAssistRunEventType.STATUS,
        payload=payload,
    )
    payload["data"] = "x" * 262_133
    sqlite_session.add(event)

    with pytest.raises(StatementError, match="event payload exceeds 262144 bytes"):
        sqlite_session.flush()


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@pytest.mark.parametrize("field", ["input", "payload"])
def test_core_insert_cannot_bypass_persistence_limits(sqlite_session: Session, field: str) -> None:
    if field == "input":
        statement = insert(WorkflowAssistRun).values(
            tenant_id="tenant-1",
            app_id="app-1",
            created_by="account-1",
            conversation_id="conversation-1",
            epoch=1,
            input="x" * 65_537,
            mode=WorkflowAssistMode.WORKFLOW,
        )
        error = "input exceeds 65536 bytes"
    else:
        statement = insert(WorkflowAssistRunEvent).values(
            tenant_id="tenant-1",
            app_id="app-1",
            created_by="account-1",
            conversation_id="conversation-1",
            run_id="run-1",
            epoch=1,
            sequence=1,
            step_id="step-1",
            event=WorkflowAssistRunEventType.STATUS,
            payload={"data": "x" * 262_133},
        )
        error = "event payload exceeds 262144 bytes"

    with pytest.raises(StatementError, match=error):
        sqlite_session.execute(statement)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@pytest.mark.parametrize("field", ["input", "payload"])
def test_core_update_cannot_bypass_persistence_limits(sqlite_session: Session, field: str) -> None:
    run = WorkflowAssistRun(
        tenant_id="tenant-1",
        app_id="app-1",
        created_by="account-1",
        conversation_id="conversation-1",
        epoch=1,
        input="small",
        mode=WorkflowAssistMode.WORKFLOW,
    )
    event = WorkflowAssistRunEvent(
        tenant_id="tenant-1",
        app_id="app-1",
        created_by="account-1",
        conversation_id="conversation-1",
        run_id="run-1",
        epoch=1,
        sequence=1,
        step_id="step-1",
        event=WorkflowAssistRunEventType.STATUS,
        payload={"data": "small"},
    )
    sqlite_session.add_all((run, event))
    sqlite_session.flush()

    if field == "input":
        statement = update(WorkflowAssistRun).where(WorkflowAssistRun.id == run.id).values(input="x" * 65_537)
        error = "input exceeds 65536 bytes"
    else:
        statement = (
            update(WorkflowAssistRunEvent)
            .where(WorkflowAssistRunEvent.id == event.id)
            .values(payload={"data": "x" * 262_133})
        )
        error = "event payload exceeds 262144 bytes"

    with pytest.raises(StatementError, match=error):
        sqlite_session.execute(statement)


def test_run_event_payload_rejects_values_the_json_column_cannot_serialize() -> None:
    with pytest.raises(ValueError, match="event payload must contain JSON-native values"):
        WorkflowAssistRunEvent(
            tenant_id="tenant-1",
            app_id="app-1",
            created_by="account-1",
            conversation_id="conversation-1",
            run_id="run-1",
            epoch=1,
            sequence=1,
            step_id="step-1",
            event=WorkflowAssistRunEventType.STATUS,
            payload={"unsupported": object()},
        )


@pytest.mark.parametrize(
    ("sequence", "step_id", "constraint_name"),
    [
        (1, "step-2", "workflow_assist_run_event_run_sequence_unique"),
        (2, "step-1", "workflow_assist_run_event_run_step_unique"),
    ],
)
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_run_events_reject_duplicate_sequence_or_step(
    sqlite_session: Session,
    sequence: int,
    step_id: str,
    constraint_name: str,
) -> None:
    first = WorkflowAssistRunEvent(
        tenant_id="tenant-1",
        app_id="app-1",
        created_by="account-1",
        conversation_id="conversation-1",
        run_id="run-1",
        epoch=1,
        sequence=1,
        step_id="step-1",
        event=WorkflowAssistRunEventType.STATUS,
        payload={},
    )
    duplicate = WorkflowAssistRunEvent(
        tenant_id="tenant-1",
        app_id="app-1",
        created_by="account-1",
        conversation_id="conversation-1",
        run_id="run-1",
        epoch=1,
        sequence=sequence,
        step_id=step_id,
        event=WorkflowAssistRunEventType.MESSAGE_DELTA,
        payload={},
    )
    sqlite_session.add(first)
    sqlite_session.flush()

    sqlite_session.add(duplicate)
    with pytest.raises(IntegrityError):
        sqlite_session.flush()

    constraints = {item.name for item in WorkflowAssistRunEvent.__table__.constraints}
    assert constraint_name in constraints


def test_run_and_event_tables_do_not_declare_database_foreign_keys() -> None:
    assert not WorkflowAssistRun.__table__.foreign_keys
    assert not WorkflowAssistRunEvent.__table__.foreign_keys


def test_run_event_timeline_index_matches_the_owner_cursor_order() -> None:
    indexes = {
        index.name: tuple(column.name for column in index.columns) for index in WorkflowAssistRunEvent.__table__.indexes
    }

    assert indexes == {
        "workflow_assist_run_event_owner_timeline_idx": (
            "tenant_id",
            "app_id",
            "created_by",
            "conversation_id",
            "epoch",
            "sequence",
        )
    }
