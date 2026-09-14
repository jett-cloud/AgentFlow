from copy import deepcopy
from dataclasses import replace
from typing import Any, cast

import pytest
from sqlalchemy import func, select

from core.workflow.generator.graph.graph_ops import connect, empty_graph, find_node, upsert_node
from core.workflow.generator.agent.tools.tool_context import ToolEnv, ToolTurnState
from core.workflow.generator.agent.tools.tools import ToolContext, dispatch
from core.workflow.generator.agent.types import ToolCall
from core.workflow.generator.model_io.llm_response import LLMJsonClient, ModelInvoker
from core.workflow.generator.compiler.node_builder import BuilderInput
from models.agent import Agent, AgentConfigRevision, AgentConfigSnapshot, AgentScope, AgentSource, AgentStatus
from models.agent_config_entities import AgentSoulConfig
from services.agent.errors import InvalidComposerConfigError
from services.workflow_assist.hydrate import AgentBindingHydrationError, hydrate_agent_bindings
from tests.unit_tests.core.workflow.generator.node_fixtures import node_config

TABLES = (Agent, AgentConfigSnapshot, AgentConfigRevision)
OWNER = {"tenant_id": "tenant", "app_id": "app", "workflow_id": "workflow"}
_TOOL_ENTRY = {
    "provider_name": "web/search",
    "provider_type": "builtin",
    "plugin_id": "",
    "tool_name": "search",
    "tool_label": "Search",
    "description": "Search the web",
    "parameters": ({"name": "query", "type": "string", "form": "llm", "required": True},),
    "parameter_names": ("query",),
    "output_names": ("text",),
}
_MCP_ENTRY = {
    "provider_name": "github-official",
    "provider_type": "mcp",
    "plugin_id": "",
    "tool_name": "get_file_contents",
    "tool_label": "Get file",
    "description": "Read a GitHub file",
    "parameters": ({"name": "path", "type": "string", "form": "llm", "required": True},),
    "parameter_names": ("path",),
}


def _knowledge(dataset_id: str = "ds-1") -> dict[str, Any]:
    return {
        "sets": [
            {
                "id": "ks-1",
                "name": "Docs",
                "description": None,
                "datasets": [{"id": dataset_id, "name": "Docs", "description": "Docs"}],
                "query": {"mode": "generated_query", "value": None},
                "retrieval": {
                    "mode": "multiple",
                    "top_k": 4,
                    "score_threshold": None,
                    "reranking_mode": "reranking_model",
                    "reranking_enable": False,
                    "reranking_model": None,
                    "weights": None,
                    "model": None,
                },
                "metadata_filtering": {"mode": "disabled", "model_config": None, "conditions": None},
            }
        ]
    }


def _dify_tool(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": True,
        "provider_type": entry["provider_type"],
        "provider_id": entry["provider_name"],
        "tool_name": entry["tool_name"],
        "credential_type": "unauthorized",
        "description": entry["description"],
    }


def _manifest_node_data(
    *,
    tool_entries: list[dict[str, Any]] | None = None,
    dataset_id: str | None = "ds-1",
) -> dict[str, Any]:
    entries = list(tool_entries) if tool_entries is not None else [_TOOL_ENTRY]
    data: dict[str, Any] = {
        "type": "agent",
        "version": "2",
        "agent_node_kind": "dify_agent",
        "agent_task": "调查问题",
        "agent_binding": {"binding_type": "inline_agent"},
        "model": {"provider": "langgenius/openai/openai", "name": "gpt-4o", "mode": "chat"},
        "assist_binding_manifest": {
            "binding_id": "agent-node",
            "tool_keys": [[entry["provider_name"], entry["tool_name"]] for entry in entries],
            "dataset_ids": [dataset_id] if dataset_id else [],
        },
    }
    if entries:
        data["dify_tools"] = [_dify_tool(entry) for entry in entries]
    if dataset_id:
        data["knowledge"] = _knowledge(dataset_id)
    return data


def _graph_from_data(data: dict[str, Any]) -> dict[str, Any]:
    return {"nodes": [{"id": "agent-node", "data": data}], "edges": []}


