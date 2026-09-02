from types import SimpleNamespace

import pytest

from services.tool_plugin_generator import test_authorization


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)


def test_issue_test_authorization_stores_only_credential_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    session = SimpleNamespace(
        revision=4,
        active_tool_name="weather",
        author="acme",
        plugin_name="demo",
        files={"manifest.yaml": "name: demo"},
    )
    monkeypatch.setattr(test_authorization, "redis_client", redis)
    monkeypatch.setattr(test_authorization, "get_session", lambda **_: session)
    monkeypatch.setattr(
        test_authorization,
        "map_files_to_preview_tool",
        lambda *_args, **_kwargs: {"provider_id": "acme/weather"},
    )

    authorization = test_authorization.issue_test_authorization(
        tenant_id="tenant-1",
        account_id="user-1",
        session_id="session-1",
        expected_revision=4,
        tool_name="weather",
        parameters={"city": "Shanghai"},
        credentials={"api_key": "super-secret"},
    )

    stored = next(iter(redis.values.values()))
    assert "super-secret" not in stored
    assert authorization["tool_name"] == "weather"
    assert authorization["provider_id"] == "acme/weather"


def test_consume_test_authorization_is_single_use_and_binds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    session = SimpleNamespace(
        revision=4,
        active_tool_name="weather",
        author="acme",
        plugin_name="demo",
        files={"manifest.yaml": "name: demo"},
    )
    monkeypatch.setattr(test_authorization, "redis_client", redis)
    monkeypatch.setattr(test_authorization, "get_session", lambda **_: session)
    monkeypatch.setattr(test_authorization, "map_files_to_preview_tool", lambda *_args, **_kwargs: {})
    authorization = test_authorization.issue_test_authorization(
        tenant_id="tenant-1",
        account_id="user-1",
        session_id="session-1",
        expected_revision=4,
        tool_name="weather",
        parameters={"city": "Shanghai"},
        credentials={},
    )

    test_authorization.consume_test_authorization(
        tenant_id="tenant-1",
        account_id="user-1",
        session_id="session-1",
        expected_revision=4,
        tool_name="weather",
        parameters={"city": "Shanghai"},
        credentials={},
        token=authorization["token"],
    )

    with pytest.raises(test_authorization.TestAuthorizationError, match="already used"):
        test_authorization.consume_test_authorization(
            tenant_id="tenant-1",
            account_id="user-1",
            session_id="session-1",
            expected_revision=4,
            tool_name="weather",
            parameters={"city": "Shanghai"},
            credentials={},
            token=authorization["token"],
        )
