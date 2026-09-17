"""Dedicated Agent V2 builder: compile without writing, commit is the only writer.

``compile_build_agent_node`` resolves catalogue tools and datasets, builds a
``VariableRegistry`` from the frozen candidate graph, and calls
``compile_agent_node_config``. The compiled config includes a declarative
``assist_binding_manifest``; commit writes it with the node. It must not rebind
``context.state.graph`` or call ``hydrate_agent_bindings``. Generic
``build_node`` must not compile Agent nodes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from core.workflow.generator.agent.tools.tool_build_tool import _variable_registry_for_tool
from core.workflow.generator.agent.tools.tool_context import ToolContext
from core.workflow.generator.agent.tools.tool_mutate import (
    _BUILD_MODES,
    _apply_agent_binding_ids,
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
from core.workflow.generator.compiler.agent_knowledge import agent_knowledge_intent_dataset_ids
from core.workflow.generator.compiler.agent_node_compiler import AgentNodeConfigError, compile_agent_node_config
from core.workflow.generator.compiler.intents.agent_intent import (
    AgentBindingManifest,
    AgentNodeBuildIntent,
)
from core.workflow.generator.compiler.intents.build_contracts import BuildAgentNodeArgs
from core.workflow.generator.graph.graph_ops import find_node, upsert_node
from core.workflow.generator.graph.id_policy import validate_mutation_node_id
from core.workflow.generator.resources.model_catalogue import resolve_agent_model


@dataclass(frozen=True)
class CompiledAgentNode:
    """Validated ``build_agent_node`` work that has not been written yet."""

    call: ToolCall
    node_id: str
    title: str
    desc: str
    config: dict[str, Any]
    parent: str | None
    mode: str
    old_config: dict[str, Any]
    old_parent: str | None
    manifest: AgentBindingManifest


def compile_build_agent_node(call: ToolCall, context: ToolContext) -> CompiledAgentNode | ToolResult:
    """Validate arguments and compile Agent V2 config without mutating the graph."""
    try:
        parsed = BuildAgentNodeArgs.model_validate(call["arguments"])
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
    if mode == "update" and existing is not None and str(existing["data"].get("type") or "") != "agent":
        return error(call, "INVALID_ARGUMENT", "update requires an existing Agent node")
    if mode == "replace" and existing is not None and str(existing["data"].get("type") or "") == "agent":
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

    try:
        intent = AgentNodeBuildIntent(
            model=parsed.model,
            instruction=parsed.instruction,
            inputs=parsed.inputs,
            outputs=parsed.outputs,
            tools=parsed.tools,
            mcp_tools=parsed.mcp_tools,
            knowledge=parsed.knowledge,
        )
    except ValidationError as exc:
        return error(call, "INVALID_ARGUMENT", _args_validation_detail(exc))

    if not context.env.models_available:
        return error(call, "CAPABILITY_UNAVAILABLE", "Agent model catalogue is unavailable")
    if (
        resolve_agent_model(
            context.env.agent_model_entries,
            provider=intent.model.provider,
            name=intent.model.name,
        )
        is None
    ):
        return error(
            call,
            "UNKNOWN_MODEL",
            f"Model {intent.model.provider}/{intent.model.name} is not in this run's model snapshot",
        )

    if (intent.tools or intent.mcp_tools) and not context.env.tools_available:
        return error(call, "CAPABILITY_UNAVAILABLE", "Tool catalogue is unavailable")
    if intent.knowledge is not None and (
        not context.env.knowledge_available or context.env.installed_dataset_ids is None
    ):
        return error(call, "CAPABILITY_UNAVAILABLE", "Knowledge catalogue is unavailable")
    if intent.knowledge is not None:
        catalogue_dataset_ids = {entry["id"] for entry in context.env.knowledge_entries}
        unknown_dataset_ids = [
            dataset_id
            for dataset_id in agent_knowledge_intent_dataset_ids(intent.knowledge)
            if dataset_id not in catalogue_dataset_ids
        ]
        if unknown_dataset_ids:
            return error(
                call,
                "UNKNOWN_DATASET",
                f"Dataset {unknown_dataset_ids[0]!r} is not in this run's knowledge snapshot",
            )

    registry = _variable_registry_for_tool(
        context,
        referrer_id=node_id,
        parent=parent,
        arguments={},
    )
    try:
        config, manifest = compile_agent_node_config(
            intent=intent,
            tool_entries=context.env.tool_entries,
            knowledge_entries=context.env.knowledge_entries,
            variable_registry=registry,
            referrer_id=node_id,
            mode=str(mode),
            old_config=old_config,
        )
    except AgentNodeConfigError as exc:
        return error(call, exc.code, exc.detail)

    _apply_agent_binding_ids(mode=str(mode), config=config, old_config=old_config)
    membership_error = _snapshot_membership_error(call, context, config)
    if membership_error is not None:
        return membership_error
    config_error = _node_config_error(call, node_id=node_id, node_type="agent", title=title, config=config)
    if config_error is not None:
        return config_error

    return CompiledAgentNode(
        call=call,
        node_id=node_id,
        title=title,
        desc=desc,
        config=config,
        parent=parent,
        mode=str(mode),
        old_config=old_config,
        old_parent=old_parent,
        manifest=manifest,
    )


def commit_build_agent_node(compiled: CompiledAgentNode, context: ToolContext) -> ToolResult:
    """Write a compiled Agent node onto ``context.state.graph``."""
    context.state.graph = upsert_node(
        context.state.graph,
        node_id=compiled.node_id,
        node_type="agent",
        title=compiled.title,
        desc=compiled.desc,
        config=compiled.config,
        parent=compiled.parent,
    )
    content = _build_node_content(
        node_id=compiled.node_id,
        node_type="agent",
        title=compiled.title,
        parent=compiled.parent,
        mode=compiled.mode,
        old_config=compiled.old_config,
        new_config=compiled.config,
        old_parent=compiled.old_parent,
        edges=context.state.graph["edges"],
    )
    return ok(compiled.call, changed=True, content=content)


def build_agent_node(call: ToolCall, context: ToolContext) -> ToolResult:
    compiled = compile_build_agent_node(call, context)
    return commit_build_agent_node(compiled, context) if isinstance(compiled, CompiledAgentNode) else compiled


def _args_validation_detail(exc: ValidationError) -> str:
    first = exc.errors(include_input=False)[0]
    path = ".".join(str(part) for part in first.get("loc", ()))
    message = str(first.get("msg") or "invalid value")
    return f"{path}: {message}" if path else message
