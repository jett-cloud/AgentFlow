"""Client contract for daemon-native candidate staging and atomic activation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.plugin.impl.base import BasePluginClient


class DaemonActivationUnavailableError(RuntimeError):
    pass


class ActivationConflictError(RuntimeError):
    pass


class StagedCandidate(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidate_id: str = Field(min_length=1)
    plugin_id: str = Field(min_length=1)
    previous_active_id: str | None = None


class CandidateHealth(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidate_id: str
    healthy: bool
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


class ActivationResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    active_id: str
    previous_active_id: str | None = None


@dataclass(frozen=True)
class ActivationCapability:
    available: bool
    status_code: int


class DaemonActivationClient(BasePluginClient):
    def capability(self) -> ActivationCapability:
        response = self._request("OPTIONS", "plugin/candidates/stage")
        return ActivationCapability(available=response.status_code != 404, status_code=response.status_code)

    def stage_candidate(self, *, package: bytes, attempt_id: str) -> StagedCandidate:
        response = self._request(
            "POST",
            "plugin/candidates/stage",
            data={"attempt_id": attempt_id},
            files={"package": ("plugin.difypkg", package, "application/zip")},
        )
        self._require_available(response.status_code)
        response.raise_for_status()
        return StagedCandidate.model_validate(response.json())

    def health(self, candidate_id: str) -> CandidateHealth:
        response = self._request("GET", f"plugin/candidates/{candidate_id}/health")
        self._require_available(response.status_code)
        response.raise_for_status()
        return CandidateHealth.model_validate(response.json())

    def activate(self, *, candidate_id: str, expected_active_id: str | None) -> ActivationResult:
        response = self._request(
            "POST",
            f"plugin/candidates/{candidate_id}/activate",
            data={"expected_active_id": expected_active_id or ""},
        )
        self._require_available(response.status_code)
        if response.status_code == 409:
            raise ActivationConflictError("active installation changed before candidate activation")
        response.raise_for_status()
        return ActivationResult.model_validate(response.json())

    def rollback_activation(self, *, previous_active_id: str) -> ActivationResult:
        response = self._request(
            "POST", "plugin/candidates/rollback", data={"previous_active_id": previous_active_id}
        )
        self._require_available(response.status_code)
        response.raise_for_status()
        return ActivationResult.model_validate(response.json())

    def delete_candidate(self, candidate_id: str) -> None:
        response = self._request("DELETE", f"plugin/candidates/{candidate_id}")
        self._require_available(response.status_code)
        response.raise_for_status()

    @staticmethod
    def _require_available(status_code: int) -> None:
        if status_code == 404:
            raise DaemonActivationUnavailableError("plugin daemon does not provide native candidate activation")
