"""Synchronous verify-and-publish orchestration for tool-plugin studio drafts.

Credentials are request-scoped inputs: this module uses them only for the candidate
tool invocation and returns diagnostics with credential values removed. A failed
candidate is uninstalled; when a previously published source exists, it is restored.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal

import yaml

from core.plugin.plugin_service import PluginService
from services.tool_plugin_generator.candidate_builder import (
    CandidateSource,
    canonicalize_candidate_source,
    prepare_candidate_source,
    prepare_canonical_candidate,
)
from services.tool_plugin_generator.preflight import ToolPluginPreflightError
from services.tool_plugin_generator.preview_mapper import sanitize_plugin_id_segment
from services.tool_plugin_generator.publish_state_machine import PublishAttempt, PublishState
from services.tool_plugin_generator.service import (
    InstallResult,
    ToolPluginInstallError,
    ToolPluginOwnershipError,
    install_tool_plugin,
    test_tool_plugin,
    uninstall_installations_for_plugin_id,
    uninstall_plugin_unique_identifier,
)
from services.tool_plugin_generator.validator import ToolPluginValidationError


def _staging_enabled() -> bool:
    return os.environ.get("TOOL_PLUGIN_STAGING_ENABLED", "true").lower() in {"1", "true", "yes"}


def _build_staging_source(
    files: dict[str, str], *, plugin_name: str, canonical_digest: str
) -> tuple[dict[str, str], str]:
    """Give an otherwise identical candidate a collision-resistant temporary plugin id."""
    staging_name = f"{plugin_name[:40]}-studio-stage-{canonical_digest[:10]}"
    staged = dict(files)
    manifest_path = "manifest.yaml" if "manifest.yaml" in staged else "manifest.yml"
    manifest = yaml.safe_load(staged[manifest_path]) or {}
    if not isinstance(manifest, dict):
        raise ValueError("Manifest root must be an object")
    manifest["name"] = staging_name
    staged[manifest_path] = yaml.dump(manifest, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return staged, staging_name


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
    build_trace: dict[str, Any] | None = None
    attempt: PublishAttempt | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class _PreparedPublish:
    source: CandidateSource
    preview: dict[str, Any]
    provider_id: str


def _prepare_publish(
    *,
    files: dict[str, str],
    author: str,
    plugin_name: str,
    tool_name: str,
    attempt: PublishAttempt,
) -> _PreparedPublish:
    with attempt.execute_stage(PublishState.PREPARING):
        snapshot = canonicalize_candidate_source(files)
        attempt.draft_digest = snapshot.draft_digest
        attempt.canonical_digest = snapshot.canonical_digest
    with attempt.execute_stage(PublishState.PREFLIGHT):
        source = prepare_canonical_candidate(
            snapshot,
            author=author,
            plugin_name=plugin_name,
            tool_name=tool_name,
            resolve_dependencies=True,
        )
    preview = source.preview or {}
    return _PreparedPublish(
        source=source,
        preview=preview,
        provider_id=str(preview.get("provider_id") or ""),
    )


def _missing_test_input_message(
    *,
    preview: dict[str, Any],
    parameters: dict[str, Any],
    credentials: dict[str, Any],
) -> str | None:
    required_parameters = {
        str(item.get("name"))
        for item in preview.get("parameters_schema") or []
        if isinstance(item, dict) and item.get("required") and item.get("name")
    }
    missing_parameters = sorted(
        name for name in required_parameters if parameters.get(name) is None or parameters.get(name) == ""
    )
    if missing_parameters:
        return f"Missing required test parameters: {', '.join(missing_parameters)}"

    required_credentials = {
        str(item.get("name"))
        for item in preview.get("credentials_schema") or []
        if isinstance(item, dict) and item.get("required") and item.get("name")
    }
    missing_credentials = sorted(
        name for name in required_credentials if credentials.get(name) is None or credentials.get(name) == ""
    )
    if missing_credentials:
        return f"Missing required credentials: {', '.join(missing_credentials)}"
    return None


def _cleanup_stale_stage(
    *, tenant_id: str, staging_plugin_id: str, attempt: PublishAttempt
):
    with attempt.execute_stage(PublishState.STAGE_CLEANUP):
        return uninstall_installations_for_plugin_id(
            tenant_id=tenant_id,
            plugin_id=staging_plugin_id,
        )


def _install_candidate_stage(
    *,
    files: dict[str, str],
    tenant_id: str,
    user_id: str,
    previous_installation_id: str | None,
    stage: PublishState,
    attempt: PublishAttempt,
) -> InstallResult:
    with attempt.execute_stage(stage):
        return install_tool_plugin(
            files=files,
            tenant_id=tenant_id,
            user_id=user_id,
            previous_installation_id=previous_installation_id,
            files_are_canonical=True,
        )


def _verify_candidate_stage(
    *,
    tenant_id: str,
    user_id: str,
    provider_id: str,
    tool_name: str,
    parameters: dict[str, Any],
    credentials: dict[str, Any],
    attempt: PublishAttempt,
):
    with attempt.execute_stage(PublishState.STAGE_VERIFY):
        return test_tool_plugin(
            tenant_id=tenant_id,
            user_id=user_id,
            provider_id=provider_id,
            tool_name=tool_name,
            parameters=parameters,
            credentials=credentials,
            allow_workspace_credentials=False,
        )


def _cleanup_candidate_stage(
    *, tenant_id: str, installation_id: str | None, attempt: PublishAttempt
) -> bool:
    with attempt.execute_stage(PublishState.CLEANUP):
        return _uninstall_candidate(tenant_id=tenant_id, installation_id=installation_id)


def mark_publish_persisted(result: PublishResult) -> PublishResult:
    """Finalize an attempt after the controller-owned persistence stage succeeds."""
    attempt = result.attempt
    if attempt is None or not result.ok:
        return result
    attempt.publish()
    return replace(result, build_trace=attempt.to_trace())


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


def _diagnostic(
    *, stage: str, message: str, tool_name: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    if stage == "persist":
        error_type = "persistence_error"
    elif stage in {"input", "test"}:
        error_type = _classify_error(message)
    else:
        error_type = "plugin_runtime_error"
    result = {
        "stage": stage,
        "error_type": error_type,
        "message": message,
        "tool_name": tool_name,
        "created_at": datetime.now(UTC).isoformat(),
    }
    if details is not None:
        result["details"] = details
    return result


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
    attempt: PublishAttempt | None = None,
) -> PublishResult:
    """Compensate a verified candidate when final session persistence fails."""
    if attempt is None:
        attempt = PublishAttempt(publish_mode="compensation", state=PublishState.PERSIST)
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
    if not attempt.terminal:
        attempt.fail(rollback_failed=not rollback_succeeded)
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
        build_trace=attempt.to_trace(),
        attempt=attempt,
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
    attempt: PublishAttempt | None = None,
) -> PublishResult:
    """Install a valid draft, optionally invoke it, and roll back on verification failure.

    ``direct`` mode still runs local validation and package installation, but it
    deliberately skips required test inputs and external tool invocation.
    """
    attempt = attempt or PublishAttempt(publish_mode=publish_mode)
    if attempt.publish_mode != publish_mode:
        raise ValueError("Publish attempt mode does not match requested publish mode")
    try:
        prepared = _prepare_publish(
            files=files,
            author=author,
            plugin_name=plugin_name,
            tool_name=tool_name,
            attempt=attempt,
        )
    except (ToolPluginValidationError, ValueError) as exc:
        raw_message = "; ".join(exc.errors) if isinstance(exc, ToolPluginValidationError) else str(exc)
        message = redact_sensitive_text(raw_message, credentials)
        details = None
        if not attempt.terminal:
            attempt.transition(PublishState.FAILED)
        build_trace = attempt.to_trace()
        if isinstance(exc, ToolPluginPreflightError):
            details = {"diagnostics": [item.to_dict() for item in exc.diagnostics]}
        return PublishResult(
            ok=False,
            status="publish_failed",
            plugin_unique_identifier=owned_plugin_unique_identifier,
            installation_id=owned_installation_id,
            output_text="",
            elapsed_ms=0,
            diagnostic=_diagnostic(stage="validate", message=message, tool_name=tool_name, details=details),
            build_trace=build_trace,
            attempt=attempt,
        )
    candidate_source = prepared.source
    preview = prepared.preview
    provider_id = prepared.provider_id
    if publish_mode == "test":
        input_error = _missing_test_input_message(
            preview=preview,
            parameters=parameters,
            credentials=credentials,
        )
        if input_error:
            attempt.fail()
            return PublishResult(
                ok=False,
                status="publish_failed",
                plugin_unique_identifier=owned_plugin_unique_identifier,
                installation_id=owned_installation_id,
                output_text="",
                elapsed_ms=0,
                diagnostic=_diagnostic(stage="input", message=input_error, tool_name=tool_name),
                build_trace=attempt.to_trace(),
                attempt=attempt,
            )

    staged_output = ""
    staged_elapsed_ms = 0
    if _staging_enabled():
        staged_files, staging_plugin_name = _build_staging_source(
            candidate_source.canonical_files,
            plugin_name=plugin_name,
            canonical_digest=candidate_source.canonical_digest,
        )
        staged_preview = prepare_candidate_source(
            staged_files,
            author=author,
            plugin_name=staging_plugin_name,
            tool_name=tool_name,
        ).preview or {}
        staging_plugin_id = (
            f"{sanitize_plugin_id_segment(author)}/{sanitize_plugin_id_segment(staging_plugin_name)}"
        )
        stale_cleanup = _cleanup_stale_stage(
            tenant_id=tenant_id,
            staging_plugin_id=staging_plugin_id,
            attempt=attempt,
        )
        if stale_cleanup.failed_installation_ids:
            attempt.fail(rollback_failed=True)
            return PublishResult(
                ok=False,
                status="rollback_failed",
                plugin_unique_identifier=owned_plugin_unique_identifier,
                installation_id=owned_installation_id,
                output_text="",
                elapsed_ms=0,
                diagnostic=_diagnostic(
                    stage="stage_cleanup",
                    message="A stale staged candidate could not be removed",
                    tool_name=tool_name,
                    details={
                        "staging_plugin_id": staging_plugin_id,
                        "failed_installation_ids": stale_cleanup.failed_installation_ids,
                    },
                ),
                rollback_succeeded=False,
                build_trace=attempt.to_trace(),
                attempt=attempt,
            )
        try:
            staged_candidate = _install_candidate_stage(
                files=staged_files,
                tenant_id=tenant_id,
                user_id=user_id,
                previous_installation_id=None,
                stage=PublishState.STAGE_INSTALL,
                attempt=attempt,
            )
        except ToolPluginOwnershipError:
            raise
        except ToolPluginInstallError as exc:
            removed = not exc.plugin_unique_identifier or uninstall_plugin_unique_identifier(
                tenant_id=tenant_id,
                plugin_unique_identifier=exc.plugin_unique_identifier,
            )
            attempt.fail(rollback_failed=not removed)
            return PublishResult(
                ok=False,
                status="publish_failed" if removed else "rollback_failed",
                plugin_unique_identifier=owned_plugin_unique_identifier,
                installation_id=owned_installation_id,
                output_text="",
                elapsed_ms=0,
                diagnostic=_diagnostic(
                    stage="stage_install",
                    message=redact_sensitive_text(exc.message, credentials),
                    tool_name=tool_name,
                ),
                rollback_succeeded=removed,
                build_trace=attempt.to_trace(),
                attempt=attempt,
            )

        if publish_mode == "test":
            staged_test = _verify_candidate_stage(
                tenant_id=tenant_id,
                user_id=user_id,
                provider_id=str(staged_preview.get("provider_id") or ""),
                tool_name=tool_name,
                parameters=parameters,
                credentials=credentials,
                attempt=attempt,
            )
            staged_output = redact_sensitive_text(staged_test.output_text, credentials)
            staged_elapsed_ms = staged_test.elapsed_ms
            runtime_matches_stage = staged_test.plugin_unique_identifier == staged_candidate.plugin_unique_identifier
            if not staged_test.ok or not runtime_matches_stage:
                failure_message = staged_test.error or staged_test.output_text or "Staged tool verification failed"
                if staged_test.ok and not runtime_matches_stage:
                    failure_message = "Tool verification resolved a runtime other than the staged candidate"
                removed = _uninstall_candidate(
                    tenant_id=tenant_id,
                    installation_id=staged_candidate.installation_id,
                )
                attempt.fail(rollback_failed=not removed)
                return PublishResult(
                    ok=False,
                    status="publish_failed" if removed else "rollback_failed",
                    plugin_unique_identifier=owned_plugin_unique_identifier,
                    installation_id=owned_installation_id,
                    output_text=staged_output,
                    elapsed_ms=staged_elapsed_ms,
                    diagnostic=_diagnostic(
                        stage="stage_test",
                        message=redact_sensitive_text(failure_message, credentials),
                        tool_name=tool_name,
                    ),
                    rollback_succeeded=removed,
                    build_trace=attempt.to_trace(),
                    attempt=attempt,
                )

        staged_candidate_removed = _cleanup_candidate_stage(
            tenant_id=tenant_id,
            installation_id=staged_candidate.installation_id,
            attempt=attempt,
        )
        if not staged_candidate_removed:
            attempt.fail(rollback_failed=True)
            return PublishResult(
                ok=False,
                status="rollback_failed",
                plugin_unique_identifier=owned_plugin_unique_identifier,
                installation_id=owned_installation_id,
                output_text=staged_output,
                elapsed_ms=staged_elapsed_ms,
                diagnostic=_diagnostic(
                    stage="stage_cleanup",
                    message="Staged candidate passed verification but could not be removed",
                    tool_name=tool_name,
                ),
                rollback_succeeded=False,
                build_trace=attempt.to_trace(),
                attempt=attempt,
            )
    try:
        candidate = _install_candidate_stage(
            files=candidate_source.canonical_files,
            tenant_id=tenant_id,
            user_id=user_id,
            previous_installation_id=owned_installation_id,
            stage=PublishState.COMMIT_INSTALL,
            attempt=attempt,
        )
    except ToolPluginOwnershipError:
        raise
    except ToolPluginInstallError as exc:
        message = redact_sensitive_text(exc.message, credentials)
        if not exc.plugin_unique_identifier:
            attempt.fail()
            return PublishResult(
                ok=False,
                status="publish_failed",
                plugin_unique_identifier=owned_plugin_unique_identifier,
                installation_id=owned_installation_id,
                output_text="",
                elapsed_ms=0,
                diagnostic=_diagnostic(stage="package", message=message, tool_name=tool_name),
                rollback_succeeded=True,
                build_trace=attempt.to_trace(),
                attempt=attempt,
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
        attempt.fail(rollback_failed=not rollback_succeeded)
        return PublishResult(
            ok=False,
            status="publish_failed" if rollback_succeeded else "rollback_failed",
            plugin_unique_identifier=restored.plugin_unique_identifier if restored else None,
            installation_id=restored.installation_id if restored else None,
            output_text="",
            elapsed_ms=0,
            diagnostic=_diagnostic(stage="install", message=message, tool_name=tool_name),
            rollback_succeeded=rollback_succeeded,
            build_trace=attempt.to_trace(),
            attempt=attempt,
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
            build_trace=attempt.to_trace(),
            attempt=attempt,
        )

    if _staging_enabled():
        return PublishResult(
            ok=True,
            status="published",
            plugin_unique_identifier=candidate.plugin_unique_identifier,
            installation_id=candidate.installation_id,
            output_text=staged_output,
            elapsed_ms=staged_elapsed_ms,
            diagnostic=None,
            build_trace=attempt.to_trace(),
            attempt=attempt,
        )

    test_result = _verify_candidate_stage(
        tenant_id=tenant_id,
        user_id=user_id,
        provider_id=provider_id,
        tool_name=tool_name,
        parameters=parameters,
        credentials=credentials,
        attempt=attempt,
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
            build_trace=attempt.to_trace(),
            attempt=attempt,
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
    attempt.fail(rollback_failed=not rollback_succeeded)
    return PublishResult(
        ok=False,
        status="publish_failed" if rollback_succeeded else "rollback_failed",
        plugin_unique_identifier=restored.plugin_unique_identifier if restored else None,
        installation_id=restored.installation_id if restored else None,
        output_text=output_text,
        elapsed_ms=test_result.elapsed_ms,
        diagnostic=_diagnostic(stage="test", message=message, tool_name=tool_name),
        rollback_succeeded=rollback_succeeded,
        build_trace=attempt.to_trace(),
        attempt=attempt,
    )
