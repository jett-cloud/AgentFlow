from unittest.mock import Mock

import httpx
import pytest

from services.tool_plugin_generator.daemon_preflight import (
    DaemonPreflightClient,
    DaemonPreflightLimits,
    DaemonPreflightUnavailableError,
)


def _response(status: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=payload or {}, request=httpx.Request("GET", "http://daemon"))


def test_daemon_preflight_limits_are_secure_by_default() -> None:
    limits = DaemonPreflightLimits()
    assert limits.network_enabled is False
    assert limits.workspace_credentials_enabled is False
    assert limits.memory_bytes > 0
    assert limits.import_timeout_seconds < limits.total_timeout_seconds


def test_daemon_preflight_capability_does_not_fake_missing_api(monkeypatch) -> None:
    request = Mock(return_value=_response(404))
    monkeypatch.setattr(DaemonPreflightClient, "_request", request)
    client = DaemonPreflightClient()

    assert client.capability().available is False
    with pytest.raises(DaemonPreflightUnavailableError):
        client.stage(package=b"zip", attempt_id="attempt-1")


def test_daemon_preflight_stage_uses_package_and_explicit_limits(monkeypatch) -> None:
    request = Mock(return_value=_response(200, {"attempt_id": "attempt-1", "status": "staged"}))
    monkeypatch.setattr(DaemonPreflightClient, "_request", request)

    result = DaemonPreflightClient().stage(package=b"zip", attempt_id="attempt-1")

    assert result.status == "staged"
    call = request.call_args
    assert call.args[:2] == ("POST", "plugin/preflight/stage")
    assert call.kwargs["files"]["package"][1] == b"zip"
    assert '"network_enabled": false' in call.kwargs["data"]["limits"]
