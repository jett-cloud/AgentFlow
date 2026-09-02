"""Graph-mutating tools: build_node, delete, connect, disconnect.

``compile_build_node`` builds config without writing the graph;
``commit_build_node`` is the writer. ``dispatch("build_node")`` still runs both
in order. Parallel create only overlaps compile.
"""

import logging
from dataclasses import dataclass
from typing import Any

from core.workflow.generator.agent.graph_ops import (
    connect as connect_edge,
)
from core.workflow.generator.agent.graph_ops import (
    delete_node as remove_node,
)
from core.workflow.generator.agent.graph_ops import (
    disconnect as disconnect_edge,
)
from core.workflow.generator.agent.graph_ops import (
    find_node,
    upsert_node,
)
from core.workflow.generator.agent.tool_context import ToolContext
from core.workflow.generator.agent.tool_results import error, ok, require_str
from core.workflow.generator.agent.types import MinimalGraphNodeDict, ToolCall, ToolResult
from core.workflow.generator.node_builder import build_single_node
from core.workflow.generator.variable_references import collect_references

logger = logging.getLogger(__name__)

_CONTAINER_TYPES = frozenset({"iteration", "loop"})
_BUILD_MODES = frozenset({"create", "update", "replace"})
_EFFECT_KEYS: dict[str, str] = {
    "model": "model",
    "prompt": "prompt",
    "prompt_template": "prompt",
    "answer": "prompt",
    "template": "prompt",
    "agent_task": "prompt",
    "structured_output": "structured_output",
    "dataset_ids": "dataset_binding",
    "provider_id": "tool_binding",
    "provider_name": "tool_binding",
    "tool_name": "tool_binding",
    "variables": "variables",
}


@dataclass(frozen=True)
class CompiledBuildNode:
    """Validated ``build_node`` work that has not been written to the graph yet.

    ``compile_build_node`` may call the node-builder LLM. It must not rebind
    ``context.state.graph``. ``commit_build_node`` is the only writer. ``dispatch``
    still runs compile then commit on one call; later parallel create only
    overlaps compile.
    """

    call: ToolCall
    node_id: str
    node_type: str
    title: str
    desc: str
    config: dict[str, Any]
    parent: str | None
    mode: str
    old_config: dict[str, Any]
    old_parent: str | None


def compile_build_node(call: ToolCall, context: ToolContext) -> CompiledBuildNode | ToolResult:
    """Validate arguments and build node config without mutating ``context.state.graph``."""
    arguments = call["arguments"]
    mode = arguments.get("mode")
    if mode not in _BUILD_MODES:
        return error(call, "INVALID_ARGUMENT", "mode must be create, update, or replace")
    node_id = require_str(arguments, "id")
    purpose = arguments.get("purpose")
    if node_id is None or not isinstance(purpose, str) or not purpose.strip():
        return error(call, "INVALID_ARGUMENT", "id and purpose are required")
    if mode == "update" and "type" in arguments:
        return error(call, "INVALID_ARGUMENT", "update must not include type; use replace to change type")

    existing = find_node(context.state.graph, node_id)
    if mode == "create" and existing is not None:
        return error(call, "NODE_EXISTS", f"Node {node_id!r} already exists")
    if mode in {"update", "replace"} and existing is None:
        return error(call, "NODE_NOT_FOUND", f"Node {node_id!r} does not exist")

    requested_type = arguments.get("type")
    if mode in {"create", "replace"}:
        if not isinstance(requested_type, str) or not requested_type:
            return error(call, "INVALID_ARGUMENT", "type is required")
        node_type = requested_type
    else:
        assert existing is not None
        node_type = str(existing["data"].get("type") or "")

    if mode == "replace" and existing is not None and str(existing["data"].get("type") or "") == node_type:
        return error(call, "TYPE_UNCHANGED_USE_UPDATE", "replace requires a different type; use update")

    if mode == "create" and not require_str(arguments, "title"):
        return error(call, "INVALID_ARGUMENT", "title is required when creating a node")

    parent, parent_error = _resolve_parent(mode, arguments, existing)
    if parent_error is not None:
        return error(call, parent_error, "parent is invalid")
    if parent is not None:
        parent_node = find_node(context.state.graph, parent)
        if parent_node is None or str(parent_node["data"].get("type") or "") not in _CONTAINER_TYPES:
            return error(call, "INVALID_PARENT", f"Parent {parent!r} is not an existing container")

    title = _resolve_title(mode, arguments, existing)
    desc = str(existing["data"].get("desc") or "") if existing is not None else ""
    old_config = _node_config(existing) if existing is not None else {}
    old_parent = _existing_parent(existing)

    # Builder/LLM failures must bounce as a ToolResult; never leave a half-written node.
    try:
        config = build_single_node(
            client=context.env.llm_client,
            request=context.env.builder_input,
            node_id=node_id,
            node_type=node_type,
            title=title,
            purpose=purpose,
            existing_node=dict(existing) if existing is not None else None,
        )
    except Exception:
        logger.exception("Workflow agent: node builder failed for %s", node_id)
        return error(call, "CAPABILITY_UNAVAILABLE", "Node builder failed")

    membership_error = _snapshot_membership_error(call, context, config)
    if membership_error is not None:
        return membership_error

    return CompiledBuildNode(
        call=call,
        node_id=node_id,
        node_type=node_type,
        title=title,
        desc=desc,
        config=config,
        parent=parent,
        mode=str(mode),
        old_config=old_config,
        old_parent=old_parent,
    )


