from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.tool_plugin_generator import session_service


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.deleted: list[object] = []
        self._store: dict[str, object] = {}

    def add(self, row: object) -> None:
        self.added.append(row)
        row_id = getattr(row, "id", None)
        if row_id:
            self._store[str(row_id)] = row

    def delete(self, row: object) -> None:
        self.deleted.append(row)
        row_id = getattr(row, "id", None)
        if row_id is not None:
            self._store.pop(str(row_id), None)
        self.added = [item for item in self.added if item is not row]

    def commit(self) -> None:
        for row in self.added:
            if not getattr(row, "id", None):
                row.id = f"id-{len(self._store) + 1}"
            self._store[str(row.id)] = row
        self.added = []

    def get(self, _model: object, session_id: str) -> object | None:
        return self._store.get(session_id)

    def scalars(self, _stmt: object) -> MagicMock:
        result = MagicMock()
        rows = list(self._store.values())
        result.all.return_value = rows
        result.first.return_value = rows[0] if rows else None
        return result


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> _FakeSession:
    fake = _FakeSession()
    monkeypatch.setattr(session_service.db, "session", fake)

    def find_by_plugin_name(*, tenant_id: str, account_id: str, plugin_name: str):
        for row in fake._store.values():
            if (
                getattr(row, "tenant_id", None) == tenant_id
                and getattr(row, "account_id", None) == account_id
                and getattr(row, "plugin_name", None) == plugin_name
            ):
                return row
        return None

    monkeypatch.setattr(session_service, "find_by_plugin_name", find_by_plugin_name)

    def find_sessions_by_plugin_name(*, tenant_id: str, account_id: str, plugin_name: str):
        return [
            row
            for row in fake._store.values()
            if getattr(row, "tenant_id", None) == tenant_id
            and getattr(row, "account_id", None) == account_id
            and getattr(row, "plugin_name", None) == plugin_name
        ]

    monkeypatch.setattr(session_service, "find_sessions_by_plugin_name", find_sessions_by_plugin_name)

    def list_sessions(*, tenant_id: str, account_id: str, include_hidden: bool = False):
        rows = [
            row
            for row in fake._store.values()
            if getattr(row, "tenant_id", None) == tenant_id
            and getattr(row, "account_id", None) == account_id
            and (include_hidden or not getattr(row, "is_hidden", False))
        ]
        rows.sort(key=lambda item: getattr(item, "updated_at", None) or 0, reverse=True)
        return [session_service.session_to_summary(row) for row in rows]

    monkeypatch.setattr(session_service, "list_sessions", list_sessions)
    return fake


def test_create_session_uses_draft_name_and_lists(fake_db: _FakeSession) -> None:
    row = session_service.create_session(tenant_id="t1", account_id="a1", author="acme")
    assert session_service.is_draft_plugin_name(row.plugin_name)
    assert row.phase == "creating"
    summaries = session_service.list_sessions(tenant_id="t1", account_id="a1")
    assert len(summaries) == 1
    assert summaries[0]["display_name"] == "未命名插件草稿"
    assert row.revision == 0
    assert row.published_files == {}
    assert row.last_publish_diagnostic is None


def test_plugin_publish_lock_is_scoped_by_tenant_and_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    lock = MagicMock()
    lock.acquire.return_value = True
    create_lock = MagicMock(return_value=lock)
    monkeypatch.setattr(session_service.redis_client, "lock", create_lock)

    acquired = session_service.acquire_plugin_publish_lock(
        tenant_id="tenant-1",
        plugin_id="acme/weather",
    )

    assert acquired is lock
    create_lock.assert_called_once_with(
        "tool_plugin_publish:tenant-1:acme/weather",
        timeout=session_service.SESSION_OPERATION_LOCK_SECONDS,
        blocking_timeout=0,
    )
    lock.acquire.assert_called_once_with(blocking=False)


