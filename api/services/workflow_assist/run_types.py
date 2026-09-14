"""Typed values crossing the Workflow Assist run-coordination seam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

AGENT_RESPONSE_OUTBOX_KEY = "__agent_response_outbox"


@dataclass(frozen=True)
class RunOwner:
    """Complete ownership scope required by every run write."""

    tenant_id: str
    app_id: str
    account_id: str
    conversation_id: str


@dataclass(frozen=True)
class RunLease:
    """Fencing identity for one queued or worker-owned run.

    ``worker_id`` is ``None`` only while the run is queued. A running lease must
    carry the worker id and ``attempt`` stored on the run. Writers compare
    ``attempt`` so a later claim cannot be overwritten by a stale lease.
    """

    owner: RunOwner
    run_id: str
    epoch: int
    attempt: int
    worker_id: str | None


@dataclass(frozen=True)
class UserAbortFence:
    """Current-run fencing identity for an explicit user abort."""

    owner: RunOwner
    run_id: str
    epoch: int


@dataclass(frozen=True)
class DispatchFailureFence:
    """Exact queued Run coordinate whose broker dispatch was not confirmed."""

    owner: RunOwner
    run_id: str
    epoch: int


@dataclass(frozen=True)
class QueueTimeoutFence:
    """Immutable evidence captured by one queued-run timeout scan."""

    owner: RunOwner
    run_id: str
    epoch: int
    cutoff: datetime
    observed_queued_at: datetime


@dataclass(frozen=True)
class WorkerTimeoutFence:
    """Immutable evidence captured by one running-worker timeout scan."""

    owner: RunOwner
    run_id: str
    epoch: int
    cutoff: datetime
    observed_heartbeat_at: datetime


@dataclass(frozen=True)
class CandidateMutation:
    """Server-produced candidate graph to commit with one run event."""

    graph: dict[str, Any]
    base_hash: str | None = None


@dataclass(frozen=True)
class WorkflowContractCheckpoint:
    """Authoritative plan snapshot persisted independently from compaction."""

    protocol_version: int
    revision: int
    contract_hash: str
    contract: dict[str, object]


@dataclass(frozen=True)
class AgentCheckpoint:
    """Durable Agent prompt state committed under a worker fence."""

    compacted_until_sequence: int | None
    compacted_state: dict[str, Any] | None
    last_validation: dict[str, Any] | None
    workflow_contract: WorkflowContractCheckpoint | None = None


@dataclass(frozen=True)
class AgentResponseOutbox:
    """One immutable assistant response staged before its visible delta chunks."""

    sequence: int
    payload: dict[str, Any]
    checkpoint: AgentCheckpoint | None


class CommitStepOutcome(StrEnum):
    """Observable result of a fenced, idempotent step commit."""

    COMMITTED = "committed"
    DUPLICATE = "duplicate"
    FENCED = "fenced"


@dataclass(frozen=True)
class CommitStepResult:
    """Result returned without exposing the coordinator's event insert seam."""

    outcome: CommitStepOutcome
    sequence: int | None = None
    candidate_revision: int | None = None