def _agent_count(session) -> int:
    return int(session.scalar(select(func.count()).select_from(Agent)) or 0)


def _install_catalogues(monkeypatch: pytest.MonkeyPatch, *, tools: list[dict[str, Any]], datasets: set[str]) -> None:
    monkeypatch.setattr(
        "services.workflow_assist.hydrate.build_tool_catalogue",
        lambda tenant_id, limit=None, raise_on_error=False: tools,
    )
    monkeypatch.setattr(
        "services.workflow_assist.hydrate.build_knowledge_catalogue",
        lambda tenant_id, limit=None, raise_on_error=False: [
            {"id": item, "name": item, "description": ""} for item in datasets
        ],
    )
    monkeypatch.setattr(
        "services.workflow_assist.hydrate.AgentComposerService.validate_knowledge_datasets",
        lambda **kwargs: None,
    )


def _stub_inline_create(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    created: list[tuple[str, str]] = []

    def create_inline_binding_for_node(
        *,
        session,
        tenant_id: str,
        app_id: str,
        workflow_id: str,
        node_id: str,
        account_id: str,
        agent_soul: AgentSoulConfig | None = None,
    ) -> tuple[str, str]:
        aid = f"agent-{len(created) + 1}"
        sid = f"snap-{len(created) + 1}"
        session.add(
            Agent(
                id=aid,
                tenant_id=tenant_id,
                app_id=app_id,
                workflow_id=workflow_id,
                workflow_node_id=node_id,
                name="Agent",
                scope=AgentScope.WORKFLOW_ONLY,
                source=AgentSource.WORKFLOW,
                status=AgentStatus.ACTIVE,
                active_config_snapshot_id=sid,
            )
        )
        session.add(
            AgentConfigSnapshot(
                id=sid,
                tenant_id=tenant_id,
                agent_id=aid,
                version=len(created) + 1,
                config_snapshot=agent_soul or AgentSoulConfig(),
            )
        )
        session.flush()
        created.append((aid, sid))
        return aid, sid

    monkeypatch.setattr(
        "services.workflow_assist.hydrate.create_inline_binding_for_node",
        create_inline_binding_for_node,
    )
    return created


def _hydrate(session, graph: dict[str, Any]) -> dict[str, Any]:
    return hydrate_agent_bindings(session=session, account_id="user", graph=graph, **OWNER)


def _call(name: str, **arguments: object) -> ToolCall:
    return {"id": "c1", "name": name, "arguments": arguments}


def _builder_input() -> BuilderInput:
    return BuilderInput(
        provider="openai",
        model_name="gpt-4o",
        model_mode="chat",
        mode="workflow",
        instruction="生成工作流",
        ideal_output="",
        plan_nodes=[],
        plan_edges=[],
        tool_catalogue_text="",
        knowledge_catalogue_text="",
        start_inputs=[],
        current_graph=None,
        output_language="zh-Hans",
    )


def _tool_context(graph: dict[str, Any]) -> ToolContext:
    return ToolContext(
        env=ToolEnv(
            tenant_id="tenant",
            mode="workflow",
            tool_entries=[_TOOL_ENTRY],
            knowledge_entries=[{"id": "ds-1", "name": "Docs", "description": ""}],
            installed_tools={("web/search", "search")},
            installed_dataset_ids={"ds-1"},
            knowledge_available=True,
            tools_available=True,
            builder_input=_builder_input(),
            llm_client=LLMJsonClient(model_instance=cast("ModelInvoker", object()), model_parameters={}),
            agent_model_entries=(
                {
                    "provider": "langgenius/openai/openai",
                    "name": "gpt-4o",
                    "model_type": "llm",
                    "features": (),
                },
            ),
            models_available=True,
            hydrate_graph=None,
        ),
        state=ToolTurnState(graph=graph),
    )


def _connected_manifest_graph(*, data: dict[str, Any] | None = None) -> dict[str, Any]:
    graph = upsert_node(
        empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={"variables": []}
    )
    graph = upsert_node(
        graph,
        node_id="agent-node",
        node_type="agent",
        title="助手",
        desc="",
        config=_manifest_node_data() if data is None else {k: v for k, v in data.items() if k != "type"},
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
    graph = connect(graph, source="start", target="agent-node")
    return connect(graph, source="agent-node", target="end")


class _FakeAcceptanceRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def run(self, *, graph, revision, graph_hash, case_ids, mode):
        self.calls.append({"revision": revision, "graph_hash": graph_hash, "graph": graph, "mode": mode})
        return [
            {
                "attempt_id": "att-1",
                "revision": revision,
                "graph_hash": graph_hash,
                "case_id": case_ids[0],
                "passed": True,
                "executed": True,
                "status": "simulated",
                "failed_nodes": [],
                "evidence": [{"passed": True}],
                "trace_summary": "ok",
                "unverified_nodes": [],
            }
        ]


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_hydrate_same_manifest_twice_reuses_one_inline_agent(sqlite_session, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_catalogues(monkeypatch, tools=[_TOOL_ENTRY], datasets={"ds-1"})
    created = _stub_inline_create(monkeypatch)
    graph = _graph_from_data(_manifest_node_data())

    first = _hydrate(sqlite_session, graph)
    second = _hydrate(sqlite_session, graph)

    assert created == [("agent-1", "snap-1")]
    assert _agent_count(sqlite_session) == 1
    assert first["nodes"][0]["data"]["agent_binding"]["agent_id"] == "agent-1"
    assert first["nodes"][0]["data"]["agent_binding"]["current_snapshot_id"] == "snap-1"
    assert second["nodes"][0]["data"]["agent_binding"] == first["nodes"][0]["data"]["agent_binding"]
    assert graph["nodes"][0]["data"]["assist_binding_manifest"]["binding_id"] == "agent-node"
    assert "agent_id" not in graph["nodes"][0]["data"]["agent_binding"]


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_hydrate_tool_mcp_knowledge_update_keeps_same_soul(sqlite_session, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_catalogues(monkeypatch, tools=[_TOOL_ENTRY, _MCP_ENTRY], datasets={"ds-1", "ds-2"})
    created = _stub_inline_create(monkeypatch)
    original = _graph_from_data(_manifest_node_data())
    first = _hydrate(sqlite_session, original)

    updated_data = _manifest_node_data(tool_entries=[_TOOL_ENTRY, _MCP_ENTRY], dataset_id="ds-2")
    updated = _graph_from_data(updated_data)
    second = _hydrate(sqlite_session, updated)

    assert created == [("agent-1", "snap-1")]
    assert _agent_count(sqlite_session) == 1
    first_binding = first["nodes"][0]["data"]["agent_binding"]
    second_binding = second["nodes"][0]["data"]["agent_binding"]
    assert second_binding["agent_id"] == first_binding["agent_id"]
    assert second_binding["current_snapshot_id"] != first_binding["current_snapshot_id"]
    snapshots = list(sqlite_session.scalars(select(AgentConfigSnapshot)).all())
    assert len(snapshots) == 2
    assert {item.agent_id for item in snapshots} == {"agent-1"}


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_agent_update_with_empty_tools_clears_existing_soul_tools(
    sqlite_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_catalogues(monkeypatch, tools=[_TOOL_ENTRY], datasets={"ds-1"})
    _stub_inline_create(monkeypatch)
    first = _hydrate(sqlite_session, _graph_from_data(_manifest_node_data()))

    cleared_data = _manifest_node_data(tool_entries=[], dataset_id="ds-1")
    cleared_data["dify_tools"] = []
    cleared_data["agent_binding"] = first["nodes"][0]["data"]["agent_binding"]
    hydrated = _hydrate(sqlite_session, _graph_from_data(cleared_data))

    snapshot_id = hydrated["nodes"][0]["data"]["agent_binding"]["current_snapshot_id"]
    snapshot = sqlite_session.scalar(select(AgentConfigSnapshot).where(AgentConfigSnapshot.id == snapshot_id))
    assert snapshot is not None
    soul = AgentSoulConfig.model_validate(snapshot.config_snapshot)
    assert soul.tools.dify_tools == []


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_uninstalled_tool_blocks_evidence_and_keeps_declarative_config(
    sqlite_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_catalogues(monkeypatch, tools=[], datasets={"ds-1"})
    created = _stub_inline_create(monkeypatch)
    graph = _connected_manifest_graph()
    original = deepcopy(graph)
    runner = _FakeAcceptanceRunner()
    context = _tool_context(graph)

    def hydrate_graph(candidate):
        return _hydrate(sqlite_session, candidate)

    context.env = replace(context.env, hydrate_graph=hydrate_graph, acceptance_runner=runner)

    acceptance = dispatch(_call("run_acceptance"), context)
    finished = dispatch(_call("finish", summary="已完成"), context)

    assert created == []
    assert _agent_count(sqlite_session) == 0
    assert runner.calls == []
    assert acceptance["ok"] is False
    assert acceptance["retryable"] is True
    assert acceptance["error_code"] == "UNKNOWN_TOOL"
    assert finished["ok"] is False
    assert finished["retryable"] is True
    assert finished["error_code"] == "UNKNOWN_TOOL"
    assert context.state.attempts == {}
    node = find_node(context.state.graph, "agent-node")
    assert node["data"]["assist_binding_manifest"] == original["nodes"][1]["data"]["assist_binding_manifest"]
    assert "agent_id" not in node["data"]["agent_binding"]
    assert "current_snapshot_id" not in node["data"]["agent_binding"]


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_out_of_scope_dataset_blocks_evidence_and_keeps_declarative_config(
    sqlite_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_catalogues(monkeypatch, tools=[_TOOL_ENTRY], datasets={"ds-other"})
    monkeypatch.setattr(
        "services.workflow_assist.hydrate.AgentComposerService.validate_knowledge_datasets",
        lambda **kwargs: (_ for _ in ()).throw(InvalidComposerConfigError("knowledge_dataset_not_found")),
    )
    created = _stub_inline_create(monkeypatch)
    graph = _connected_manifest_graph()
    runner = _FakeAcceptanceRunner()
    context = _tool_context(graph)
    context.env = replace(
        context.env,
        hydrate_graph=lambda candidate: _hydrate(sqlite_session, candidate),
        acceptance_runner=runner,
    )

    finished = dispatch(_call("finish", summary="done"), context)

    assert created == []
    assert _agent_count(sqlite_session) == 0
    assert runner.calls == []
    assert finished["ok"] is False
    assert finished["retryable"] is True
    assert finished["error_code"] == "UNKNOWN_DATASET"
    node = find_node(context.state.graph, "agent-node")
    assert node["data"]["assist_binding_manifest"]["dataset_ids"] == ["ds-1"]
    assert "agent_id" not in node["data"]["agent_binding"]


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_persistence_error_is_recoverable_and_does_not_write_half_bindings(
    sqlite_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_catalogues(monkeypatch, tools=[_TOOL_ENTRY], datasets={"ds-1"})

    def boom(**kwargs):
        raise RuntimeError("snapshot write failed")

    monkeypatch.setattr("services.workflow_assist.hydrate.create_inline_binding_for_node", boom)
    graph = _connected_manifest_graph()
    runner = _FakeAcceptanceRunner()
    context = _tool_context(graph)
    context.env = replace(
        context.env,
        hydrate_graph=lambda candidate: _hydrate(sqlite_session, candidate),
        acceptance_runner=runner,
    )

    with pytest.raises(AgentBindingHydrationError):
        _hydrate(sqlite_session, _graph_from_data(_manifest_node_data()))

    finished = dispatch(_call("finish", summary="已完成"), context)

    assert _agent_count(sqlite_session) == 0
    assert runner.calls == []
    assert finished["ok"] is False
    assert finished["retryable"] is True
    assert finished["error_code"] == "INVALID_AGENT_NODE"
    node = find_node(context.state.graph, "agent-node")
    assert node["data"]["assist_binding_manifest"]["binding_id"] == "agent-node"
    assert "agent_id" not in node["data"]["agent_binding"]
