from __future__ import annotations

from unittest.mock import Mock

from core.plugin.entities.plugin_daemon import PluginInstallTaskStartResponse
from services.tool_plugin_generator import publish_service
from services.tool_plugin_generator.service import InstallResult, ToolPluginInstallError
from services.tool_plugin_generator.service import TestToolPluginResult as ToolTestResult

FILES = {
    "manifest.yaml": "version: 0.0.1\nauthor: acme\nname: demo\n",
    "main.py": "pass\n",
    "requirements.txt": "",
    "README.md": "# Demo\n",
    "provider/demo.yaml": "identity:\n  name: demo\n",
    "tools/echo.yaml": "identity:\n  name: echo\n",
    "tools/echo.py": "pass\n",
}


def _install_result(identifier: str, installation_id: str) -> InstallResult:
    return InstallResult(
        plugin_unique_identifier=identifier,
        installation_id=installation_id,
        task=PluginInstallTaskStartResponse(all_installed=True, task_id="", task=None),
    )


def test_first_publish_failure_removes_candidate_and_redacts_credentials(monkeypatch) -> None:
    secret = "sk-super-secret"
    monkeypatch.setattr(
        publish_service,
        "install_tool_plugin",
        Mock(return_value=_install_result("acme/demo:0.0.1@new", "candidate-1")),
    )
    monkeypatch.setattr(
        publish_service,
        "test_tool_plugin",
        Mock(
            return_value=ToolTestResult(
                ok=False,
                output_text="",
                error=f"request failed: invalid api key {secret}",
                elapsed_ms=10,
            )
        ),
    )
    uninstall = Mock(return_value=True)
    monkeypatch.setattr(publish_service.PluginService, "uninstall", uninstall)

    result = publish_service.publish_tool_plugin(
        files=FILES,
        published_files={},
        tenant_id="tenant-1",
        user_id="user-1",
        owned_installation_id=None,
        owned_plugin_unique_identifier=None,
        author="acme",
        plugin_name="demo",
        tool_name="echo",
        parameters={"text": "hello"},
        credentials={"api_key": secret},
    )

    assert result.ok is False
    assert result.status == "publish_failed"
    assert result.installation_id is None
    assert result.rollback_succeeded is True
    assert secret not in str(result)
    assert result.diagnostic is not None
    assert result.diagnostic["error_type"] == "credential_error"
    uninstall.assert_called_once_with("tenant-1", "candidate-1")


def test_upgrade_publish_failure_restores_previous_source(monkeypatch) -> None:
    install = Mock(
        side_effect=[
            _install_result("acme/demo:0.0.2@new", "candidate-2"),
            _install_result("acme/demo:0.0.1@old", "restored-1"),
        ]
    )
    monkeypatch.setattr(publish_service, "install_tool_plugin", install)
    monkeypatch.setattr(
        publish_service,
        "test_tool_plugin",
        Mock(
            return_value=ToolTestResult(
                ok=False,
                output_text="",
                error="NameError: missing_helper is not defined",
                elapsed_ms=12,
            )
        ),
    )
    monkeypatch.setattr(publish_service.PluginService, "uninstall", Mock(return_value=True))

    result = publish_service.publish_tool_plugin(
        files={**FILES, "tools/echo.py": "missing_helper()\n"},
        published_files=FILES,
        tenant_id="tenant-1",
        user_id="user-1",
        owned_installation_id="old-1",
        owned_plugin_unique_identifier="acme/demo:0.0.1@old",
        author="acme",
        plugin_name="demo",
        tool_name="echo",
        parameters={"text": "hello"},
        credentials={},
    )

    assert result.ok is False
    assert result.status == "publish_failed"
    assert result.installation_id == "restored-1"
    assert result.plugin_unique_identifier == "acme/demo:0.0.1@old"
    assert result.rollback_succeeded is True
    assert result.diagnostic is not None
    assert result.diagnostic["error_type"] == "plugin_runtime_error"
    assert install.call_args_list[1].kwargs["files"] == FILES
    assert install.call_args_list[1].kwargs["previous_installation_id"] is None


def test_successful_publish_returns_candidate_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        publish_service,
        "install_tool_plugin",
        Mock(return_value=_install_result("acme/demo:0.0.2@new", "candidate-2")),
    )
    invoke = Mock(
        return_value=ToolTestResult(
            ok=True,
            output_text="ok",
            error=None,
            elapsed_ms=5,
            plugin_unique_identifier="acme/demo:0.0.2@new",
        )
    )
    monkeypatch.setattr(
        publish_service,
        "test_tool_plugin",
        invoke,
    )

    result = publish_service.publish_tool_plugin(
        files=FILES,
        published_files=FILES,
        tenant_id="tenant-1",
        user_id="user-1",
        owned_installation_id="old-1",
        owned_plugin_unique_identifier="acme/demo:0.0.1@old",
        author="acme",
        plugin_name="demo",
        tool_name="echo",
        parameters={"text": "hello"},
        credentials={},
    )

    assert result.ok is True
    assert result.status == "published"
    assert result.installation_id == "candidate-2"
    assert result.plugin_unique_identifier == "acme/demo:0.0.2@new"
    assert result.diagnostic is None
    assert invoke.call_args.kwargs["allow_workspace_credentials"] is False


