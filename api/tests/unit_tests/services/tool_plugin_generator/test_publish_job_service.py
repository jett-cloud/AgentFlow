from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from models.tools import ToolPluginPublishJob
from services.tool_plugin_generator import publish_job_service
from services.tool_plugin_generator.publish_job_service import PublishJobCancellationError


def _job(*, status: str = "queued", trace_json: str | None = None) -> ToolPluginPublishJob:
    job = ToolPluginPublishJob(
        tenant_id="tenant-1",
        account_id="account-1",
        session_id="session-1",
        publish_mode="test",
        tool_name="echo",
        expected_revision=1,
        parameters_json="{}",
        encrypted_credentials_json="{}",
        status=status,
        trace_json=trace_json,
    )
    job.created_at = datetime.now(UTC).replace(tzinfo=None)
    job.updated_at = job.created_at
    return job


def test_create_job_encrypts_each_credential_and_never_serializes_it(monkeypatch) -> None:
    session = Mock()
    monkeypatch.setattr(publish_job_service.db, "session", session)
    monkeypatch.setattr(
        publish_job_service.encrypter,
        "encrypt_token",
        lambda tenant_id, token: f"encrypted:{tenant_id}:{token}",
    )

    job = publish_job_service.create_publish_job(
        tenant_id="tenant-1",
        account_id="account-1",
        session_id="session-1",
        publish_mode="test",
        tool_name="echo",
        expected_revision=1,
        parameters={"prompt": "hello"},
        credentials={"api_key": "secret-value"},
    )

    assert "secret-value" not in publish_job_service.publish_job_to_dict(job).__repr__()
    assert "encrypted:tenant-1:secret-value" in job.encrypted_credentials_json
    session.add.assert_called_once_with(job)
    session.commit.assert_called_once()


@pytest.mark.parametrize("stage", [None, "preparing", "preflight", "stage_cleanup"])
def test_cancel_is_allowed_only_before_candidate_install(stage: str | None) -> None:
    status = "queued" if stage is None else "running"
    trace = None if stage is None else f'{{"state":"{stage}"}}'
    assert publish_job_service.can_cancel_job(_job(status=status, trace_json=trace)) is True


@pytest.mark.parametrize("stage", ["stage_install", "stage_verify", "commit_install", "persist"])
def test_cancel_is_rejected_after_candidate_install(stage: str) -> None:
    job = _job(status="running", trace_json=f'{{"state":"{stage}"}}')
    assert publish_job_service.can_cancel_job(job) is False
    with pytest.raises(PublishJobCancellationError):
        publish_job_service.request_job_cancel(job)
