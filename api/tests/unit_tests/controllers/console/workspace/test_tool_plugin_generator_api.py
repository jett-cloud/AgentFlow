from __future__ import annotations

import io
import zipfile
from inspect import unwrap
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask_restx import Resource
from werkzeug.exceptions import BadRequest

from controllers.console.workspace.tool_plugin_generator import (
    ToolPluginAgentTurnApi,
    ToolPluginAgentTurnPayload,
    ToolPluginDownloadApi,
    ToolPluginGenerateApi,
    ToolPluginTestAuthorizationApi,
    ToolPluginValidateApi,
    _agent_request_message,
    _make_agent_checkpoint_callback,
    create_llm_fill_client,
)
from libs.external_api import ExternalApi
from services.tool_plugin_generator.agent_runner import AgentTurnResult
from services.tool_plugin_generator.service import GenerateResult
from services.tool_plugin_generator.validator import ToolPluginValidationError

DUPLICATE_FILES_PAYLOAD = {
    "files": [
        {"path": "manifest.yaml", "content": "version: 0.0.1"},
        {"path": "manifest.yaml", "content": "version: 0.0.2"},
    ],
}


@pytest.fixture
def app() -> Flask:
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    return flask_app


def test_generate_returns_files_and_preview(app: Flask) -> None:
    api = ToolPluginGenerateApi()
    method = unwrap(api.post)
    payload = {
        "author": "acme",
        "plugin_name": "demo",
        "tool_name": "echo",
        "user_prompt": "Create an echo tool",
        "api_doc": "POST /echo",
        "model_provider": "langgenius/openai/openai",
        "model": "gpt-4.1",
    }
    result = GenerateResult(
        files={"manifest.yaml": "version: 0.0.1"},
        preview_tool={"provider_id": "acme/demo", "tool_name": "echo", "provider_type": "plugin"},
    )

    with (
        app.test_request_context("/", json=payload),
        patch(
            "controllers.console.workspace.tool_plugin_generator.create_agent_llm_client",
            return_value=MagicMock(),
        ),
        patch(
            "controllers.console.workspace.tool_plugin_generator.create_llm_fill_client",
            return_value=MagicMock(),
        ) as create_client,
        patch(
            "controllers.console.workspace.tool_plugin_generator.generate_tool_plugin",
            return_value=result,
        ) as generate,
    ):
        response = method(api, "tenant-1")

    assert response == {
        "files": [{"path": "manifest.yaml", "content": "version: 0.0.1"}],
        "preview_tool": result.preview_tool,
    }
    create_client.assert_called_once_with(
        tenant_id="tenant-1",
        provider="langgenius/openai/openai",
        model="gpt-4.1",
    )
    generate.assert_called_once()


def test_create_llm_fill_client_uses_tenant_model_manager() -> None:
    model_manager = MagicMock()

    with patch(
        "controllers.console.workspace.tool_plugin_generator.ModelManager.for_tenant",
        return_value=model_manager,
    ) as create_model_manager:
        client = create_llm_fill_client(
            tenant_id="tenant-1",
            provider="langgenius/openai/openai",
            model="gpt-4.1",
        )

    create_model_manager.assert_called_once_with(tenant_id="tenant-1")
    assert client.tenant_id == "tenant-1"
    assert client.provider == "langgenius/openai/openai"
    assert client.model == "gpt-4.1"
    assert client.model_manager is model_manager


def test_repair_intent_rejects_input_errors_before_calling_agent() -> None:
    payload = ToolPluginAgentTurnPayload(
        message="Please fix it",
        session_id="session-1",
        expected_revision=1,
        model_provider="langgenius/openai/openai",
        model="gpt-4.1",
        intent="repair_last_publish",
    )
    session = MagicMock(
        last_publish_diagnostic={
            "stage": "input",
            "error_type": "credential_error",
            "message": "Missing required credentials: api_key",
        }
    )

    with pytest.raises(BadRequest, match="cannot be repaired"):
        _agent_request_message(payload, session)


