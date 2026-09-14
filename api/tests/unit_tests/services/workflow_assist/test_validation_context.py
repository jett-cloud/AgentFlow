from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services.workflow_assist.validation_context import build_validation_context, namespace_names


def test_empty_catalogue_is_distinct_from_failed_catalogue(monkeypatch):
    catalogue = Mock(return_value=[])
    monkeypatch.setattr("services.workflow_assist.validation_context.build_knowledge_catalogue", catalogue)
    graph = {"nodes": [{"id": "kr", "data": {"type": "knowledge-retrieval"}}], "edges": []}
    assert build_validation_context(tenant_id="t", graph=graph, draft=None)["installed_dataset_ids"] == set()
    catalogue.assert_called_once_with("t", limit=None, raise_on_error=True)
    catalogue.side_effect = RuntimeError("catalogue unavailable")
    with pytest.raises(RuntimeError, match="catalogue unavailable"):
        build_validation_context(tenant_id="t", graph=graph, draft=None)


def test_agent_knowledge_loads_the_complete_dataset_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    catalogue = Mock(return_value=[{"id": "ds-1", "name": "Docs", "description": ""}])
    monkeypatch.setattr("services.workflow_assist.validation_context.build_knowledge_catalogue", catalogue)
    graph = {
        "nodes": [
            {
                "id": "agent",
                "data": {
                    "type": "agent",
                    "knowledge": {"sets": [{"datasets": [{"id": "ds-1"}]}]},
                },
            }
        ],
        "edges": [],
    }

    result = build_validation_context(tenant_id="t", graph=graph, draft=None)

    assert result["installed_dataset_ids"] == {"ds-1"}
    catalogue.assert_called_once_with("t", limit=None, raise_on_error=True)


def test_assist_binding_manifest_loads_tool_and_dataset_catalogues(monkeypatch: pytest.MonkeyPatch) -> None:
    tools = Mock(return_value=[])
    datasets = Mock(return_value=[{"id": "ds-1", "name": "Docs", "description": ""}])
    monkeypatch.setattr("services.workflow_assist.validation_context.build_tool_catalogue", tools)
    monkeypatch.setattr("services.workflow_assist.validation_context.build_knowledge_catalogue", datasets)
    graph = {
        "nodes": [
            {
                "id": "agent",
                "data": {
                    "type": "agent",
                    "assist_binding_manifest": {
                        "binding_id": "agent",
                        "tool_keys": [["web/search", "search"]],
                        "dataset_ids": ["ds-1"],
                    },
                },
            }
        ],
        "edges": [],
    }

    result = build_validation_context(tenant_id="t", graph=graph, draft=None)

    assert result["installed_tools"] == set()
    assert result["installed_dataset_ids"] == {"ds-1"}
    tools.assert_called_once_with("t", limit=None, raise_on_error=True)
    datasets.assert_called_once_with("t", limit=None, raise_on_error=True)


def test_namespace_context_uses_names_without_decrypting_values():
    draft = SimpleNamespace(
        _environment_variables='{"id": {"name": "token", "value": "encrypted"}}',
        _conversation_variables='{"id": {"name": "history"}}',
    )
    assert build_validation_context(tenant_id="t", graph={"nodes": [], "edges": []}, draft=draft) == {
        "environment_variables": {"token"},
        "conversation_variables": {"history"},
    }


def test_tool_validation_context_reuses_one_complete_catalogue_snapshot(monkeypatch):
    entries = [
        {
            "provider_name": "image/provider",
            "provider_type": "builtin",
            "plugin_id": "image/provider",
            "tool_name": "generate",
            "tool_label": "Generate",
            "description": "Generate an image",
            "parameters": ({"name": "prompt", "type": "string", "form": "llm", "required": True},),
            "parameter_names": ("prompt",),
            "output_names": ("files",),
        }
    ]
    catalogue = Mock(return_value=entries)
    monkeypatch.setattr("services.workflow_assist.validation_context.build_tool_catalogue", catalogue)

    result = build_validation_context(
        tenant_id="t",
        graph={"nodes": [{"id": "tool_1", "data": {"type": "tool"}}], "edges": []},
        draft=None,
    )

    assert result["tool_entries"] is entries
    assert result["installed_tools"] == {("image/provider", "generate")}
    assert result["tool_parameter_names"] == {("image/provider", "generate"): frozenset({"prompt"})}
    assert result["tool_output_names"] == {("image/provider", "generate"): frozenset({"files"})}
    catalogue.assert_called_once_with("t", limit=None, raise_on_error=True)


def test_model_validation_context_uses_current_tenant_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    catalogue = Mock(
        return_value=(
            {
                "provider": "openai",
                "name": "gpt-4o",
                "model_type": "llm",
                "features": (),
            },
        )
    )
    monkeypatch.setattr("services.workflow_assist.validation_context.build_agent_model_catalogue", catalogue)

    result = build_validation_context(
        tenant_id="t",
        graph={
            "nodes": [
                {
                    "id": "llm",
                    "data": {
                        "type": "llm",
                        "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
                    },
                }
            ],
            "edges": [],
        },
        draft=None,
        include_models=True,
    )

    assert result["installed_models"] == {("openai", "gpt-4o")}
    catalogue.assert_called_once_with("t")


def test_invalid_namespace_is_not_silently_empty():
    with pytest.raises(ValueError):
        namespace_names("[]")


@pytest.mark.parametrize("nodes", [42, [42], None])
def test_http_compositor_returns_structured_error_for_malformed_nodes(nodes):
    from services.workflow_assist.validate import validate_graph

    result = validate_graph(
        graph={"nodes": nodes, "edges": []},
        mode="local",
        generation_mode="workflow",
        base_graph={"nodes": [], "edges": []},
        mutable_node_ids=set(),
        planned_new_ids=set(),
        intent_flags={},
    )
    assert not result["ok"]
    assert result["errors"][0]["code"] == "INVALID_SCHEMA"
