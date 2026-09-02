"""Console endpoints for drafting, validating, publishing, and downloading tool plugins."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable, Generator
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any

from flask import request, send_file
from flask_restx import Resource
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from werkzeug.exceptions import BadRequest, Conflict, NotFound

from controllers.common.fields import BinaryFileResponse
from controllers.common.schema import register_response_schema_models, register_schema_models
from controllers.console import console_ns
from controllers.console.wraps import (
    RBACPermission,
    RBACResourceScope,
    account_initialization_required,
    is_admin_or_owner_required,
    rbac_permission_required,
    setup_required,
    with_current_tenant_id,
)
from core.model_manager import ModelManager
from fields.base import ResponseModel
from libs.helper import compact_generate_response
from libs.login import current_account_with_tenant, login_required
from services.tool_plugin_generator.agent_runner import (
    AgentBudgetExceededError,
    AgentCheckpointError,
    create_agent_llm_client,
    create_bootstrap_llm_client,
    iter_agent_turn,
    run_agent_turn,
)
from services.tool_plugin_generator.llm_fill import (
    LLMFillClient,
    LLMFillConfigurationError,
    LLMFillResponseError,
    TenantLLMFillClient,
)
from services.tool_plugin_generator.preview_mapper import normalize_plugin_provider_id, sanitize_plugin_id_segment
from services.tool_plugin_generator.publish_service import (
    publish_tool_plugin,
    redact_sensitive_text,
    rollback_published_candidate,
)
from services.tool_plugin_generator.service import (
    ToolPluginOwnershipError,
    generate_tool_plugin,
    test_tool_plugin,
)
from services.tool_plugin_generator.session_service import (
    ToolPluginStudioSessionError,
    acquire_plugin_publish_lock,
    acquire_session_operation_lock,
    create_session,
    delete_session,
    fork_session,
    get_session,
    hide_session,
    list_sessions,
    list_sessions_by_installation,
    persist_turn_result,
    release_session_operation_lock,
    session_to_detail,
    unhide_session,
    update_session,
)
from services.tool_plugin_generator.test_authorization import (
    TestAuthorizationError,
    consume_test_authorization,
    issue_test_authorization,
)
from services.tool_plugin_generator.uninstall_service import (
    purge_installations_for_plugin_id,
    uninstall_plugin_with_studio_sessions,
)
from services.tool_plugin_generator.validator import ToolPluginValidationError, validate_plugin_files


class ToolPluginFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    content: str

    @field_validator("path")
    @classmethod
    def validate_archive_path(cls, path: str) -> str:
        normalized_path = PurePosixPath(path)
        if "\\" in path or normalized_path.is_absolute() or ".." in normalized_path.parts:
            raise ValueError("file path must be a relative POSIX path")
        return path


class ToolPluginGeneratePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author: str = Field(min_length=1)
    plugin_name: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    user_prompt: str = Field(min_length=1)
    api_doc: str = ""
    model_provider: str = Field(min_length=1)
    model: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_model_selection(self) -> ToolPluginGeneratePayload:
        self.model_provider = self.model_provider.strip()
        self.model = self.model.strip()
        if not self.model_provider or not self.model:
            raise ValueError("model_provider and model are required")
        return self


class ToolPluginFilesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[ToolPluginFile]

    @model_validator(mode="after")
    def validate_unique_paths(self) -> ToolPluginFilesPayload:
        paths = [file.path for file in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("file paths must be unique")
        return self


class ToolPluginDownloadPayload(ToolPluginFilesPayload):
    plugin_name: str = Field(min_length=1)


class ToolPluginTestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    parameters: dict[str, Any]
    credentials: dict[str, SecretStr] = Field(default_factory=dict)


class ToolPluginPublishPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    tool_name: str = Field(min_length=1)
    parameters: dict[str, Any]
    credentials: dict[str, SecretStr] = Field(default_factory=dict)
    authorization_token: str | None = Field(default=None, min_length=1)


class ToolPluginTestAuthorizationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    tool_name: str = Field(min_length=1)
    parameters: dict[str, Any]
    credentials: dict[str, SecretStr] = Field(default_factory=dict)


class ToolPluginAgentTurnPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    model_provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    intent: str | None = None

    @model_validator(mode="after")
    def validate_model_selection(self) -> ToolPluginAgentTurnPayload:
        self.model_provider = self.model_provider.strip()
        self.model = self.model.strip()
        if not self.model_provider or not self.model:
            raise ValueError("model_provider and model are required")
        return self


class ToolPluginSessionCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author: str = ""
    plugin_name: str | None = None


class ToolPluginSessionForkPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_session_id: str = Field(min_length=1)
    title: str | None = None


class ToolPluginUninstallPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_installation_id: str = Field(min_length=1)
    delete_studio_sessions: bool = True
    plugin_unique_identifier: str | None = None


class ToolPluginUninstallResponse(ResponseModel):
    success: bool
    deleted_session_ids: list[str]
    sessions: list[dict[str, Any]]


class ToolPluginPurgeByPluginIdPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: str = Field(min_length=1)
    delete_studio_sessions: bool = True


class ToolPluginPurgeByPluginIdResponse(ResponseModel):
    plugin_id: str
    uninstalled_installation_ids: list[str]
    failed_installation_ids: list[str]
    deleted_session_ids: list[str]


class ToolPluginSessionUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    author: str | None = None
    plugin_name: str | None = None
    active_tool_name: str | None = None
    tool_names: list[str] | None = None
    files: list[ToolPluginFile] | None = None
    preview_tool: dict[str, Any] | None = None
    model_provider: str | None = None
    model_name: str | None = None
    title: str | None = None

    @model_validator(mode="after")
    def validate_optional_files_and_model(self) -> ToolPluginSessionUpdatePayload:
        if self.files is not None:
            paths = [file.path for file in self.files]
            if len(set(paths)) != len(paths):
                raise ValueError("file paths must be unique")
        self.model_provider = (self.model_provider or "").strip() or None
        self.model_name = (self.model_name or "").strip() or None
        if self.model_provider and not self.model_name:
            raise ValueError("model_name is required when model_provider is set")
        if self.model_name and not self.model_provider:
            raise ValueError("model_provider is required when model_name is set")
        return self


class ToolPluginGenerateResponse(ResponseModel):
    files: list[ToolPluginFile]
    preview_tool: dict[str, Any]


class ToolPluginValidationResponse(ResponseModel):
    valid: bool
    errors: list[str]


class ToolPluginTestResponse(ResponseModel):
    ok: bool
    output_text: str
    error: str | None
    elapsed_ms: int
    plugin_unique_identifier: str | None = None


class ToolPluginPublishResponse(ResponseModel):
    ok: bool
    status: str
    revision: int
    plugin_unique_identifier: str | None
    installation_id: str | None
    output_text: str
    elapsed_ms: int
    diagnostic: dict[str, Any] | None
    rollback_succeeded: bool | None


class ToolPluginTestAuthorizationResponse(ResponseModel):
    token: str
    expires_in: int
    max_calls: int
    tool_name: str
    provider_id: str
    parameter_count: int
    credential_names: list[str]


class ToolPluginAgentTurnResponse(ResponseModel):
    messages: list[dict[str, Any]]
    files: list[ToolPluginFile]
    preview_tool: dict[str, Any] | None
    plugin_unique_identifier: str | None
    installation_id: str | None
    task: dict[str, Any] | None
    dirty_installed: bool
    validation_errors: list[str]
    revision: int


register_schema_models(
    console_ns,
    ToolPluginFile,
    ToolPluginGeneratePayload,
    ToolPluginFilesPayload,
    ToolPluginDownloadPayload,
    ToolPluginTestPayload,
    ToolPluginPublishPayload,
    ToolPluginTestAuthorizationPayload,
    ToolPluginAgentTurnPayload,
    ToolPluginSessionCreatePayload,
    ToolPluginSessionForkPayload,
    ToolPluginSessionUpdatePayload,
    ToolPluginUninstallPayload,
    ToolPluginPurgeByPluginIdPayload,
)
register_response_schema_models(
    console_ns,
    ToolPluginGenerateResponse,
    ToolPluginValidationResponse,
    ToolPluginTestResponse,
    ToolPluginPublishResponse,
    ToolPluginTestAuthorizationResponse,
    ToolPluginAgentTurnResponse,
    ToolPluginUninstallResponse,
    ToolPluginPurgeByPluginIdResponse,
    BinaryFileResponse,
)


def create_llm_fill_client(
    *,
    tenant_id: str,
    provider: str | None = None,
    model: str | None = None,
) -> LLMFillClient:
    """Create a request-scoped adapter for a workspace-configured LLM."""
    return TenantLLMFillClient(
        tenant_id=tenant_id,
        provider=provider,
        model=model,
        model_manager=ModelManager.for_tenant(tenant_id=tenant_id),
    )


def _files_to_mapping(files: list[ToolPluginFile]) -> dict[str, str]:
    return {file.path: file.content for file in files}


def _raise_session_error(exc: ToolPluginStudioSessionError) -> None:
    if exc.code == "not_found":
        raise NotFound(exc.message) from exc
    if exc.code == "conflict":
        raise Conflict(
            description=json.dumps(
                {"message": exc.message, "conflict_session_id": exc.conflict_session_id},
                ensure_ascii=False,
            )
        ) from exc
    raise BadRequest(exc.message) from exc


def _persist_agent_session(
    *,
    tenant_id: str,
    account_id: str,
    session_id: str,
    expected_revision: int,
    existing_messages: list[dict[str, Any]],
    active_tool_name: str,
    plugin_unique_identifier: str | None,
    installation_id: str | None,
    result: Any,
) -> Any:
    try:
        return persist_turn_result(
            tenant_id=tenant_id,
            account_id=account_id,
            session_id=session_id,
            files=result.files,
            messages=[*existing_messages, *result.messages],
            preview_tool=result.preview_tool,
            plugin_unique_identifier=plugin_unique_identifier,
            installation_id=installation_id,
            plugin_status="draft_ready" if result.files else "idle",
            active_tool_name=active_tool_name,
            expected_revision=expected_revision,
        )
    except ToolPluginStudioSessionError as exc:
        _raise_session_error(exc)


def _make_agent_checkpoint_callback(
    *,
    tenant_id: str,
    account_id: str,
    session_id: str,
    existing_messages: list[dict[str, Any]],
    plugin_unique_identifier: str | None,
    installation_id: str | None,
    revision_state: dict[str, int],
) -> Callable[[dict[str, Any]], int]:
    def checkpoint(state: dict[str, Any]) -> int:
        persisted = persist_turn_result(
            tenant_id=tenant_id,
            account_id=account_id,
            session_id=session_id,
            files=state["files"],
            messages=[*existing_messages, *state["messages"]],
            preview_tool=state.get("preview_tool"),
            plugin_unique_identifier=plugin_unique_identifier,
            installation_id=installation_id,
            plugin_status=str(state.get("plugin_status") or "draft_ready"),
            active_tool_name=str(state.get("active_tool_name") or ""),
            expected_revision=revision_state["value"],
        )
        revision_state["value"] = persisted.revision
        return persisted.revision

    return checkpoint


def _agent_request_message(payload: ToolPluginAgentTurnPayload, session: Any) -> str:
    if payload.intent != "repair_last_publish":
        return payload.message
    diagnostic = session.last_publish_diagnostic
    if not diagnostic:
        raise BadRequest("No publish failure diagnostic is available for repair")
    if diagnostic.get("error_type") != "plugin_runtime_error":
        raise BadRequest("This publish failure cannot be repaired by changing the plugin draft")
    return (
        f"{payload.message}\n\n"
        "The last publish verification failed with this sanitized diagnostic. "
        f"Fix the draft without requesting credentials: {json.dumps(diagnostic, ensure_ascii=False)}"
    )


def _require_session_revision(session: Any, expected_revision: int) -> None:
    if session.revision != expected_revision:
        raise Conflict(
            description=json.dumps(
                {
                    "message": "Session was updated by another request",
                    "expected_revision": expected_revision,
                    "current_revision": session.revision,
                },
                ensure_ascii=False,
            )
        )


def _acquire_session_lock(*, tenant_id: str, account_id: str, session_id: str):
    try:
        return acquire_session_operation_lock(
            tenant_id=tenant_id,
            account_id=account_id,
            session_id=session_id,
        )
    except ToolPluginStudioSessionError as exc:
        _raise_session_error(exc)


def _request_is_disconnected() -> bool:
    checker = getattr(request, "is_disconnected", None)
    if checker is None:
        return False
    try:
        return bool(checker() if callable(checker) else checker)
    except Exception:
        return False


@console_ns.route("/workspaces/current/tool-plugin/generate")
class ToolPluginGenerateApi(Resource):
    @console_ns.expect(console_ns.models[ToolPluginGeneratePayload.__name__])
    @console_ns.response(200, "Tool plugin generated", console_ns.models[ToolPluginGenerateResponse.__name__])
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        payload = ToolPluginGeneratePayload.model_validate(console_ns.payload or {})
        try:
            create_agent_llm_client(
                tenant_id=tenant_id,
                provider=payload.model_provider,
                model=payload.model,
            )
            result = generate_tool_plugin(
                author=payload.author,
                plugin_name=payload.plugin_name,
                tool_name=payload.tool_name,
                user_prompt=payload.user_prompt,
                api_doc=payload.api_doc,
                llm_client=create_llm_fill_client(
                    tenant_id=tenant_id,
                    provider=payload.model_provider,
                    model=payload.model,
                ),
            )
        except LLMFillConfigurationError as exc:
            raise BadRequest(str(exc)) from exc
        except (ValueError, ToolPluginValidationError) as exc:
            raise BadRequest(str(exc)) from exc
        return {
            "files": [{"path": path, "content": content} for path, content in result.files.items()],
            "preview_tool": result.preview_tool,
        }


@console_ns.route("/workspaces/current/tool-plugin/agent/turn")
class ToolPluginAgentTurnApi(Resource):
    @console_ns.expect(console_ns.models[ToolPluginAgentTurnPayload.__name__])
    @console_ns.response(
        200,
        "Tool plugin agent turn completed",
        console_ns.models[ToolPluginAgentTurnResponse.__name__],
    )
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        payload = ToolPluginAgentTurnPayload.model_validate(console_ns.payload or {})
        current_user, _ = current_account_with_tenant()
        lock = _acquire_session_lock(
            tenant_id=tenant_id,
            account_id=str(current_user.id),
            session_id=payload.session_id,
        )
        try:
            studio_session = get_session(
                tenant_id=tenant_id,
                account_id=str(current_user.id),
                session_id=payload.session_id,
            )
            _require_session_revision(studio_session, payload.expected_revision)
            revision_state = {"value": payload.expected_revision}
            checkpoint = _make_agent_checkpoint_callback(
                tenant_id=tenant_id,
                account_id=str(current_user.id),
                session_id=payload.session_id,
                existing_messages=studio_session.messages,
                plugin_unique_identifier=studio_session.plugin_unique_identifier,
                installation_id=studio_session.installation_id,
                revision_state=revision_state,
            )
            result = run_agent_turn(
                message=_agent_request_message(payload, studio_session),
                files=studio_session.files,
                author=studio_session.author,
                plugin_name=studio_session.plugin_name,
                tool_name=studio_session.active_tool_name,
                tenant_id=tenant_id,
                user_id=str(current_user.id),
                llm_client=create_agent_llm_client(
                    tenant_id=tenant_id,
                    provider=payload.model_provider,
                    model=payload.model,
                ),
                history=studio_session.messages,
                has_published_version=bool(studio_session.installation_id),
                bootstrap_llm=create_bootstrap_llm_client(
                    tenant_id=tenant_id,
                    provider=payload.model_provider,
                    model=payload.model,
                ),
                intent=payload.intent,
                plugin_identity_locked=studio_session.plugin_locked_at is not None,
                on_checkpoint=checkpoint,
            )
            persisted = _persist_agent_session(
                tenant_id=tenant_id,
                account_id=str(current_user.id),
                session_id=payload.session_id,
                expected_revision=revision_state["value"],
                existing_messages=studio_session.messages,
                active_tool_name=studio_session.active_tool_name,
                plugin_unique_identifier=studio_session.plugin_unique_identifier,
                installation_id=studio_session.installation_id,
                result=result,
            )
        except ToolPluginStudioSessionError as exc:
            _raise_session_error(exc)
        except AgentCheckpointError as exc:
            cause = exc.__cause__
            if isinstance(cause, ToolPluginStudioSessionError):
                _raise_session_error(cause)
            raise BadRequest(str(exc)) from exc
        except AgentBudgetExceededError as exc:
            raise BadRequest(str(exc)) from exc
        except LLMFillConfigurationError as exc:
            raise BadRequest(str(exc)) from exc
        except ValueError as exc:
            raise BadRequest(str(exc)) from exc
        finally:
            release_session_operation_lock(lock)

        task_payload = None
        if result.task is not None:
            task_payload = result.task.model_dump(mode="json") if hasattr(result.task, "model_dump") else result.task

        return ToolPluginAgentTurnResponse(
            messages=result.messages,
            files=[ToolPluginFile(path=path, content=content) for path, content in result.files.items()],
            preview_tool=result.preview_tool,
            plugin_unique_identifier=result.plugin_unique_identifier,
            installation_id=result.installation_id,
            task=task_payload,
            dirty_installed=result.dirty_installed,
            validation_errors=result.validation_errors,
            revision=persisted.revision,
        ).model_dump(mode="json")


@console_ns.route("/workspaces/current/tool-plugin/agent/turn/stream")
class ToolPluginAgentTurnStreamApi(Resource):
    @console_ns.expect(console_ns.models[ToolPluginAgentTurnPayload.__name__])
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        payload = ToolPluginAgentTurnPayload.model_validate(console_ns.payload or {})
        current_user, _ = current_account_with_tenant()
        lock = _acquire_session_lock(
            tenant_id=tenant_id,
            account_id=str(current_user.id),
            session_id=payload.session_id,
        )
        try:
            studio_session = get_session(
                tenant_id=tenant_id,
                account_id=str(current_user.id),
                session_id=payload.session_id,
            )
            _require_session_revision(studio_session, payload.expected_revision)
            agent_message = _agent_request_message(payload, studio_session)
            revision_state = {"value": payload.expected_revision}
            checkpoint = _make_agent_checkpoint_callback(
                tenant_id=tenant_id,
                account_id=str(current_user.id),
                session_id=payload.session_id,
                existing_messages=studio_session.messages,
                plugin_unique_identifier=studio_session.plugin_unique_identifier,
                installation_id=studio_session.installation_id,
                revision_state=revision_state,
            )
            llm_client = create_agent_llm_client(
                tenant_id=tenant_id,
                provider=payload.model_provider,
                model=payload.model,
            )
            bootstrap_llm = create_bootstrap_llm_client(
                tenant_id=tenant_id,
                provider=payload.model_provider,
                model=payload.model,
            )
        except ToolPluginStudioSessionError as exc:
            release_session_operation_lock(lock)
            _raise_session_error(exc)
        except (LLMFillConfigurationError, ValueError) as exc:
            release_session_operation_lock(lock)
            raise BadRequest(str(exc)) from exc
        except Exception:
            release_session_operation_lock(lock)
            raise

        def generate() -> Generator[str, None, None]:
            try:
                for event in iter_agent_turn(
                    message=agent_message,
                    files=studio_session.files,
                    author=studio_session.author,
                    plugin_name=studio_session.plugin_name,
                    tool_name=studio_session.active_tool_name,
                    tenant_id=tenant_id,
                    user_id=str(current_user.id),
                    llm_client=llm_client,
                    history=studio_session.messages,
                    has_published_version=bool(studio_session.installation_id),
                    bootstrap_llm=bootstrap_llm,
                    is_cancelled=_request_is_disconnected,
                    intent=payload.intent,
                    plugin_identity_locked=studio_session.plugin_locked_at is not None,
                    on_checkpoint=checkpoint,
                ):
                    if event.get("event") == "done":
                        result = SimpleNamespace()
                        result.files = {item["path"]: item["content"] for item in event.get("files") or []}
                        result.messages = event.get("messages") or []
                        result.preview_tool = event.get("preview_tool")
                        persisted = _persist_agent_session(
                            tenant_id=tenant_id,
                            account_id=str(current_user.id),
                            session_id=payload.session_id,
                            expected_revision=revision_state["value"],
                            existing_messages=studio_session.messages,
                            active_tool_name=studio_session.active_tool_name,
                            plugin_unique_identifier=studio_session.plugin_unique_identifier,
                            installation_id=studio_session.installation_id,
                            result=result,
                        )
                        event["revision"] = persisted.revision
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except LLMFillConfigurationError as exc:
                yield f"data: {json.dumps({'event': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
            except LLMFillResponseError as exc:
                error_event = {
                    "event": "error",
                    "code": "llm_response_invalid",
                    "retryable": False,
                    "provider": exc.provider,
                    "model": exc.model,
                    "parsed_type": exc.parsed_type,
                    "message": str(exc),
                }
                yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            except ToolPluginStudioSessionError as exc:
                yield f"data: {json.dumps({'event': 'error', 'message': exc.message}, ensure_ascii=False)}\n\n"
            except AgentCheckpointError as exc:
                error_event = {
                    "event": "error",
                    "code": "checkpoint_failed",
                    "retryable": True,
                    "message": str(exc),
                }
                yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            except AgentBudgetExceededError as exc:
                error_event = {
                    "event": "error",
                    "code": "agent_budget_exceeded",
                    "reason": exc.reason,
                    "retryable": False,
                    "message": str(exc),
                }
                yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'event': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
            finally:
                release_session_operation_lock(lock)

        return compact_generate_response(generate())


@console_ns.route("/workspaces/current/tool-plugin/uninstall")
class ToolPluginUninstallApi(Resource):
    @console_ns.expect(console_ns.models[ToolPluginUninstallPayload.__name__])
    @console_ns.response(200, "Plugin uninstalled", console_ns.models[ToolPluginUninstallResponse.__name__])
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        payload = ToolPluginUninstallPayload.model_validate(console_ns.payload or {})
        current_user, _ = current_account_with_tenant()
        try:
            result = uninstall_plugin_with_studio_sessions(
                tenant_id=tenant_id,
                account_id=str(current_user.id),
                plugin_installation_id=payload.plugin_installation_id,
                delete_studio_sessions=payload.delete_studio_sessions,
                plugin_unique_identifier=payload.plugin_unique_identifier,
            )
        except ToolPluginStudioSessionError as exc:
            _raise_session_error(exc)
        return ToolPluginUninstallResponse(
            success=result.success,
            deleted_session_ids=result.deleted_session_ids,
            sessions=result.sessions,
        ).model_dump(mode="json")


@console_ns.route("/workspaces/current/tool-plugin/purge-by-plugin-id")
class ToolPluginPurgeByPluginIdApi(Resource):
    @console_ns.expect(console_ns.models[ToolPluginPurgeByPluginIdPayload.__name__])
    @console_ns.response(
        200,
        "Plugins purged by plugin_id",
        console_ns.models[ToolPluginPurgeByPluginIdResponse.__name__],
    )
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        payload = ToolPluginPurgeByPluginIdPayload.model_validate(console_ns.payload or {})
        current_user, _ = current_account_with_tenant()
        try:
            result = purge_installations_for_plugin_id(
                tenant_id=tenant_id,
                account_id=str(current_user.id),
                plugin_id=payload.plugin_id.strip(),
                delete_studio_sessions=payload.delete_studio_sessions,
            )
        except ToolPluginStudioSessionError as exc:
            _raise_session_error(exc)
        return ToolPluginPurgeByPluginIdResponse(
            plugin_id=result.plugin_id,
            uninstalled_installation_ids=result.uninstalled_installation_ids,
            failed_installation_ids=result.failed_installation_ids,
            deleted_session_ids=result.deleted_session_ids,
        ).model_dump(mode="json")


@console_ns.route("/workspaces/current/tool-plugin/sessions/by-installation")
class ToolPluginSessionsByInstallationApi(Resource):
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def get(self, tenant_id: str):
        current_user, _ = current_account_with_tenant()
        installation_id = (request.args.get("installation_id") or "").strip() or None
        plugin_unique_identifier = (request.args.get("plugin_unique_identifier") or "").strip() or None
        if not installation_id and not plugin_unique_identifier:
            raise BadRequest("installation_id or plugin_unique_identifier is required")
        return {
            "sessions": list_sessions_by_installation(
                tenant_id=tenant_id,
                account_id=str(current_user.id),
                installation_id=installation_id,
                plugin_unique_identifier=plugin_unique_identifier,
            )
        }


@console_ns.route("/workspaces/current/tool-plugin/sessions")
class ToolPluginSessionListApi(Resource):
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def get(self, tenant_id: str):
        current_user, _ = current_account_with_tenant()
        include_hidden = str(request.args.get("include_hidden") or "").lower() in {"1", "true", "yes"}
        return {
            "data": list_sessions(
                tenant_id=tenant_id,
                account_id=str(current_user.id),
                include_hidden=include_hidden,
            )
        }

    @console_ns.expect(console_ns.models[ToolPluginSessionCreatePayload.__name__])
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        payload = ToolPluginSessionCreatePayload.model_validate(console_ns.payload or {})
        current_user, _ = current_account_with_tenant()
        try:
            row = create_session(
                tenant_id=tenant_id,
                account_id=str(current_user.id),
                author=payload.author,
                plugin_name=payload.plugin_name,
            )
        except ToolPluginStudioSessionError as exc:
            _raise_session_error(exc)
        return session_to_detail(row), 201


@console_ns.route("/workspaces/current/tool-plugin/session-fork")
class ToolPluginSessionForkApi(Resource):
    @console_ns.expect(console_ns.models[ToolPluginSessionForkPayload.__name__])
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        payload = ToolPluginSessionForkPayload.model_validate(console_ns.payload or {})
        current_user, _ = current_account_with_tenant()
        try:
            row = fork_session(
                tenant_id=tenant_id,
                account_id=str(current_user.id),
                source_session_id=payload.source_session_id,
                title=payload.title,
            )
        except ToolPluginStudioSessionError as exc:
            _raise_session_error(exc)
        return session_to_detail(row), 201


@console_ns.route("/workspaces/current/tool-plugin/sessions/<string:session_id>")
class ToolPluginSessionDetailApi(Resource):
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def get(self, tenant_id: str, session_id: str):
        current_user, _ = current_account_with_tenant()
        try:
            row = get_session(tenant_id=tenant_id, account_id=str(current_user.id), session_id=session_id)
        except ToolPluginStudioSessionError as exc:
            _raise_session_error(exc)
        return session_to_detail(row)

    @console_ns.expect(console_ns.models[ToolPluginSessionUpdatePayload.__name__])
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def put(self, tenant_id: str, session_id: str):
        payload = ToolPluginSessionUpdatePayload.model_validate(console_ns.payload or {})
        current_user, _ = current_account_with_tenant()
        patch = payload.model_dump(exclude_none=True)
        expected_revision = patch.pop("expected_revision")
        if "files" in patch:
            patch["files"] = [{"path": item["path"], "content": item["content"]} for item in patch["files"]]
        lock = _acquire_session_lock(
            tenant_id=tenant_id,
            account_id=str(current_user.id),
            session_id=session_id,
        )
        try:
            row = update_session(
                tenant_id=tenant_id,
                account_id=str(current_user.id),
                session_id=session_id,
                patch=patch,
                expected_revision=expected_revision,
            )
        except ToolPluginStudioSessionError as exc:
            _raise_session_error(exc)
        finally:
            release_session_operation_lock(lock)
        return session_to_detail(row)

    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def delete(self, tenant_id: str, session_id: str):
        current_user, _ = current_account_with_tenant()
        lock = _acquire_session_lock(
            tenant_id=tenant_id,
            account_id=str(current_user.id),
            session_id=session_id,
        )
        try:
            delete_session(tenant_id=tenant_id, account_id=str(current_user.id), session_id=session_id)
        except ToolPluginStudioSessionError as exc:
            _raise_session_error(exc)
        finally:
            release_session_operation_lock(lock)
        return {"result": "success"}


@console_ns.route("/workspaces/current/tool-plugin/sessions/<string:session_id>/hide")
class ToolPluginSessionHideApi(Resource):
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def post(self, tenant_id: str, session_id: str):
        current_user, _ = current_account_with_tenant()
        lock = _acquire_session_lock(
            tenant_id=tenant_id,
            account_id=str(current_user.id),
            session_id=session_id,
        )
        try:
            row = hide_session(tenant_id=tenant_id, account_id=str(current_user.id), session_id=session_id)
        except ToolPluginStudioSessionError as exc:
            _raise_session_error(exc)
        finally:
            release_session_operation_lock(lock)
        return session_to_detail(row)


@console_ns.route("/workspaces/current/tool-plugin/sessions/<string:session_id>/unhide")
class ToolPluginSessionUnhideApi(Resource):
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def post(self, tenant_id: str, session_id: str):
        current_user, _ = current_account_with_tenant()
        lock = _acquire_session_lock(
            tenant_id=tenant_id,
            account_id=str(current_user.id),
            session_id=session_id,
        )
        try:
            row = unhide_session(tenant_id=tenant_id, account_id=str(current_user.id), session_id=session_id)
        except ToolPluginStudioSessionError as exc:
            _raise_session_error(exc)
        finally:
            release_session_operation_lock(lock)
        return session_to_detail(row)


@console_ns.route("/workspaces/current/tool-plugin/validate")
class ToolPluginValidateApi(Resource):
    @console_ns.expect(console_ns.models[ToolPluginFilesPayload.__name__])
    @console_ns.response(200, "Tool plugin validation result", console_ns.models[ToolPluginValidationResponse.__name__])
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        del tenant_id
        payload = ToolPluginFilesPayload.model_validate(console_ns.payload or {})
        try:
            validate_plugin_files(_files_to_mapping(payload.files))
        except ToolPluginValidationError as exc:
            return {"valid": False, "errors": exc.errors}
        return {"valid": True, "errors": []}


@console_ns.route("/workspaces/current/tool-plugin/sessions/<string:session_id>/publish")
class ToolPluginPublishApi(Resource):
    @console_ns.expect(console_ns.models[ToolPluginPublishPayload.__name__])
    @console_ns.response(
        200,
        "Tool plugin verified and published",
        console_ns.models[ToolPluginPublishResponse.__name__],
    )
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def post(self, tenant_id: str, session_id: str):
        payload = ToolPluginPublishPayload.model_validate(console_ns.payload or {})
        current_user, _ = current_account_with_tenant()
        account_id = str(current_user.id)
        lock = _acquire_session_lock(
            tenant_id=tenant_id,
            account_id=account_id,
            session_id=session_id,
        )
        plugin_lock = None
        try:
            studio_session = get_session(
                tenant_id=tenant_id,
                account_id=account_id,
                session_id=session_id,
            )
            _require_session_revision(studio_session, payload.expected_revision)
            if payload.tool_name != studio_session.active_tool_name:
                raise BadRequest("tool_name must match the session's active tool")
            if not payload.authorization_token:
                raise BadRequest("Explicit confirmation is required before a live tool test")
            credentials = {name: value.get_secret_value() for name, value in payload.credentials.items()}
            try:
                consume_test_authorization(
                    tenant_id=tenant_id,
                    account_id=account_id,
                    session_id=session_id,
                    expected_revision=payload.expected_revision,
                    tool_name=payload.tool_name,
                    parameters=payload.parameters,
                    credentials=credentials,
                    token=payload.authorization_token,
                )
            except TestAuthorizationError as exc:
                raise BadRequest(str(exc)) from exc
            plugin_identity = (
                sanitize_plugin_id_segment(studio_session.author),
                sanitize_plugin_id_segment(studio_session.plugin_name),
            )
            if not all(plugin_identity):
                raise BadRequest("Session author and plugin_name must be valid before publishing")
            plugin_id = "/".join(plugin_identity)
            try:
                plugin_lock = acquire_plugin_publish_lock(tenant_id=tenant_id, plugin_id=plugin_id)
            except ToolPluginStudioSessionError as exc:
                _raise_session_error(exc)
            try:
                result = publish_tool_plugin(
                    files=studio_session.files,
                    published_files=studio_session.published_files,
                    tenant_id=tenant_id,
                    user_id=account_id,
                    owned_installation_id=studio_session.installation_id,
                    owned_plugin_unique_identifier=studio_session.plugin_unique_identifier,
                    author=studio_session.author,
                    plugin_name=studio_session.plugin_name,
                    tool_name=payload.tool_name,
                    parameters=payload.parameters,
                    credentials=credentials,
                )
            except ToolPluginOwnershipError as exc:
                raise Conflict(str(exc)) from exc

            try:
                persisted = update_session(
                    tenant_id=tenant_id,
                    account_id=account_id,
                    session_id=session_id,
                    expected_revision=payload.expected_revision,
                    patch={
                        "published_files": studio_session.files if result.ok else studio_session.published_files,
                        "plugin_unique_identifier": result.plugin_unique_identifier,
                        "installation_id": result.installation_id,
                        "plugin_status": result.status,
                        "last_publish_diagnostic": result.diagnostic,
                    },
                )
            except Exception as persistence_error:
                if not result.ok:
                    raise
                result = rollback_published_candidate(
                    tenant_id=tenant_id,
                    user_id=account_id,
                    candidate_installation_id=result.installation_id,
                    published_files=studio_session.published_files,
                    tool_name=payload.tool_name,
                )
                try:
                    current_session = get_session(
                        tenant_id=tenant_id,
                        account_id=account_id,
                        session_id=session_id,
                    )
                    persisted = update_session(
                        tenant_id=tenant_id,
                        account_id=account_id,
                        session_id=session_id,
                        expected_revision=current_session.revision,
                        patch={
                            "plugin_unique_identifier": result.plugin_unique_identifier,
                            "installation_id": result.installation_id,
                            "plugin_status": result.status,
                            "last_publish_diagnostic": result.diagnostic,
                        },
                    )
                except Exception:
                    if isinstance(persistence_error, ToolPluginStudioSessionError):
                        _raise_session_error(persistence_error)
                    raise persistence_error
            response = ToolPluginPublishResponse(
                ok=result.ok,
                status=result.status,
                revision=persisted.revision,
                plugin_unique_identifier=result.plugin_unique_identifier,
                installation_id=result.installation_id,
                output_text=result.output_text,
                elapsed_ms=result.elapsed_ms,
                diagnostic=result.diagnostic,
                rollback_succeeded=result.rollback_succeeded,
            ).model_dump(mode="json")
            return response if result.ok else (response, 422)
        finally:
            if plugin_lock is not None:
                release_session_operation_lock(plugin_lock)
            release_session_operation_lock(lock)


@console_ns.route("/workspaces/current/tool-plugin/sessions/<string:session_id>/test-authorization")
class ToolPluginTestAuthorizationApi(Resource):
    @console_ns.expect(console_ns.models[ToolPluginTestAuthorizationPayload.__name__])
    @console_ns.response(
        200,
        "Live tool-plugin test authorization",
        console_ns.models[ToolPluginTestAuthorizationResponse.__name__],
    )
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def post(self, tenant_id: str, session_id: str):
        payload = ToolPluginTestAuthorizationPayload.model_validate(console_ns.payload or {})
        current_user, _ = current_account_with_tenant()
        account_id = str(current_user.id)
        lock = _acquire_session_lock(
            tenant_id=tenant_id,
            account_id=account_id,
            session_id=session_id,
        )
        try:
            credentials = {name: value.get_secret_value() for name, value in payload.credentials.items()}
            try:
                authorization = issue_test_authorization(
                    tenant_id=tenant_id,
                    account_id=account_id,
                    session_id=session_id,
                    expected_revision=payload.expected_revision,
                    tool_name=payload.tool_name,
                    parameters=payload.parameters,
                    credentials=credentials,
                )
            except TestAuthorizationError as exc:
                raise BadRequest(str(exc)) from exc
            return ToolPluginTestAuthorizationResponse.model_validate(authorization).model_dump(mode="json")
        finally:
            release_session_operation_lock(lock)


@console_ns.route("/workspaces/current/tool-plugin/test")
class ToolPluginTestApi(Resource):
    @console_ns.expect(console_ns.models[ToolPluginTestPayload.__name__])
    @console_ns.response(200, "Tool plugin test result", console_ns.models[ToolPluginTestResponse.__name__])
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        payload = ToolPluginTestPayload.model_validate(console_ns.payload or {})
        current_user, _ = current_account_with_tenant()
        credentials = {name: value.get_secret_value() for name, value in payload.credentials.items()}
        result = test_tool_plugin(
            tenant_id=tenant_id,
            user_id=str(current_user.id),
            provider_id=normalize_plugin_provider_id(payload.provider_id),
            tool_name=payload.tool_name,
            parameters=payload.parameters,
            credentials=credentials,
            allow_workspace_credentials=True,
        )
        return ToolPluginTestResponse(
            ok=result.ok,
            output_text=redact_sensitive_text(result.output_text, credentials),
            error=redact_sensitive_text(result.error, credentials) if result.error else None,
            elapsed_ms=result.elapsed_ms,
            plugin_unique_identifier=result.plugin_unique_identifier,
        ).model_dump(mode="json")


@console_ns.route("/workspaces/current/tool-plugin/download")
class ToolPluginDownloadApi(Resource):
    @console_ns.expect(console_ns.models[ToolPluginDownloadPayload.__name__])
    @console_ns.response(200, "Tool plugin zip archive", console_ns.models[BinaryFileResponse.__name__])
    @setup_required
    @login_required
    @is_admin_or_owner_required
    @rbac_permission_required(RBACResourceScope.WORKSPACE, RBACPermission.TOOL_MANAGE, resource_required=False)
    @account_initialization_required
    @with_current_tenant_id
    def post(self, tenant_id: str):
        del tenant_id
        payload = ToolPluginDownloadPayload.model_validate(console_ns.payload or {})
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, content in _files_to_mapping(payload.files).items():
                archive.writestr(path, content)
        archive_buffer.seek(0)
        return send_file(
            archive_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{payload.plugin_name}.zip",
        )
