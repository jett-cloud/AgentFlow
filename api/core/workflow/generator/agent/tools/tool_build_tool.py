"""Dedicated Tool-node builder: compile without writing, commit is the only writer.

``compile_build_tool_node`` resolves an exact catalogue entry, builds a
``VariableRegistry`` from the frozen candidate graph (plus pending plan nodes),
and calls ``compile_tool_node_config`` with that registry. Iteration ``item``
follows ``iterator_input_type`` (pending ``BuildIterationArgs.iterator_input_type``),
matching ``iteration_scope_declarations``. It must not rebind
``context.state.graph``. Generic ``build_node`` must not compile Tool nodes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from core.workflow.generator.agent.tools.tool_context import ToolContext
from core.workflow.generator.agent.tools.tool_mutate import (
    _BUILD_MODES,
    _ancestor_ids_from_parent,
    _build_node_content,
    _existing_parent,
    _node_config,
    _node_config_error,
    _parent_allowed,
    _resolve_parent,
    _resolve_title,
    _snapshot_membership_error,
)
from core.workflow.generator.agent.tools.tool_results import error, ok
from core.workflow.generator.agent.types import ToolCall, ToolResult
from core.workflow.generator.compiler.intents.build_contracts import BuildToolNodeArgs
from core.workflow.generator.compiler.intents.tool_intent import (
    ToolArgument,
    ToolInvocationIntent,
    ToolNodeBuildIntent,
    VariableToolArgument,
)
from core.workflow.generator.compiler.tool_parameter_normalize import ToolNodeConfigError, compile_tool_node_config
from core.workflow.generator.graph.graph_ops import find_node, upsert_node
from core.workflow.generator.graph.id_policy import validate_mutation_node_id
from core.workflow.generator.resources.tool_catalogue import ToolCatalogueEntry, find_tool_entry
from core.workflow.generator.variables.variable_references import VariableReferences
from core.workflow.generator.variables.variable_registry import (
    VariableDeclaration,
    VariableReferrer,
    VariableRegistry,
    VariableResolutionError,
)
from core.workflow.generator.variables.variable_types import array_item_type

logger = logging.getLogger(__name__)

_CONTAINER_TYPES = frozenset({"iteration", "loop"})
_FILE_PARAM_TYPES = frozenset({"file", "files", "system-files"})


@dataclass(frozen=True)
class CompiledToolNode:
    """Validated ``build_tool_node`` work that has not been written yet."""

    call: ToolCall
    node_id: str
    title: str
    desc: str
    config: dict[str, Any]
    parent: str | None
    mode: str
    old_config: dict[str, Any]
    old_parent: str | None


def compile_build_tool_node(call: ToolCall, context: ToolContext) -> CompiledToolNode | ToolResult:
    """Validate arguments and compile Tool config without mutating the graph."""
    try:
        parsed = BuildToolNodeArgs.model_validate(call["arguments"])
    except ValidationError as exc:
        return error(call, "INVALID_ARGUMENT", _args_validation_detail(exc))

    mode = parsed.mode
    if mode not in _BUILD_MODES:
        return error(call, "INVALID_ARGUMENT", "mode must be create, update, or replace")
    try:
        node_id = validate_mutation_node_id(parsed.id)
    except ValueError as exc:
        return error(call, "INVALID_NODE_ID", str(exc))

    existing = find_node(context.state.graph, node_id)
    if mode == "create" and existing is not None:
        return error(call, "NODE_EXISTS", f"Node {node_id!r} already exists")
    if mode in {"update", "replace"} and existing is None:
        return error(call, "NODE_NOT_FOUND", f"Node {node_id!r} does not exist")
    if mode == "create" and not (parsed.title or "").strip():
        return error(call, "INVALID_ARGUMENT", "title is required when creating a node")
    if mode == "update" and existing is not None and str(existing["data"].get("type") or "") != "tool":
        return error(call, "INVALID_ARGUMENT", "update requires an existing Tool node")
    if mode == "replace" and existing is not None and str(existing["data"].get("type") or "") == "tool":
        return error(call, "TYPE_UNCHANGED_USE_UPDATE", "replace requires a different type; use update")

    parent, parent_error = _resolve_parent(mode, call["arguments"], existing)
    if parent_error is not None:
        return error(call, parent_error, "parent is invalid")
    if parent is not None and not _parent_allowed(parent, node_id, context):
        return error(call, "INVALID_PARENT", f"Parent {parent!r} is not an existing container")

    title = _resolve_title(mode, call["arguments"], existing)
    desc = str(existing["data"].get("desc") or "") if existing is not None else ""
    old_config = _node_config(existing) if existing is not None else {}
    old_parent = _existing_parent(existing)

    if not context.env.tools_available:
        return error(call, "CAPABILITY_UNAVAILABLE", "Tool catalogue is unavailable")

    intent = ToolNodeBuildIntent(binding=parsed.tool, arguments=parsed.arguments)
    entry = find_tool_entry(
        context.env.tool_entries,
        provider_name=intent.binding.provider_name,
        tool_name=intent.binding.tool_name,
    )
    if entry is None:
        return error(call, "UNKNOWN_TOOL", "Tool binding is not present in the current catalogue")

    schema_error = _typed_file_schema_error(call, intent, entry, context, node_id=node_id)
    if schema_error is not None:
        return schema_error

    registry = _variable_registry_for_tool(
        context,
        referrer_id=node_id,
        parent=parent,
        arguments=intent.arguments,
    )
    invocation = ToolInvocationIntent(binding=intent.binding, arguments=intent.arguments)
    try:
        config = compile_tool_node_config(
            invocation=invocation,
            entry=entry,
            variable_registry=registry,
            referrer_id=node_id,
            existing_config=old_config if existing is not None else None,
        )
    except ToolNodeConfigError as exc:
        cause = _variable_resolution_cause(exc.__cause__, registry)
        return error(call, exc.code, exc.detail, cause=cause)
    except Exception:
        logger.exception("Workflow agent: tool compiler failed for %s", node_id)
        return error(call, "CAPABILITY_UNAVAILABLE", "Tool compiler failed")

    membership_error = _snapshot_membership_error(call, context, config)
    if membership_error is not None:
        return membership_error
    config_error = _node_config_error(call, node_id=node_id, node_type="tool", title=title, config=config)
    if config_error is not None:
        return config_error

    return CompiledToolNode(
        call=call,
        node_id=node_id,
        title=title,
        desc=desc,
        config=config,
        parent=parent,
        mode=str(mode),
        old_config=old_config,
        old_parent=old_parent,
    )


def commit_build_tool_node(compiled: CompiledToolNode, context: ToolContext) -> ToolResult:
    """Write a compiled Tool node onto ``context.state.graph``."""
    context.state.graph = upsert_node(
        context.state.graph,
        node_id=compiled.node_id,
        node_type="tool",
        title=compiled.title,
        desc=compiled.desc,
        config=compiled.config,
        parent=compiled.parent,
    )
    content = _build_node_content(
        node_id=compiled.node_id,
        node_type="tool",
        title=compiled.title,
        parent=compiled.parent,
        mode=compiled.mode,
        old_config=compiled.old_config,
        new_config=compiled.config,
        old_parent=compiled.old_parent,
        edges=context.state.graph["edges"],
    )
    return ok(compiled.call, changed=True, content=content)


def build_tool_node(call: ToolCall, context: ToolContext) -> ToolResult:
    compiled = compile_build_tool_node(call, context)
    return commit_build_tool_node(compiled, context) if isinstance(compiled, CompiledToolNode) else compiled


def _args_validation_detail(exc: ValidationError) -> str:
    first = exc.errors(include_input=False)[0]
    path = ".".join(str(part) for part in first.get("loc", ()))
    message = str(first.get("msg") or "invalid value")
    return f"{path}: {message}" if path else message


def _variable_resolution_cause(
    underlying: BaseException | None,
    registry: VariableRegistry,
) -> dict[str, object] | None:
    if not isinstance(underlying, VariableResolutionError):
        return None
    cause: dict[str, object] = {
        "error_code": underlying.code,
        "error": underlying.detail,
        "selector": list(underlying.selector),
    }
    if underlying.code == "UNKNOWN_OUTPUT" and underlying.selector:
        cause["available_outputs"] = list(registry.outputs_for(underlying.selector[0])[:50])
    return cause


def _typed_file_schema_error(
    call: ToolCall,
    intent: ToolNodeBuildIntent,
    entry: ToolCatalogueEntry,
    context: ToolContext,
    *,
    node_id: str,
) -> ToolResult | None:
    """Names-only upstream Tool outputs cannot prove file/array[file] compatibility."""
    specs = {spec["name"]: spec for spec in entry.get("parameters") or ()}
    nodes_by_id = _graph_nodes_by_id(context)
    pending_by_id = {pending.id: pending for pending in context.state.pending_plan_nodes if pending.id != node_id}
    for name, argument in intent.arguments.items():
        spec = specs.get(name)
        if spec is None or spec["type"] not in _FILE_PARAM_TYPES:
            continue
        if not isinstance(argument, VariableToolArgument):
            continue
        source_id = argument.selector[0]
        source = nodes_by_id.get(source_id)
        pending = pending_by_id.get(source_id)
        provider = ""
        tool_name = ""
        if source is not None and str((source.get("data") or {}).get("type") or "") == "tool":
            data = source.get("data") or {}
            provider = str(data.get("provider_id") or data.get("provider_name") or "")
            tool_name = str(data.get("tool_name") or "")
        elif pending is not None and pending.type == "tool":
            continue
        if not provider or not tool_name:
            continue
        source_entry = find_tool_entry(context.env.tool_entries, provider_name=provider, tool_name=tool_name)
        if source_entry is None:
            continue
        outputs = source_entry.get("outputs")
        if outputs:
            continue
        return error(
            call,
            "TOOL_OUTPUT_SCHEMA_UNAVAILABLE",
            f"Tool {provider}/{tool_name} does not expose typed outputs for a file argument",
        )
    return None


def _variable_registry_for_tool(
    context: ToolContext,
    *,
    referrer_id: str,
    parent: str | None,
    arguments: dict[str, ToolArgument],
) -> VariableRegistry:
    nodes_by_id = _graph_nodes_by_id(context)
    layers = _producer_layers(context.state.graph)
    pending_parent_by_id = {pending.id: pending.parent for pending in context.state.pending_plan_nodes}
    declarations: list[VariableDeclaration] = []
    known: set[str] = set(nodes_by_id)
    referrer_layer = max(layers.values(), default=-1) + 1
    if referrer_id in layers:
        referrer_layer = max(referrer_layer, layers[referrer_id] + 1)
    else:
        referrer_layer = max(referrer_layer, 1)

    for node_id, node in nodes_by_id.items():
        if node_id == referrer_id:
            continue
        known.add(node_id)
        producer_layer = layers.get(node_id, 0)
        owner = _owner_container_id(node_id, nodes_by_id, pending_parent_by_id)
        declarations.extend(
            _declarations_for_graph_node(
                node,
                producer_layer=producer_layer,
                owner_container_id=owner,
                tool_entries=context.env.tool_entries,
            )
        )

    for pending in context.state.pending_plan_nodes:
        if pending.id == referrer_id:
            continue
        known.add(pending.id)
        if pending.type == "iteration":
            declarations.extend(
                _iteration_scope_declarations(
                    pending.id,
                    _iteration_item_type(pending.iterator_input_type),
                    producer_layer=0,
                )
            )
        for output in pending.provisional_outputs:
            declarations.append(
                VariableDeclaration(
                    selector=(pending.id, output),
                    value_type="string",
                    owner_container_id=None,
                    producer_layer=0,
                    guaranteed=True,
                )
            )

    for argument in arguments.values():
        if not isinstance(argument, VariableToolArgument) or len(argument.selector) < 3:
            continue
        source_id, scope = argument.selector[0], argument.selector[1]
        if scope not in {"item", "index"}:
            continue
        source = nodes_by_id.get(source_id)
        pending_source = next((item for item in context.state.pending_plan_nodes if item.id == source_id), None)
        is_iteration = False
        if source is not None:
            is_iteration = str((source.get("data") or {}).get("type") or "") == "iteration"
        elif pending_source is not None:
            is_iteration = pending_source.type == "iteration"
        if not is_iteration:
            continue
        if source is not None:
            item_type = _graph_iteration_item_type(source)
        else:
            item_type = _iteration_item_type(pending_source.iterator_input_type if pending_source is not None else None)
        declarations.append(
            VariableDeclaration(
                selector=tuple(argument.selector),
                value_type=item_type if scope == "item" else "number",
                owner_container_id=source_id,
                producer_layer=layers.get(source_id, 0),
                guaranteed=True,
            )
        )

    ancestors = tuple(
        sorted(
            _ancestor_ids_from_parent(
                parent,
                {key: dict(value) for key, value in nodes_by_id.items()},
                pending_parent_by_id=pending_parent_by_id,
            )
        )
    )
    referrer = VariableReferrer(
        node_id=referrer_id,
        layer=referrer_layer,
        ancestor_container_ids=ancestors,
    )
    return VariableRegistry(declarations, referrers=(referrer,), known_node_ids=frozenset(known))


def _graph_nodes_by_id(context: ToolContext) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    for node in context.state.graph["nodes"]:
        node_id = node.get("id")
        if isinstance(node_id, str) and node_id:
            nodes[node_id] = dict(node)
    return nodes


def _producer_layers(graph: dict[str, Any]) -> dict[str, int]:
    nodes = [str(node["id"]) for node in graph["nodes"] if isinstance(node.get("id"), str)]
    incoming: dict[str, int] = dict.fromkeys(nodes, 0)
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for edge in graph.get("edges") or []:
        source, target = edge.get("source"), edge.get("target")
        if source in incoming and target in incoming:
            outgoing[str(source)].append(str(target))
            incoming[str(target)] += 1
    layers = dict.fromkeys(nodes, 0)
    ready = [node_id for node_id, count in incoming.items() if count == 0]
    while ready:
        current = ready.pop()
        for successor in outgoing[current]:
            layers[successor] = max(layers[successor], layers[current] + 1)
            incoming[successor] -= 1
            if incoming[successor] == 0:
                ready.append(successor)
    return layers


def _owner_container_id(
    node_id: str,
    nodes_by_id: dict[str, dict[str, Any]],
    pending_parent_by_id: dict[str, str | None],
) -> str | None:
    node = nodes_by_id.get(node_id)
    parent: str | None = None
    if node is not None:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        raw = node.get("parentId") or (data.get("parentId") if isinstance(data, dict) else None)
        parent = raw if isinstance(raw, str) and raw else None
        node_type = str((data or {}).get("type") or "")
        if node_type in _CONTAINER_TYPES:
            return node_id
    else:
        parent = pending_parent_by_id.get(node_id)
    return parent or None


def _declarations_for_graph_node(
    node: dict[str, Any],
    *,
    producer_layer: int,
    owner_container_id: str | None,
    tool_entries: list[ToolCatalogueEntry],
) -> list[VariableDeclaration]:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    node_id = str(node.get("id") or "")
    node_type = str((data or {}).get("type") or "")
    declarations: list[VariableDeclaration] = []
    if node_type == "tool":
        provider = str((data or {}).get("provider_id") or (data or {}).get("provider_name") or "")
        tool_name = str((data or {}).get("tool_name") or "")
        entry = find_tool_entry(tool_entries, provider_name=provider, tool_name=tool_name)
        outputs = entry.get("outputs") if entry is not None else None
        if outputs:
            for spec in outputs:
                declarations.append(
                    VariableDeclaration(
                        selector=(node_id, spec["name"]),
                        value_type=spec["type"],
                        owner_container_id=owner_container_id if owner_container_id != node_id else None,
                        producer_layer=producer_layer,
                        guaranteed=True,
                    )
                )
        return declarations
    if node_type == "iteration":
        declarations.extend(
            _iteration_scope_declarations(
                node_id,
                _graph_iteration_item_type(node),
                producer_layer=producer_layer,
            )
        )
    if node_type == "loop":
        owner_container_id = node_id
    names = VariableReferences._declared_outputs(node)
    for name in names:
        schema = VariableReferences._declared_output_schema(node, name)
        raw_type = str(schema.get("type") or "string")
        value_type = "array[file]" if raw_type in {"arrayFile", "array[file]", "file-list"} else raw_type
        if value_type == "file-list":
            value_type = "array[file]"
        owner = node_id if node_type in _CONTAINER_TYPES else owner_container_id
        if node_type in _CONTAINER_TYPES and name in {"item", "index"}:
            owner = node_id
        elif node_type in _CONTAINER_TYPES:
            owner = None
        declarations.append(
            VariableDeclaration(
                selector=(node_id, name),
                value_type=value_type if value_type != "arrayFile" else "array[file]",
                owner_container_id=owner,
                producer_layer=producer_layer,
                guaranteed=True,
            )
        )
    return declarations


def _iteration_item_type(iterator_input_type: str | None) -> str:
    try:
        return array_item_type(iterator_input_type or "array")
    except ValueError:
        return "object"


def _graph_iteration_item_type(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    raw = data.get("iterator_input_type") if isinstance(data, dict) else None
    return _iteration_item_type(raw if isinstance(raw, str) else None)


def _iteration_scope_declarations(
    container_id: str,
    item_type: str,
    *,
    producer_layer: int,
) -> list[VariableDeclaration]:
    return [
        VariableDeclaration(
            selector=(container_id, "item"),
            value_type=item_type,
            owner_container_id=container_id,
            producer_layer=producer_layer,
            guaranteed=True,
        ),
        VariableDeclaration(
            selector=(container_id, "index"),
            value_type="number",
            owner_container_id=container_id,
            producer_layer=producer_layer,
            guaranteed=True,
        ),
    ]
