from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.plugin.entities.plugin_daemon import (
    PluginDecodeResponse,
    PluginInstallTaskStartResponse,
    PluginInstallTaskStatus,
)
from services.tool_plugin_generator import service


def _valid_files() -> dict[str, str]:
    return {
        "manifest.yaml": "version: 0.0.1\n",
        "main.py": "pass\n",
        "requirements.txt": "",
        "README.md": "# Demo\n",
        "tools/echo.yaml": "identity:\n  name: echo\n",
        "tools/echo.py": "pass\n",
    }


def test_install_tool_plugin_packages_uploads_and_installs(monkeypatch) -> None:
    files = _valid_files()
    package_plugin_files = Mock(return_value=b"PK_FAKE_DIFYPKG")
    decoded = Mock(spec=PluginDecodeResponse)
    decoded.unique_identifier = "acme/demo:0.0.1"
    upload_pkg = Mock(return_value=decoded)
    task_start = PluginInstallTaskStartResponse(all_installed=False, task_id="task-1", task=None)
    install_from_local_pkg = Mock(return_value=task_start)
    resolve_installation_id = Mock(return_value="install-1")
    wait_for_install_task = Mock(return_value=SimpleNamespace(status=PluginInstallTaskStatus.Success))
    monkeypatch.setattr(service, "package_plugin_files", package_plugin_files)
    monkeypatch.setattr(service.PluginService, "upload_pkg", upload_pkg)
    monkeypatch.setattr(service.PluginService, "install_from_local_pkg", install_from_local_pkg)
    monkeypatch.setattr(service, "resolve_installation_id", resolve_installation_id)
    monkeypatch.setattr(service, "wait_for_install_task", wait_for_install_task)
    monkeypatch.setattr(service, "_list_installed_plugins", Mock(return_value=[]))
    monkeypatch.setattr(
        service,
        "uninstall_installations_for_plugin_id",
        Mock(return_value=service.UninstallByPluginIdResult("acme/demo", [], [])),
    )

    result = service.install_tool_plugin(files=files, tenant_id="tenant-1", user_id="user-1")

    package_plugin_files.assert_called_once()
    upload_pkg.assert_called_once_with("tenant-1", b"PK_FAKE_DIFYPKG")
    install_from_local_pkg.assert_called_once_with("tenant-1", ["acme/demo:0.0.1"])
    wait_for_install_task.assert_called_once()
    assert result.plugin_unique_identifier == "acme/demo:0.0.1"
    assert result.task.all_installed is True
    assert result.task.task_id == "task-1"
    assert result.installation_id == "install-1"


def test_install_tool_plugin_uninstalls_previous_installation(monkeypatch) -> None:
    files = _valid_files()
    uninstall = Mock(return_value=True)
    package_plugin_files = Mock(return_value=b"PK_FAKE")
    decoded = Mock(spec=PluginDecodeResponse)
    decoded.unique_identifier = "acme/demo:0.0.2"
    monkeypatch.setattr(service.PluginService, "uninstall", uninstall)
    monkeypatch.setattr(service, "package_plugin_files", package_plugin_files)
    monkeypatch.setattr(service.PluginService, "upload_pkg", Mock(return_value=decoded))
    monkeypatch.setattr(
        service.PluginService,
        "install_from_local_pkg",
        Mock(return_value=PluginInstallTaskStartResponse(all_installed=True, task_id="t", task=None)),
    )
    monkeypatch.setattr(service, "resolve_installation_id", Mock(return_value="install-2"))
    monkeypatch.setattr(service, "wait_for_install_task", Mock(return_value=None))
    monkeypatch.setattr(
        service,
        "_list_installed_plugins",
        Mock(
            return_value=[
                SimpleNamespace(
                    plugin_id="acme/demo",
                    plugin_unique_identifier="acme/demo:0.0.1@old",
                    installation_id="install-1",
                )
            ]
        ),
    )
    monkeypatch.setattr(service.time, "sleep", Mock())
    monkeypatch.setattr(
        service,
        "uninstall_installations_for_plugin_id",
        Mock(return_value=service.UninstallByPluginIdResult("acme/demo", [], [])),
    )

    service.install_tool_plugin(
        files=files,
        tenant_id="tenant-1",
        user_id="user-1",
        previous_installation_id="install-1",
    )

    uninstall.assert_called_once_with("tenant-1", "install-1")


