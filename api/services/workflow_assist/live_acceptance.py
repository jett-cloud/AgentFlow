"""Resolve UI approval against a pending server request and consume it under a worker lease."""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.session_factory import session_factory
from core.workflow.generator.acceptance.authorization import LIVE_CONSENT_QUESTION_ID, LiveAcceptanceRequest
from core.workflow.generator.acceptance.evidence import canonical_graph_hash
from models.workflow_assist import WorkflowAssistConversation, WorkflowAssistMessage
from services.workflow_assist.run_types import RunLease


def resolve_live_approval(
    session: Session,
    conversation: WorkflowAssistConversation,
    request_id: str | None,
) -> dict[str, object] | None:
    if request_id is None:
        return None
    latest = session.scalar(
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
        latest is None
        or latest.status != "pending"
        or latest.event_type != "tool_call"
        or latest.payload.get("name") != "ask_user"
    ):
        raise ValueError("No pending live execution request")
    questions = (latest.payload.get("arguments") or {}).get("questions") or []
    if (
        len(questions) != 1
        or questions[0].get("id") != LIVE_CONSENT_QUESTION_ID
        or questions[0].get("kind") != "live_acceptance"
    ):
        raise ValueError("No pending live execution request")
    request = LiveAcceptanceRequest.model_validate(questions[0].get("execution_request"))
    if (
        request.request_id != request_id
        or conversation.candidate_revision != request.candidate_revision
        or not isinstance(conversation.candidate_graph, dict)
        or canonical_graph_hash(conversation.candidate_graph) != request.graph_hash
    ):
        raise ValueError("Live execution request is stale")
    return {**request.model_dump(mode="json"), "consumed": False}


def bind_live_authorizer(lease: RunLease) -> Callable[[int, str], bool]:
    def authorize(revision: int, graph_hash: str) -> bool:
        from services.workflow_assist.run_coordinator import RunCoordinator

        with session_factory.create_session() as session:
            accepted = RunCoordinator(session).consume_live_acceptance(
                lease=lease,
                revision=revision,
                graph_hash=graph_hash,
            )
            session.commit()
            return accepted

    return authorize
