from copy import deepcopy

import pytest
from sqlalchemy.orm import sessionmaker

from models.agent import (
    Agent,
    AgentConfigRevision,
    AgentConfigSnapshot,
    AgentScope,
    AgentSource,
    AgentStatus,
    WorkflowAgentBindingType,
    WorkflowAgentNodeBinding,
)
from models.agent_config_entities import WorkflowNodeJobConfig
from services.workflow_assist.acceptance_bindings import AcceptanceSessionStore, CandidateBindingResolver
from services.workflow_assist.hydrate import (
    _agent_soul_from_node_data,
    activate_candidate_bindings,
    collect_invalid_inline_agent_binding_errors,
    hydrate_agent_bindings,
)

TABLES = (Agent, AgentConfigSnapshot, AgentConfigRevision, WorkflowAgentNodeBinding)


def test_acceptance_sessions_are_attempt_local_and_never_use_database(monkeypatch):
    from agenton.compositor import CompositorSessionSnapshot

    from core.workflow.nodes.agent_v2.session_store import WorkflowAgentSessionScope

    def forbidden_database():
        raise AssertionError("Acceptance sessions must not use the database")

    monkeypatch.setattr("core.db.session_factory.session_factory.create_session", forbidden_database)
    scope = WorkflowAgentSessionScope(
        tenant_id="t",
        app_id="a",
        workflow_id="w",
        workflow_run_id="r",
        node_id="n",
        node_execution_id="e",
        binding_id="b",
        agent_id="agent",
        agent_config_snapshot_id="snapshot",
    )
    first, second = AcceptanceSessionStore(), AcceptanceSessionStore()
    snapshot = CompositorSessionSnapshot(layers=[])
    first.save_active_snapshot(
        scope=scope,
        backend_run_id="run",
        snapshot=snapshot,
        runtime_layer_specs=[],
        pending_form_id="form",
        pending_tool_call_id="call",
    )
    assert first.load_active_session(scope).pending_form_id == "form"
    assert first.load_active_snapshot(scope) == snapshot
    assert second.load_active_snapshot(scope) is None
    first.mark_cleaned(scope=scope)
    assert first.list_active_sessions(workflow_run_id="r") == []


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_candidates_are_isolated_until_activation(sqlite_session, monkeypatch):
    data = {
        "type": "agent",
        "version": "2",
        "agent_node_kind": "dify_agent",
        "agent_task": "A",
        "model": {"provider": "langgenius/openai/openai", "name": "model-a"},
        "agent_binding": {"binding_type": "inline_agent", "agent_id": "agent", "current_snapshot_id": "snap"},
    }
    agent = Agent(
        id="agent",
        tenant_id="tenant",
        app_id="app",
        workflow_id="workflow",
        workflow_node_id="node",
        name="Agent",
        scope=AgentScope.WORKFLOW_ONLY,
        source=AgentSource.WORKFLOW,
        status=AgentStatus.ACTIVE,
        active_config_snapshot_id="snap",
    )
    snapshot = AgentConfigSnapshot(
        id="snap", tenant_id="tenant", agent_id="agent", version=1, config_snapshot=_agent_soul_from_node_data(data)
    )
    binding = WorkflowAgentNodeBinding(
        id="binding",
        tenant_id="tenant",
        app_id="app",
        workflow_id="workflow",
        workflow_version="draft",
        node_id="node",
        agent_id="agent",
        current_snapshot_id="snap",
        binding_type=WorkflowAgentBindingType.INLINE_AGENT,
        node_job_config=WorkflowNodeJobConfig(workflow_prompt="A"),
    )
    sqlite_session.add_all([agent, snapshot, binding])
    sqlite_session.commit()
    candidate = {"nodes": [{"id": "node", "data": deepcopy(data)}], "edges": []}
    candidate["nodes"][0]["data"]["agent_task"] = "B"
    candidate["nodes"][0]["data"]["model"]["name"] = "model-b"
    owner = {"tenant_id": "tenant", "app_id": "app", "workflow_id": "workflow"}
    hydrated = hydrate_agent_bindings(session=sqlite_session, account_id="user", graph=candidate, **owner)
    sqlite_session.commit()
    sqlite_session.refresh(binding)
    sqlite_session.refresh(agent)
    assert binding.node_job_config.workflow_prompt == "A"
    assert binding.current_snapshot_id == agent.active_config_snapshot_id == "snap"
    assert hydrated["nodes"][0]["data"]["agent_binding"]["current_snapshot_id"] != "snap"
    assert hydrate_agent_bindings(session=sqlite_session, account_id="user", graph=hydrated, **owner) == hydrated
    sqlite_session.commit()

    monkeypatch.setattr(
        "services.workflow_assist.acceptance_bindings.session_factory.create_session",
        sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False),
    )
    resolver_b = CandidateBindingResolver(graph=hydrated, **owner)
    other = deepcopy(hydrated)
    other["nodes"][0]["data"]["agent_task"] = "C"
    resolver_c = CandidateBindingResolver(graph=other, **owner)
    bundle_b = resolver_b.resolve(node_id="node", **owner)
    bundle_c = resolver_c.resolve(node_id="node", **owner)
    assert bundle_b.binding.node_job_config.workflow_prompt == "B"
    assert bundle_c.binding.node_job_config.workflow_prompt == "C"
    assert bundle_b.binding.id != bundle_c.binding.id
    assert bundle_b.snapshot.config_snapshot.model.model == "model-b"
    mismatched = deepcopy(hydrated)
    mismatched["nodes"][0]["data"]["model"]["name"] = "not-the-snapshot-model"
    errors = collect_invalid_inline_agent_binding_errors(session=sqlite_session, nodes=mismatched["nodes"], **owner)
    assert errors[0]["code"] == "INVALID_AGENT_NODE"
    assert "snapshot" in errors[0]["detail"]
    sqlite_session.refresh(binding)
    assert binding.node_job_config.workflow_prompt == "A"

    def failing_apply():
        with sqlite_session.begin_nested():
            activate_candidate_bindings(session=sqlite_session, account_id="user", nodes=hydrated["nodes"], **owner)
            sqlite_session.flush()
            raise RuntimeError("draft sync failed")

    with pytest.raises(RuntimeError):
        failing_apply()
    sqlite_session.refresh(binding)
    sqlite_session.refresh(agent)
    assert binding.node_job_config.workflow_prompt == "A"
    assert agent.active_config_snapshot_id == "snap"

    activate_candidate_bindings(session=sqlite_session, account_id="user", nodes=hydrated["nodes"], **owner)
    sqlite_session.commit()
    sqlite_session.refresh(binding)
    assert binding.node_job_config.workflow_prompt == "B"
    assert binding.current_snapshot_id == hydrated["nodes"][0]["data"]["agent_binding"]["current_snapshot_id"]
