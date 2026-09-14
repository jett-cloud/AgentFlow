"""Application facade for durable Workflow Assist runs and candidate apply."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session, sessionmaker

from core.db.session_factory import session_factory
from core.workflow.generator.resources.knowledge_catalogue import installed_dataset_keys
from core.workflow.generator.resources.tool_catalogue import installed_tool_keys
from models import Account, App
from models.workflow_assist import WorkflowAssistMode, WorkflowAssistRun, WorkflowAssistRunStatus
from services.workflow_assist.apply import apply_draft
from services.workflow_assist.conversations import WorkflowAssistConversationService
from services.workflow_assist.hydrate import hydrate_agent_bindings
from services.workflow_assist.knowledge_catalogue import list_assist_knowledge_catalogue_as_dict
from services.workflow_assist.knowledge_catalogue_loader import build_knowledge_catalogue
from services.workflow_assist.run_coordinator import RunCoordinator
from services.workflow_assist.run_events import RunSummary, WorkflowAssistRunEventService
from services.workflow_assist.run_types import DispatchFailureFence, RunOwner, UserAbortFence
from services.workflow_assist.tool_catalogue import list_assist_tool_catalogue_as_dict
from services.workflow_assist.tool_catalogue_loader import build_tool_catalogue
from services.workflow_assist.turn_references import (
    UnknownTurnReferenceError,
    bind_turn_references,
    normalize_turn_references,
)
from services.workflow_assist.types import ValidationResult
from services.workflow_assist.validate import validate_graph
from services.workflow_service import WorkflowService

logger = logging.getLogger(__name__)


class WorkflowAssistInvalidTurnError(ValueError):
    """Raised when a v2 Turn cannot be accepted as an owned app command."""


class WorkflowAssistInvalidRetryError(ValueError):
    """Raised when a v2 Retry cannot restore from a complete, retryable step."""


@dataclass(frozen=True)
class WorkflowAssistAbortResult:
    """Outcome plus authoritative reconciliation facts for an Abort command."""

    aborted: bool
    active_run: RunSummary | None
    latest_run: RunSummary | None


class WorkflowAssistService:
    """Coordinate authenticated Workflow Assist operations."""

    @staticmethod
    def start_turn(
        *,
        session: Session,
        app_model: App,
        account: Account,
        conversation_id: str,
        message: str,
        mode: WorkflowAssistMode | str,
        model_config: dict[str, Any],
        selected_node: str | None = None,
        references: list[dict[str, Any]] | None = None,
        live_acceptance_request_id: str | None = None,
    ) -> WorkflowAssistRun:
        """Commit a durable turn before dispatching its worker task."""
        try:
            requested_mode = WorkflowAssistMode(mode)
        except (TypeError, ValueError) as exc:
            raise WorkflowAssistInvalidTurnError("unsupported Workflow Assist mode") from exc
        app_mode = str(getattr(app_model.mode, "value", app_model.mode))
        if requested_mode.value != app_mode:
            raise WorkflowAssistInvalidTurnError("Workflow Assist turn mode must match the app mode")

        owner = RunOwner(
            tenant_id=app_model.tenant_id,
            app_id=app_model.id,
            account_id=account.id,
            conversation_id=conversation_id,
        )
        draft = WorkflowAssistService._freeze_turn_draft(
            session=session,
            app_model=app_model,
            account=account,
            conversation_id=conversation_id,
        )
        try:
            bound_references = WorkflowAssistService._bind_turn_references(
                references,
                draft=draft,
                tenant_id=str(app_model.tenant_id),
            )
            run = RunCoordinator(session).start_turn(
                owner=owner,
                message=message,
                mode=requested_mode,
                model_config=model_config,
                selected_node=selected_node,
                references=bound_references,
                live_acceptance_request_id=live_acceptance_request_id,
            )
        except (ValueError, UnknownTurnReferenceError) as exc:
            raise WorkflowAssistInvalidTurnError(str(exc)) from exc
        session.commit()
        try:
            WorkflowAssistService.dispatch_run(run)
        except Exception:
            logger.exception(
                "Workflow Assist Run dispatch failed: tenant_id=%s app_id=%s account_id=%s "
                "conversation_id=%s run_id=%s epoch=%s",
                run.tenant_id,
                run.app_id,
                run.created_by,
                run.conversation_id,
                run.id,
                run.epoch,
            )
            WorkflowAssistService._record_dispatch_failure(run)
        return run

    @staticmethod
    def retry_run(
        *,
        session: Session,
        app_model: App,
        account: Account,
        conversation_id: str,
        run_id: str,
        epoch: int,
        failed_step_id: str,
    ) -> WorkflowAssistRun:
        """Commit a durable retry from the last complete step before dispatching."""
        owner = RunOwner(
            tenant_id=app_model.tenant_id,
            app_id=app_model.id,
            account_id=account.id,
            conversation_id=conversation_id,
        )
        try:
            WorkflowAssistService._freeze_turn_draft(
                session=session,
                app_model=app_model,
                account=account,
                conversation_id=conversation_id,
            )
            run = RunCoordinator(session).retry_failed_step(
                owner=owner,
                run_id=run_id,
                epoch=epoch,
                failed_step_id=failed_step_id,
            )
        except (ValueError, UnknownTurnReferenceError) as exc:
            raise WorkflowAssistInvalidRetryError(str(exc)) from exc
        session.commit()
        try:
            WorkflowAssistService.dispatch_run(run)
        except Exception:
            logger.exception(
                "Workflow Assist Retry dispatch failed: tenant_id=%s app_id=%s account_id=%s "
                "conversation_id=%s run_id=%s epoch=%s",
                run.tenant_id,
                run.app_id,
                run.created_by,
                run.conversation_id,
                run.id,
                run.epoch,
            )
            WorkflowAssistService._record_dispatch_failure(run)
        return run

    @staticmethod
    def _freeze_turn_draft(
        *,
        session: Session,
        app_model: App,
        account: Account,
        conversation_id: str,
    ) -> Any:
        """Lock Conversation then draft Workflow and freeze its canonical hash.

        A new conversation has no candidate of its own. Copy the current draft
        graph so ``read_graph`` sees the canvas the previous chat applied,
        without overwriting an in-progress candidate on this conversation.
        """
        conversation = (
            WorkflowAssistConversationService(session)
            .get(
                tenant_id=app_model.tenant_id,
                app_id=app_model.id,
                account_id=account.id,
                conversation_id=conversation_id,
                lock=True,
            )
            .conversation
        )
        workflow_service = WorkflowService(sessionmaker(bind=session.get_bind(), expire_on_commit=False))
        draft = workflow_service.get_draft_workflow(app_model=app_model, session=session, lock=True)
        if draft is None:
            raise WorkflowAssistInvalidTurnError("Workflow Assist requires an initialized workflow draft")
        conversation.draft_hash = draft.unique_hash
        if not isinstance(conversation.candidate_graph, dict):
            graph = getattr(draft, "graph_dict", None)
            conversation.candidate_graph = deepcopy(graph) if isinstance(graph, dict) else {"nodes": [], "edges": []}
            if conversation.candidate_base_hash is None:
                conversation.candidate_base_hash = draft.unique_hash
        session.flush()
        return draft

    @staticmethod
    def _bind_turn_references(
        references: list[dict[str, Any]] | None,
        *,
        draft: Any,
        tenant_id: str,
    ) -> list[dict[str, Any]] | None:
        normalized = normalize_turn_references(references)
        if not normalized:
            return None
        graph = getattr(draft, "graph_dict", None)
        canvas = dict(graph) if isinstance(graph, Mapping) else {}
        try:
            tool_entries = build_tool_catalogue(tenant_id, limit=None)
            knowledge_entries = build_knowledge_catalogue(tenant_id, limit=None, raise_on_error=True)
        except Exception as exc:
            raise WorkflowAssistInvalidTurnError("failed to validate turn references") from exc
        return bind_turn_references(
            normalized,
            canvas_graph=canvas,
            installed_tools=installed_tool_keys(tool_entries),
            installed_datasets=installed_dataset_keys(knowledge_entries),
        )

    @staticmethod
    def _record_dispatch_failure(run: WorkflowAssistRun) -> None:
        """Fence an unconfirmed queued dispatch in a fresh short transaction."""
        owner = RunOwner(
            tenant_id=run.tenant_id,
            app_id=run.app_id,
            account_id=run.created_by,
            conversation_id=run.conversation_id,
        )
        with session_factory.create_session() as recovery_session:
            terminated = RunCoordinator(recovery_session).terminate(
                lease=DispatchFailureFence(owner=owner, run_id=run.id, epoch=run.epoch),
                status=WorkflowAssistRunStatus.ERROR,
                step_id="error:dispatch_failed",
                payload={"status": "error", "reason": "dispatch_failed"},
                reason="dispatch_failed",
            )
            if terminated:
                recovery_session.commit()

    @staticmethod
    def abort_run(
        *,
        session: Session,
        app_model: App,
        account: Account,
        conversation_id: str,
        run_id: str,
        epoch: int,
    ) -> WorkflowAssistAbortResult:
        """Abort only the current active Run under the typed user fence."""
        owner = RunOwner(
            tenant_id=app_model.tenant_id,
            app_id=app_model.id,
            account_id=account.id,
            conversation_id=conversation_id,
        )
        aborted = RunCoordinator(session).terminate(
            lease=UserAbortFence(owner=owner, run_id=run_id, epoch=epoch),
            status=WorkflowAssistRunStatus.ABORTED,
            step_id="aborted:user_abort",
            payload={"status": "aborted", "reason": "user_abort"},
            reason="user_abort",
        )
        snapshot = WorkflowAssistRunEventService(session).get_candidate(owner=owner)
        return WorkflowAssistAbortResult(
            aborted=aborted,
            active_run=snapshot.active_run,
            latest_run=snapshot.latest_run,
        )

    @staticmethod
    def dispatch_run(run: WorkflowAssistRun) -> None:
        """Dispatch one committed run using only its durable owner coordinates."""
        from tasks.workflow_assist_run_task import execute_workflow_assist_run

        execute_workflow_assist_run.delay(
            tenant_id=run.tenant_id,
            app_id=run.app_id,
            account_id=run.created_by,
            conversation_id=run.conversation_id,
            run_id=run.id,
            epoch=run.epoch,
        )

    @staticmethod
    def validate(
        *,
        graph: dict[str, Any],
        mode: Literal["local", "rebuild"],
        generation_mode: Literal["workflow", "advanced-chat"],
        base_graph: dict[str, Any] | None,
        mutable_node_ids: list[str],
        planned_new_ids: list[str],
        intent_flags: dict[str, bool],
        app_model: App | None = None,
    ) -> ValidationResult:
        validation_context = None
        if app_model is not None:
            from core.db.session_factory import session_factory
            from services.workflow_assist.validation_context import build_validation_context

            try:
                with session_factory.create_session() as session:
                    draft = WorkflowService().get_draft_workflow(app_model=app_model, session=session)
                    validation_context = build_validation_context(
                        tenant_id=str(app_model.tenant_id),
                        graph=graph,
                        draft=draft,
                    )
            except Exception:
                return {
                    "ok": False,
                    "errors": [
                        {"code": "CAPABILITY_UNAVAILABLE", "detail": "Unable to load tenant validation resources"}
                    ],
                    "warnings": [],
                }
        return validate_graph(
            graph=graph,
            mode=mode,
            generation_mode=generation_mode,
            base_graph=base_graph,
            mutable_node_ids=set(mutable_node_ids),
            planned_new_ids=set(planned_new_ids),
            intent_flags=intent_flags,
            validation_context=validation_context,
        )

    @staticmethod
    def hydrate_bindings(
        *,
        session: Session,
        app_model: App,
        account: Account,
        graph: dict[str, Any],
    ) -> dict[str, Any]:
        draft_workflow = WorkflowService().get_draft_workflow(app_model=app_model, session=session)
        if draft_workflow is None:
            raise ValueError("Draft workflow must be initialized before hydrating bindings")
        return hydrate_agent_bindings(
            session=session,
            tenant_id=str(app_model.tenant_id),
            app_id=str(app_model.id),
            account_id=str(account.id),
            workflow_id=str(draft_workflow.id),
            graph=graph,
        )

    @staticmethod
    def apply(
        *,
        session: Session,
        app_model: App,
        account: Account,
        conversation_id: str,
        unique_hash: str,
    ) -> dict[str, str]:
        return apply_draft(
            session=session,
            app_model=app_model,
            account=account,
            conversation_id=conversation_id,
            unique_hash=unique_hash,
        )

    @staticmethod
    def list_tool_catalogue(*, app_model: App) -> dict[str, Any]:
        return list_assist_tool_catalogue_as_dict(str(app_model.tenant_id))

    @staticmethod
    def list_knowledge_catalogue(*, app_model: App) -> dict[str, Any]:
        return list_assist_knowledge_catalogue_as_dict(str(app_model.tenant_id))