def test_plugin_publish_lock_rejects_a_concurrent_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    lock = MagicMock()
    lock.acquire.return_value = False
    monkeypatch.setattr(session_service.redis_client, "lock", MagicMock(return_value=lock))

    with pytest.raises(session_service.ToolPluginStudioSessionError) as exc_info:
        session_service.acquire_plugin_publish_lock(
            tenant_id="tenant-1",
            plugin_id="acme/weather",
        )

    assert exc_info.value.code == "conflict"


def test_update_session_rejects_a_stale_revision(fake_db: _FakeSession) -> None:
    row = session_service.create_session(
        tenant_id="t1",
        account_id="a1",
        author="acme",
        plugin_name="weather_plugin",
    )
    fake_db._store[row.id] = row

    updated = session_service.update_session(
        tenant_id="t1",
        account_id="a1",
        session_id=row.id,
        expected_revision=0,
        patch={"title": "new title"},
    )

    assert updated.revision == 1
    with pytest.raises(session_service.ToolPluginStudioSessionError) as exc_info:
        session_service.update_session(
            tenant_id="t1",
            account_id="a1",
            session_id=row.id,
            expected_revision=0,
            patch={"title": "stale title"},
        )
    assert exc_info.value.code == "conflict"
    assert updated.title == "new title"


def test_legacy_agent_credentials_are_redacted_from_session_messages(fake_db: _FakeSession) -> None:
    row = session_service.create_session(tenant_id="t1", account_id="a1", author="acme")
    row.messages_json = session_service._dump(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "name": "verify_cycle",
                        "arguments": {"parameters": {"text": "ok"}, "credentials": {"api_key": "sk-secret"}},
                    }
                ],
            }
        ]
    )

    messages = row.messages

    assert "sk-secret" not in str(messages)
    assert messages[0]["tool_calls"][0]["arguments"]["credentials"] == {"api_key": "******"}


def test_update_session_never_persists_structured_credentials(fake_db: _FakeSession) -> None:
    row = session_service.create_session(tenant_id="t1", account_id="a1", author="acme")
    fake_db._store[row.id] = row

    updated = session_service.update_session(
        tenant_id="t1",
        account_id="a1",
        session_id=row.id,
        patch={
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [{"arguments": {"credentials": {"api_key": "sk-secret"}}}],
                }
            ]
        },
    )

    assert "sk-secret" not in updated.messages_json
    assert "******" in updated.messages_json


def test_create_allows_duplicate_plugin_name(fake_db: _FakeSession) -> None:
    first = session_service.create_session(
        tenant_id="t1",
        account_id="a1",
        author="acme",
        plugin_name="weather_plugin",
    )
    fake_db._store[first.id] = first
    second = session_service.create_session(
        tenant_id="t1",
        account_id="a1",
        author="acme",
        plugin_name="weather_plugin",
    )
    assert second.id != first.id
    assert second.plugin_name == "weather_plugin"
    matches = session_service.find_sessions_by_plugin_name(
        tenant_id="t1",
        account_id="a1",
        plugin_name="weather_plugin",
    )
    assert len(matches) == 2


def test_update_locks_after_files_and_blocks_rename(fake_db: _FakeSession) -> None:
    row = session_service.create_session(
        tenant_id="t1",
        account_id="a1",
        author="acme",
        plugin_name="weather_plugin",
    )
    fake_db._store[row.id] = row
    updated = session_service.update_session(
        tenant_id="t1",
        account_id="a1",
        session_id=row.id,
        patch={"files": {"manifest.yaml": "version: 0.0.1\n"}},
    )
    assert updated.phase == "editing"
    assert updated.plugin_locked_at is not None
    with pytest.raises(session_service.ToolPluginStudioSessionError, match="locked"):
        session_service.update_session(
            tenant_id="t1",
            account_id="a1",
            session_id=row.id,
            patch={"plugin_name": "other"},
        )


def test_update_allows_same_plugin_name_as_other_session(fake_db: _FakeSession) -> None:
    first = session_service.create_session(
        tenant_id="t1",
        account_id="a1",
        author="acme",
        plugin_name="weather_plugin",
    )
    fake_db._store[first.id] = first
    second = session_service.create_session(
        tenant_id="t1",
        account_id="a1",
        author="acme",
        plugin_name="__draft__aaaaaaaaaaaa",
    )
    fake_db._store[second.id] = second
    updated = session_service.update_session(
        tenant_id="t1",
        account_id="a1",
        session_id=second.id,
        patch={"plugin_name": "weather_plugin"},
    )
    assert updated.plugin_name == "weather_plugin"


