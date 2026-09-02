"""Timeout reaper tests using the same typed observations as RunCoordinator."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from configs.feature import CeleryScheduleTasksConfig, WorkflowAssistRunConfig
from extensions import ext_celery
from libs.datetime_utils import naive_utc_now
from models.workflow_assist import (
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
    WorkflowAssistRunStatus,
)
from services.workflow_assist.conversations import WorkflowAssistConversationService
from services.workflow_assist.run_coordinator import RunCoordinator
from services.workflow_assist.run_types import QueueTimeoutFence, RunOwner, WorkerTimeoutFence
from tasks import workflow_assist_run_reaper_task as reaper_module

TABLES = (
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
)


def _owner(suffix: str) -> RunOwner:
    return RunOwner(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
        conversation_id=f"conversation-{suffix}",
    )


def _start(session: Session, suffix: str, *, claim: bool) -> WorkflowAssistRun:
    owner = _owner(suffix)
    conversation = WorkflowAssistConversationService(session).create(
        tenant_id=owner.tenant_id,
        app_id=owner.app_id,
        account_id=owner.account_id,
    )
    conversation.id = owner.conversation_id
    session.flush()
    run = RunCoordinator(session).start_turn(
        owner=owner,
        message="Build a workflow",
        mode="workflow",
        model_config={"provider": "test"},
    )
    if claim:
        assert (
            RunCoordinator(session).claim(
                owner=owner,
                run_id=run.id,
                epoch=run.epoch,
                worker_id=f"worker-{suffix}",
            )
            is not None
        )
    session.commit()
    return run


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_scan_builds_typed_timeout_fences_with_observed_timestamps(sqlite_session: Session) -> None:
    now = naive_utc_now()
    queued = _start(sqlite_session, "queued", claim=False)
    running = _start(sqlite_session, "running", claim=True)
    queued.queued_at = now - timedelta(seconds=121)
    running.heartbeat_at = now - timedelta(seconds=61)
    sqlite_session.commit()

    fences = reaper_module._find_timeout_fences(
        sqlite_session,
        now=now,
        queue_timeout_seconds=120,
        heartbeat_timeout_seconds=60,
        batch_size=100,
    )

    assert len(fences) == 2
    queue_fence = next(fence for fence in fences if isinstance(fence, QueueTimeoutFence))
    worker_fence = next(fence for fence in fences if isinstance(fence, WorkerTimeoutFence))
    assert queue_fence.observed_queued_at == queued.queued_at
    assert queue_fence.cutoff == now - timedelta(seconds=120)
    assert worker_fence.observed_heartbeat_at == running.heartbeat_at
    assert worker_fence.cutoff == now - timedelta(seconds=60)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_reaper_observation_cannot_kill_a_fresh_claim_or_heartbeat(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    now = naive_utc_now()
    queued = _start(sqlite_session, "queued", claim=False)
    running = _start(sqlite_session, "running", claim=True)
    queued.queued_at = now - timedelta(seconds=121)
    running.heartbeat_at = now - timedelta(seconds=61)
    sqlite_session.commit()
    fences = reaper_module._find_timeout_fences(
        sqlite_session,
        now=now,
        queue_timeout_seconds=120,
        heartbeat_timeout_seconds=60,
        batch_size=100,
    )
    queue_fence = next(fence for fence in fences if isinstance(fence, QueueTimeoutFence))
    worker_fence = next(fence for fence in fences if isinstance(fence, WorkerTimeoutFence))

    # A claim changes queued -> running; a heartbeat advances the observed value.
    assert (
        RunCoordinator(sqlite_session).claim(
            owner=queue_fence.owner,
            run_id=queue_fence.run_id,
            epoch=queue_fence.epoch,
            worker_id="fresh-worker",
        )
        is not None
    )
    running.heartbeat_at = now
    sqlite_session.commit()
    maker = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(reaper_module.session_factory, "create_session", maker)

    assert reaper_module._terminate_timeout_fence(queue_fence) is False
    assert reaper_module._terminate_timeout_fence(worker_fence) is False

    sqlite_session.expire_all()
    statuses = dict(sqlite_session.execute(select(WorkflowAssistRun.id, WorkflowAssistRun.status)).all())
    assert statuses[queued.id] is WorkflowAssistRunStatus.RUNNING
    assert statuses[running.id] is WorkflowAssistRunStatus.RUNNING


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_reaper_terminates_only_stale_runs_and_respects_batch_size(
    sqlite_session: Session,
    monkeypatch,
) -> None:
    now = naive_utc_now()
    stale_queued = _start(sqlite_session, "stale-queued", claim=False)
    stale_running = _start(sqlite_session, "stale-running", claim=True)
    fresh_queued = _start(sqlite_session, "fresh-queued", claim=False)
    fresh_running = _start(sqlite_session, "fresh-running", claim=True)
    stale_queued.queued_at = now - timedelta(seconds=121)
    stale_running.heartbeat_at = now - timedelta(seconds=61)
    fresh_queued.queued_at = now - timedelta(seconds=119)
    fresh_running.heartbeat_at = now - timedelta(seconds=59)
    sqlite_session.commit()
    maker = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(reaper_module.session_factory, "create_session", maker)

    result = reaper_module.reap_stale_workflow_assist_runs(
        now=now,
        queue_timeout_seconds=120,
        heartbeat_timeout_seconds=60,
        batch_size=100,
    )

    assert result == 2
    sqlite_session.expire_all()
    statuses = dict(sqlite_session.execute(select(WorkflowAssistRun.id, WorkflowAssistRun.status)).all())
    assert statuses[stale_queued.id] is WorkflowAssistRunStatus.ERROR
    assert statuses[stale_running.id] is WorkflowAssistRunStatus.ERROR
    assert statuses[fresh_queued.id] is WorkflowAssistRunStatus.QUEUED
    assert statuses[fresh_running.id] is WorkflowAssistRunStatus.RUNNING


def test_celery_reaper_is_pinned_to_schedule_executor_queue() -> None:
    assert reaper_module.reap_workflow_assist_runs.queue == "schedule_executor"


def test_workflow_assist_run_config_defaults_match_the_recovery_contract() -> None:
    config = WorkflowAssistRunConfig()

    assert config.WORKFLOW_ASSIST_HEARTBEAT_INTERVAL_SECONDS == 10
    assert config.WORKFLOW_ASSIST_HEARTBEAT_TIMEOUT_SECONDS == 60
    assert config.WORKFLOW_ASSIST_QUEUE_TIMEOUT_SECONDS == 120
    assert config.WORKFLOW_ASSIST_REAPER_INTERVAL_SECONDS == 30
    assert config.WORKFLOW_ASSIST_REAPER_BATCH_SIZE == 100
    assert CeleryScheduleTasksConfig().ENABLE_WORKFLOW_ASSIST_REAPER_TASK is True


@pytest.mark.parametrize(("enabled", "registered"), [(True, True), (False, False)])
def test_workflow_assist_reaper_beat_registration_has_an_operational_switch(
    monkeypatch,
    enabled: bool,
    registered: bool,
) -> None:
    monkeypatch.setattr(ext_celery.dify_config, "ENABLE_WORKFLOW_ASSIST_REAPER_TASK", enabled, raising=False)
    schedule = {}

    ext_celery._register_workflow_assist_reaper(schedule)

    assert ("workflow_assist_run_reaper" in schedule) is registered