def commit_build_node(compiled: CompiledBuildNode, context: ToolContext) -> ToolResult:
    """Write a compiled ``build_node`` onto ``context.state.graph``."""
    context.state.graph = upsert_node(
        context.state.graph,
        node_id=compiled.node_id,
        node_type=compiled.node_type,
        title=compiled.title,
        desc=compiled.desc,
        config=compiled.config,
        parent=compiled.parent,
    )
    content = _build_node_content(
        node_id=compiled.node_id,
        node_type=compiled.node_type,
        title=compiled.title,
        parent=compiled.parent,
        mode=compiled.mode,
        old_config=compiled.old_config,
        new_config=compiled.config,
        old_parent=compiled.old_parent,
        edges=context.state.graph["edges"],
    )
    return ok(compiled.call, changed=True, content=content)


def build_node(call: ToolCall, context: ToolContext) -> ToolResult:
    compiled = compile_build_node(call, context)
    if isinstance(compiled, CompiledBuildNode):
        return commit_build_node(compiled, context)
    return compiled


def delete_node(call: ToolCall, context: ToolContext) -> ToolResult:
    node_id = require_str(call["arguments"], "node_id")
    if node_id is None:
        return error(call, "INVALID_ARGUMENT", "node_id is required")
    if find_node(context.state.graph, node_id) is None:
        return ok(call, changed=False, content={"reason": "node_not_present"})
    context.state.graph = remove_node(context.state.graph, node_id)
    return ok(call, changed=True, content={"id": node_id})


def connect(call: ToolCall, context: ToolContext) -> ToolResult:
    source = require_str(call["arguments"], "source")
    target = require_str(call["arguments"], "target")
    if source is None or target is None:
        return error(call, "INVALID_ARGUMENT", "source and target are required")
    if find_node(context.state.graph, source) is None or find_node(context.state.graph, target) is None:
        return error(call, "NODE_NOT_FOUND", "Both endpoints must exist")
    handle = call["arguments"].get("source_handle")
    source_handle = handle if isinstance(handle, str) else None
    before = len(context.state.graph["edges"])
    context.state.graph = connect_edge(context.state.graph, source=source, target=target, source_handle=source_handle)
    if len(context.state.graph["edges"]) == before:
        return ok(call, changed=False, content={"reason": "edge_already_exists"})
    content: dict[str, object] = {"source": source, "target": target}
    if source_handle:
        content["source_handle"] = source_handle
    return ok(call, changed=True, content=content)


def disconnect(call: ToolCall, context: ToolContext) -> ToolResult:
    source = require_str(call["arguments"], "source")
    target = require_str(call["arguments"], "target")
    if source is None or target is None:
        return error(call, "INVALID_ARGUMENT", "source and target are required")
    handle = call["arguments"].get("source_handle")
    source_handle = handle if isinstance(handle, str) else None
    graph, match_count = disconnect_edge(context.state.graph, source=source, target=target, source_handle=source_handle)
    if source_handle in (None, "") and match_count > 1:
        return error(call, "AMBIGUOUS_EDGE", "Pass source_handle to choose which edge to remove")
    if match_count == 0:
        return ok(call, changed=False, content={"reason": "edge_not_present"})
    context.state.graph = graph
    return ok(call, changed=True, content={"source": source, "target": target})


def _resolve_parent(
    mode: str,
    arguments: dict[str, Any],
    existing: MinimalGraphNodeDict | None,
) -> tuple[str | None, str | None]:
    if "parent" not in arguments:
        if mode == "create" or existing is None:
            return None, None
        return _existing_parent(existing), None
    parent = arguments.get("parent")
    if parent is None or parent == "":
        return None, None
    if not isinstance(parent, str):
        return None, "INVALID_ARGUMENT"
    return parent, None


def _resolve_title(mode: str, arguments: dict[str, Any], existing: MinimalGraphNodeDict | None) -> str:
    title = arguments.get("title")
    if isinstance(title, str) and title:
        return title
    if existing is not None:
        return str(existing["data"].get("title") or existing["id"])
    return str(arguments.get("id") or "")


def _existing_parent(existing: MinimalGraphNodeDict | None) -> str | None:
    if existing is None:
        return None
    parent = existing.get("parentId") or existing["data"].get("parentId")
    if isinstance(parent, str) and parent:
        return parent
    return None


def _node_config(node: MinimalGraphNodeDict) -> dict[str, Any]:
    return {key: value for key, value in node["data"].items() if key not in {"type", "title", "desc", "parentId"}}


