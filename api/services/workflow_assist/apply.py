"""Atomically apply a server-owned Workflow Assist candidate.

The browser supplies only an owned conversation coordinate and the current
draft hash. This boundary locks the conversation, validates durable completion
evidence, synchronizes the candidate graph, and clears the candidate in one
transaction. Client-provided graphs and force overrides are intentionally not
accepted.
"""

from __future__ import annotations

import logging
import re
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from core.workflow.generator.graph_postprocessor import postprocess_graph
from core.workflow.generator.types import GraphDict, WorkflowGenerationMode
from events.app_event import app_draft_workflow_was_synced
from models import Account, App
from models.workflow_assist import (
    WORKFLOW_ASSIST_RUN_ACTIVE_STATUSES,
    WorkflowAssistCompletionAssertion,
    WorkflowAssistConversation,
    WorkflowAssistRun,
    WorkflowAssistRunStatus,
)
from services.workflow_assist.conversations import WorkflowAssistConversationNotFound
from services.workflow_assist.run_events import RunSummary, WorkflowAssistRunEventService
from services.workflow_assist.run_types import RunOwner
from services.workflow_service import WorkflowService

logger = logging.getLogger(__name__)


class WorkflowAssistApplyConflictError(RuntimeError):
    """Rejected Apply carrying the authoritative Run reconciliation summary."""

    active_run: RunSummary | None
    latest_run: RunSummary | None

    def __init__(self, message: str, *, active_run: RunSummary | None, latest_run: RunSummary | None) -> None:
        super().__init__(message)
        self.active_run = active_run
        self.latest_run = latest_run


def apply_draft(
    *,
    session: Session,
    app_model: App,
    account: Account,
    conversation_id: str,
    unique_hash: str,
) -> dict[str, str]:
    """Apply a verified candidate and close it without exposing partial success.

    The method commits before emitting the normal draft-synchronized signal, so
    signal handlers cannot observe a workflow whose candidate cleanup rolled
    back. Rejections contain only server-owned active/latest Run summaries.
    """
    owner = RunOwner(
        tenant_id=app_model.tenant_id,
        app_id=app_model.id,
        account_id=account.id,
        conversation_id=conversation_id,
    )
    workflow_service = WorkflowService(sessionmaker(bind=session.get_bind(), expire_on_commit=False))
    with session.begin_nested():
        # All shared writes acquire Conversation -> draft Workflow -> Run rows.
        conversation = _lock_conversation(session=session, owner=owner)
        draft_workflow = workflow_service.get_draft_workflow(app_model=app_model, session=session, lock=True)
        active_run = session.scalar(
            select(WorkflowAssistRun)
            .where(
                *_run_owner_predicates(owner),
                WorkflowAssistRun.status.in_(WORKFLOW_ASSIST_RUN_ACTIVE_STATUSES),
            )
            .order_by(WorkflowAssistRun.epoch.desc())
            .with_for_update()
        )
        if active_run is not None:
            raise _conflict(session, owner, "A Workflow Assist run is still active")

        if re.fullmatch(r"[0-9a-f]{64}", unique_hash) is None:
            raise _conflict(session, owner, "The submitted draft hash is invalid")
        if draft_workflow is None or draft_workflow.unique_hash != unique_hash:
            raise _conflict(session, owner, "The workflow draft changed")
        if conversation.candidate_base_hash != unique_hash or not isinstance(conversation.candidate_graph, dict):
            raise _conflict(session, owner, "The Workflow Assist candidate is stale")

        completion_run = _lock_completion_run(session=session, owner=owner, conversation=conversation)
        if completion_run is None or not _completion_is_current(
            conversation=conversation,
            run=completion_run,
            unique_hash=unique_hash,
            app_mode=str(app_model.mode),
        ):
            raise _conflict(session, owner, "Workflow Assist completion evidence is stale")

        graph = postprocess_graph(
            graph=cast(GraphDict, conversation.candidate_graph),
            mode=_generation_mode(app_model),
        )
        workflow = workflow_service.sync_draft_workflow(
            app_model=app_model,
            graph=graph,
            features=draft_workflow.features_dict,
            unique_hash=unique_hash,
            account=account,
            environment_variables=draft_workflow.environment_variables,
            conversation_variables=draft_workflow.conversation_variables,
            session=session,
            commit=False,
        )
        conversation.draft_hash = workflow.unique_hash
        conversation.candidate_graph = None
        conversation.candidate_base_hash = None
        _clear_completion_evidence(conversation)
        session.flush()

    session.commit()
    try:
        app_draft_workflow_was_synced.send(app_model, synced_draft_workflow=workflow)
    except Exception:
        logger.exception(
            "Workflow Assist Apply committed but a draft-sync receiver failed: app_id=%s conversation_id=%s hash=%s",
            app_model.id,
            conversation_id,
            workflow.unique_hash,
        )
    return {"hash": workflow.unique_hash}


