from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from models.workflow_assist import (
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
)
from services.workflow_assist.conversations import (
    ConversationRunLease,
    WorkflowAssistConversationNotFound,
    WorkflowAssistConversationPayloadTooLargeError,
    WorkflowAssistConversationService,
)

TABLES = (WorkflowAssistConversation, WorkflowAssistMessage, WorkflowAssistRun, WorkflowAssistRunEvent)

_RETIRED_PLANNER_WRITERS = [
    "record_clarification",
    "resolve_clarification",
    "record_pending_message",
]


@pytest.mark.parametrize("name", _RETIRED_PLANNER_WRITERS)
def test_conversation_service_does_not_expose_planner_writers(name: str) -> None:
    assert not hasattr(WorkflowAssistConversationService, name)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_create_and_get_conversation_persists_safe_resume_state(sqlite_session: Session) -> None:
    service = WorkflowAssistConversationService(sqlite_session)

    conversation = service.create(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
        title="Summarize invoices",
        draft_hash="draft-1",
        state={"model_config": {"api_key": "must-not-persist"}, "selected_tool": {"credential_id": "cred-1"}},
    )
    service.append_message(
        conversation=conversation,
        role="user",
        event_type="instruction",
        payload={"instruction": "Use the billing tool", "authorization": "must-not-persist"},
    )
    sqlite_session.commit()

    restored = service.get(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
        conversation_id=conversation.id,
    )

    assert restored.conversation.id == conversation.id
    assert restored.conversation.state == {"model_config": {}, "selected_tool": {"credential_id": "cred-1"}}
    assert restored.messages[0].payload == {"instruction": "Use the billing tool"}


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_conversation_is_inaccessible_to_a_different_account(sqlite_session: Session) -> None:
    service = WorkflowAssistConversationService(sqlite_session)
    conversation = service.create(tenant_id="tenant-1", app_id="app-1", account_id="account-1")
    sqlite_session.commit()

    with pytest.raises(WorkflowAssistConversationNotFound):
        service.get(
            tenant_id="tenant-1",
            app_id="app-1",
            account_id="account-2",
            conversation_id=conversation.id,
        )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_soft_deleted_conversation_is_excluded_from_list_and_get(sqlite_session: Session) -> None:
    service = WorkflowAssistConversationService(sqlite_session)
    conversation = service.create(tenant_id="tenant-1", app_id="app-1", account_id="account-1")
    sqlite_session.commit()

    service.delete(tenant_id="tenant-1", app_id="app-1", account_id="account-1", conversation_id=conversation.id)
    sqlite_session.commit()

    assert service.list(tenant_id="tenant-1", app_id="app-1", account_id="account-1", page=1, limit=20).items == []
    with pytest.raises(WorkflowAssistConversationNotFound):
        service.get(
            tenant_id="tenant-1",
            app_id="app-1",
            account_id="account-1",
            conversation_id=conversation.id,
        )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_snapshot_update_keeps_the_server_side_last_plan_revision(sqlite_session: Session) -> None:
    service = WorkflowAssistConversationService(sqlite_session)
    conversation = service.create(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
        state={"last_plan_draft_hash": "draft-1", "session": {"phase": "await_plan_confirm"}},
    )
    sqlite_session.commit()

    updated = service.update(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
        conversation_id=conversation.id,
        state={"session": {"phase": "await_apply"}},
    )

    assert updated.state == {
        "last_plan_draft_hash": "draft-1",
        "session": {"phase": "await_apply"},
    }


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_update_title_does_not_touch_resume_state(sqlite_session: Session) -> None:
    service = WorkflowAssistConversationService(sqlite_session)
    conversation = service.create(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
        title="New workflow chat",
        state={"session": {"phase": "await_apply"}},
    )
    sqlite_session.commit()

    updated = service.update(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
        conversation_id=conversation.id,
        title="Invoice review",
    )

    assert updated.title == "Invoice review"
    assert updated.state == {"session": {"phase": "await_apply"}}


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_create_rejects_oversized_resume_state(sqlite_session: Session) -> None:
    service = WorkflowAssistConversationService(sqlite_session)

    with pytest.raises(WorkflowAssistConversationPayloadTooLargeError) as exc_info:
        service.create(
            tenant_id="tenant-1",
            app_id="app-1",
            account_id="account-1",
            state={"graph": "x" * 1_100_000},
        )

    assert exc_info.value.error_code == "CONVERSATION_STATE_TOO_LARGE"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_append_message_rejects_oversized_event_payload(sqlite_session: Session) -> None:
    service = WorkflowAssistConversationService(sqlite_session)
    conversation = service.create(tenant_id="tenant-1", app_id="app-1", account_id="account-1")

    with pytest.raises(WorkflowAssistConversationPayloadTooLargeError) as exc_info:
        service.append_message(
            conversation=conversation,
            role="assistant",
            event_type="plan_stream",
            payload={"events": [{"text": "x" * 600_000}]},
        )

    assert exc_info.value.error_code == "CONVERSATION_STATE_TOO_LARGE"


def test_append_message_locks_the_parent_before_allocating_sequence() -> None:
    session = MagicMock(spec=Session)
    conversation = WorkflowAssistConversation(
        id="conversation-1",
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
    )
    session.scalar.side_effect = [conversation, 0]

    message = WorkflowAssistConversationService(session).append_message(
        conversation=conversation,
        role="user",
        event_type="instruction",
        payload={"instruction": "hello"},
    )

    lock_statement = session.scalar.call_args_list[0].args[0]
    assert lock_statement._for_update_arg is not None
    assert message.sequence == 1


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_superseding_run_fences_old_graph_write(sqlite_session: Session) -> None:
    service = WorkflowAssistConversationService(sqlite_session)
    conversation = service.create(tenant_id="tenant-1", app_id="app-1", account_id="account-1")
    first: ConversationRunLease = service.acquire_run(conversation=conversation, run_id="r1")
    second: ConversationRunLease = service.acquire_run(conversation=conversation, run_id="r2", supersede=True)

    empty = {"nodes": [], "edges": [], "viewport": {"x": 0.0, "y": 0.0, "zoom": 0.7}}
    assert (
        service.save_candidate_state(
            conversation.id,
            first,
            graph=empty,
            revision=1,
            base_hash=None,
            compacted_until_sequence=None,
            compacted_state=None,
        )
        is False
    )
    assert (
        service.save_candidate_state(
            conversation.id,
            second,
            graph=empty,
            revision=1,
            base_hash=None,
            compacted_until_sequence=None,
            compacted_state=None,
        )
        is True
    )
    sqlite_session.refresh(conversation)
    assert conversation.active_run_id == "r2"
    assert conversation.candidate_revision == 1
