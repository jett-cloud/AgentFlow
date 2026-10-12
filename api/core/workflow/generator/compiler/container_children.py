"""Compile individual children deterministically; never commit graph state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from core.workflow.generator.compiler.agent_node_compiler import AgentNodeConfigError, compile_agent_node_config
from core.workflow.generator.compiler.container_scope import _resolution_cause
from core.workflow.generator.compiler.container_types import ChildCompileContext, CompiledChild, ContainerCompileError
from core.workflow.generator.compiler.intents.container_intent import (
    AgentContainerChildIntent,
    ContainerChildIntent,
    StandardContainerChildIntent,
    ToolContainerChildIntent,
)
from core.workflow.generator.compiler.intents.tool_intent import ToolInvocationIntent
from core.workflow.generator.compiler.node_compile_context import NodeCompileContext
from core.workflow.generator.compiler.node_intent_compiler import NodeIntentCompileError, compile_node_intent
from core.workflow.generator.compiler.tool_parameter_normalize import ToolNodeConfigError, compile_tool_node_config
from core.workflow.generator.graph.types import MinimalGraphNodeDict
from core.workflow.generator.resources.tool_catalogue import find_tool_entry
from core.workflow.generator.validation.intent_config_validator import validate_node_config_against_intent
from core.workflow.generator.validation.node_config_validator import (
    collect_generated_node_completeness_errors,
    collect_node_config_errors,
)
from core.workflow.generator.variables.variable_registry import VariableResolutionError


def compile_container_child(child: ContainerChildIntent, context: ChildCompileContext) -> CompiledChild:
    try:
        if child.kind == "tool":
            return compile_tool_child(child, context)
        if child.kind == "agent":
            return compile_agent_child(child, context)
        return compile_standard_child(child, context)
    except ContainerCompileError:
        raise
    except (ToolNodeConfigError, AgentNodeConfigError, VariableResolutionError) as exc:
        resolution = exc if isinstance(exc, VariableResolutionError) else exc.__cause__
        if isinstance(resolution, VariableResolutionError):
            code = resolution.code
            detail = resolution.detail
            cause = _resolution_cause(resolution, context.registry)
        else:
            code = str(getattr(exc, "code", "INVALID_NODE_CONFIG"))
            detail = str(getattr(exc, "detail", exc))
            cause = {"error_code": code, "error": detail}
        raise ContainerCompileError(
            code,
            detail,
            path=f"children.{child.ref}",
            child_ref=child.ref,
            cause=cause,
        ) from exc


def compile_tool_child(child: ToolContainerChildIntent, context: ChildCompileContext) -> CompiledChild:
    node_id = context.ref_map[child.ref]
    entry = find_tool_entry(
        list(context.tool_entries),
        provider_name=child.intent.binding.provider_name,
        tool_name=child.intent.binding.tool_name,
    )
    if entry is None:
        raise ContainerCompileError(
            "UNKNOWN_TOOL",
            "Tool binding is not present in the current catalogue",
            path=f"children.{child.ref}",
            child_ref=child.ref,
            cause={"error_code": "UNKNOWN_TOOL", "error": "unknown tool binding"},
        )
    invocation = ToolInvocationIntent(binding=child.intent.binding, arguments=child.intent.arguments)
    config = compile_tool_node_config(
        invocation=invocation,
        entry=entry,
        variable_registry=context.registry,
        referrer_id=node_id,
    )
    outputs = entry.get("outputs")
    if outputs:
        config["outputs"] = {spec["name"]: {"type": spec["type"]} for spec in outputs}
    return _child_node(
        child.ref, node_id, "tool", child.ref, config, context.container_id, in_iteration=context.in_iteration
    )


def compile_agent_child(child: AgentContainerChildIntent, context: ChildCompileContext) -> CompiledChild:
    node_id = context.ref_map[child.ref]
    config, _manifest = compile_agent_node_config(
        intent=child.intent,
        tool_entries=list(context.tool_entries),
        knowledge_entries=list(context.knowledge_entries),
        variable_registry=context.registry,
        referrer_id=node_id,
        mode="create",
        old_config=None,
    )
    return _child_node(
        child.ref, node_id, "agent", child.ref, config, context.container_id, in_iteration=context.in_iteration
    )


def compile_standard_child(child: StandardContainerChildIntent, context: ChildCompileContext) -> CompiledChild:
    node_id = context.ref_map[child.ref]
    if child.intent.structure is None:
        raise ContainerCompileError(
            "MISSING_NODE_STRUCTURE",
            f"container child type {child.node_type!r} requires typed structure",
            path=f"children.{child.ref}.intent.structure",
            child_ref=child.ref,
            cause={
                "error_code": "MISSING_NODE_STRUCTURE",
                "node_type": child.node_type,
                "surface": "container_child",
            },
        )
    return compile_typed_child(child, context)


def compile_typed_child(child: StandardContainerChildIntent, context: ChildCompileContext) -> CompiledChild:
    """Compile every ordinary child through the shared deterministic dispatcher."""
    node_id = context.ref_map[child.ref]
    try:
        config = compile_node_intent(
            intent=child.intent,
            base_config={},
            context=NodeCompileContext(
                node_id=node_id,
                surface="container_child",
                mode="create",
                variable_registry=context.registry,
                model_entries=context.model_entries,
                installed_dataset_ids=context.installed_dataset_ids,
                http_credential_reference_ids=context.http_credential_reference_ids,
                human_input_delivery_capabilities=context.human_input_delivery_capabilities,
                human_input_member_reference_ids=context.human_input_member_reference_ids,
            ),
        )
    except NodeIntentCompileError as exc:
        raise ContainerCompileError(
            exc.code,
            exc.detail,
            path=f"children.{child.ref}.intent.{exc.path}",
            child_ref=child.ref,
            cause=exc.cause,
        ) from exc
    _assert_node_config(node_id, child.node_type, child.ref, config)
    intent_issues = validate_node_config_against_intent(
        node_id=node_id,
        node_type=child.node_type,
        title=child.ref,
        intent=child.intent,
        config=config,
    )
    if intent_issues:
        issue = intent_issues[0]
        raise ContainerCompileError(
            issue.code,
            issue.detail,
            path=f"children.{child.ref}",
            child_ref=child.ref,
            cause=issue.cause(),
        )
    return _child_node(
        child.ref, node_id, child.node_type, child.ref, config, context.container_id, in_iteration=context.in_iteration
    )


def _child_node(
    ref: str,
    node_id: str,
    node_type: str,
    title: str,
    config: dict[str, Any],
    container_id: str,
    *,
    in_iteration: bool = False,
) -> CompiledChild:
    data = {key: value for key, value in config.items() if key not in {"type", "title", "desc", "parentId"}}
    marker = "isInIteration" if in_iteration else "isInLoop"
    node: MinimalGraphNodeDict = {
        "id": node_id,
        "parentId": container_id,
        "data": {
            "type": node_type,
            "title": title,
            "desc": "",
            "assist_ref": ref,
            marker: True,
            **data,
        },
    }
    return CompiledChild(ref=ref, node=node)


def _assert_node_config(
    node_id: str,
    node_type: str,
    ref: str,
    config: dict[str, Any],
) -> None:
    wrapped = {"id": node_id, "data": {"type": node_type, "title": ref, **config}}
    shape_errors = collect_node_config_errors([wrapped])
    completeness_errors = collect_generated_node_completeness_errors([wrapped]) if not shape_errors else []
    errors = shape_errors or completeness_errors
    if not errors:
        return
    first = errors[0]
    raise ContainerCompileError(
        str(first["code"]),
        str(first["detail"]),
        path=f"children.{ref}",
        child_ref=ref,
        cause={"error_code": str(first["code"]), "error": str(first["detail"])},
    )


def _canonical_container_data(
    *,
    kind: Literal["loop", "iteration"],
    title: str,
    old_data: Mapping[str, object],
) -> dict[str, Any]:
    """Build minimal container data without inheriting prior node config."""
    return {
        "type": kind,
        "title": title,
        "desc": str(old_data.get("desc") or ""),
    }