def _generation_mode(app_model: App) -> WorkflowGenerationMode:
    mode = str(getattr(app_model, "mode", "workflow"))
    return "advanced-chat" if mode == "advanced-chat" else "workflow"


def _lock_conversation(*, session: Session, owner: RunOwner) -> WorkflowAssistConversation:
    """Resolve and lock one active conversation using its complete owner."""
    conversation = session.scalar(
        select(WorkflowAssistConversation)
        .where(
            WorkflowAssistConversation.id == owner.conversation_id,
            WorkflowAssistConversation.tenant_id == owner.tenant_id,
            WorkflowAssistConversation.app_id == owner.app_id,
            WorkflowAssistConversation.account_id == owner.account_id,
            WorkflowAssistConversation.is_deleted.is_(False),
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if conversation is None:
        raise WorkflowAssistConversationNotFound()
    return conversation


def _lock_completion_run(
    *,
    session: Session,
    owner: RunOwner,
    conversation: WorkflowAssistConversation,
) -> WorkflowAssistRun | None:
    if conversation.completion_run_id is None:
        return None
    return session.scalar(
        select(WorkflowAssistRun)
        .where(
            *_run_owner_predicates(owner),
            WorkflowAssistRun.id == conversation.completion_run_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )


def _completion_is_current(
    *,
    conversation: WorkflowAssistConversation,
    run: WorkflowAssistRun,
    unique_hash: str,
    app_mode: str,
) -> bool:
    """Match every durable fact that authorized the server candidate."""
    normalized_app_mode = str(getattr(conversation.completion_app_mode, "value", conversation.completion_app_mode))
    normalized_assertion = str(getattr(conversation.completion_assertion, "value", conversation.completion_assertion))
    return (
        run.status is WorkflowAssistRunStatus.DONE
        and conversation.latest_run_id == run.id == conversation.completion_run_id
        and conversation.run_epoch == run.epoch == conversation.completion_epoch
        and run.candidate_revision == conversation.candidate_revision == conversation.completion_candidate_revision
        and conversation.candidate_base_hash == conversation.completion_candidate_base_hash == unique_hash
        and normalized_app_mode == app_mode
        and normalized_assertion == WorkflowAssistCompletionAssertion.WORKFLOW_STRUCTURE_REACHES_TERMINAL.value
    )


def _conflict(session: Session, owner: RunOwner, message: str) -> WorkflowAssistApplyConflictError:
    snapshot = WorkflowAssistRunEventService(session).get_reconciliation(owner=owner)
    return WorkflowAssistApplyConflictError(
        message,
        active_run=snapshot.active_run,
        latest_run=snapshot.latest_run,
    )


def _clear_completion_evidence(conversation: WorkflowAssistConversation) -> None:
    conversation.completion_run_id = None
    conversation.completion_epoch = None
    conversation.completion_candidate_revision = None
    conversation.completion_candidate_base_hash = None
    conversation.completion_app_mode = None
    conversation.completion_assertion = None


def _run_owner_predicates(owner: RunOwner) -> tuple[ColumnElement[bool], ...]:
    return (
        WorkflowAssistRun.tenant_id == owner.tenant_id,
        WorkflowAssistRun.app_id == owner.app_id,
        WorkflowAssistRun.created_by == owner.account_id,
        WorkflowAssistRun.conversation_id == owner.conversation_id,
    )
