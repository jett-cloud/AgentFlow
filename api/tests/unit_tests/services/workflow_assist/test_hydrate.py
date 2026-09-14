from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from models.agent_config_entities import AgentSoulConfig
from services.agent.errors import InvalidComposerConfigError
from services.workflow_assist.hydrate import (
    _agent_soul_from_node_data,
    candidate_soul_matches_snapshot,
    collect_invalid_inline_agent_binding_errors,
    hydrate_agent_bindings,
)


def _graph(nodes: list[dict]) -> dict:
    return {"nodes": nodes, "edges": []}


def _knowledge(dataset_id: str = "ds-old") -> dict:
    return {
        "sets": [
            {
                "id": "ks-old",
                "name": "Old docs",
                "description": None,
                "datasets": [{"id": dataset_id, "name": "Old", "description": "Old docs"}],
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


def _base_soul() -> AgentSoulConfig:
    return AgentSoulConfig.model_validate(
        {
            "prompt": {"system_prompt": "Keep this prompt"},
            "tools": {
                "dify_tools": [
                    {
                        "provider_type": "mcp",
                        "provider_id": "github-official",
                        "tool_name": None,
                        "credential_type": "unauthorized",
                    }
                ]
            },
            "knowledge": _knowledge(),
            "human": {"contacts": [{"name": "Reviewer"}]},
            "config_files": [{"name": "guide.txt", "file_kind": "upload_file", "file_id": "file-1"}],
            "sandbox": {"provider": "docker", "config": {"image": "python:3.12"}},
            "memory": {"scope": "conversation", "budget": "small"},
            "config_note": "keep-note",
            "model": {
                "plugin_id": "langgenius/openai",
                "model_provider": "langgenius/openai/openai",
                "model": "gpt-4o",
            },
        }
    )


@pytest.fixture(autouse=True)
def _stub_binding_rows(monkeypatch):
    monkeypatch.setattr("services.workflow_assist.hydrate._ensure_inline_binding", lambda **kwargs: None)


@patch("services.workflow_assist.hydrate._load_trusted_inline_binding", return_value=None)
@patch("services.workflow_assist.hydrate.create_inline_binding_for_node", return_value=("aid", "sid"))
def test_hydrate_fills_missing_inline_ids(
    create_inline_binding_for_node: MagicMock,
    load_trusted_inline_binding: MagicMock,
):
    graph = _graph(
        [
            {
                "id": "agent-node",
                "data": {
                    "type": "agent",
                    "version": 2,
                },
            }
        ]
    )
    original_graph = deepcopy(graph)

    result = hydrate_agent_bindings(
        session=MagicMock(),
        tenant_id="tenant",
        app_id="app",
        account_id="account",
        workflow_id="workflow",
        graph=graph,
    )

    assert result["nodes"][0]["data"] == {
        "type": "agent",
        "version": "2",
        "agent_binding": {
            "binding_type": "inline_agent",
            "agent_id": "aid",
            "current_snapshot_id": "sid",
        },
        "agent_node_kind": "dify_agent",
    }
    assert graph == original_graph
    create_inline_binding_for_node.assert_called_once_with(
        session=create_inline_binding_for_node.call_args.kwargs["session"],
        tenant_id="tenant",
        app_id="app",
        workflow_id="workflow",
        node_id="agent-node",
        account_id="account",
        agent_soul=None,
    )


@patch("services.workflow_assist.hydrate._load_trusted_inline_binding", return_value=None)
@patch("services.workflow_assist.hydrate.create_inline_binding_for_node", return_value=("aid", "sid"))
def test_hydrate_copies_generated_model_into_agent_soul(
    create_inline_binding_for_node: MagicMock,
    load_trusted_inline_binding: MagicMock,
):
    graph = _graph(
        [
            {
                "id": "agent-node",
                "data": {
                    "type": "agent",
                    "version": 2,
                    "model": {
                        "provider": "langgenius/openai/openai",
                        "name": "gpt-4o",
                        "mode": "chat",
                        "completion_params": {"temperature": 0.3, "top_p": 0.8},
                    },
                },
            }
        ]
    )

    hydrate_agent_bindings(
        session=MagicMock(),
        tenant_id="tenant",
        app_id="app",
        account_id="account",
        workflow_id="workflow",
        graph=graph,
    )

    soul = create_inline_binding_for_node.call_args.kwargs.get("agent_soul")
    assert soul is not None
    assert soul.model is not None
    assert soul.model.plugin_id == "langgenius/openai"
    assert soul.model.model_provider == "langgenius/openai/openai"
    assert soul.model.model == "gpt-4o"
    assert soul.model.model_settings.temperature == 0.3
    assert soul.model.model_settings.top_p == 0.8


@patch("services.workflow_assist.hydrate._load_trusted_inline_binding", return_value=None)
@patch("services.workflow_assist.hydrate.create_inline_binding_for_node", return_value=("aid", "sid"))
def test_hydrate_copies_generated_dify_tools_into_agent_soul(
    create_inline_binding_for_node: MagicMock,
    load_trusted_inline_binding: MagicMock,
):
    graph = _graph(
        [
            {
                "id": "agent-node",
                "data": {
                    "type": "agent",
                    "version": 2,
                    "model": {
                        "provider": "langgenius/openai/openai",
                        "name": "gpt-4o",
                    },
                    "dify_tools": [
                        {
                            "provider_type": "mcp",
                            "provider_id": "github-official",
                            "tool_name": None,
                            "credential_type": "unauthorized",
                        }
                    ],
                },
            }
        ]
    )

    hydrate_agent_bindings(
        session=MagicMock(),
        tenant_id="tenant",
        app_id="app",
        account_id="account",
        workflow_id="workflow",
        graph=graph,
    )

    soul = create_inline_binding_for_node.call_args.kwargs.get("agent_soul")
    assert soul is not None
    assert len(soul.tools.dify_tools) == 1
    assert soul.tools.dify_tools[0].provider_type == "mcp"
    assert soul.tools.dify_tools[0].provider_id == "github-official"
    assert soul.tools.dify_tools[0].tool_name is None


@patch("services.workflow_assist.hydrate._load_trusted_inline_binding", return_value=None)
@patch("services.workflow_assist.hydrate.create_inline_binding_for_node", return_value=("aid", "sid"))
def test_hydrate_copies_generated_knowledge_into_agent_soul(
    create_inline_binding_for_node: MagicMock,
    load_trusted_inline_binding: MagicMock,
) -> None:
    graph = _graph(
        [
            {
                "id": "agent-node",
                "data": {
                    "type": "agent",
                    "version": 2,
                    "model": {"provider": "langgenius/openai/openai", "name": "gpt-4o"},
                    "knowledge": _knowledge("ds-new"),
                },
            }
        ]
    )

    hydrate_agent_bindings(
        session=MagicMock(),
        tenant_id="tenant",
        app_id="app",
        account_id="account",
        workflow_id="workflow",
        graph=graph,
    )

    soul = create_inline_binding_for_node.call_args.kwargs["agent_soul"]
    assert soul.knowledge.sets[0].datasets[0].id == "ds-new"


@patch("services.workflow_assist.hydrate._load_trusted_inline_binding", return_value=None)
@patch("services.workflow_assist.hydrate.create_inline_binding_for_node")
def test_hydrate_rejects_invalid_knowledge_without_creating_an_empty_soul(
    create_inline_binding_for_node: MagicMock,
    load_trusted_inline_binding: MagicMock,
) -> None:
    graph = _graph(
        [
            {
                "id": "agent-node",
                "data": {
                    "type": "agent",
                    "version": 2,
                    "model": {"provider": "langgenius/openai/openai", "name": "gpt-4o"},
                    "knowledge": {"sets": [{"id": "broken"}]},
                },
            }
        ]
    )

    with pytest.raises(ValueError, match="invalid Agent Soul projection.*agent-node"):
        hydrate_agent_bindings(
            session=MagicMock(),
            tenant_id="tenant",
            app_id="app",
            account_id="account",
            workflow_id="workflow",
            graph=graph,
        )

    create_inline_binding_for_node.assert_not_called()


def test_agent_soul_overlay_preserves_unprojected_snapshot_sections() -> None:
    base = _base_soul()

    merged = _agent_soul_from_node_data({"agent_task": "Updated task"}, base_soul=base)

    assert merged is not None
    assert merged.model_dump(mode="json") == base.model_dump(mode="json")
    assert merged is not base


def test_agent_soul_overlay_replaces_and_clears_only_explicit_sections() -> None:
    base = _base_soul()
    replacement = _knowledge("ds-new")

    replaced = _agent_soul_from_node_data({"knowledge": replacement}, base_soul=base)
    cleared = _agent_soul_from_node_data({"knowledge": {"sets": []}, "dify_tools": []}, base_soul=base)

    assert replaced is not None
    assert replaced.knowledge.model_dump(mode="json", by_alias=True) == replacement
    assert replaced.prompt == base.prompt
    assert replaced.human == base.human
    assert replaced.config_files == base.config_files
    assert replaced.sandbox == base.sandbox
    assert replaced.memory == base.memory
    assert cleared is not None
    assert cleared.knowledge.sets == []
    assert cleared.tools.dify_tools == []
    assert cleared.prompt == base.prompt


def test_agent_soul_overlay_missing_tools_preserves_snapshot_tools() -> None:
    base = _base_soul()

    merged = _agent_soul_from_node_data({"knowledge": _knowledge("ds-new")}, base_soul=base)

    assert merged is not None
    assert merged.tools == base.tools


def test_candidate_soul_match_uses_the_same_snapshot_overlay() -> None:
    base = _base_soul()
    snapshot = SimpleNamespace(config_snapshot=base)

    assert candidate_soul_matches_snapshot({"agent_task": "Task only"}, snapshot) is True
    assert candidate_soul_matches_snapshot({"knowledge": {"sets": []}}, snapshot) is False


def test_invalid_snapshot_knowledge_is_translated_to_unknown_dataset() -> None:
    base = _base_soul()
    trusted = SimpleNamespace(
        agent=SimpleNamespace(id="aid"),
        snapshot=SimpleNamespace(id="sid", config_snapshot=base),
    )
    node = {
        "id": "agent-node",
        "data": {
            "type": "agent",
            "version": "2",
            "agent_node_kind": "dify_agent",
            "agent_task": "Answer",
            "agent_binding": {
                "binding_type": "inline_agent",
                "agent_id": "aid",
                "current_snapshot_id": "sid",
            },
        },
    }

    with (
        patch("services.workflow_assist.hydrate._load_trusted_inline_binding", return_value=trusted),
        patch(
            "services.workflow_assist.hydrate.AgentComposerService.validate_knowledge_datasets",
            side_effect=InvalidComposerConfigError("knowledge_dataset_not_found"),
        ),
    ):
        errors = collect_invalid_inline_agent_binding_errors(
            session=MagicMock(),
            tenant_id="tenant",
            app_id="app",
            workflow_id="workflow",
            nodes=[node],
        )

    assert errors == [
        {
            "code": "UNKNOWN_DATASET",
            "detail": "Agent node 'agent-node' references a missing or out-of-scope knowledge dataset",
            "node_id": "agent-node",
        }
    ]


@patch("services.workflow_assist.hydrate.create_inline_binding_for_node")
def test_hydrate_skips_already_bound_when_ids_are_trusted(create_inline_binding_for_node: MagicMock):
    trusted = MagicMock()
    trusted.agent.id = "aid"
    trusted.snapshot.id = "sid"
    graph = _graph(
        [
            {
                "id": "agent-node",
                "data": {
                    "type": "agent",
                    "version": "2",
                    "agent_binding": {
                        "binding_type": "inline_agent",
                        "agent_id": "aid",
                        "current_snapshot_id": "sid",
                    },
                },
            }
        ]
    )

    with patch("services.workflow_assist.hydrate._load_trusted_inline_binding", return_value=trusted):
        result = hydrate_agent_bindings(
            session=MagicMock(),
            tenant_id="tenant",
            app_id="app",
            account_id="account",
            workflow_id="workflow",
            graph=graph,
        )

    assert result["nodes"][0]["data"]["agent_binding"]["agent_id"] == "aid"
    assert result["nodes"][0]["data"]["agent_binding"]["current_snapshot_id"] == "sid"
    create_inline_binding_for_node.assert_not_called()


@patch("services.workflow_assist.hydrate._load_trusted_inline_binding", return_value=None)
@patch("services.workflow_assist.hydrate.create_inline_binding_for_node", return_value=("new-aid", "new-sid"))
def test_hydrate_recreates_untrusted_binding_ids(
    create_inline_binding_for_node: MagicMock,
    load_trusted_inline_binding: MagicMock,
):
    graph = _graph(
        [
            {
                "id": "agent-node",
                "data": {
                    "type": "agent",
                    "version": "2",
                    "agent_binding": {
                        "binding_type": "inline_agent",
                        "agent_id": "forged-agent",
                        "current_snapshot_id": "forged-snap",
                    },
                },
            }
        ]
    )

    result = hydrate_agent_bindings(
        session=MagicMock(),
        tenant_id="tenant",
        app_id="app",
        account_id="account",
        workflow_id="workflow",
        graph=graph,
    )

    assert result["nodes"][0]["data"]["agent_binding"]["agent_id"] == "new-aid"
    assert result["nodes"][0]["data"]["agent_binding"]["current_snapshot_id"] == "new-sid"
    create_inline_binding_for_node.assert_called_once()


@patch("services.workflow_assist.hydrate.AgentComposerService._create_config_version")
@patch("services.workflow_assist.hydrate.create_inline_binding_for_node")
def test_hydrate_updates_existing_agent_snapshot_when_soul_changes(
    create_inline_binding_for_node: MagicMock,
    create_config_version: MagicMock,
):
    trusted = MagicMock()
    trusted.agent.id = "aid"
    trusted.agent.tenant_id = "tenant"
    trusted.agent.active_config_snapshot_id = "old-sid"
    trusted.snapshot.id = "old-sid"
    trusted.snapshot.config_snapshot.model_dump.return_value = {"model": None}
    create_config_version.return_value = SimpleNamespace(id="new-sid")
    graph = _graph(
        [
            {
                "id": "agent-node",
                "data": {
                    "type": "agent",
                    "version": "2",
                    "agent_binding": {
                        "binding_type": "inline_agent",
                        "agent_id": "aid",
                        "current_snapshot_id": "old-sid",
                    },
                    "model": {
                        "provider": "langgenius/openai/openai",
                        "name": "gpt-4o",
                    },
                },
            }
        ]
    )

    with patch("services.workflow_assist.hydrate._load_trusted_inline_binding", return_value=trusted):
        result = hydrate_agent_bindings(
            session=MagicMock(),
            tenant_id="tenant",
            app_id="app",
            account_id="account",
            workflow_id="workflow",
            graph=graph,
        )

    create_inline_binding_for_node.assert_not_called()
    create_config_version.assert_called_once()
    assert result["nodes"][0]["data"]["agent_binding"]["agent_id"] == "aid"
    assert result["nodes"][0]["data"]["agent_binding"]["current_snapshot_id"] == "new-sid"
    assert trusted.agent.active_config_snapshot_id == "old-sid"
