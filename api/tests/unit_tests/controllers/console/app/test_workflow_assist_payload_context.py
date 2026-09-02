from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from controllers.console.app import workflow_assist as workflow_assist_module

_RETIRED_PLAN_GENERATE_SYMBOLS = [
    "WorkflowAssistPlanApi",
    "WorkflowAssistPlanStreamApi",
    "WorkflowAssistGenerateApi",
    "WorkflowAssistGenerateStreamApi",
    "PlanPayload",
    "GeneratePayload",
    "ClarificationAnswerPayload",
    "ClarificationResponsePayload",
    "_prepare_plan_request",
    "_commit_transition_if_needed",
    "_public_plan_event_payload",
]


@pytest.mark.parametrize("name", _RETIRED_PLAN_GENERATE_SYMBOLS)
def test_assist_plan_generate_payloads_and_helpers_are_gone(name: str) -> None:
    assert not hasattr(workflow_assist_module, name)


def test_conversation_create_requires_a_fixed_length_draft_revision() -> None:
    revision = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    payload_type = workflow_assist_module.WorkflowAssistConversationCreatePayload

    assert payload_type.model_validate({"draft_hash": revision}).draft_hash == revision
    with pytest.raises(ValidationError) as exc_info:
        payload_type.model_validate({"draft_hash": '{"nodes":[]}'})
    assert exc_info.value.errors()[0]["type"] == "INVALID_DRAFT_REVISION"
    assert exc_info.value.errors()[0]["msg"] == "The submitted draft hash is invalid"
    with pytest.raises(ValidationError) as legacy_exc:
        payload_type.model_validate({"draft_hash": "0123456789abcdef0123456789abcdef"})
    assert legacy_exc.value.errors()[0]["type"] == "INVALID_DRAFT_REVISION"


def test_conversation_list_serialization_omits_state_but_detail_keeps_sanitized_state() -> None:
    conversation = MagicMock()
    conversation.id = "conversation-1"
    conversation.title = "Title"
    conversation.draft_hash = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    conversation.state = {
        "last_instruction": "Build a workflow",
        "planning_session": {"version": 4, "requirements": {"secret": {}}},
        "pending_clarification": {
            "clarification_id": "clarify-1",
            "questions": [],
            "context_checkpoint": {"version": 4},
        },
        "clarification_history": [{"clarification_id": "clarify-1"}],
        "retry_pending_clarification": {"clarification_id": "clarify-1"},
        "request_kind": "instruction",
    }
    conversation.created_at = datetime(2026, 8, 9)
    conversation.updated_at = datetime(2026, 8, 9)

    assert "state" not in workflow_assist_module._serialize_conversation(conversation, include_state=False)
    assert workflow_assist_module._serialize_conversation(conversation)["state"] == {
        "last_instruction": "Build a workflow",
    }