def test_install_tool_plugin_requires_exact_installation_id(monkeypatch) -> None:
    files = _valid_files()
    decoded = Mock(spec=PluginDecodeResponse)
    decoded.unique_identifier = "acme/demo:0.0.3"
    monkeypatch.setattr(service, "package_plugin_files", Mock(return_value=b"PK"))
    monkeypatch.setattr(service.PluginService, "upload_pkg", Mock(return_value=decoded))
    monkeypatch.setattr(
        service.PluginService,
        "install_from_local_pkg",
        Mock(return_value=PluginInstallTaskStartResponse(all_installed=True, task_id="t", task=None)),
    )
    monkeypatch.setattr(service, "wait_for_install_task", Mock(return_value=None))
    monkeypatch.setattr(service, "resolve_installation_id", Mock(return_value=None))
    monkeypatch.setattr(service, "_list_installed_plugins", Mock(return_value=[]))
    monkeypatch.setattr(
        service,
        "uninstall_installations_for_plugin_id",
        Mock(return_value=service.UninstallByPluginIdResult("acme/demo", [], [])),
    )

    with pytest.raises(service.ToolPluginInstallError, match="installation_id"):
        service.install_tool_plugin(files=files, tenant_id="tenant-1", user_id="user-1")


def test_install_tool_plugin_rejects_foreign_same_plugin_id(monkeypatch) -> None:
    files = _valid_files()
    decoded = Mock(spec=PluginDecodeResponse)
    decoded.unique_identifier = "ghy/remove-bg:0.0.1@newhash"
    install_from_local_pkg = Mock()
    monkeypatch.setattr(service, "package_plugin_files", Mock(return_value=b"PK"))
    monkeypatch.setattr(service.PluginService, "upload_pkg", Mock(return_value=decoded))
    monkeypatch.setattr(service.PluginService, "install_from_local_pkg", install_from_local_pkg)
    monkeypatch.setattr(
        service,
        "_list_installed_plugins",
        Mock(
            return_value=[
                SimpleNamespace(
                    plugin_id="ghy/remove-bg",
                    plugin_unique_identifier="ghy/remove-bg:0.0.1@oldhash",
                    installation_id="foreign-1",
                )
            ]
        ),
    )

    with pytest.raises(service.ToolPluginOwnershipError, match="already installed"):
        service.install_tool_plugin(files=files, tenant_id="tenant-1", user_id="user-1")

    install_from_local_pkg.assert_not_called()


def test_install_tool_plugin_does_not_adopt_same_hash_without_owned_id(monkeypatch) -> None:
    files = _valid_files()
    decoded = Mock(spec=PluginDecodeResponse)
    decoded.unique_identifier = "ghy/doubao-tool:0.1.0@same"
    install_from_local_pkg = Mock()
    monkeypatch.setattr(service, "package_plugin_files", Mock(return_value=b"PK"))
    monkeypatch.setattr(service.PluginService, "upload_pkg", Mock(return_value=decoded))
    monkeypatch.setattr(service.PluginService, "install_from_local_pkg", install_from_local_pkg)
    monkeypatch.setattr(
        service,
        "_list_installed_plugins",
        Mock(
            return_value=[
                SimpleNamespace(
                    plugin_id="ghy/doubao-tool",
                    plugin_unique_identifier="ghy/doubao-tool:0.1.0@same",
                    installation_id="keep-me",
                )
            ]
        ),
    )

    try:
        service.install_tool_plugin(files=files, tenant_id="tenant-1", user_id="user-1")
    except service.ToolPluginOwnershipError:
        pass
    else:
        raise AssertionError("An existing same-hash install still needs session ownership")

    install_from_local_pkg.assert_not_called()


