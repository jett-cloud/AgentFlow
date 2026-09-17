"""Recover Workflow Assist runs whose queue or worker lease went stale.

The scan is deliberately observation-only. Each candidate carries the exact
timestamp observed by the scan and is terminated in a new short transaction;
``RunCoordinator`` rejects it if a claim or heartbeat won the race meanwhile.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import Session

from configs import dify_config
from core.db.session_factory import session_factory
from libs.datetime_utils import naive_utc_now
from models.workflow_assist import WorkflowAssistRun, WorkflowAssistRunStatus
from services.workflow_assist.run_coordinator import RunCoordinator
from services.workflow_assist.run_types import QueueTimeoutFence, RunOwner, WorkerTimeoutFence

logger = logging.getLogger(__name__)

TimeoutFence = QueueTimeoutFence | WorkerTimeoutFence


def _owner(run: WorkflowAssistRun) -> RunOwner:
    return RunOwner(
        tenant_id=run.tenant_id,
        app_id=run.app_id,
        account_id=run.created_by,
        conversation_id=run.conversation_id,
    )


def _find_timeout_fences(
    session: Session,
    *,
    now: datetime,
    queue_timeout_seconds: int,
    heartbeat_timeout_seconds: int,
    batch_size: int,
) -> list[TimeoutFence]:
    """Capture at most ``batch_size`` oldest timeout observations."""
    if batch_size < 1:
        return []
    queue_cutoff = now - timedelta(seconds=queue_timeout_seconds)
    heartbeat_cutoff = now - timedelta(seconds=heartbeat_timeout_seconds)
    stale_runs = list(
        session.scalars(
            select(WorkflowAssistRun)
            .where(
                (WorkflowAssistRun.status == WorkflowAssistRunStatus.QUEUED)
                & (WorkflowAssistRun.queued_at <= queue_cutoff)
                | (WorkflowAssistRun.status == WorkflowAssistRunStatus.RUNNING)
                & (WorkflowAssistRun.heartbeat_at.is_not(None))
                & (WorkflowAssistRun.heartbeat_at <= heartbeat_cutoff)
            )
            .order_by(WorkflowAssistRun.queued_at.asc(), WorkflowAssistRun.id.asc())
            .limit(batch_size)
        ).all()
    )
    fences: list[TimeoutFence] = []
    for run in stale_runs:
        owner = _owner(run)
        if run.status is WorkflowAssistRunStatus.QUEUED:
            fences.append(
                QueueTimeoutFence(
                    owner=owner,
                    run_id=run.id,
                    epoch=run.epoch,
                    cutoff=queue_cutoff,
                    observed_queued_at=run.queued_at,
                )
            )
        elif run.heartbeat_at is not None:
            fences.append(
                WorkerTimeoutFence(
                    owner=owner,
                    run_id=run.id,
                    epoch=run.epoch,
                    cutoff=heartbeat_cutoff,
                    observed_heartbeat_at=run.heartbeat_at,
                )
            )
    return fences


def _terminate_timeout_fence(fence: TimeoutFence) -> bool:
    """Apply one observed timeout only if its typed fence is still current."""
    reason = "queue_timeout" if isinstance(fence, QueueTimeoutFence) else "worker_lost"
    with session_factory.create_session() as session:
        terminated = RunCoordinator(session).terminate(
            lease=fence,
            status=WorkflowAssistRunStatus.ERROR,
            step_id=f"timeout:{reason}",
            payload={"status": "error", "reason": reason},
            reason=reason,
        )
        session.commit()
        return terminated


def reap_stale_workflow_assist_runs(
    *,
    now: datetime | None = None,
    queue_timeout_seconds: int | None = None,
    heartbeat_timeout_seconds: int | None = None,
    batch_size: int | None = None,
) -> int:
    """Terminate one bounded batch of stale queued and running runs."""
    observed_now = now or naive_utc_now()
    queue_timeout = queue_timeout_seconds or dify_config.WORKFLOW_ASSIST_QUEUE_TIMEOUT_SECONDS
    heartbeat_timeout = heartbeat_timeout_seconds or dify_config.WORKFLOW_ASSIST_HEARTBEAT_TIMEOUT_SECONDS
    limit = batch_size or dify_config.WORKFLOW_ASSIST_REAPER_BATCH_SIZE
    with session_factory.create_session() as session:
        fences = _find_timeout_fences(
            session,
            now=observed_now,
            queue_timeout_seconds=queue_timeout,
            heartbeat_timeout_seconds=heartbeat_timeout,
            batch_size=limit,
        )
    terminated = sum(_terminate_timeout_fence(fence) for fence in fences)
    if terminated:
        logger.warning("Recovered %s stale Workflow Assist runs", terminated)
    return terminated


@shared_task(queue="schedule_executor")
def reap_workflow_assist_runs() -> None:
    """Celery Beat entrypoint for bounded stale-run recovery."""
    reap_stale_workflow_assist_runs()
