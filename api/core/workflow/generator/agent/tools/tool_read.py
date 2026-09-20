"""Read and search tools: graph, node, schema, and bounded catalogue views."""

import json
from operator import itemgetter
from typing import cast

from core.workflow.generator.agent.tools.tool_context import ToolContext
from core.workflow.generator.agent.tools.tool_results import error, ok, require_str
from core.workflow.generator.agent.types import ToolCall, ToolResult
from core.workflow.generator.graph.graph_ops import read_node_view, render_compact_graph
from core.workflow.generator.prompts.builder_prompts import get_node_config_snippet
from core.workflow.generator.prompts.loader import node_config_snippets, registered_skill_names, skill_body
from core.workflow.generator.resources.resource_search import search_knowledge
from core.workflow.generator.resources.resource_search import search_tools as search_tool_catalogue
from core.workflow.generator.resources.tool_catalogue import ToolCatalogueEntry, find_tool_entry

_MAX_ACTIVE_SKILLS = 4
_MODEL_PAGE_SIZE = 12


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
    """Return known schema guidance or a recoverable error with supported types."""
    node_type = require_str(call["arguments"], "node_type")
    if node_type is None:
        return error(call, "INVALID_ARGUMENT", "node_type is required")
    snippet = get_node_config_snippet(node_type)
    if not snippet:
        return error(
            call,
            "INVALID_ARGUMENT",
            f"No node schema is available for {node_type!r}; choose an available type",
            cause={"available_types": sorted(key for key, value in node_config_snippets().items() if value)},
        )
    return ok(call, changed=False, content={"node_type": node_type, "snippet": snippet})


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
    """Expose bounded discovery and distinguish no match, empty, and unavailable.

    ``catalogue_count`` counts this run's complete tenant snapshot, not matches.
    Unknown counts remain null when loading failed; blank queries browse it.
    """
    query = call["arguments"].get("query")
    if not isinstance(query, str):
        return error(call, "INVALID_ARGUMENT", "query is required")
    if not context.env.knowledge_available:
        return ok(call, changed=False, content={"hits": [], "available": False, "catalogue_count": None})
    hits = search_knowledge(context.env.knowledge_entries, query)
    return ok(
        call,
        changed=False,
        content={"hits": list(hits), "available": True, "catalogue_count": len(context.env.knowledge_entries)},
    )


def search_tools(call: ToolCall, context: ToolContext) -> ToolResult:
    """Browse/search bounded summaries; catalogue_count distinguishes a keyword miss.

    Counts describe the run snapshot after provider filtering, not all installed
    plugins. A failed load has an unknown count, never a successful empty count.
    """
    query = call["arguments"].get("query")
    if not isinstance(query, str):
        return error(call, "INVALID_ARGUMENT", "query is required")
    if not context.env.tools_available:
        return ok(call, changed=False, content={"hits": [], "available": False, "catalogue_count": None})
    hits = search_tool_catalogue(context.env.tool_entries, query)
    return ok(
        call,
        changed=False,
        content={
            "hits": [_tool_search_hit(entry) for entry in hits],
            "available": True,
            "catalogue_count": len(context.env.tool_entries),
        },
    )


def list_models(call: ToolCall, context: ToolContext) -> ToolResult:
    """Page through the same credential-free model snapshot used by Agent builds.

    Explicit projection and copied feature lists keep observations detached from
    the snapshot. Pagination is stable within this run; no provider calls occur.
    """
    offset = call["arguments"].get("offset", 0)
    if type(offset) is not int or offset < 0:
        return error(call, "INVALID_ARGUMENT", "offset must be a non-negative integer")
    if not context.env.models_available:
        return ok(
            call,
            changed=False,
            content={
                "available": False,
                "hits": [],
                "catalogue_count": None,
                "next_offset": None,
            },
        )
    entries = sorted(context.env.agent_model_entries, key=itemgetter("provider", "name"))
    page = entries[offset : offset + _MODEL_PAGE_SIZE]
    next_offset = offset + len(page)
    return ok(
        call,
        changed=False,
        content={
            "available": True,
            "catalogue_count": len(entries),
            "next_offset": next_offset if next_offset < len(entries) else None,
            "hits": [
                {
                    "provider": entry["provider"],
                    "name": entry["name"],
                    "model_type": entry["model_type"],
                    "features": list(entry["features"]),
                }
                for entry in page
            ],
        },
    )


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
    if "outputs" in entry:
        content["outputs"] = entry["outputs"]
    return ok(call, changed=False, content=json.loads(json.dumps(content, ensure_ascii=False)))
