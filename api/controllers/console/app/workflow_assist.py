"""Console routes for durable Workflow Assist Runs and explicit candidate Apply."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from flask import Response, request
from flask_restx import Resource
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, field_validator
from pydantic_core import PydanticCustomError
from sqlalchemy.orm import Session
from werkzeug.exceptions import BadRequest

from controllers.common.schema import (
    query_params_from_model,
    register_response_schema_models,
    register_schema_models,
)
from controllers.console import console_ns
from controllers.console.app.error import (
    WorkflowAssistConversationStateTooLarge,
    WorkflowAssistConversationWriteConflict,
)
from controllers.console.app.wraps import get_app_model, with_session
from controllers.console.wraps import account_initialization_required, setup_required, with_current_user
from fields.base import ResponseModel
from libs.helper import dump_response
from libs.login import login_required
from models import Account, App, AppMode
from services.workflow_assist.apply import WorkflowAssistApplyConflictError
from services.workflow_assist.conversations import (
    WorkflowAssistConversationPayloadTooLargeError,
    WorkflowAssistConversationService,
)
from services.workflow_assist.conversations import (
    WorkflowAssistConversationWriteConflictError as ConversationWriteConflict,
)
from services.workflow_assist.run_events import WorkflowAssistRunEventService, WorkflowAssistRunEventStream
from services.workflow_assist.run_types import RunOwner
from services.workflow_assist.run_values import prepare_run_input
from services.workflow_assist.service import (
    WorkflowAssistInvalidRetryError,
    WorkflowAssistInvalidTurnError,
    WorkflowAssistService,
)
from services.workflow_assist.turn_references import normalize_turn_references

_PLANNER_STATE_KEYS = frozenset(
    {
        "planning_session",
        "pending_clarification",
        "clarification_history",
        "retry_pending_clarification",
        "request_kind",
    }
)


class _WorkflowAssistPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validate_draft_revision(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise PydanticCustomError(
            "INVALID_DRAFT_REVISION",
            "The submitted draft hash is invalid",
        )
    return value


DraftRevision = Annotated[str, BeforeValidator(_validate_draft_revision)]


class WorkflowAssistConversationCreatePayload(_WorkflowAssistPayload):
    title: str = Field(default="New workflow chat", max_length=255)
    draft_hash: DraftRevision | None = None
    state: dict[str, Any] = Field(default_factory=dict)


class WorkflowAssistConversationTitlePayload(_WorkflowAssistPayload):
    title: str = Field(min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        """Keep rename writes title-only: strip whitespace and reject a blank name."""
        title = value.strip()
        if not title:
            raise PydanticCustomError("INVALID_TITLE", "Title must not be empty")
        return title


class WorkflowAssistConversationQuery(_WorkflowAssistPayload):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)


class WorkflowAssistRunListQuery(_WorkflowAssistPayload):
    after_epoch: int = Field(default=0, ge=0, description="Exclusive Run epoch cursor")
    limit: int = Field(default=50, ge=1, le=100, description="Run metadata page size")


class WorkflowAssistTimelineQuery(_WorkflowAssistPayload):
    after_epoch: int = Field(default=0, ge=0, description="Timeline cursor epoch")
    after_sequence: int = Field(default=0, ge=0, description="Timeline cursor sequence")
    limit: int = Field(default=200, ge=1, le=500, description="Timeline page size")


class WorkflowAssistRunEventsQuery(_WorkflowAssistPayload):
    after: int = Field(default=0, ge=0, description="Exclusive Run event sequence cursor")


class WorkflowAssistTurnPayload(_WorkflowAssistPayload):
    message: str = Field(min_length=1)
    mode: Literal["workflow", "advanced-chat"]
    model_config_data: dict[str, Any] = Field(alias="model_config")
    selected_node: str | None = Field(default=None, min_length=1, max_length=255)
    references: list[dict[str, Any]] | None = Field(default=None)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        """Normalize and enforce the persisted Run input byte contract."""
        return prepare_run_input(value)

    @field_validator("references", mode="before")
    @classmethod
    def validate_references(cls, value: object) -> list[dict[str, Any]] | None:
        """Drop malformed items; reject a list longer than eight."""
        return normalize_turn_references(value)


class WorkflowAssistAbortPayload(_WorkflowAssistPayload):
    epoch: int = Field(ge=1, strict=True)


class WorkflowAssistRetryPayload(_WorkflowAssistPayload):
    epoch: int = Field(ge=1, strict=True)
    failed_step_id: str = Field(min_length=1, max_length=255)


class WorkflowAssistRunSummaryResponse(ResponseModel):
    run_id: str
    epoch: int
    status: str
    mode: str
    candidate_revision: int
    attempt: int
    selected_node: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    termination_reason: str | None


class WorkflowAssistRunListResponse(ResponseModel):
    items: list[WorkflowAssistRunSummaryResponse]
    has_more: bool
    next_after_epoch: int


class WorkflowAssistEventResponse(ResponseModel):
    event: str
    run_id: str
    epoch: int
    sequence: int
    step_id: str
    created_at: datetime
    data: dict[str, Any]


class WorkflowAssistTimelineCursorResponse(ResponseModel):
    epoch: int
    sequence: int


class WorkflowAssistTimelineResponse(ResponseModel):
    items: list[WorkflowAssistEventResponse]
    has_more: bool
    cursor: WorkflowAssistTimelineCursorResponse


class WorkflowAssistCompletionEvidenceResponse(ResponseModel):
    run_id: str
    epoch: int
    candidate_revision: int
    candidate_base_hash: str | None
    app_mode: str
    assertion: str


class WorkflowAssistCandidateResponse(ResponseModel):
    graph: dict[str, Any] | None
    revision: int
    base_hash: str | None
    completion_evidence: WorkflowAssistCompletionEvidenceResponse | None
    active_run: WorkflowAssistRunSummaryResponse | None
    latest_run: WorkflowAssistRunSummaryResponse | None


class WorkflowAssistTurnResponse(ResponseModel):
    conversation_id: str
    run_id: str
    epoch: int
    cursor: Literal[0]


class WorkflowAssistAbortResponse(ResponseModel):
    run_id: str
    epoch: int
    status: Literal["aborted"]


class WorkflowAssistApplyResponse(ResponseModel):
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class WorkflowAssistConflictResponse(ResponseModel):
    active_run: WorkflowAssistRunSummaryResponse | None
    latest_run: WorkflowAssistRunSummaryResponse | None


class ValidatePayload(_WorkflowAssistPayload):
    graph: dict[str, Any]
    mode: Literal["local", "rebuild"]
    base_graph: dict[str, Any] | None = None
    mutable_node_ids: list[str]
    planned_new_ids: list[str] = Field(default_factory=list)
    intent_flags: dict[str, bool]


class HydrateBindingsPayload(_WorkflowAssistPayload):
    graph: dict[str, Any]


class ApplyPayload(_WorkflowAssistPayload):
    conversation_id: UUID
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")


register_schema_models(
    console_ns,
    ValidatePayload,
    HydrateBindingsPayload,
    ApplyPayload,
    WorkflowAssistConversationCreatePayload,
    WorkflowAssistConversationTitlePayload,
    WorkflowAssistConversationQuery,
    WorkflowAssistRunListQuery,
    WorkflowAssistTimelineQuery,
    WorkflowAssistRunEventsQuery,
    WorkflowAssistTurnPayload,
    WorkflowAssistAbortPayload,
    WorkflowAssistRetryPayload,
)
register_response_schema_models(
    console_ns,
    WorkflowAssistRunListResponse,
    WorkflowAssistTimelineResponse,
    WorkflowAssistCandidateResponse,
    WorkflowAssistTurnResponse,
    WorkflowAssistAbortResponse,
    WorkflowAssistApplyResponse,
    WorkflowAssistConflictResponse,
)


def _workflow_assist_route(path: str):
    return console_ns.route(f"/apps/<uuid:app_id>/workflow-assist/{path}")


def _run_owner(app_model: App, account: Account, conversation_id: UUID) -> RunOwner:
    """Bind nested Run reads to the complete authenticated conversation owner."""
    return RunOwner(
        tenant_id=str(app_model.tenant_id),
        app_id=str(app_model.id),
        account_id=str(account.id),
        conversation_id=str(conversation_id),
    )


def _serialize_conversation(conversation, *, include_state: bool = True) -> dict[str, Any]:
    payload = {
        "id": conversation.id,
        "title": conversation.title,
        "draft_hash": conversation.draft_hash,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }
    if include_state:
        payload["state"] = {
            key: value for key, value in dict(conversation.state).items() if key not in _PLANNER_STATE_KEYS
        }
    return payload


def _serialize_message(message) -> dict[str, Any]:
    return {
        "id": message.id,
        "sequence": message.sequence,
        "role": message.role,
        "event_type": message.event_type,
        "status": message.status,
        "retryable": message.retryable,
        "payload": message.payload,
        "created_at": message.created_at.isoformat(),
    }


@_workflow_assist_route("validate")
class WorkflowAssistValidateApi(Resource):
    @console_ns.expect(console_ns.models[ValidatePayload.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def post(self, app_model: App):
        args = ValidatePayload.model_validate(console_ns.payload or {})
        return WorkflowAssistService.validate(
            graph=args.graph,
            mode=args.mode,
            base_graph=args.base_graph,
            mutable_node_ids=args.mutable_node_ids,
            planned_new_ids=args.planned_new_ids,
            intent_flags=args.intent_flags,
        )


@_workflow_assist_route("hydrate-bindings")
class WorkflowAssistHydrateBindingsApi(Resource):
    @console_ns.expect(console_ns.models[HydrateBindingsPayload.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @with_session
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def post(self, session: Session, current_user: Account, app_model: App):
        args = HydrateBindingsPayload.model_validate(console_ns.payload or {})
        try:
            graph = WorkflowAssistService.hydrate_bindings(
                session=session,
                app_model=app_model,
                account=current_user,
                graph=args.graph,
            )
        except ValueError as exc:
            raise BadRequest(str(exc)) from exc
        return {"graph": graph}


@_workflow_assist_route("apply")
class WorkflowAssistApplyApi(Resource):
    @console_ns.expect(console_ns.models[ApplyPayload.__name__])
    @console_ns.response(
        200,
        "Workflow Assist candidate applied",
        console_ns.models[WorkflowAssistApplyResponse.__name__],
    )
    @console_ns.response(
        409,
        "Workflow Assist candidate conflicts with current server state",
        console_ns.models[WorkflowAssistConflictResponse.__name__],
    )
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @with_session
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def post(self, session: Session, current_user: Account, app_model: App):
        args = ApplyPayload.model_validate(console_ns.payload or {})
        try:
            return dump_response(
                WorkflowAssistApplyResponse,
                WorkflowAssistService.apply(
                    session=session,
                    app_model=app_model,
                    account=current_user,
                    conversation_id=str(args.conversation_id),
                    unique_hash=args.hash,
                ),
            )
        except WorkflowAssistApplyConflictError as exc:
            return (
                dump_response(
                    WorkflowAssistConflictResponse,
                    {"active_run": exc.active_run, "latest_run": exc.latest_run},
                ),
                409,
            )


@_workflow_assist_route("tool-catalogue")
class WorkflowAssistToolCatalogueApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def get(self, app_model: App):
        """Installed tools visible to the workflow generator (capped)."""
        return WorkflowAssistService.list_tool_catalogue(app_model=app_model)


@_workflow_assist_route("knowledge-catalogue")
class WorkflowAssistKnowledgeCatalogueApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def get(self, app_model: App):
        """Knowledge bases visible to the workflow generator (capped)."""
        return WorkflowAssistService.list_knowledge_catalogue(app_model=app_model)


@_workflow_assist_route("conversations")
class WorkflowAssistConversationListApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @with_session(write=False)
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def get(self, session: Session, current_user: Account, app_model: App):
        """List recent workflow-assist conversations visible to the current editor only."""
        args = WorkflowAssistConversationQuery.model_validate(request.args.to_dict(flat=True))
        conversations = WorkflowAssistConversationService(session).list(
            tenant_id=str(app_model.tenant_id),
            app_id=str(app_model.id),
            account_id=str(current_user.id),
            page=args.page,
            limit=args.limit,
        )
        return {
            "page": conversations.page,
            "limit": conversations.per_page,
            "total": conversations.total,
            "has_next": conversations.has_next,
            "items": [
                _serialize_conversation(conversation, include_state=False) for conversation in conversations.items
            ],
        }

    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @with_session
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def post(self, session: Session, current_user: Account, app_model: App):
        """Create an account-scoped workflow-assist conversation ready for the first instruction."""
        args = WorkflowAssistConversationCreatePayload.model_validate(console_ns.payload or {})
        try:
            conversation = WorkflowAssistConversationService(session).create(
                tenant_id=str(app_model.tenant_id),
                app_id=str(app_model.id),
                account_id=str(current_user.id),
                title=args.title,
                draft_hash=args.draft_hash,
                state=args.state,
            )
        except WorkflowAssistConversationPayloadTooLargeError as exc:
            raise WorkflowAssistConversationStateTooLarge() from exc
        return _serialize_conversation(conversation), 201


@_workflow_assist_route("conversations/<uuid:conversation_id>")
class WorkflowAssistConversationDetailApi(Resource):
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @with_session(write=False)
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def get(self, session: Session, current_user: Account, app_model: App, conversation_id: UUID):
        """Return one owned conversation with its ordered, sanitized history."""
        detail = WorkflowAssistConversationService(session).get(
            tenant_id=str(app_model.tenant_id),
            app_id=str(app_model.id),
            account_id=str(current_user.id),
            conversation_id=str(conversation_id),
        )
        return {
            "conversation": _serialize_conversation(detail.conversation),
            "messages": [_serialize_message(message) for message in detail.messages],
        }

    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @with_session
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def delete(self, session: Session, current_user: Account, app_model: App, conversation_id: UUID):
        """Soft delete an owned conversation; messages remain retained for audit purposes."""
        WorkflowAssistConversationService(session).delete(
            tenant_id=str(app_model.tenant_id),
            app_id=str(app_model.id),
            account_id=str(current_user.id),
            conversation_id=str(conversation_id),
        )
        return "", 204


@_workflow_assist_route("conversations/<uuid:conversation_id>/title")
class WorkflowAssistConversationTitleApi(Resource):
    @console_ns.expect(console_ns.models[WorkflowAssistConversationTitlePayload.__name__])
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @with_session
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def patch(self, session: Session, current_user: Account, app_model: App, conversation_id: UUID):
        """Rename an owned conversation without writing candidate graph or resume state.

        PATCH on the conversation resource itself stays 405 so the retired
        `draft_hash`/`state` write path cannot come back through a general update.
        """
        args = WorkflowAssistConversationTitlePayload.model_validate(console_ns.payload or {})
        conversation = WorkflowAssistConversationService(session).update(
            tenant_id=str(app_model.tenant_id),
            app_id=str(app_model.id),
            account_id=str(current_user.id),
            conversation_id=str(conversation_id),
            title=args.title,
        )
        return _serialize_conversation(conversation, include_state=False)


@_workflow_assist_route("conversations/<uuid:conversation_id>/turns")
class WorkflowAssistTurnApi(Resource):
    @console_ns.expect(console_ns.models[WorkflowAssistTurnPayload.__name__])
    @console_ns.response(
        202,
        "Workflow Assist turn accepted",
        console_ns.models[WorkflowAssistTurnResponse.__name__],
    )
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @with_session
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def post(
        self,
        session: Session,
        current_user: Account,
        app_model: App,
        conversation_id: UUID,
    ) -> tuple[dict[str, Any], int]:
        """Parse one exact v2 Turn and translate concurrent persistence conflicts to retryable HTTP 409."""
        try:
            payload = WorkflowAssistTurnPayload.model_validate(console_ns.payload or {})
            run = WorkflowAssistService.start_turn(
                session=session,
                app_model=app_model,
                account=current_user,
                conversation_id=str(conversation_id),
                message=payload.message,
                mode=payload.mode,
                model_config=payload.model_config_data,
                selected_node=payload.selected_node,
                references=payload.references,
            )
        except (ValidationError, WorkflowAssistInvalidTurnError) as exc:
            raise BadRequest(str(exc)) from exc
        except ConversationWriteConflict as exc:
            raise WorkflowAssistConversationWriteConflict() from exc
        return (
            dump_response(
                WorkflowAssistTurnResponse,
                {
                    "conversation_id": str(conversation_id),
                    "run_id": run.id,
                    "epoch": run.epoch,
                    "cursor": 0,
                },
            ),
            202,
        )


@_workflow_assist_route("conversations/<uuid:conversation_id>/runs")
class WorkflowAssistRunListApi(Resource):
    @console_ns.doc(params=query_params_from_model(WorkflowAssistRunListQuery))
    @console_ns.response(
        200,
        "Workflow Assist runs retrieved",
        console_ns.models[WorkflowAssistRunListResponse.__name__],
    )
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @with_session(write=False)
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def get(
        self,
        session: Session,
        current_user: Account,
        app_model: App,
        conversation_id: UUID,
    ) -> dict[str, Any]:
        """Return ascending Run metadata for one owned conversation."""
        query = WorkflowAssistRunListQuery.model_validate(request.args.to_dict(flat=True))
        page = WorkflowAssistRunEventService(session).list_runs(
            owner=_run_owner(app_model, current_user, conversation_id),
            after_epoch=query.after_epoch,
            limit=query.limit,
        )
        return dump_response(
            WorkflowAssistRunListResponse,
            {
                "items": page.items,
                "has_more": page.has_more,
                "next_after_epoch": page.next_after_epoch,
            },
        )


@_workflow_assist_route("conversations/<uuid:conversation_id>/timeline")
class WorkflowAssistTimelineApi(Resource):
    @console_ns.doc(params=query_params_from_model(WorkflowAssistTimelineQuery))
    @console_ns.response(
        200,
        "Workflow Assist timeline retrieved",
        console_ns.models[WorkflowAssistTimelineResponse.__name__],
    )
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @with_session(write=False)
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def get(
        self,
        session: Session,
        current_user: Account,
        app_model: App,
        conversation_id: UUID,
    ) -> dict[str, Any]:
        """Return the Run-derived timeline after an exclusive tuple cursor."""
        query = WorkflowAssistTimelineQuery.model_validate(request.args.to_dict(flat=True))
        page = WorkflowAssistRunEventService(session).timeline(
            owner=_run_owner(app_model, current_user, conversation_id),
            after_epoch=query.after_epoch,
            after_sequence=query.after_sequence,
            limit=query.limit,
        )
        return dump_response(
            WorkflowAssistTimelineResponse,
            {
                "items": [item.as_dict() for item in page.items],
                "has_more": page.has_more,
                "cursor": {"epoch": page.cursor_epoch, "sequence": page.cursor_sequence},
            },
        )


@_workflow_assist_route("conversations/<uuid:conversation_id>/candidate")
class WorkflowAssistCandidateApi(Resource):
    @console_ns.response(
        200,
        "Workflow Assist candidate retrieved",
        console_ns.models[WorkflowAssistCandidateResponse.__name__],
    )
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @with_session(write=False)
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def get(
        self,
        session: Session,
        current_user: Account,
        app_model: App,
        conversation_id: UUID,
    ) -> dict[str, Any]:
        """Return the server-owned candidate and Run reconciliation snapshot."""
        snapshot = WorkflowAssistRunEventService(session).get_candidate(
            owner=_run_owner(app_model, current_user, conversation_id)
        )
        return dump_response(WorkflowAssistCandidateResponse, snapshot)


@_workflow_assist_route("conversations/<uuid:conversation_id>/runs/<uuid:run_id>/events")
class WorkflowAssistRunEventsApi(Resource):
    @console_ns.doc(params=query_params_from_model(WorkflowAssistRunEventsQuery))
    @console_ns.response(200, "Workflow Assist Run event stream")
    @console_ns.response(204, "Terminal Run has no events after the cursor")
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def get(
        self,
        current_user: Account,
        app_model: App,
        conversation_id: UUID,
        run_id: UUID,
    ) -> Response:
        """Replay Run events, then briefly poll using a fresh session each time."""
        header_cursor = request.headers.get("Last-Event-ID")
        raw_after = header_cursor if header_cursor is not None else request.args.get("after", "0")
        query = WorkflowAssistRunEventsQuery.model_validate({"after": raw_after})
        stream = WorkflowAssistRunEventStream(
            owner=_run_owner(app_model, current_user, conversation_id),
            run_id=str(run_id),
            after=query.after,
        )
        start = stream.start()
        if start.terminal and not start.events:
            return Response(status=204)
        return Response(
            stream.iter_chunks(start),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


@_workflow_assist_route("conversations/<uuid:conversation_id>/runs/<uuid:run_id>/abort")
class WorkflowAssistRunAbortApi(Resource):
    @console_ns.expect(console_ns.models[WorkflowAssistAbortPayload.__name__])
    @console_ns.response(
        200,
        "Workflow Assist Run aborted",
        console_ns.models[WorkflowAssistAbortResponse.__name__],
    )
    @console_ns.response(
        409,
        "Workflow Assist Run fence is stale",
        console_ns.models[WorkflowAssistConflictResponse.__name__],
    )
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @with_session
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def post(
        self,
        session: Session,
        current_user: Account,
        app_model: App,
        conversation_id: UUID,
        run_id: UUID,
    ) -> dict[str, Any] | tuple[dict[str, Any], int]:
        """Translate the typed user-abort fence, including retryable persistence conflicts."""
        payload = WorkflowAssistAbortPayload.model_validate(console_ns.payload or {})
        try:
            result = WorkflowAssistService.abort_run(
                session=session,
                app_model=app_model,
                account=current_user,
                conversation_id=str(conversation_id),
                run_id=str(run_id),
                epoch=payload.epoch,
            )
        except ConversationWriteConflict as exc:
            raise WorkflowAssistConversationWriteConflict() from exc
        if not result.aborted:
            return (
                dump_response(
                    WorkflowAssistConflictResponse,
                    {"active_run": result.active_run, "latest_run": result.latest_run},
                ),
                409,
            )
        return dump_response(
            WorkflowAssistAbortResponse,
            {"run_id": str(run_id), "epoch": payload.epoch, "status": "aborted"},
        )


@_workflow_assist_route("conversations/<uuid:conversation_id>/runs/<uuid:run_id>/retry")
class WorkflowAssistRunRetryApi(Resource):
    @console_ns.expect(console_ns.models[WorkflowAssistRetryPayload.__name__])
    @console_ns.response(
        202,
        "Workflow Assist retry accepted",
        console_ns.models[WorkflowAssistTurnResponse.__name__],
    )
    @setup_required
    @login_required
    @account_initialization_required
    @with_current_user
    @with_session
    @get_app_model(mode=[AppMode.ADVANCED_CHAT, AppMode.WORKFLOW])
    def post(
        self,
        session: Session,
        current_user: Account,
        app_model: App,
        conversation_id: UUID,
        run_id: UUID,
    ) -> tuple[dict[str, Any], int]:
        """Parse one exact v2 Retry and translate fence conflicts to HTTP 409."""
        try:
            payload = WorkflowAssistRetryPayload.model_validate(console_ns.payload or {})
            run = WorkflowAssistService.retry_run(
                session=session,
                app_model=app_model,
                account=current_user,
                conversation_id=str(conversation_id),
                run_id=str(run_id),
                epoch=payload.epoch,
                failed_step_id=payload.failed_step_id,
            )
        except (ValidationError, WorkflowAssistInvalidRetryError) as exc:
            raise BadRequest(str(exc)) from exc
        except ConversationWriteConflict as exc:
            raise WorkflowAssistConversationWriteConflict() from exc
        return (
            dump_response(
                WorkflowAssistTurnResponse,
                {
                    "conversation_id": str(conversation_id),
                    "run_id": run.id,
                    "epoch": run.epoch,
                    "cursor": 0,
                },
            ),
            202,
        )