def test_validate_returns_validation_errors(app: Flask) -> None:
    api = ToolPluginValidateApi()
    method = unwrap(api.post)

    with (
        app.test_request_context("/", json={"files": [{"path": "main.py", "content": "pass"}]}),
        patch(
            "controllers.console.workspace.tool_plugin_generator.validate_plugin_files",
            side_effect=ToolPluginValidationError(["Missing required file: manifest.yaml"]),
        ),
    ):
        response = method(api, "tenant-1")

    assert response == {
        "valid": False,
        "errors": ["Missing required file: manifest.yaml"],
    }


def test_test_authorization_returns_one_shot_token(app: Flask) -> None:
    api = ToolPluginTestAuthorizationApi()
    method = unwrap(api.post)
    lock = MagicMock()
    account = MagicMock(id="user-1")
    authorization = {
        "token": "token-1",
        "expires_in": 300,
        "max_calls": 1,
        "tool_name": "echo",
        "provider_id": "acme/echo",
        "parameter_count": 1,
        "credential_names": ["api_key"],
    }

    with (
        app.test_request_context(
            "/",
            json={
                "expected_revision": 2,
                "tool_name": "echo",
                "parameters": {"text": "hi"},
                "credentials": {"api_key": "secret"},
            },
        ),
        patch(
            "controllers.console.workspace.tool_plugin_generator.current_account_with_tenant",
            return_value=(account, None),
        ),
        patch(
            "controllers.console.workspace.tool_plugin_generator._acquire_session_lock",
            return_value=lock,
        ),
        patch(
            "controllers.console.workspace.tool_plugin_generator.issue_test_authorization",
            return_value=authorization,
        ) as issue,
        patch("controllers.console.workspace.tool_plugin_generator.release_session_operation_lock"),
    ):
        response = method(api, "tenant-1", "session-1")

    assert response == authorization
    issue.assert_called_once_with(
        tenant_id="tenant-1",
        account_id="user-1",
        session_id="session-1",
        expected_revision=2,
        tool_name="echo",
        parameters={"text": "hi"},
        credentials={"api_key": "secret"},
    )


def test_agent_turn_uses_server_owned_draft_and_returns_revision(app: Flask) -> None:
    api = ToolPluginAgentTurnApi()
    method = unwrap(api.post)
    account = MagicMock()
    account.id = "user-1"
    payload = {
        "message": "Make echo return ok",
        "session_id": "session-1",
        "expected_revision": 4,
        "model_provider": "langgenius/openai/openai",
        "model": "gpt-4.1",
    }
    result = AgentTurnResult(
        messages=[{"role": "assistant", "content": "done"}],
        files={"manifest.yaml": "version: 0.0.2"},
        preview_tool={"tool_name": "echo", "provider_type": "plugin"},
        plugin_unique_identifier=None,
        installation_id=None,
        task=None,
        dirty_installed=False,
        validation_errors=[],
    )
    session = MagicMock()
    session.revision = 4
    session.files = {"manifest.yaml": "version: 0.0.1"}
    session.author = "acme"
    session.plugin_name = "demo"
    session.active_tool_name = "echo"
    session.messages = []
    session.installation_id = "install-old"
    session.plugin_unique_identifier = "acme/demo:0.0.1"
    session.plugin_locked_at = None
    persisted = MagicMock(revision=5)
    lock = MagicMock()

    with (
        app.test_request_context("/", json=payload),
        patch(
            "controllers.console.workspace.tool_plugin_generator.current_account_with_tenant",
            return_value=(account, "tenant-1"),
        ),
        patch(
            "controllers.console.workspace.tool_plugin_generator.acquire_session_operation_lock",
            return_value=lock,
        ),
        patch(
            "controllers.console.workspace.tool_plugin_generator.get_session",
            return_value=session,
        ),
        patch(
            "controllers.console.workspace.tool_plugin_generator.create_agent_llm_client",
            return_value=MagicMock(),
        ),
        patch(
            "controllers.console.workspace.tool_plugin_generator.create_bootstrap_llm_client",
            return_value=MagicMock(),
        ),
        patch(
            "controllers.console.workspace.tool_plugin_generator.run_agent_turn",
            return_value=result,
        ) as run_turn,
        patch(
            "controllers.console.workspace.tool_plugin_generator.persist_turn_result",
            return_value=persisted,
        ) as persist,
        patch("controllers.console.workspace.tool_plugin_generator.release_session_operation_lock"),
    ):
        response = method(api, "tenant-1")

    assert response["dirty_installed"] is False
    assert response["plugin_unique_identifier"] is None
    assert response["installation_id"] is None
    assert response["files"] == [{"path": "manifest.yaml", "content": "version: 0.0.2"}]
    assert response["revision"] == 5
    run_turn.assert_called_once()
    assert callable(run_turn.call_args.kwargs["on_checkpoint"])
    assert run_turn.call_args.kwargs["has_published_version"] is True
    assert persist.call_args.kwargs["installation_id"] == "install-old"
    assert persist.call_args.kwargs["plugin_unique_identifier"] == "acme/demo:0.0.1"


