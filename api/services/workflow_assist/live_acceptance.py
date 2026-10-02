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
    """Return a one-shot grant, a decline marker for a consent card left unapproved, or ``None``."""
    request = _pending_live_request(session, conversation)
    if request_id is None:
        if request is None:
            return None
        return {"declined": True, "graph_hash": request.graph_hash, "candidate_revision": request.candidate_revision}
    if request is None:
        raise ValueError("No pending live execution request")
    if (
        request.request_id != request_id
        or conversation.candidate_revision != request.candidate_revision
        or not isinstance(conversation.candidate_graph, dict)
        or canonical_graph_hash(conversation.candidate_graph) != request.graph_hash
    ):
        raise ValueError("Live execution request is stale")
    return {**request.model_dump(mode="json"), "consumed": False}


def live_grant(record: object) -> dict[str, object] | None:
    """Return ``record`` only when it is an approval grant, never a decline marker."""
    if isinstance(record, dict) and "consumed" in record and not record.get("declined"):
        return record
    return None


def declined_live_graph_hash(record: object) -> str | None:
    if isinstance(record, dict) and record.get("declined") is True and isinstance(record.get("graph_hash"), str):
        return record["graph_hash"]
    return None


def _pending_live_request(
    session: Session, conversation: WorkflowAssistConversation
) -> LiveAcceptanceRequest | None:
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
        return None
    questions = (latest.payload.get("arguments") or {}).get("questions") or []
    if (
        len(questions) != 1
        or not isinstance(questions[0], dict)
        or questions[0].get("id") != LIVE_CONSENT_QUESTION_ID
        or questions[0].get("kind") != "live_acceptance"
    ):
        return None
    try:
        return LiveAcceptanceRequest.model_validate(questions[0].get("execution_request"))
    except ValueError:
        return None


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
