from unittest.mock import MagicMock

from services.tool_plugin_generator import publish_job_runner


def _job(*, status: str = "queued", cancel_requested: bool = False) -> MagicMock:
    return MagicMock(
        id="job-1",
        tenant_id="tenant-1",
        account_id="account-1",
        session_id="session-1",
        publish_mode="direct",
        tool_name="echo",
        expected_revision=1,
        status=status,
        cancel_requested=cancel_requested,
    )


def test_terminal_publish_job_is_an_idempotent_noop(monkeypatch) -> None:
    job = _job(status="published")
    update = MagicMock()
    monkeypatch.setattr(publish_job_runner, "_load_job", lambda _job_id: job)
    monkeypatch.setattr(publish_job_runner, "update_publish_job", update)

    publish_job_runner.execute_publish_job(job.id)

    update.assert_not_called()


def test_queued_cancelled_job_never_decrypts_credentials(monkeypatch) -> None:
    job = _job(cancel_requested=True)
    decrypt = MagicMock()
    update = MagicMock()
    monkeypatch.setattr(publish_job_runner, "_load_job", lambda _job_id: job)
    monkeypatch.setattr(publish_job_runner, "decrypt_job_credentials", decrypt)
    monkeypatch.setattr(publish_job_runner, "update_publish_job", update)

    publish_job_runner.execute_publish_job(job.id)

    decrypt.assert_not_called()
    update.assert_called_once_with(job, status="cancelled", clear_credentials=True)


def test_worker_redacts_unexpected_failure_and_clears_credentials(monkeypatch) -> None:
    job = _job()
    updates: list[dict] = []
    monkeypatch.setattr(publish_job_runner, "_load_job", lambda _job_id: job)
    monkeypatch.setattr(publish_job_runner, "decrypt_job_credentials", lambda _job: {"api_key": "secret-value"})
    monkeypatch.setattr(
        publish_job_runner,
        "update_publish_job",
        lambda _job, **kwargs: updates.append(kwargs),
    )
    monkeypatch.setattr(
        publish_job_runner,
        "acquire_session_operation_lock",
        MagicMock(side_effect=RuntimeError("failed with secret-value")),
    )

    publish_job_runner.execute_publish_job(job.id)

    assert updates[0] == {"status": "running"}
    assert updates[-1]["status"] == "publish_failed"
    assert updates[-1]["clear_credentials"] is True
    assert "secret-value" not in updates[-1]["diagnostic"]["message"]

