"""Regression coverage for resource discovery before graph construction."""

from dataclasses import replace

import pytest

from core.workflow.generator.agent.tools.tools import dispatch


def call(name, **arguments):
    return {"id": "discovery", "name": name, "arguments": arguments}


def test_tool_browse_recovers_from_keyword_miss_and_keeps_summaries_safe(tool_context):
    entries = [
        {
            "provider_name": "provider",
            "provider_type": "mcp",
            "plugin_id": "internal",
            "tool_name": f"lookup_{index:02d}",
            "tool_label": "Lookup",
            "description": "Read records",
            "parameters": (),
        }
        for index in reversed(range(15))
    ]
    tool_context.env = replace(tool_context.env, tools_available=True, tool_entries=entries)
    miss = dispatch(call("search_tools", query="unrelated"), tool_context)["content"]
    assert miss["hits"] == []
    assert miss["catalogue_count"] == 15
    page = dispatch(call("search_tools", query=" \t"), tool_context)["content"]
    assert [hit["binding"]["tool_name"] for hit in page["hits"]] == [f"lookup_{i:02d}" for i in range(12)]
    assert all(set(hit) == {"binding", "label", "description"} for hit in page["hits"])
    assert entries[0]["tool_name"] == "lookup_14"


def test_tool_discovery_distinguishes_empty_from_unavailable(tool_context):
    tool_context.env = replace(tool_context.env, tools_available=True, tool_entries=[])
    assert dispatch(call("search_tools", query=""), tool_context)["content"]["catalogue_count"] == 0
    tool_context.env = replace(tool_context.env, tools_available=False)
    content = dispatch(call("search_tools", query=""), tool_context)["content"]
    assert content["available"] is False
    assert content["catalogue_count"] is None


def test_list_models_browses_all_pages_with_exact_identities_and_features(tool_context):
    entries = tuple(
        {"provider": "tenant/provider", "name": f"model-{i:02d}", "model_type": "llm", "features": ("tool-call",)}
        for i in reversed(range(15))
    )
    tool_context.env = replace(tool_context.env, models_available=True, agent_model_entries=entries)
    result = dispatch(call("list_models"), tool_context)
    assert result["ok"] is True
    first = result["content"]
    assert first["catalogue_count"] == 15
    assert first["next_offset"] == 12
    second = dispatch(call("list_models", offset=first["next_offset"]), tool_context)["content"]
    assert second["next_offset"] is None
    assert [hit["name"] for hit in first["hits"] + second["hits"]] == [f"model-{i:02d}" for i in range(15)]
    assert first["hits"][0] == {
        "provider": "tenant/provider",
        "name": "model-00",
        "model_type": "llm",
        "features": ["tool-call"],
    }
    first["hits"][0]["features"].append("mutated")
    assert entries[-1]["features"] == ("tool-call",)


@pytest.mark.parametrize(("available", "expected"), [(True, 0), (False, None)])
def test_list_models_distinguishes_empty_from_unavailable(tool_context, available, expected):
    tool_context.env = replace(tool_context.env, models_available=available, agent_model_entries=())
    result = dispatch(call("list_models"), tool_context)
    assert result["ok"] is True
    assert result["content"] == {"available": available, "hits": [], "catalogue_count": expected, "next_offset": None}


@pytest.mark.parametrize("offset", [-1, True, "12", 0.5])
def test_list_models_rejects_invalid_offset(tool_context, offset):
    result = dispatch(call("list_models", offset=offset), tool_context)
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_ARGUMENT"


def test_inspect_tool_exposes_known_output_types_without_aliasing_snapshot(tool_context):
    entry = {
        "provider_name": "provider",
        "provider_type": "mcp",
        "plugin_id": "internal",
        "tool_name": "lookup",
        "tool_label": "Lookup",
        "description": "Read records",
        "parameters": (),
        "output_names": ("rows",),
        "outputs": ({"name": "rows", "type": "array[object]"},),
    }
    tool_context.env = replace(tool_context.env, tools_available=True, tool_entries=[entry])
    result = dispatch(call("inspect_tool", provider_name="provider", tool_name="lookup"), tool_context)
    assert result["content"]["outputs"] == [{"name": "rows", "type": "array[object]"}]
    result["content"]["outputs"][0]["type"] = "string"
    assert entry["outputs"][0]["type"] == "array[object]"


def test_unknown_node_schema_is_actionable_error(tool_context):
    result = dispatch(call("inspect_node_schema", node_type="nonexistent_node"), tool_context)
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["retryable"] is True
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert "llm" in result["cause"]["available_types"]
    assert "nonexistent_node" not in result["cause"]["available_types"]