def test_install_tool_plugin_force_rebuilds_same_hash_on_reinstall(monkeypatch) -> None:
    files = _valid_files()
    decoded = Mock(spec=PluginDecodeResponse)
    decoded.unique_identifier = "ghy/removebg:0.0.1@same"
    install_from_local_pkg = Mock(
        return_value=PluginInstallTaskStartResponse(all_installed=True, task_id="t", task=None)
    )
    call_order: list[str] = []

    def upload_tracking(*_args, **_kwargs):
        call_order.append("upload")
        return decoded

    def uninstall_tracking(*_args, **_kwargs):
        call_order.append("uninstall")
        return True

    upload_pkg = Mock(side_effect=upload_tracking)
    uninstall = Mock(side_effect=uninstall_tracking)
    sleep = Mock()
    monkeypatch.setattr(service, "package_plugin_files", Mock(return_value=b"PK"))
    monkeypatch.setattr(service.PluginService, "upload_pkg", upload_pkg)
    monkeypatch.setattr(service.PluginService, "install_from_local_pkg", install_from_local_pkg)
    monkeypatch.setattr(service.PluginService, "uninstall", uninstall)
    monkeypatch.setattr(service, "wait_for_install_task", Mock(return_value=None))
    monkeypatch.setattr(service, "resolve_installation_id", Mock(return_value="install-new"))
    monkeypatch.setattr(service, "purge_plugin_cwd_for_unique_identifier", Mock())
    monkeypatch.setattr(service.time, "sleep", sleep)
    monkeypatch.setattr(
        service,
        "_list_installed_plugins",
        Mock(
            return_value=[
                SimpleNamespace(
                    plugin_id="ghy/removebg",
                    plugin_unique_identifier="ghy/removebg:0.0.1@same",
                    installation_id="keep-me",
                )
            ]
        ),
    )

    result = service.install_tool_plugin(
        files=files,
        tenant_id="tenant-1",
        user_id="user-1",
        previous_installation_id="keep-me",
    )

    uninstall.assert_called_once_with("tenant-1", "keep-me")
    sleep.assert_called_once_with(1)
    assert upload_pkg.call_count == 2
    # Last upload must happen after uninstall so decode still finds the package.
    assert call_order == ["upload", "uninstall", "upload"]
    install_from_local_pkg.assert_called_once_with("tenant-1", ["ghy/removebg:0.0.1@same"])
    assert result.installation_id == "install-new"


def test_uninstall_installations_for_plugin_id_removes_all_matches(monkeypatch) -> None:
    plugins = [
        SimpleNamespace(
            plugin_id="ghy/remove-bg",
            installation_id="a",
            plugin_unique_identifier="ghy/remove-bg:0.0.1@a",
        ),
        SimpleNamespace(plugin_id="other/x", installation_id="b", plugin_unique_identifier="other/x:1@b"),
        SimpleNamespace(
            plugin_id="ghy/remove-bg",
            installation_id="c",
            plugin_unique_identifier="ghy/remove-bg:0.0.1@c",
        ),
    ]
    uninstall = Mock(return_value=True)
    monkeypatch.setattr(service, "_list_installed_plugins", Mock(return_value=plugins))
    monkeypatch.setattr(service.PluginService, "uninstall", uninstall)

    result = service.uninstall_installations_for_plugin_id(tenant_id="tenant-1", plugin_id="ghy/remove-bg")

    assert result.uninstalled_installation_ids == ["a", "c"]
    assert result.failed_installation_ids == []
    assert [call.args for call in uninstall.call_args_list] == [
        ("tenant-1", "a"),
        ("tenant-1", "c"),
    ]


def test_uninstall_installations_for_plugin_id_skips_excluded_unique_identifier(monkeypatch) -> None:
    plugins = [
        SimpleNamespace(
            plugin_id="ghy/remove-bg",
            installation_id="old",
            plugin_unique_identifier="ghy/remove-bg:0.0.1@old",
        ),
        SimpleNamespace(
            plugin_id="ghy/remove-bg",
            installation_id="keep",
            plugin_unique_identifier="ghy/remove-bg:0.0.1@new",
        ),
    ]
    uninstall = Mock(return_value=True)
    monkeypatch.setattr(service, "_list_installed_plugins", Mock(return_value=plugins))
    monkeypatch.setattr(service.PluginService, "uninstall", uninstall)

    result = service.uninstall_installations_for_plugin_id(
        tenant_id="tenant-1",
        plugin_id="ghy/remove-bg",
        exclude_unique_identifiers={"ghy/remove-bg:0.0.1@new"},
    )

    assert result.uninstalled_installation_ids == ["old"]
    uninstall.assert_called_once_with("tenant-1", "old")


def test_enrich_install_error_message_adds_cwd_hint_for_gevent() -> None:
    message = service.enrich_install_error_message(
        "failed to launch plugin: ModuleNotFoundError: No module named 'gevent._gevent_c_hub_local'"
    )
    assert "gevent._gevent_c_hub_local" in message
    assert "cwd/.venv" in message
    assert "plugin_daemon" in message


def test_plugin_id_from_unique_identifier() -> None:
    assert service.plugin_id_from_unique_identifier("ghy/remove-bg:0.0.1@abc") == "ghy/remove-bg"
    assert service.plugin_id_from_unique_identifier("acme/demo:0.0.1") == "acme/demo"
    assert service.plugin_id_from_unique_identifier("acme/demo") == "acme/demo"


