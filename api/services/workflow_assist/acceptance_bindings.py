"""Attempt-local Agent dependencies; never change a draft binding or runtime session."""

from copy import deepcopy
from typing import Any
from uuid import uuid4

from agenton.compositor import CompositorSessionSnapshot
from dify_agent.protocol import RuntimeLayerSpec

from core.db.session_factory import session_factory
from core.workflow.generator.graph.types import MinimalGraphDict
from core.workflow.nodes.agent_v2.binding_resolver import WorkflowAgentBindingBundle, WorkflowAgentBindingError
from core.workflow.nodes.agent_v2.session_store import (
    StoredWorkflowAgentSession,
    WorkflowAgentRuntimeSessionStore,
    WorkflowAgentSessionScope,
)
from models.agent import WorkflowAgentBindingType, WorkflowAgentNodeBinding
from services.workflow_assist.hydrate import (
    _load_trusted_inline_binding,
    _node_job_from_data,
    candidate_soul_matches_snapshot,
)


class CandidateBindingResolver:
    """Frozen candidate config with exact, owner-checked snapshots on every lookup.

    ``assist_binding_manifest`` is ignored here. Binding ids must already be
    hydrated and owned by this tenant/app/workflow/node.
    """

    _owner: tuple[str, str, str]
    _nodes: dict[str, dict[str, Any]]
    _ids: dict[str, str]

    def __init__(self, *, graph: MinimalGraphDict, tenant_id: str, app_id: str, workflow_id: str) -> None:
        self._owner = (tenant_id, app_id, workflow_id)
        self._nodes = {n["id"]: deepcopy(n["data"]) for n in graph.get("nodes") or []}
        self._ids = {node_id: str(uuid4()) for node_id in self._nodes}

    def resolve(self, *, tenant_id: str, app_id: str, workflow_id: str, node_id: str) -> WorkflowAgentBindingBundle:
        if self._owner != (tenant_id, app_id, workflow_id) or node_id not in self._nodes:
            raise WorkflowAgentBindingError("agent_binding_not_found", "Candidate binding owner mismatch")
        data = self._nodes[node_id]
        ref = data.get("agent_binding") or {}
        with session_factory.create_session() as session:
            trusted = _load_trusted_inline_binding(
                session=session,
                tenant_id=tenant_id,
                app_id=app_id,
                workflow_id=workflow_id,
                node_id=node_id,
                agent_id=ref.get("agent_id"),
                snapshot_id=ref.get("current_snapshot_id"),
            )
            if trusted is None or not candidate_soul_matches_snapshot(data, trusted.snapshot):
                raise WorkflowAgentBindingError("agent_binding_not_found", "Candidate snapshot is unavailable")
            binding = WorkflowAgentNodeBinding(
                id=self._ids[node_id],
                tenant_id=tenant_id,
                app_id=app_id,
                workflow_id=workflow_id,
                workflow_version="draft",
                node_id=node_id,
                binding_type=WorkflowAgentBindingType.INLINE_AGENT,
                agent_id=trusted.agent.id,
                current_snapshot_id=trusted.snapshot.id,
                node_job_config=_node_job_from_data(data),
            )
            session.expunge(trusted.agent)
            session.expunge(trusted.snapshot)
            return WorkflowAgentBindingBundle(binding=binding, agent=trusted.agent, snapshot=trusted.snapshot)


class AcceptanceSessionStore(WorkflowAgentRuntimeSessionStore):
    """One engine attempt's sessions. No writes to durable workflow runtime tables."""

    _sessions: dict[WorkflowAgentSessionScope, StoredWorkflowAgentSession]

    def __init__(self) -> None:
        self._sessions: dict[WorkflowAgentSessionScope, StoredWorkflowAgentSession] = {}

    def load_active_session(self, scope: WorkflowAgentSessionScope) -> StoredWorkflowAgentSession | None:
        return self._sessions.get(scope)

    def list_active_sessions(self, *, workflow_run_id: str) -> list[StoredWorkflowAgentSession]:
        return [s for s in self._sessions.values() if s.scope.workflow_run_id == workflow_run_id]

    def save_active_snapshot(
        self,
        *,
        scope: WorkflowAgentSessionScope,
        backend_run_id: str,
        snapshot: CompositorSessionSnapshot | None,
        runtime_layer_specs: list[RuntimeLayerSpec],
        pending_form_id: str | None = None,
        pending_tool_call_id: str | None = None,
    ) -> None:
        if snapshot is not None:
            self._sessions[scope] = StoredWorkflowAgentSession(
                scope=scope,
                session_snapshot=snapshot,
                backend_run_id=backend_run_id,
                runtime_layer_specs=runtime_layer_specs,
                pending_form_id=pending_form_id,
                pending_tool_call_id=pending_tool_call_id,
            )

    def mark_cleaned(self, *, scope: WorkflowAgentSessionScope, backend_run_id: str | None = None) -> None:
        self._sessions.pop(scope, None)
