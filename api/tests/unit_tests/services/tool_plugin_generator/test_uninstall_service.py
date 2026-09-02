from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call

from services.tool_plugin_generator import uninstall_service


def test_uninstall_plugin_with_studio_sessions_deletes_linked_sessions(monkeypatch) -> None:
    sessions = [
        {
            "id": "s1",
            "message_count": 2,
            "plugin_name": "demo",
            "plugin_unique_identifier": "acme/demo:0.0.1",
        }
    ]
    monkeypatch.setattr(
        uninstall_service,
        "preview_sessions_for_installation",
        Mock(return_value=sessions),
    )
    monkeypatch.setattr(
        uninstall_service,
        "delete_sessions_by_installation",
        Mock(return_value=["s1"]),
    )
    monkeypatch.setattr(uninstall_service.PluginService, "uninstall", Mock(return_value=True))
    installed = MagicMock(installation_id="inst-1", plugin_id="acme/demo")
    monkeypatch.setattr(
        uninstall_service,
        "PluginInstaller",
        Mock(return_value=MagicMock(list_plugins=Mock(return_value=[installed]))),
    )
    session_lock = MagicMock()
    plugin_lock = MagicMock()
    acquire_session = Mock(return_value=session_lock)
    acquire_plugin = Mock(return_value=plugin_lock)
    release = Mock()
    monkeypatch.setattr(uninstall_service, "acquire_session_operation_lock", acquire_session)
    monkeypatch.setattr(uninstall_service, "acquire_plugin_publish_lock", acquire_plugin)
    monkeypatch.setattr(uninstall_service, "release_session_operation_lock", release)

    result = uninstall_service.uninstall_plugin_with_studio_sessions(
        tenant_id="t1",
        account_id="a1",
        plugin_installation_id="inst-1",
        delete_studio_sessions=True,
        plugin_unique_identifier="acme/demo:0.0.1",
    )

    assert result.success is True
    assert result.deleted_session_ids == ["s1"]
    assert result.sessions == sessions
    uninstall_service.PluginService.uninstall.assert_called_once_with("t1", "inst-1")
    uninstall_service.delete_sessions_by_installation.assert_called_once()
    acquire_session.assert_called_once_with(tenant_id="t1", account_id="a1", session_id="s1")
    acquire_plugin.assert_called_once_with(tenant_id="t1", plugin_id="acme/demo")
    assert release.call_args_list == [call(plugin_lock), call(session_lock)]


def test_list_sessions_by_installation_filters(monkeypatch) -> None:
    from services.tool_plugin_generator import session_service

    row_match = MagicMock()
    row_match.installation_id = "inst-1"
    row_match.plugin_unique_identifier = "acme/demo:1"
    row_match.messages = [{"role": "user", "content": "hi"}]
    row_match.id = "s1"
    row_other = MagicMock()
    row_other.installation_id = "inst-2"
    row_other.plugin_unique_identifier = "other"
    row_other.messages = []
    row_other.id = "s2"

    fake = MagicMock()
    fake.scalars.return_value.all.return_value = [row_match, row_other]
    monkeypatch.setattr(session_service.db, "session", fake)
    monkeypatch.setattr(
        session_service,
        "session_to_summary",
        lambda row: {"id": row.id, "plugin_name": "x"},
    )

    result = session_service.list_sessions_by_installation(
        tenant_id="t1",
        account_id="a1",
        installation_id="inst-1",
    )
    assert len(result) == 1
    assert result[0]["id"] == "s1"
    assert result[0]["message_count"] == 1


def test_purge_holds_plugin_and_linked_session_locks(monkeypatch) -> None:
    sessions = [
        {
            "id": "s1",
            "installation_id": "inst-1",
            "plugin_unique_identifier": "acme/demo:0.0.1",
        }
    ]
    monkeypatch.setattr(uninstall_service, "_sessions_for_plugin_id", Mock(return_value=sessions))
    monkeypatch.setattr(
        uninstall_service,
        "uninstall_installations_for_plugin_id",
        Mock(
            return_value=SimpleNamespace(
                plugin_id="acme/demo",
                uninstalled_installation_ids=["inst-1"],
                failed_installation_ids=[],
            )
        ),
    )
    monkeypatch.setattr(uninstall_service, "delete_sessions_by_installation", Mock(return_value=["s1"]))
    session_lock = MagicMock()
    plugin_lock = MagicMock()
    acquire_session = Mock(return_value=session_lock)
    acquire_plugin = Mock(return_value=plugin_lock)
    release = Mock()
    monkeypatch.setattr(uninstall_service, "acquire_session_operation_lock", acquire_session)
    monkeypatch.setattr(uninstall_service, "acquire_plugin_publish_lock", acquire_plugin)
    monkeypatch.setattr(uninstall_service, "release_session_operation_lock", release)

    result = uninstall_service.purge_installations_for_plugin_id(
        tenant_id="t1",
        account_id="a1",
        plugin_id="acme/demo",
    )

    assert result.uninstalled_installation_ids == ["inst-1"]
    assert result.deleted_session_ids == ["s1"]
    acquire_session.assert_called_once_with(tenant_id="t1", account_id="a1", session_id="s1")
    acquire_plugin.assert_called_once_with(tenant_id="t1", plugin_id="acme/demo")
    assert release.call_args_list == [call(plugin_lock), call(session_lock)]
