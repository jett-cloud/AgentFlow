"""Durable lifecycle helpers for asynchronous Studio publish jobs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select

from core.helper import encrypter
from extensions.ext_database import db
from models.tools import ToolPluginPublishJob

PublishJobStatus = Literal[
    "queued",
    "running",
    "published",
    "publish_failed",
    "rollback_failed",
    "cancelled",
]

TERMINAL_JOB_STATUSES = frozenset({"published", "publish_failed", "rollback_failed", "cancelled"})
SAFE_CANCEL_STAGES = frozenset({"preparing", "preflight", "stage_cleanup"})


class PublishJobNotFoundError(LookupError):
    pass


class PublishJobCancellationError(RuntimeError):
    pass


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_mapping(value: str | None) -> dict[str, Any]:
    try:
        loaded = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _encrypt_credentials(tenant_id: str, credentials: dict[str, str]) -> str:
    return _dump(
        {
            name: encrypter.encrypt_token(tenant_id=tenant_id, token=value)
            for name, value in credentials.items()
        }
    )


def decrypt_job_credentials(job: ToolPluginPublishJob) -> dict[str, str]:
    encrypted = _load_mapping(job.encrypted_credentials_json)
    return {
        str(name): encrypter.decrypt_token(tenant_id=job.tenant_id, token=str(value))
        for name, value in encrypted.items()
    }


def load_job_parameters(job: ToolPluginPublishJob) -> dict[str, Any]:
    return _load_mapping(job.parameters_json)


def create_publish_job(
    *,
    tenant_id: str,
    account_id: str,
    session_id: str,
    publish_mode: str,
    tool_name: str,
    expected_revision: int,
    parameters: dict[str, Any],
    credentials: dict[str, str],
) -> ToolPluginPublishJob:
    job = ToolPluginPublishJob(
        tenant_id=tenant_id,
        account_id=account_id,
        session_id=session_id,
        publish_mode=publish_mode,
        tool_name=tool_name,
        expected_revision=expected_revision,
        parameters_json=_dump(parameters),
        encrypted_credentials_json=_encrypt_credentials(tenant_id, credentials),
    )
    db.session.add(job)
    db.session.commit()
    return job


def get_publish_job(
    *, tenant_id: str, account_id: str, job_id: str, for_update: bool = False
) -> ToolPluginPublishJob:
    stmt = select(ToolPluginPublishJob).where(
        ToolPluginPublishJob.id == job_id,
        ToolPluginPublishJob.tenant_id == tenant_id,
        ToolPluginPublishJob.account_id == account_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    job = db.session.scalar(stmt)
    if job is None:
        raise PublishJobNotFoundError("Publish job was not found")
    return job


def current_job_stage(job: ToolPluginPublishJob) -> str | None:
    trace = _load_mapping(job.trace_json)
    state = trace.get("state")
    return str(state) if state else None


def can_cancel_job(job: ToolPluginPublishJob) -> bool:
    if job.status in TERMINAL_JOB_STATUSES:
        return False
    if job.status == "queued":
        return True
    return current_job_stage(job) in SAFE_CANCEL_STAGES


def request_job_cancel(job: ToolPluginPublishJob) -> ToolPluginPublishJob:
    if not can_cancel_job(job):
        raise PublishJobCancellationError("Publish can no longer be cancelled safely")
    job.cancel_requested = True
    job.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.session.add(job)
    db.session.commit()
    return job


def update_publish_job(
    job: ToolPluginPublishJob,
    *,
    status: PublishJobStatus | None = None,
    celery_task_id: str | None = None,
    attempt_id: str | None = None,
    trace: dict[str, Any] | None = None,
    diagnostic: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    clear_credentials: bool = False,
) -> ToolPluginPublishJob:
    if status is not None:
        job.status = status
    if celery_task_id is not None:
        job.celery_task_id = celery_task_id
    if attempt_id is not None:
        job.attempt_id = attempt_id
    if trace is not None:
        job.trace_json = _dump(trace)
    if diagnostic is not None:
        job.diagnostic_json = _dump(diagnostic)
    if result is not None:
        job.result_json = _dump(result)
    if clear_credentials:
        job.encrypted_credentials_json = "{}"
    db.session.add(job)
    db.session.commit()
    return job


def publish_job_to_dict(job: ToolPluginPublishJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "session_id": job.session_id,
        "status": job.status,
        "publish_mode": job.publish_mode,
        "attempt_id": job.attempt_id,
        "candidate_id": job.candidate_id,
        "cancel_requested": job.cancel_requested,
        "can_cancel": can_cancel_job(job),
        "trace": _load_mapping(job.trace_json) or None,
        "diagnostic": _load_mapping(job.diagnostic_json) or None,
        "result": _load_mapping(job.result_json) or None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }
