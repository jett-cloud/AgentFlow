"""Compile individual children with bounded mechanical retries; never commit graph state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from core.workflow.generator.compiler.agent_node_compiler import AgentNodeConfigError, compile_agent_node_config
from core.workflow.generator.compiler.container_scope import _ref_for_id, _resolution_cause
from core.workflow.generator.compiler.container_types import ChildCompileContext, CompiledChild, ContainerCompileError
from core.workflow.generator.compiler.container_values import _MECHANICAL_ATTEMPTS, _NEVER_MECHANICAL_RETRY
from core.workflow.generator.compiler.intents.container_intent import (
    AgentContainerChildIntent,
    ContainerChildIntent,
    StandardContainerChildIntent,
    ToolContainerChildIntent,
)
from core.workflow.generator.compiler.intents.node_intent import NodeBuildIntent, render_node_builder_spec
from core.workflow.generator.compiler.intents.tool_intent import ToolInvocationIntent
from core.workflow.generator.compiler.node_builder import build_single_node
from core.workflow.generator.compiler.ordinary_node_compiler import compile_structured_node_config
from core.workflow.generator.compiler.tool_parameter_normalize import ToolNodeConfigError, compile_tool_node_config
from core.workflow.generator.graph.types import MinimalGraphNodeDict
from core.workflow.generator.model_io.budget import ModelCallBudgetExceededError, RunCancelledError
from core.workflow.generator.model_io.llm_response import StageJSONError, StageSchemaError
from core.workflow.generator.resources.tool_catalogue import find_tool_entry
from core.workflow.generator.validation.intent_config_validator import validate_node_config_against_intent
from core.workflow.generator.validation.node_config_validator import (
    collect_generated_node_completeness_errors,
    collect_node_config_errors,
)
from core.workflow.generator.variables.variable_registry import (
    VariableResolutionError,
)


def compile_child_with_mechanical_retry(child: ContainerChildIntent, context: ChildCompileContext) -> CompiledChild:
    """Retry Builder protocol / same-intent completeness at most once; never retry semantic errors."""
    last_error: ContainerCompileError | None = None
    for attempt in range(_MECHANICAL_ATTEMPTS):
        try:
            return compile_container_child(child, context)
        except ContainerCompileError as exc:
            retryable = exc.mechanical_retry and exc.code not in _NEVER_MECHANICAL_RETRY
            if not retryable or attempt >= _MECHANICAL_ATTEMPTS - 1:
                if last_error is not None:
                    cause = dict(exc.cause)
                    cause["previous"] = last_error.cause
                    raise ContainerCompileError(
                        exc.code,
                        exc.detail,
                        path=exc.path,
                        child_ref=exc.child_ref,
                        cause=cause,
                        mechanical_retry=False,
                    ) from exc
                raise
            last_error = exc
    raise ContainerCompileError("INVALID_NODE_CONFIG", "mechanical retry exhausted", path=f"children.{child.ref}")


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
    if child.node_type == "assigner":
        config = _compile_assigner_config(child.intent, context, node_id)
        _assert_node_config(node_id, child.node_type, child.ref, config)
        return _child_node(
            child.ref,
            node_id,
            child.node_type,
            child.ref,
            config,
            context.container_id,
            in_iteration=context.in_iteration,
        )
    return compile_builder_child(child, context)


def compile_builder_child(child: StandardContainerChildIntent, context: ChildCompileContext) -> CompiledChild:
    if child.intent.structure is None and (context.builder_client is None or context.builder_input is None):
        raise ContainerCompileError(
            "UNSUPPORTED_NODE_TYPE",
            f"standard child type {child.node_type!r} has no deterministic container compiler",
            path=f"children.{child.ref}",
            child_ref=child.ref,
        )
    node_id = context.ref_map[child.ref]
    for item in child.intent.inputs:
        try:
            context.registry.resolve(item.source, referrer_id=node_id, expected_type=None)
        except VariableResolutionError as exc:
            raise ContainerCompileError(
                exc.code,
                exc.detail,
                path=f"children.{child.ref}",
                child_ref=child.ref,
                cause=_resolution_cause(exc, context.registry),
            ) from exc
    spec = render_node_builder_spec(child.intent, node_type=child.node_type)
    if child.intent.structure is not None:
        config = {}
    else:
        try:
            config = build_single_node(
                client=context.builder_client,
                request=context.builder_input,
                node_id=node_id,
                node_type=child.node_type,
                title=child.ref,
                purpose=spec,
                existing_node=None,
                extra_plan_nodes=[],
                topology_graph=dict(context.frozen_graph or {"nodes": [], "edges": []}),
            )
        except (ModelCallBudgetExceededError, RunCancelledError):
            raise
        except (StageJSONError, StageSchemaError) as exc:
            raise ContainerCompileError(
                "INVALID_JSON",
                str(exc),
                path=f"children.{child.ref}",
                child_ref=child.ref,
                mechanical_retry=True,
            ) from exc
        except Exception as exc:
            raise ContainerCompileError(
                "CAPABILITY_UNAVAILABLE",
                "Node builder failed",
                path=f"children.{child.ref}",
                child_ref=child.ref,
            ) from exc
    config = compile_structured_node_config(intent=child.intent, builder_config=config)
    _assert_node_config(node_id, child.node_type, child.ref, config, mechanical_retry=True)
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
            mechanical_retry=True,
        )
    return _child_node(
        child.ref, node_id, child.node_type, child.ref, config, context.container_id, in_iteration=context.in_iteration
    )


def _compile_assigner_config(intent: NodeBuildIntent, context: ChildCompileContext, node_id: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    child_ref = _ref_for_id(node_id, context.ref_map)
    for item in intent.inputs:
        try:
            context.registry.resolve(item.source, referrer_id=node_id, expected_type=None)
        except VariableResolutionError as exc:
            raise ContainerCompileError(
                exc.code,
                exc.detail,
                path=f"children.{child_ref or node_id}",
                child_ref=child_ref,
                cause=_resolution_cause(exc, context.registry),
            ) from exc
        items.append(
            {
                "variable_selector": [context.container_id, item.role],
                "input_type": "variable",
                "operation": "over-write",
                "value": list(item.source),
            }
        )
    if not items:
        raise ContainerCompileError(
            "INVALID_NODE_CONFIG",
            "assigner children require inputs",
            path=f"children.{child_ref or node_id}",
            child_ref=child_ref,
        )
    return {"version": "2", "items": items}


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
    *,
    mechanical_retry: bool = False,
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
        mechanical_retry=mechanical_retry and not shape_errors,
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
