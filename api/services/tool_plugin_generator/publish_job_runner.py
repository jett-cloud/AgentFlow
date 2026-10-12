"""Execute one durable Studio publish job outside the request process."""

from __future__ import annotations

import logging
from typing import Any

from extensions.ext_database import db
from models.tools import ToolPluginPublishJob
from services.tool_plugin_generator.preview_mapper import sanitize_plugin_id_segment
from services.tool_plugin_generator.publish_job_service import (
    decrypt_job_credentials,
    load_job_parameters,
    update_publish_job,
)
from services.tool_plugin_generator.publish_service import (
    PublishResult,
    mark_publish_persisted,
    publish_tool_plugin,
    redact_sensitive_text,
    rollback_published_candidate,
)
from services.tool_plugin_generator.publish_state_machine import PublishAttempt, PublishState
from services.tool_plugin_generator.session_service import (
    acquire_plugin_publish_lock,
    acquire_session_operation_lock,
    get_session,
    release_session_operation_lock,
    update_session,
)

logger = logging.getLogger(__name__)


class PublishJobCancelledError(RuntimeError):
    """Raised only before the publish crosses its first unsafe side-effect boundary."""


def _result_payload(result: PublishResult, *, revision: int | None) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "status": result.status,
        "revision": revision,
        "plugin_unique_identifier": result.plugin_unique_identifier,
        "installation_id": result.installation_id,
        "output_text": result.output_text,
        "elapsed_ms": result.elapsed_ms,
        "diagnostic": result.diagnostic,
        "rollback_succeeded": result.rollback_succeeded,
        "build_trace": result.build_trace,
    }


def _load_job(job_id: str) -> ToolPluginPublishJob:
    job = db.session.get(ToolPluginPublishJob, job_id)
    if job is None:
        raise LookupError(f"Publish job {job_id} was not found")
    return job


def _persist_result(job: ToolPluginPublishJob, result: PublishResult, *, revision: int | None) -> None:
    update_publish_job(
        job,
        status=result.status,
        attempt_id=result.attempt.attempt_id if result.attempt else None,
        trace=result.build_trace,
        diagnostic=result.diagnostic,
        result=_result_payload(result, revision=revision),
        clear_credentials=True,
    )


def execute_publish_job(job_id: str) -> None:
    """Run a queued job once; terminal jobs are idempotent no-ops."""
    job = _load_job(job_id)
    if job.status in {"published", "publish_failed", "rollback_failed", "cancelled"}:
        return
    if job.cancel_requested:
        update_publish_job(job, status="cancelled", clear_credentials=True)
        return

    update_publish_job(job, status="running")
    credentials = decrypt_job_credentials(job)
    session_lock = None
    plugin_lock = None

    def on_change(trace: dict[str, Any]) -> None:
        db.session.refresh(job, attribute_names=["cancel_requested"])
        update_publish_job(job, attempt_id=str(trace["attempt_id"]), trace=trace)

    def before_transition(_target: PublishState) -> None:
        db.session.refresh(job, attribute_names=["cancel_requested"])
        if job.cancel_requested:
            raise PublishJobCancelledError("Publish was cancelled before installation started")

    attempt = PublishAttempt(
        publish_mode=job.publish_mode,
        before_transition=before_transition,
        on_change=on_change,
    )
    try:
        session_lock = acquire_session_operation_lock(
            tenant_id=job.tenant_id,
            account_id=job.account_id,
            session_id=job.session_id,
        )
        studio_session = get_session(
            tenant_id=job.tenant_id,
            account_id=job.account_id,
            session_id=job.session_id,
        )
        if studio_session.revision != job.expected_revision:
            raise RuntimeError(
                f"Session revision changed before publish started: expected {job.expected_revision}, "
                f"got {studio_session.revision}"
            )
        if job.tool_name != studio_session.active_tool_name:
            raise RuntimeError("tool_name no longer matches the session's active tool")
        plugin_identity = (
            sanitize_plugin_id_segment(studio_session.author),
            sanitize_plugin_id_segment(studio_session.plugin_name),
        )
        if not all(plugin_identity):
            raise RuntimeError("Session author and plugin_name must be valid before publishing")
        plugin_lock = acquire_plugin_publish_lock(
            tenant_id=job.tenant_id,
            plugin_id="/".join(plugin_identity),
        )
        result = publish_tool_plugin(
            files=studio_session.files,
            published_files=studio_session.published_files,
            tenant_id=job.tenant_id,
            user_id=job.account_id,
            owned_installation_id=studio_session.installation_id,
            owned_plugin_unique_identifier=studio_session.plugin_unique_identifier,
            author=studio_session.author,
            plugin_name=studio_session.plugin_name,
            tool_name=job.tool_name,
            parameters=load_job_parameters(job),
            credentials=credentials,
            publish_mode=job.publish_mode,
            attempt=attempt,
        )
        update_kwargs = {
            "tenant_id": job.tenant_id,
            "account_id": job.account_id,
            "session_id": job.session_id,
            "expected_revision": job.expected_revision,
            "patch": {
                "published_files": studio_session.files if result.ok else studio_session.published_files,
                "plugin_unique_identifier": result.plugin_unique_identifier,
                "installation_id": result.installation_id,
                "plugin_status": result.status,
                "last_publish_diagnostic": result.diagnostic,
                "last_publish_trace": result.build_trace,
            },
        }
        try:
            if result.ok and result.attempt is not None:
                with result.attempt.execute_stage(PublishState.PERSIST):
                    persisted = update_session(**update_kwargs)
                result = mark_publish_persisted(result)
            else:
                persisted = update_session(**update_kwargs)
        except Exception as persistence_error:
            if not result.ok:
                raise
            result = rollback_published_candidate(
                tenant_id=job.tenant_id,
                user_id=job.account_id,
                candidate_installation_id=result.installation_id,
                published_files=studio_session.published_files,
                tool_name=job.tool_name,
                attempt=result.attempt,
            )
            try:
                current_session = get_session(
                    tenant_id=job.tenant_id,
                    account_id=job.account_id,
                    session_id=job.session_id,
                )
                persisted = update_session(
                    tenant_id=job.tenant_id,
                    account_id=job.account_id,
                    session_id=job.session_id,
                    expected_revision=current_session.revision,
                    patch={
                        "plugin_unique_identifier": result.plugin_unique_identifier,
                        "installation_id": result.installation_id,
                        "plugin_status": result.status,
                        "last_publish_diagnostic": result.diagnostic,
                        "last_publish_trace": result.build_trace,
                    },
                )
            except Exception:
                raise persistence_error
        _persist_result(job, result, revision=persisted.revision)
    except PublishJobCancelledError:
        update_publish_job(
            job,
            status="cancelled",
            attempt_id=attempt.attempt_id,
            trace=attempt.to_trace(),
            clear_credentials=True,
        )
    except Exception as exc:
        logger.exception("Tool-plugin publish job %s failed", job.id)
        diagnostic = {
            "stage": attempt.state.value,
            "message": redact_sensitive_text(str(exc), credentials),
            "tool_name": job.tool_name,
        }
        update_publish_job(
            job,
            status="publish_failed",
            attempt_id=attempt.attempt_id,
            trace=attempt.to_trace(),
            diagnostic=diagnostic,
            result={
                "ok": False,
                "status": "publish_failed",
                "revision": None,
                "diagnostic": diagnostic,
                "build_trace": attempt.to_trace(),
            },
            clear_credentials=True,
        )
    finally:
        credentials.clear()
        if plugin_lock is not None:
            release_session_operation_lock(plugin_lock)
        if session_lock is not None:
            release_session_operation_lock(session_lock)

