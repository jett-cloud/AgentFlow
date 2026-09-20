"""Synchronous verify-and-publish orchestration for tool-plugin studio drafts.

Credentials are request-scoped inputs: this module uses them only for the candidate
tool invocation and returns diagnostics with credential values removed. A failed
candidate is uninstalled; when a previously published source exists, it is restored.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import yaml

from core.plugin.plugin_service import PluginService
from services.tool_plugin_generator.preview_mapper import map_files_to_preview_tool, sanitize_plugin_id_segment
from services.tool_plugin_generator.service import (
    InstallResult,
    ToolPluginInstallError,
    ToolPluginOwnershipError,
    install_tool_plugin,
    test_tool_plugin,
    uninstall_plugin_unique_identifier,
)
from services.tool_plugin_generator.validator import ToolPluginValidationError, validate_plugin_files


@dataclass(frozen=True)
class PublishResult:
    ok: bool
    status: str
    plugin_unique_identifier: str | None
    installation_id: str | None
    output_text: str
    elapsed_ms: int
    diagnostic: dict[str, Any] | None
    rollback_succeeded: bool | None = None


def redact_sensitive_text(text: str | None, credentials: dict[str, Any]) -> str:
    redacted = str(text or "")
    secret_values = sorted(
        {str(value) for value in credentials.values() if value is not None and str(value)},
        key=len,
        reverse=True,
    )
    for value in secret_values:
        redacted = redacted.replace(value, "******")
    return redacted[:2000]


def _classify_error(message: str) -> str:
    lowered = message.lower()
    if any(marker in lowered for marker in ("api key", "credential", "unauthorized", "401", "403", "forbidden")):
        return "credential_error"
    if any(marker in lowered for marker in ("parameter", "required field", "missing input", "validation error")):
        return "parameter_error"
    return "plugin_runtime_error"


def _diagnostic(*, stage: str, message: str, tool_name: str) -> dict[str, Any]:
    if stage == "persist":
        error_type = "persistence_error"
    elif stage in {"input", "test"}:
        error_type = _classify_error(message)
    else:
        error_type = "plugin_runtime_error"
    return {
        "stage": stage,
        "error_type": error_type,
        "message": message,
        "tool_name": tool_name,
        "created_at": datetime.now(UTC).isoformat(),
    }


def _require_session_manifest_identity(
    files: dict[str, str],
    *,
    author: str,
    plugin_name: str,
) -> None:
    manifest_content = files.get("manifest.yaml") or files.get("manifest.yml") or ""
    manifest = yaml.safe_load(manifest_content) or {}
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be an object")
    actual_identity = (
        sanitize_plugin_id_segment(str(manifest.get("author") or "")),
        sanitize_plugin_id_segment(str(manifest.get("name") or "")),
    )
    expected_identity = (
        sanitize_plugin_id_segment(author),
        sanitize_plugin_id_segment(plugin_name),
    )
    if actual_identity != expected_identity:
        raise ValueError("Manifest identity must match the server-owned studio session identity")


def _uninstall_candidate(*, tenant_id: str, installation_id: str | None) -> bool:
    if not installation_id:
        return True
    try:
        return bool(PluginService.uninstall(tenant_id, installation_id))
    except Exception:
        return False


def _restore_previous(
    *,
    tenant_id: str,
    user_id: str,
    published_files: dict[str, str],
) -> InstallResult | None:
    if not published_files:
        return None
    try:
        # The daemon can briefly report a just-uninstalled candidate as present.
        time.sleep(1)
        return install_tool_plugin(
            files=published_files,
            tenant_id=tenant_id,
            user_id=user_id,
            previous_installation_id=None,
        )
    except Exception:
        return None


def rollback_published_candidate(
    *,
    tenant_id: str,
    user_id: str,
    candidate_installation_id: str | None,
    published_files: dict[str, str],
    tool_name: str,
) -> PublishResult:
    """Compensate a verified candidate when final session persistence fails."""
    candidate_removed = _uninstall_candidate(
        tenant_id=tenant_id,
        installation_id=candidate_installation_id,
    )
    restored = _restore_previous(
        tenant_id=tenant_id,
        user_id=user_id,
        published_files=published_files,
    )
    rollback_succeeded = candidate_removed and (not published_files or restored is not None)
    return PublishResult(
        ok=False,
        status="publish_failed" if rollback_succeeded else "rollback_failed",
        plugin_unique_identifier=restored.plugin_unique_identifier if restored else None,
        installation_id=restored.installation_id if restored else None,
        output_text="",
        elapsed_ms=0,
        diagnostic=_diagnostic(
            stage="persist",
            message="Installed candidate could not be recorded; publish was rolled back",
            tool_name=tool_name,
        ),
        rollback_succeeded=rollback_succeeded,
    )


def publish_tool_plugin(
    *,
    files: dict[str, str],
    published_files: dict[str, str],
    tenant_id: str,
    user_id: str,
    owned_installation_id: str | None,
    owned_plugin_unique_identifier: str | None,
    author: str,
    plugin_name: str,
    tool_name: str,
    parameters: dict[str, Any],
    credentials: dict[str, Any],
    publish_mode: Literal["test", "direct"] = "test",
) -> PublishResult:
    """Install a valid draft, optionally invoke it, and roll back on verification failure.

    ``direct`` mode still runs local validation and package installation, but it
    deliberately skips required test inputs and external tool invocation.
    """
    try:
        validate_plugin_files(files)
        _require_session_manifest_identity(files, author=author, plugin_name=plugin_name)
        preview = map_files_to_preview_tool(
            files,
            author=author,
            plugin_name=plugin_name,
            tool_name=tool_name,
        )
    except (ToolPluginValidationError, ValueError) as exc:
        raw_message = "; ".join(exc.errors) if isinstance(exc, ToolPluginValidationError) else str(exc)
        message = redact_sensitive_text(raw_message, credentials)
        return PublishResult(
            ok=False,
            status="publish_failed",
            plugin_unique_identifier=owned_plugin_unique_identifier,
            installation_id=owned_installation_id,
            output_text="",
            elapsed_ms=0,
            diagnostic=_diagnostic(stage="validate", message=message, tool_name=tool_name),
        )
    provider_id = str(preview.get("provider_id") or "")
    if publish_mode == "test":
        required_parameters = {
            str(item.get("name"))
            for item in preview.get("parameters_schema") or []
            if isinstance(item, dict) and item.get("required") and item.get("name")
        }
        missing_parameters = sorted(
            name for name in required_parameters if parameters.get(name) is None or parameters.get(name) == ""
        )
        if missing_parameters:
            message = f"Missing required test parameters: {', '.join(missing_parameters)}"
            return PublishResult(
                ok=False,
                status="publish_failed",
                plugin_unique_identifier=owned_plugin_unique_identifier,
                installation_id=owned_installation_id,
                output_text="",
                elapsed_ms=0,
                diagnostic=_diagnostic(stage="input", message=message, tool_name=tool_name),
            )
        required_credentials = {
            str(item.get("name"))
            for item in preview.get("credentials_schema") or []
            if isinstance(item, dict) and item.get("required") and item.get("name")
        }
        missing_credentials = sorted(
            name for name in required_credentials if credentials.get(name) is None or credentials.get(name) == ""
        )
        if missing_credentials:
            message = f"Missing required credentials: {', '.join(missing_credentials)}"
            return PublishResult(
                ok=False,
                status="publish_failed",
                plugin_unique_identifier=owned_plugin_unique_identifier,
                installation_id=owned_installation_id,
                output_text="",
                elapsed_ms=0,
                diagnostic=_diagnostic(stage="input", message=message, tool_name=tool_name),
            )
    try:
        candidate = install_tool_plugin(
            files=files,
            tenant_id=tenant_id,
            user_id=user_id,
            previous_installation_id=owned_installation_id,
        )
    except ToolPluginOwnershipError:
        raise
    except ToolPluginInstallError as exc:
        message = redact_sensitive_text(exc.message, credentials)
        if not exc.plugin_unique_identifier:
            return PublishResult(
                ok=False,
                status="publish_failed",
                plugin_unique_identifier=owned_plugin_unique_identifier,
                installation_id=owned_installation_id,
                output_text="",
                elapsed_ms=0,
                diagnostic=_diagnostic(stage="package", message=message, tool_name=tool_name),
                rollback_succeeded=True,
            )
        candidate_removed = not exc.plugin_unique_identifier or uninstall_plugin_unique_identifier(
            tenant_id=tenant_id,
            plugin_unique_identifier=exc.plugin_unique_identifier,
        )
        restored = _restore_previous(
            tenant_id=tenant_id,
            user_id=user_id,
            published_files=published_files,
        )
        rollback_succeeded = candidate_removed and (not published_files or restored is not None)
        return PublishResult(
            ok=False,
            status="publish_failed" if rollback_succeeded else "rollback_failed",
            plugin_unique_identifier=restored.plugin_unique_identifier if restored else None,
            installation_id=restored.installation_id if restored else None,
            output_text="",
            elapsed_ms=0,
            diagnostic=_diagnostic(stage="install", message=message, tool_name=tool_name),
            rollback_succeeded=rollback_succeeded,
        )

    if publish_mode == "direct":
        return PublishResult(
            ok=True,
            status="published",
            plugin_unique_identifier=candidate.plugin_unique_identifier,
            installation_id=candidate.installation_id,
            output_text="未执行真实 API 测试。",
            elapsed_ms=0,
            diagnostic=None,
        )

    test_result = test_tool_plugin(
        tenant_id=tenant_id,
        user_id=user_id,
        provider_id=provider_id,
        tool_name=tool_name,
        parameters=parameters,
        credentials=credentials,
        allow_workspace_credentials=False,
    )
    output_text = redact_sensitive_text(test_result.output_text, credentials)
    runtime_matches_candidate = test_result.plugin_unique_identifier == candidate.plugin_unique_identifier
    if test_result.ok and runtime_matches_candidate:
        return PublishResult(
            ok=True,
            status="published",
            plugin_unique_identifier=candidate.plugin_unique_identifier,
            installation_id=candidate.installation_id,
            output_text=output_text,
            elapsed_ms=test_result.elapsed_ms,
            diagnostic=None,
        )

    failure_message = test_result.error or test_result.output_text or "Tool verification failed"
    if test_result.ok and not runtime_matches_candidate:
        failure_message = "Tool verification resolved a runtime other than the installed candidate"
    message = redact_sensitive_text(failure_message, credentials)
    candidate_removed = _uninstall_candidate(
        tenant_id=tenant_id,
        installation_id=candidate.installation_id,
    )
    restored = _restore_previous(
        tenant_id=tenant_id,
        user_id=user_id,
        published_files=published_files,
    )
    rollback_succeeded = candidate_removed and (not published_files or restored is not None)
    return PublishResult(
        ok=False,
        status="publish_failed" if rollback_succeeded else "rollback_failed",
        plugin_unique_identifier=restored.plugin_unique_identifier if restored else None,
        installation_id=restored.installation_id if restored else None,
        output_text=output_text,
        elapsed_ms=test_result.elapsed_ms,
        diagnostic=_diagnostic(stage="test", message=message, tool_name=tool_name),
        rollback_succeeded=rollback_succeeded,
    )
