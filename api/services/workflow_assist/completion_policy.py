"""Owner-scoped completion policy for persisted Workflow Assist candidates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.agent import (
    Agent,
    AgentConfigSnapshot,
    AgentScope,
    AgentSource,
    AgentStatus,
    WorkflowAgentBindingType,
)
from models.workflow import Workflow, WorkflowType
from models.workflow_assist import WorkflowAssistMode
from services.workflow_assist.run_types import RunOwner


@dataclass(frozen=True)
class _InlineAgentBinding:
    node_id: str
    agent_id: str
    snapshot_id: str


@dataclass(frozen=True)
class _CanonicalCandidate:
    reaches_terminal: bool
    inline_bindings: tuple[_InlineAgentBinding, ...]


class CompletionPolicy:
    """Verify topology and authoritative hydration for one locked candidate."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def candidate_is_complete(
        self,
        *,
        owner: RunOwner,
        graph: dict[str, Any],
        mode: WorkflowAssistMode,
    ) -> bool:
        candidate = _canonicalize_candidate(graph, mode=mode)
        if candidate is None or not candidate.reaches_terminal:
            return False
        if not candidate.inline_bindings:
            return True

        workflow_id = self._lock_draft_workflow_id(owner, mode=mode)
        if workflow_id is None:
            return False
        return all(
            self._binding_is_owner_scoped(owner=owner, workflow_id=workflow_id, binding=binding)
            for binding in candidate.inline_bindings
        )

    def _lock_draft_workflow_id(self, owner: RunOwner, *, mode: WorkflowAssistMode) -> str | None:
        workflow_type = WorkflowType.WORKFLOW if mode is WorkflowAssistMode.WORKFLOW else WorkflowType.CHAT
        return self._session.scalar(
            select(Workflow.id)
            .where(
                Workflow.tenant_id == owner.tenant_id,
                Workflow.app_id == owner.app_id,
                Workflow.version == Workflow.VERSION_DRAFT,
                Workflow.type == workflow_type,
            )
            .limit(1)
            .with_for_update()
        )

    def _binding_is_owner_scoped(
        self,
        *,
        owner: RunOwner,
        workflow_id: str,
        binding: _InlineAgentBinding,
    ) -> bool:
        agent = self._session.scalar(
            select(Agent)
            .where(
                Agent.id == binding.agent_id,
                Agent.tenant_id == owner.tenant_id,
                Agent.app_id == owner.app_id,
                Agent.workflow_id == workflow_id,
                Agent.workflow_node_id == binding.node_id,
                Agent.created_by == owner.account_id,
                Agent.scope == AgentScope.WORKFLOW_ONLY,
                Agent.source == AgentSource.WORKFLOW,
                Agent.status == AgentStatus.ACTIVE,
                Agent.active_config_snapshot_id == binding.snapshot_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if agent is None:
            return False
        snapshot = self._session.scalar(
            select(AgentConfigSnapshot)
            .where(
                AgentConfigSnapshot.id == binding.snapshot_id,
                AgentConfigSnapshot.tenant_id == owner.tenant_id,
                AgentConfigSnapshot.agent_id == agent.id,
                AgentConfigSnapshot.created_by == owner.account_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        return snapshot is not None


def _canonicalize_candidate(graph: dict[str, Any], *, mode: WorkflowAssistMode) -> _CanonicalCandidate | None:
    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return None

    node_types: dict[str, object] = {}
    inline_bindings: dict[str, _InlineAgentBinding] = {}
    for raw_node in raw_nodes:
        if not isinstance(raw_node, Mapping):
            return None
        node_id = _canonical_id(raw_node.get("id"))
        if node_id is None or node_id in node_types:
            return None
        data = raw_node.get("data")
        node_type = data.get("type") if isinstance(data, Mapping) else raw_node.get("type")
        node_types[node_id] = node_type
        if node_type == "agent" and isinstance(data, Mapping) and str(data.get("version")) == "2":
            binding = _inline_binding(node_id=node_id, data=data)
            if binding is False:
                return None
            if isinstance(binding, _InlineAgentBinding):
                inline_bindings[node_id] = binding

    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_types}
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, Mapping):
            return None
        source = _canonical_id(raw_edge.get("source"))
        target = _canonical_id(raw_edge.get("target"))
        if source is None or target is None or source not in node_types or target not in node_types:
            return None
        adjacency[source].add(target)

    starts = {node_id for node_id, node_type in node_types.items() if node_type == "start"}
    terminal_type = "end" if mode is WorkflowAssistMode.WORKFLOW else "answer"
    terminals = {node_id for node_id, node_type in node_types.items() if node_type == terminal_type}
    reachable = _reachable_nodes(starts=starts, adjacency=adjacency)
    return _CanonicalCandidate(
        reaches_terminal=bool(reachable & terminals),
        inline_bindings=tuple(inline_bindings.values()),
    )


def _canonical_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _inline_binding(*, node_id: str, data: Mapping[str, Any]) -> _InlineAgentBinding | bool:
    raw_binding = data.get("agent_binding")
    if not isinstance(raw_binding, Mapping):
        return False
    binding_type = raw_binding.get("binding_type")
    if binding_type == WorkflowAgentBindingType.ROSTER_AGENT.value:
        return True
    if binding_type != WorkflowAgentBindingType.INLINE_AGENT.value:
        return False
    agent_id = _canonical_id(raw_binding.get("agent_id"))
    snapshot_id = _canonical_id(raw_binding.get("current_snapshot_id"))
    if agent_id is None or snapshot_id is None:
        return False
    return _InlineAgentBinding(node_id=node_id, agent_id=agent_id, snapshot_id=snapshot_id)


def _reachable_nodes(*, starts: set[str], adjacency: dict[str, set[str]]) -> set[str]:
    pending = list(starts)
    reachable: set[str] = set()
    while pending:
        node_id = pending.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        pending.extend(adjacency[node_id] - reachable)
    return reachable