def test_resolve_installation_id_hits_second_page(monkeypatch) -> None:
    page1 = SimpleNamespace(
        list=[SimpleNamespace(plugin_unique_identifier="other/a:1@x", plugin_id="other/a", installation_id="i1")],
        total=2,
    )
    page2 = SimpleNamespace(
        list=[
            SimpleNamespace(
                plugin_unique_identifier="ghy/remove-bg:0.0.1@hash",
                plugin_id="ghy/remove-bg",
                installation_id="install-new",
            )
        ],
        total=2,
    )
    list_with_total = Mock(side_effect=[page1, page2])
    monkeypatch.setattr(service.PluginService, "list_with_total", list_with_total)

    installation_id = service.resolve_installation_id(
        tenant_id="tenant-1",
        plugin_unique_identifier="ghy/remove-bg:0.0.1@hash",
        max_attempts=1,
        interval_seconds=0,
        page_size=1,
    )

    assert installation_id == "install-new"
    assert list_with_total.call_count == 2


def test_resolve_installation_id_retries_until_found(monkeypatch) -> None:
    empty = SimpleNamespace(list=[], total=0)
    found = SimpleNamespace(
        list=[
            SimpleNamespace(
                plugin_unique_identifier="acme/demo:0.0.1@h",
                plugin_id="acme/demo",
                installation_id="install-later",
            )
        ],
        total=1,
    )
    list_with_total = Mock(side_effect=[empty, found])
    sleep = Mock()
    monkeypatch.setattr(service.PluginService, "list_with_total", list_with_total)
    monkeypatch.setattr(service.time, "sleep", sleep)

    installation_id = service.resolve_installation_id(
        tenant_id="tenant-1",
        plugin_unique_identifier="acme/demo:0.0.1@h",
        max_attempts=5,
        interval_seconds=1.0,
    )

    assert installation_id == "install-later"
    sleep.assert_called_once_with(1.0)


def test_resolve_installation_id_does_not_fall_back_to_same_plugin_id(monkeypatch) -> None:
    response = SimpleNamespace(
        list=[
            SimpleNamespace(
                plugin_unique_identifier="ghy/remove-bg:0.0.1@old",
                plugin_id="ghy/remove-bg",
                installation_id="install-old",
                created_at=1,
            ),
            SimpleNamespace(
                plugin_unique_identifier="ghy/remove-bg:0.0.1@newer",
                plugin_id="ghy/remove-bg",
                installation_id="install-newer",
                created_at=2,
            ),
        ],
        total=2,
    )
    monkeypatch.setattr(service.PluginService, "list_with_total", Mock(return_value=response))

    installation_id = service.resolve_installation_id(
        tenant_id="tenant-1",
        plugin_unique_identifier="ghy/remove-bg:0.0.1@missing",
        max_attempts=1,
        interval_seconds=0,
    )

    assert installation_id is None


def test_wait_for_install_task_polls_until_success(monkeypatch) -> None:
    pending = SimpleNamespace(status=PluginInstallTaskStatus.Running, plugins=[])
    success = SimpleNamespace(status=PluginInstallTaskStatus.Success, plugins=[])
    fetch = Mock(side_effect=[pending, success])
    sleep = Mock()
    monkeypatch.setattr(service.PluginService, "fetch_install_task", fetch)
    monkeypatch.setattr(service.time, "sleep", sleep)

    result = service.wait_for_install_task(
        tenant_id="tenant-1",
        task_start=PluginInstallTaskStartResponse(all_installed=False, task_id="task-9", task=None),
        interval_seconds=0.01,
    )

    assert result is success
    assert fetch.call_count == 2
    sleep.assert_called_once()


def test_plugin_cwd_relpath_from_unique_identifier() -> None:
    assert (
        service.plugin_cwd_relpath_from_unique_identifier(
            "ghy/doubao-tool:0.1.0@0787fa074ded2fc36f8064087ebc9bf57fda130d54bbdf4039f3568fe01aa030"
        )
        == "ghy/doubao-tool-0.1.0@0787fa074ded2fc36f8064087ebc9bf57fda130d54bbdf4039f3568fe01aa030"
    )


def test_enrich_install_error_mentions_deps_timeout() -> None:
    msg = service.enrich_install_error_message(
        "failed to launch plugin: failed to install dependencies: BrokenPipe"
    )
    assert "PLUGIN_PYTHON_ENV_INIT_TIMEOUT" in msg
    assert "PIP_MIRROR_URL" in msg


def test_purge_plugin_cwd_for_unique_identifier(tmp_path, monkeypatch) -> None:
    plugin_dir = tmp_path / "ghy" / "demo-0.0.1@abc"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / ".venv").mkdir()
    monkeypatch.setenv("PLUGIN_DAEMON_HOST_CWD", str(tmp_path))
    assert service.purge_plugin_cwd_for_unique_identifier("ghy/demo:0.0.1@abc") is True
    assert not plugin_dir.exists()