def test_hide_session_keeps_plugin_name_and_unhide_restores(fake_db: _FakeSession) -> None:
    row = session_service.create_session(
        tenant_id="t1",
        account_id="a1",
        author="acme",
        plugin_name="weather_plugin",
    )
    fake_db._store[row.id] = row
    hidden = session_service.hide_session(tenant_id="t1", account_id="a1", session_id=row.id)
    assert hidden.is_hidden is True
    assert hidden.title == "weather_plugin"
    assert hidden.plugin_name == "weather_plugin"
    assert hidden.revision == 1

    other = session_service.create_session(
        tenant_id="t1",
        account_id="a1",
        author="acme",
        plugin_name="weather_plugin",
    )
    assert other.id != hidden.id

    restored = session_service.unhide_session(tenant_id="t1", account_id="a1", session_id=hidden.id)
    assert restored.is_hidden is False
    assert restored.plugin_name == "weather_plugin"
    assert restored.revision == 2


def test_unhide_restores_legacy_hidden_plugin_name(fake_db: _FakeSession) -> None:
    row = session_service.create_session(
        tenant_id="t1",
        account_id="a1",
        author="acme",
        plugin_name="weather_plugin",
    )
    fake_db._store[row.id] = row
    row.title = "weather_plugin"
    row.plugin_name = f"{session_service.HIDDEN_PLUGIN_NAME_PREFIX}{row.id}"
    row.is_hidden = True

    restored = session_service.unhide_session(tenant_id="t1", account_id="a1", session_id=row.id)
    assert restored.is_hidden is False
    assert restored.plugin_name == "weather_plugin"


def test_fork_session_copies_files_and_clears_messages(fake_db: _FakeSession) -> None:
    source = session_service.create_session(
        tenant_id="t1",
        account_id="a1",
        author="acme",
        plugin_name="weather_plugin",
    )
    fake_db._store[source.id] = source
    source = session_service.update_session(
        tenant_id="t1",
        account_id="a1",
        session_id=source.id,
        patch={
            "files": {"manifest.yaml": "version: 0.0.1\n", "tools/echo.yaml": "identity:\n  name: echo\n"},
            "tool_names": ["echo"],
            "active_tool_name": "echo",
            "messages": [{"role": "user", "content": "old chat"}],
            "installation_id": "inst-1",
            "plugin_unique_identifier": "acme/weather_plugin:0.0.1",
            "plugin_status": "installed",
        },
    )
    fake_db._store[source.id] = source

    forked = session_service.fork_session(
        tenant_id="t1",
        account_id="a1",
        source_session_id=source.id,
    )
    assert forked.id != source.id
    assert forked.plugin_name == "weather_plugin"
    assert forked.author == "acme"
    assert forked.files == source.files
    assert forked.messages == []
    assert forked.tool_names == ["echo"]
    assert forked.installation_id is None
    assert forked.plugin_unique_identifier is None
    assert forked.plugin_status == "draft_ready"
    assert forked.phase == "editing"
    assert forked.plugin_locked_at is not None
    assert forked.title == "新增工具 · weather_plugin"
    # source unchanged
    assert source.messages == [{"role": "user", "content": "old chat"}]
    assert source.installation_id == "inst-1"
    assert source.plugin_unique_identifier == "acme/weather_plugin:0.0.1"


def test_fork_empty_draft_raises(fake_db: _FakeSession) -> None:
    source = session_service.create_session(tenant_id="t1", account_id="a1", author="acme")
    fake_db._store[source.id] = source
    with pytest.raises(session_service.ToolPluginStudioSessionError) as exc_info:
        session_service.fork_session(
            tenant_id="t1",
            account_id="a1",
            source_session_id=source.id,
        )
    assert exc_info.value.code == "invalid_param"
