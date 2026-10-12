"""Client contract for the daemon-native isolated preflight API.

The deployed daemon currently returns 404 for these routes. This adapter is kept
feature-inactive until capability discovery succeeds; it must not fall back to
installing a temporary plugin while claiming native isolation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.plugin.impl.base import BasePluginClient


class DaemonPreflightUnavailableError(RuntimeError):
    pass


class DaemonPreflightLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    network_enabled: bool = False
    cpu_millis: int = Field(default=1000, gt=0)
    memory_bytes: int = Field(default=268_435_456, gt=0)
    process_limit: int = Field(default=32, gt=0)
    total_timeout_seconds: int = Field(default=60, gt=0)
    import_timeout_seconds: int = Field(default=10, gt=0)
    workspace_credentials_enabled: bool = False


class DaemonPreflightStatus(BaseModel):
    model_config = ConfigDict(extra="allow")

    attempt_id: str
    status: str
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


@dataclass(frozen=True)
class DaemonPreflightCapability:
    available: bool
    status_code: int


class DaemonPreflightClient(BasePluginClient):
    def capability(self) -> DaemonPreflightCapability:
        response = self._request("OPTIONS", "plugin/preflight/stage")
        return DaemonPreflightCapability(available=response.status_code != 404, status_code=response.status_code)

    def stage(
        self,
        *,
        package: bytes,
        attempt_id: str,
        limits: DaemonPreflightLimits | None = None,
    ) -> DaemonPreflightStatus:
        effective_limits = limits or DaemonPreflightLimits()
        response = self._request(
            "POST",
            "plugin/preflight/stage",
            data={
                "attempt_id": attempt_id,
                "limits": json.dumps(effective_limits.model_dump(mode="json")),
            },
            files={"package": ("plugin.difypkg", package, "application/zip")},
        )
        if response.status_code == 404:
            raise DaemonPreflightUnavailableError("plugin daemon does not provide native isolated preflight")
        response.raise_for_status()
        return DaemonPreflightStatus.model_validate(response.json())

    def status(self, attempt_id: str) -> DaemonPreflightStatus:
        response = self._request("GET", f"plugin/preflight/{attempt_id}")
        if response.status_code == 404:
            raise DaemonPreflightUnavailableError("plugin daemon preflight attempt was not found")
        response.raise_for_status()
        return DaemonPreflightStatus.model_validate(response.json())

    def cleanup(self, attempt_id: str) -> None:
        response = self._request("DELETE", f"plugin/preflight/{attempt_id}")
        if response.status_code == 404:
            raise DaemonPreflightUnavailableError("plugin daemon preflight cleanup is unavailable")
        response.raise_for_status()
