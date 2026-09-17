"""Execute one durable Workflow Assist run on the conversation queue.

This task owns claim, initialization, heartbeat, and terminal recovery. The
production adapter runs the executable Agent loop while ``AgentRunner`` remains
an injected test seam.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from celery import Task, shared_task
from sqlalchemy import select

from configs import dify_config
from core.db.session_factory import session_factory
from models import Account, App, TenantAccountJoin
from models.account import AccountStatus
from models.workflow_assist import (
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistRun,
    WorkflowAssistRunStatus,
)
from services.workflow_assist.run_coordinator import RunCoordinator
from services.workflow_assist.run_types import RunLease, RunOwner

logger = logging.getLogger(__name__)

AgentEvent = tuple[str, dict[str, Any]]


@dataclass(frozen=True)
class AgentRunContext:
    """Detached, read-only inputs supplied to one Agent runner invocation."""

    app_model: App
    account: Account
    run: WorkflowAssistRun
    conversation: WorkflowAssistConversation
    messages: tuple[WorkflowAssistMessage, ...]
    should_stop: Callable[[], bool]


class AgentRunner(Protocol):
    """Adapter implemented by the executable workflow Agent loop."""

    def __call__(self, context: AgentRunContext) -> Iterator[AgentEvent]: ...


class Heartbeat(Protocol):
    """Lifecycle of the independent worker-lease heartbeat."""

    def __enter__(self) -> Heartbeat: ...

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None: ...

    def fenced(self) -> bool: ...


class LeaseHeartbeat:
    """Refresh a run lease from its own short database session."""

    lease: RunLease
    interval_seconds: float
    _stop: threading.Event
    _fenced: threading.Event
    _thread: threading.Thread | None

    def __init__(self, lease: RunLease, interval_seconds: float) -> None:
        self.lease = lease
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._fenced = threading.Event()
        self._thread = None

    def __enter__(self) -> LeaseHeartbeat:
        self._thread = threading.Thread(target=self._run, name=f"workflow-assist-heartbeat-{self.lease.run_id}")
        self._thread.daemon = True
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self.interval_seconds, 1.0))

    def fenced(self) -> bool:
        return self._fenced.is_set()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                with session_factory.create_session() as session:
                    refreshed = RunCoordinator(session).heartbeat(lease=self.lease)
                    session.commit()
            except Exception:
                logger.exception("Workflow Assist heartbeat failed run_id=%s", self.lease.run_id)
                continue
            if not refreshed:
                self._fenced.set()
                return


def _load_context(*, lease: RunLease, heartbeat: Heartbeat) -> AgentRunContext | None:
    owner = lease.owner
    with session_factory.create_session() as session:
        app_model = session.scalar(select(App).where(App.id == owner.app_id, App.tenant_id == owner.tenant_id))
        account = session.scalar(
            select(Account)
            .join(TenantAccountJoin, TenantAccountJoin.account_id == Account.id)
            .where(
                Account.id == owner.account_id,
                Account.status == AccountStatus.ACTIVE,
                TenantAccountJoin.tenant_id == owner.tenant_id,
            )
        )
        run = session.scalar(
            select(WorkflowAssistRun).where(
                WorkflowAssistRun.id == lease.run_id,
                WorkflowAssistRun.tenant_id == owner.tenant_id,
                WorkflowAssistRun.app_id == owner.app_id,
                WorkflowAssistRun.created_by == owner.account_id,
                WorkflowAssistRun.conversation_id == owner.conversation_id,
                WorkflowAssistRun.epoch == lease.epoch,
            )
        )
        conversation = session.scalar(
            select(WorkflowAssistConversation).where(
                WorkflowAssistConversation.id == owner.conversation_id,
                WorkflowAssistConversation.tenant_id == owner.tenant_id,
                WorkflowAssistConversation.app_id == owner.app_id,
                WorkflowAssistConversation.account_id == owner.account_id,
                WorkflowAssistConversation.is_deleted.is_(False),
            )
        )
        if app_model is None or account is None or run is None or conversation is None:
            return None
        messages = tuple(
            session.scalars(
                select(WorkflowAssistMessage)
                .where(
                    WorkflowAssistMessage.tenant_id == owner.tenant_id,
                    WorkflowAssistMessage.app_id == owner.app_id,
                    WorkflowAssistMessage.account_id == owner.account_id,
                    WorkflowAssistMessage.conversation_id == owner.conversation_id,
                )
                .order_by(WorkflowAssistMessage.sequence.asc())
            ).all()
        )
        return AgentRunContext(
            app_model=app_model,
            account=account,
            run=run,
            conversation=conversation,
            messages=messages,
            should_stop=heartbeat.fenced,
        )


def _terminate(
    lease: RunLease,
    *,
    status: WorkflowAssistRunStatus,
    reason: str,
    payload: dict[str, Any] | None = None,
) -> bool:
    with session_factory.create_session() as session:
        terminated = RunCoordinator(session).terminate(
            lease=lease,
            status=status,
            step_id=f"terminal:{status.value}:{reason}",
            payload=payload or {"status": status.value, "reason": reason},
            reason=reason,
        )
        session.commit()
        return terminated


def _execute_workflow_assist_run(
    *,
    owner: RunOwner,
    run_id: str,
    epoch: int,
    worker_id: str,
    agent_runner: AgentRunner | None = None,
    heartbeat_factory: Callable[[RunLease, float], Heartbeat] = LeaseHeartbeat,
) -> None:
    """Claim one run and execute its injected Agent stream under a heartbeat."""
    with session_factory.create_session() as session:
        lease = RunCoordinator(session).claim(
            owner=owner,
            run_id=run_id,
            epoch=epoch,
            worker_id=worker_id,
        )
        session.commit()
    if lease is None:
        return

    heartbeat = heartbeat_factory(lease, float(dify_config.WORKFLOW_ASSIST_HEARTBEAT_INTERVAL_SECONDS))
    with heartbeat:
        context = _load_context(lease=lease, heartbeat=heartbeat)
        if context is None:
            _terminate(lease, status=WorkflowAssistRunStatus.ERROR, reason="run_initialization_failed")
            return
        from services.workflow_assist.agent_initializer import WorkflowAssistRunInitializationError

        try:
            from services.workflow_assist.chat import (
                AgentEventPumpOutcome,
                persist_agent_events,
                run_workflow_assist_agent,
            )

            outcome = persist_agent_events(
                lease=lease,
                events=(agent_runner or run_workflow_assist_agent)(context),
                should_stop=heartbeat.fenced,
            )
            if outcome is None:
                _terminate(
                    lease,
                    status=WorkflowAssistRunStatus.ERROR,
                    reason="agent_loop_ended_without_terminal",
                )
            elif outcome is AgentEventPumpOutcome.FENCED:
                return
        except ImportError:
            logger.exception("Workflow Assist AgentLoop initialization failed run_id=%s", run_id)
            _terminate(lease, status=WorkflowAssistRunStatus.ERROR, reason="run_initialization_failed")
        except WorkflowAssistRunInitializationError:
            logger.exception("Workflow Assist AgentLoop initialization failed run_id=%s", run_id)
            _terminate(lease, status=WorkflowAssistRunStatus.ERROR, reason="run_initialization_failed")
        except Exception as exc:
            logger.exception("Workflow Assist Agent runner failed run_id=%s", run_id)
            detail = str(exc) or "Model provider failed"
            _terminate(
                lease,
                status=WorkflowAssistRunStatus.ERROR,
                reason="provider_error",
                payload={
                    "status": WorkflowAssistRunStatus.ERROR.value,
                    "reason": "provider_error",
                    "message": detail,
                    "errors": [{"code": "provider_error", "detail": detail}],
                    "termination_reason": "provider_error",
                },
            )


@shared_task(queue="conversation", bind=True, acks_late=True, reject_on_worker_lost=True)
def execute_workflow_assist_run(
    self: Task,
    *,
    tenant_id: str,
    app_id: str,
    account_id: str,
    conversation_id: str,
    run_id: str,
    epoch: int,
) -> None:
    """Celery entrypoint for one queued Workflow Assist run delivery."""
    delivery_id = (self.request.id or "").strip()
    if not delivery_id:
        raise RuntimeError("Workflow Assist Celery delivery requires a task id")
    owner = RunOwner(
        tenant_id=tenant_id,
        app_id=app_id,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    _execute_workflow_assist_run(
        owner=owner,
        run_id=run_id,
        epoch=epoch,
        worker_id=delivery_id,
    )
