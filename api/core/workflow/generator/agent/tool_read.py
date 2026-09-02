"""Read and search tools: graph, node, schema, catalogues."""

from typing import cast

from core.workflow.generator.agent.graph_ops import read_node_view, render_compact_graph
from core.workflow.generator.agent.tool_context import ToolContext
from core.workflow.generator.agent.tool_results import error, ok, require_str
from core.workflow.generator.agent.types import ToolCall, ToolResult
from core.workflow.generator.prompts.builder_prompts import get_node_config_snippet
from core.workflow.generator.resource_search import search_knowledge
from core.workflow.generator.resource_search import search_tools as search_tool_catalogue


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


def search_datasets(call: ToolCall, context: ToolContext) -> ToolResult:
    query = call["arguments"].get("query")
    if not isinstance(query, str):
        return error(call, "INVALID_ARGUMENT", "query is required")
    if not context.env.knowledge_available:
        return ok(call, changed=False, content={"hits": [], "available": False})
    hits = search_knowledge(context.env.knowledge_entries, query)
    return ok(call, changed=False, content={"hits": list(hits), "available": True})


def search_tools(call: ToolCall, context: ToolContext) -> ToolResult:
    """Search this run's catalogue snapshot; uninstalled plugins are already dropped."""
    query = call["arguments"].get("query")
    if not isinstance(query, str):
        return error(call, "INVALID_ARGUMENT", "query is required")
    if not context.env.tools_available:
        return ok(call, changed=False, content={"hits": [], "available": False})
    hits = search_tool_catalogue(context.env.tool_entries, query)
    return ok(call, changed=False, content={"hits": list(hits), "available": True})
