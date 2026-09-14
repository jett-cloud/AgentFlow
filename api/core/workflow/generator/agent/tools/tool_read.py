"""Read and search tools: graph, node, schema, and bounded catalogue views."""

import json
from typing import cast

from core.workflow.generator.agent.tools.tool_context import ToolContext
from core.workflow.generator.agent.tools.tool_results import error, ok, require_str
from core.workflow.generator.agent.types import ToolCall, ToolResult
from core.workflow.generator.graph.graph_ops import read_node_view, render_compact_graph
from core.workflow.generator.prompts.builder_prompts import get_node_config_snippet
from core.workflow.generator.prompts.loader import registered_skill_names, skill_body
from core.workflow.generator.resources.resource_search import search_knowledge
from core.workflow.generator.resources.resource_search import search_tools as search_tool_catalogue
from core.workflow.generator.resources.tool_catalogue import ToolCatalogueEntry, find_tool_entry

_MAX_ACTIVE_SKILLS = 4


def read_graph(call: ToolCall, context: ToolContext) -> ToolResult:
    return ok(call, changed=False, content=cast(dict[str, object], render_compact_graph(context.state.graph)))


def read_node(call: ToolCall, context: ToolContext) -> ToolResult:
    node_id = require_str(call["arguments"], "id")
    if node_id is None:
        return error(call, "INVALID_ARGUMENT", "id is required")
    view = read_node_view(context.state.graph, node_id)
    if view is None:
        return error(call, "NODE_NOT_FOUND", f"Node {node_id!r} does not exist")
    return ok(call, changed=False, content=cast(dict[str, object], view))


def inspect_node_schema(call: ToolCall, context: ToolContext) -> ToolResult:
    node_type = require_str(call["arguments"], "node_type")
    if node_type is None:
        return error(call, "INVALID_ARGUMENT", "node_type is required")
    return ok(call, changed=False, content={"node_type": node_type, "snippet": get_node_config_snippet(node_type)})


def activate_skills(call: ToolCall, context: ToolContext) -> ToolResult:
    """Replace the active skill set. Does not mutate the candidate graph."""
    names = call["arguments"].get("names")
    if not isinstance(names, list):
        return error(call, "INVALID_ARGUMENT", "names must be an array of skill names")
    registered = registered_skill_names()
    available = ", ".join(registered) if registered else "(none)"
    if len(names) > _MAX_ACTIVE_SKILLS:
        return error(
            call,
            "INVALID_ARGUMENT",
            f"names may contain at most {_MAX_ACTIVE_SKILLS} skills; illegal={names!r}; available: {available}",
        )
    if any(not isinstance(name, str) or not name for name in names):
        return error(call, "INVALID_ARGUMENT", "each skill name must be a non-empty string")
    seen: set[str] = set()
    duplicates: list[str] = []
    for name in names:
        if name in seen:
            duplicates.append(name)
        seen.add(name)
    if duplicates:
        return error(
            call,
            "INVALID_ARGUMENT",
            f"duplicate skill names {duplicates!r}; illegal={names!r}; available: {available}",
        )
    unknown = [name for name in names if name not in set(registered)]
    if unknown:
        return error(
            call,
            "UNKNOWN_SKILL",
            f"Unknown skill {unknown!r}; illegal={unknown!r}; available: {available}",
        )
    missing_body = [name for name in names if skill_body(name) is None]
    if missing_body:
        return error(
            call,
            "CAPABILITY_UNAVAILABLE",
            f"Registered skill body could not be loaded: {missing_body!r}; available: {available}",
        )
    return ok(call, changed=False, content={"active_skills": list(names)})


def search_datasets(call: ToolCall, context: ToolContext) -> ToolResult:
    query = call["arguments"].get("query")
    if not isinstance(query, str):
        return error(call, "INVALID_ARGUMENT", "query is required")
    if not context.env.knowledge_available:
        return ok(call, changed=False, content={"hits": [], "available": False})
    hits = search_knowledge(context.env.knowledge_entries, query)
    return ok(call, changed=False, content={"hits": list(hits), "available": True})


def search_tools(call: ToolCall, context: ToolContext) -> ToolResult:
    """Return at most the search layer's bounded, schema-free tool summaries."""
    query = call["arguments"].get("query")
    if not isinstance(query, str):
        return error(call, "INVALID_ARGUMENT", "query is required")
    if not context.env.tools_available:
        return ok(call, changed=False, content={"hits": [], "available": False})
    hits = search_tool_catalogue(context.env.tool_entries, query)
    return ok(call, changed=False, content={"hits": [_tool_search_hit(entry) for entry in hits], "available": True})


def _tool_search_hit(entry: ToolCatalogueEntry) -> dict[str, object]:
    """Project one catalogue entry without schema, plugin ids, or provider internals."""
    return {
        "binding": {
            "provider_name": entry["provider_name"],
            "tool_name": entry["tool_name"],
        },
        "label": entry["tool_label"],
        "description": entry["description"],
    }


def inspect_tool(call: ToolCall, context: ToolContext) -> ToolResult:
    """Return one exact tool's model-safe schema from this run's snapshot."""
    provider_name = require_str(call["arguments"], "provider_name")
    tool_name = require_str(call["arguments"], "tool_name")
    if provider_name is None or tool_name is None:
        return error(call, "INVALID_ARGUMENT", "provider_name and tool_name are required")
    if not context.env.tools_available:
        return ok(call, changed=False, content={"available": False})
    entry = find_tool_entry(
        context.env.tool_entries,
        provider_name=provider_name,
        tool_name=tool_name,
    )
    if entry is None:
        return error(call, "UNKNOWN_TOOL", f"Tool {provider_name}/{tool_name} is not in this run's tool snapshot")
    content: dict[str, object] = {
        "available": True,
        "binding": {"provider_name": provider_name, "tool_name": tool_name},
        "provider_type": entry["provider_type"],
        "tool_label": entry["tool_label"],
        "description": entry["description"],
    }
    if "parameters" in entry:
        content["parameters"] = entry["parameters"]
    if "output_names" in entry:
        content["output_names"] = entry["output_names"]
    return ok(call, changed=False, content=json.loads(json.dumps(content, ensure_ascii=False)))