def test_missing_required_credentials_returns_saved_safe_diagnostic_without_install(monkeypatch) -> None:
    install = Mock()
    monkeypatch.setattr(publish_service, "install_tool_plugin", install)
    files = {
        **FILES,
        "provider/demo.yaml": (
            "identity:\n  name: demo\n"
            "credentials_for_provider:\n"
            "  api_key:\n"
            "    type: secret-input\n"
            "    required: true\n"
        ),
    }

    result = publish_service.publish_tool_plugin(
        files=files,
        published_files=FILES,
        tenant_id="tenant-1",
        user_id="user-1",
        owned_installation_id="old-1",
        owned_plugin_unique_identifier="acme/demo:0.0.1@old",
        author="acme",
        plugin_name="demo",
        tool_name="echo",
        parameters={},
        credentials={},
    )

    assert result.ok is False
    assert result.installation_id == "old-1"
    assert result.diagnostic is not None
    assert result.diagnostic["stage"] == "input"
    assert result.diagnostic["error_type"] == "credential_error"
    install.assert_not_called()


def test_upgrade_install_failure_cleans_candidate_and_restores_previous_source(monkeypatch) -> None:
    install = Mock(
        side_effect=[
            ToolPluginInstallError(
                "candidate install failed",
                plugin_unique_identifier="acme/demo:0.0.2@new",
            ),
            _install_result("acme/demo:0.0.1@old", "restored-1"),
        ]
    )
    cleanup = Mock(return_value=True)
    monkeypatch.setattr(publish_service, "install_tool_plugin", install)
    monkeypatch.setattr(publish_service, "uninstall_plugin_unique_identifier", cleanup)

    result = publish_service.publish_tool_plugin(
        files={**FILES, "tools/echo.py": "broken()\n"},
        published_files=FILES,
        tenant_id="tenant-1",
        user_id="user-1",
        owned_installation_id="old-1",
        owned_plugin_unique_identifier="acme/demo:0.0.1@old",
        author="acme",
        plugin_name="demo",
        tool_name="echo",
        parameters={},
        credentials={},
    )

    assert result.ok is False
    assert result.installation_id == "restored-1"
    assert result.rollback_succeeded is True
    cleanup.assert_called_once_with(
        tenant_id="tenant-1",
        plugin_unique_identifier="acme/demo:0.0.2@new",
    )
    assert install.call_args_list[1].kwargs["files"] == FILES


def test_success_from_a_different_runtime_rolls_back_candidate(monkeypatch) -> None:
    monkeypatch.setattr(
        publish_service,
        "install_tool_plugin",
        Mock(return_value=_install_result("acme/demo:0.0.2@new", "candidate-2")),
    )
    monkeypatch.setattr(
        publish_service,
        "test_tool_plugin",
        Mock(
            return_value=ToolTestResult(
                ok=True,
                output_text="ok",
                error=None,
                elapsed_ms=5,
                plugin_unique_identifier="acme/demo:0.0.1@stale",
            )
        ),
    )
    uninstall = Mock(return_value=True)
    monkeypatch.setattr(publish_service.PluginService, "uninstall", uninstall)

    result = publish_service.publish_tool_plugin(
        files=FILES,
        published_files={},
        tenant_id="tenant-1",
        user_id="user-1",
        owned_installation_id=None,
        owned_plugin_unique_identifier=None,
        author="acme",
        plugin_name="demo",
        tool_name="echo",
        parameters={},
        credentials={},
    )

    assert result.ok is False
    assert result.diagnostic is not None
    assert "other than the installed candidate" in result.diagnostic["message"]
    uninstall.assert_called_once_with("tenant-1", "candidate-2")


def test_invalid_draft_returns_diagnostic_without_install(monkeypatch) -> None:
    install = Mock()
    monkeypatch.setattr(publish_service, "install_tool_plugin", install)

    result = publish_service.publish_tool_plugin(
        files={**FILES, "tools/echo.py": "def broken(:\n"},
        published_files=FILES,
        tenant_id="tenant-1",
        user_id="user-1",
        owned_installation_id="old-1",
        owned_plugin_unique_identifier="acme/demo:0.0.1@old",
        author="acme",
        plugin_name="demo",
        tool_name="echo",
        parameters={},
        credentials={},
    )

    assert result.ok is False
    assert result.installation_id == "old-1"
    assert result.diagnostic is not None
    assert result.diagnostic["stage"] == "validate"
    install.assert_not_called()


def test_manifest_identity_cannot_escape_the_session_publish_lock(monkeypatch) -> None:
    install = Mock()
    monkeypatch.setattr(publish_service, "install_tool_plugin", install)
    files = dict(FILES)
    files["manifest.yaml"] = files["manifest.yaml"].replace("author: acme", "author: other")

    result = publish_service.publish_tool_plugin(
        files=files,
        published_files={},
        tenant_id="tenant-1",
        user_id="user-1",
        owned_installation_id=None,
        owned_plugin_unique_identifier=None,
        author="acme",
        plugin_name="demo",
        tool_name="echo",
        parameters={},
        credentials={},
    )

    assert result.ok is False
    assert result.diagnostic is not None
    assert result.diagnostic["stage"] == "validate"
    assert "identity" in result.diagnostic["message"].lower()
    install.assert_not_called()


def test_persistence_failure_compensation_removes_candidate_and_restores_previous(monkeypatch) -> None:
    monkeypatch.setattr(publish_service.PluginService, "uninstall", Mock(return_value=True))
    restore = Mock(return_value=_install_result("acme/demo:0.0.1@old", "restored-1"))
    monkeypatch.setattr(publish_service, "install_tool_plugin", restore)

    result = publish_service.rollback_published_candidate(
        tenant_id="tenant-1",
        user_id="user-1",
        candidate_installation_id="candidate-2",
        published_files=FILES,
        tool_name="echo",
    )

    assert result.ok is False
    assert result.status == "publish_failed"
    assert result.installation_id == "restored-1"
    assert result.diagnostic is not None
    assert result.diagnostic["stage"] == "persist"
    assert result.diagnostic["error_type"] == "persistence_error"