def test_agent_checkpoint_persists_and_advances_revision() -> None:
    revision_state = {"value": 4}
    persisted = MagicMock(revision=5)
    checkpoint = _make_agent_checkpoint_callback(
        tenant_id="tenant-1",
        account_id="user-1",
        session_id="session-1",
        existing_messages=[{"role": "user", "content": "previous"}],
        plugin_unique_identifier="acme/demo:0.0.1",
        installation_id="install-old",
        revision_state=revision_state,
    )

    with patch(
        "controllers.console.workspace.tool_plugin_generator.persist_turn_result",
        return_value=persisted,
    ) as persist:
        result = checkpoint(
            {
                "files": {"README.md": "# Updated\n"},
                "messages": [{"role": "assistant", "content": "changed"}],
                "preview_tool": {"tool_name": "echo"},
                "active_tool_name": "echo",
                "plugin_status": "draft_ready",
            }
        )

    assert result == 5
    assert revision_state["value"] == 5
    assert persist.call_args.kwargs["expected_revision"] == 4
    assert persist.call_args.kwargs["messages"] == [
        {"role": "user", "content": "previous"},
        {"role": "assistant", "content": "changed"},
    ]


def test_download_returns_zip_archive(app: Flask) -> None:
    api = ToolPluginDownloadApi()
    method = unwrap(api.post)
    payload = {
        "plugin_name": "demo",
        "files": [
            {"path": "manifest.yaml", "content": "version: 0.0.1"},
            {"path": "tools/echo.py", "content": "pass"},
        ],
    }

    with app.test_request_context("/", json=payload):
        response = method(api, "tenant-1")

    assert response.mimetype == "application/zip"
    assert response.headers["Content-Disposition"] == "attachment; filename=demo.zip"
    response.direct_passthrough = False
    with zipfile.ZipFile(io.BytesIO(response.get_data())) as archive:
        assert archive.read("manifest.yaml").decode() == "version: 0.0.1"
        assert archive.read("tools/echo.py").decode() == "pass"


@pytest.mark.parametrize(
    ("api_cls", "route", "payload"),
    [
        (
            ToolPluginValidateApi,
            "/workspaces/current/tool-plugin/validate",
            DUPLICATE_FILES_PAYLOAD,
        ),
        (
            ToolPluginDownloadApi,
            "/workspaces/current/tool-plugin/download",
            {**DUPLICATE_FILES_PAYLOAD, "plugin_name": "demo"},
        ),
    ],
)
def test_duplicate_file_paths_return_400(
    api_cls: type[ToolPluginValidateApi] | type[ToolPluginDownloadApi],
    route: str,
    payload: dict[str, object],
) -> None:
    app = Flask(__name__)
    api = ExternalApi(app)
    method = unwrap(api_cls.post)

    @api.route(route)
    class DuplicatePathsApi(Resource):
        def post(self):
            return method(api_cls(), "tenant-1")

    response = app.test_client().post(route, json=payload)

    assert response.status_code == 400
    body = response.get_json()
    assert body["code"] == "invalid_param"
    assert "file paths must be unique" in body["message"]
