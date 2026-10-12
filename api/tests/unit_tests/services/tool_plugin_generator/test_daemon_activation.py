from unittest.mock import Mock

import httpx
import pytest

from services.tool_plugin_generator.daemon_activation import (
    ActivationConflictError,
    DaemonActivationClient,
    DaemonActivationUnavailableError,
)


def _response(status: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=payload or {}, request=httpx.Request("GET", "http://daemon"))


def test_missing_activation_api_is_not_reported_as_atomic(monkeypatch) -> None:
    monkeypatch.setattr(DaemonActivationClient, "_request", Mock(return_value=_response(404)))
    client = DaemonActivationClient()
    assert client.capability().available is False
    with pytest.raises(DaemonActivationUnavailableError):
        client.stage_candidate(package=b"zip", attempt_id="attempt-1")


def test_activation_sends_compare_and_swap_expected_active_id(monkeypatch) -> None:
    request = Mock(
        return_value=_response(200, {"active_id": "new-1", "previous_active_id": "old-1"})
    )
    monkeypatch.setattr(DaemonActivationClient, "_request", request)

    result = DaemonActivationClient().activate(candidate_id="candidate-1", expected_active_id="old-1")

    assert result.active_id == "new-1"
    assert request.call_args.kwargs["data"] == {"expected_active_id": "old-1"}


def test_activation_conflict_is_explicit(monkeypatch) -> None:
    monkeypatch.setattr(DaemonActivationClient, "_request", Mock(return_value=_response(409)))
    with pytest.raises(ActivationConflictError):
        DaemonActivationClient().activate(candidate_id="candidate-1", expected_active_id="old-1")