def _build_node_content(
    *,
    node_id: str,
    node_type: str,
    title: str,
    parent: str | None,
    mode: str,
    old_config: dict[str, Any],
    new_config: dict[str, Any],
    old_parent: str | None,
    edges: list[Any],
) -> dict[str, object]:
    content: dict[str, object] = {
        "id": node_id,
        "type": node_type,
        "title": title,
        "mode": mode,
        "effects": _config_effects(
            old_config,
            new_config,
            type_changed=mode == "replace",
            parent_changed=old_parent != parent,
        ),
        "bindings": sorted(f"{source_id}.{var}" for source_id, var in collect_references(new_config)),
        "resources": _collect_resources(new_config),
    }
    if parent:
        content["parent"] = parent
    if mode == "replace":
        content["preserved_edge_count"] = sum(
            1 for edge in edges if edge.get("source") == node_id or edge.get("target") == node_id
        )
        content["requires_revalidation"] = True
    return content


def _config_effects(
    old_config: dict[str, Any],
    new_config: dict[str, Any],
    *,
    type_changed: bool,
    parent_changed: bool,
) -> list[str]:
    effects: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if name not in seen:
            seen.add(name)
            effects.append(name)

    if type_changed:
        add("type")
    if parent_changed:
        add("parent")
    for key in sorted(set(old_config) | set(new_config)):
        if old_config.get(key) == new_config.get(key):
            continue
        mapped = _EFFECT_KEYS.get(key)
        if mapped:
            add(mapped)
    return effects


def _snapshot_membership_error(call: ToolCall, context: ToolContext, config: dict[str, Any]) -> ToolResult | None:
    """Reject builder config that names a resource outside this run's snapshot.

    ``available=false`` / ``installed_*=None`` skips that side. An empty set is
    "the tenant has none", so every id is unknown. Cross-namespace reuse uses
    the same ``UNKNOWN_DATASET`` / ``UNKNOWN_TOOL`` codes as the field kind.
    """
    dataset_error = _unknown_dataset_error(call, context, config)
    if dataset_error is not None:
        return dataset_error
    return _unknown_tool_error(call, context, config)


def _unknown_dataset_error(call: ToolCall, context: ToolContext, config: dict[str, Any]) -> ToolResult | None:
    if not context.env.knowledge_available or context.env.installed_dataset_ids is None:
        return None
    dataset_ids = config.get("dataset_ids")
    if not isinstance(dataset_ids, list):
        return None
    unknown = [item for item in dataset_ids if isinstance(item, str) and item not in context.env.installed_dataset_ids]
    if not unknown:
        return None
    return error(
        call,
        "UNKNOWN_DATASET",
        f"Dataset {unknown[0]!r} is not in this run's knowledge snapshot",
    )


def _unknown_tool_error(call: ToolCall, context: ToolContext, config: dict[str, Any]) -> ToolResult | None:
    if not context.env.tools_available or context.env.installed_tools is None:
        return None
    provider = config.get("provider_id") or config.get("provider_name")
    tool_name = config.get("tool_name")
    if isinstance(provider, str) and isinstance(tool_name, str) and provider and tool_name:
        if (provider, tool_name) not in context.env.installed_tools:
            return error(
                call,
                "UNKNOWN_TOOL",
                f"Tool {provider}/{tool_name} is not in this run's tool snapshot",
            )
    return _unknown_dify_tools_error(call, context, config)


def _unknown_dify_tools_error(call: ToolCall, context: ToolContext, config: dict[str, Any]) -> ToolResult | None:
    dify_tools = config.get("dify_tools")
    if not isinstance(dify_tools, list) or context.env.installed_tools is None:
        return None
    providers = {item[0] for item in context.env.installed_tools}
    for item in dify_tools:
        if not isinstance(item, dict):
            continue
        provider = item.get("provider_id") or item.get("provider_name") or item.get("provider")
        if not isinstance(provider, str) or not provider:
            continue
        tool_name = item.get("tool_name")
        if tool_name is None or tool_name == "":
            if provider not in providers:
                return error(
                    call,
                    "UNKNOWN_TOOL",
                    f"Tool {provider} is not in this run's tool snapshot",
                )
            continue
        if not isinstance(tool_name, str):
            continue
        if (provider, tool_name) not in context.env.installed_tools:
            return error(
                call,
                "UNKNOWN_TOOL",
                f"Tool {provider}/{tool_name} is not in this run's tool snapshot",
            )
    return None


def _collect_resources(config: dict[str, Any]) -> list[str]:
    resources: list[str] = []
    dataset_ids = config.get("dataset_ids")
    if isinstance(dataset_ids, list):
        resources.extend(f"dataset:{item}" for item in dataset_ids if isinstance(item, str))
    provider = config.get("provider_name") or config.get("provider_id")
    tool_name = config.get("tool_name")
    if isinstance(provider, str) and isinstance(tool_name, str) and provider and tool_name:
        resources.append(f"tool:{provider}/{tool_name}")
    return resources
