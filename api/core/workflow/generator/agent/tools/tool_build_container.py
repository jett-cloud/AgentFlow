"""Dedicated Loop/Iteration builders: compile a container subgraph, then commit once.

``compile_build_loop`` / ``compile_build_iteration`` must not rebind
``context.state.graph``. The only writer is ``commit_build_container``, which
assigns the compiled graph when the captured revision still matches. Success
``changed=True`` lets the agent loop bump revision by 1.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Literal, cast

from pydantic import ValidationError

from core.workflow.generator.agent.tools.tool_context import ToolContext
from core.workflow.generator.agent.tools.tool_mutate import _BUILD_MODES, _build_node_content, _node_config
from core.workflow.generator.agent.tools.tool_results import error, ok
from core.workflow.generator.agent.types import ToolCall, ToolResult
from core.workflow.generator.compiler.container_compiler import compile_container_subgraph
from core.workflow.generator.compiler.container_types import (
    CompiledContainer,
    ContainerCompileError,
    ContainerCompileRequest,
)
from core.workflow.generator.compiler.intents.build_contracts import BuildIterationArgs, BuildLoopArgs
from core.workflow.generator.compiler.intents.container_intent import (
    IterationBuildIntent,
    LoopBuildIntent,
    parse_iteration_build_intent,
    parse_loop_build_intent,
)
from core.workflow.generator.graph.graph_ops import find_node
from core.workflow.generator.graph.id_policy import validate_mutation_node_id
from core.workflow.generator.model_io.budget import (
    ModelCallBudgetExceededError,
    RunCancelledError,
    budgeted_llm_json_client,
)


@dataclass(frozen=True)
class CompiledBuildContainer:
    """Validated container subgraph that has not been written yet."""

    call: ToolCall
    compiled: CompiledContainer
    container_id: str
    title: str
    mode: str
    old_config: dict[str, object]
    node_type: Literal["loop", "iteration"]


CompiledBuildLoop = CompiledBuildContainer


def compile_build_loop(call: ToolCall, context: ToolContext) -> CompiledBuildContainer | ToolResult:
    """Validate arguments and compile a Loop on a graph copy without writing."""
    try:
        parsed = BuildLoopArgs.model_validate(call["arguments"])
    except ValidationError as exc:
        return _container_validation_error(call, exc)

    prepared = _prepare_container_write(call, context, parsed, node_type="loop")
    if not isinstance(prepared, tuple):
        return prepared
    _existing, node_id, title, old_config = prepared

    try:
        intent = parse_loop_build_intent(
            {
                "loop_count": parsed.loop_count,
                "loop_variables": parsed.loop_variables,
                "children": parsed.children,
                "edges": parsed.edges,
                "break_conditions": parsed.break_conditions,
                "outputs": parsed.outputs,
                "logical_operator": parsed.logical_operator,
            }
        )
    except ValidationError as exc:
        return error(call, "INVALID_ARGUMENT", _args_validation_detail(exc))

    return _compile_container_request(
        call,
        context,
        node_id=node_id,
        title=title,
        mode=str(parsed.mode),
        old_config=old_config,
        kind="loop",
        intent=intent,
        node_type="loop",
    )


def compile_build_iteration(call: ToolCall, context: ToolContext) -> CompiledBuildContainer | ToolResult:
    """Validate arguments and compile an Iteration on a graph copy without writing."""
    try:
        parsed = BuildIterationArgs.model_validate(call["arguments"])
    except ValidationError as exc:
        return _container_validation_error(call, exc)

    prepared = _prepare_container_write(call, context, parsed, node_type="iteration")
    if not isinstance(prepared, tuple):
        return prepared
    _existing, node_id, title, old_config = prepared

    try:
        intent = parse_iteration_build_intent(
            {
                "iterator_selector": parsed.iterator_selector,
                "iterator_input_type": parsed.iterator_input_type,
                "output_selector": parsed.output_selector,
                "children": parsed.children,
                "edges": parsed.edges,
                "outputs": parsed.outputs,
                "is_parallel": parsed.is_parallel,
                "parallel_nums": parsed.parallel_nums,
                "error_handle_mode": parsed.error_handle_mode,
                "flatten_output": parsed.flatten_output,
            }
        )
    except ValidationError as exc:
        return error(call, "INVALID_ARGUMENT", _args_validation_detail(exc))

    return _compile_container_request(
        call,
        context,
        node_id=node_id,
        title=title,
        mode=str(parsed.mode),
        old_config=old_config,
        kind="iteration",
        intent=intent,
        node_type="iteration",
    )


def commit_build_container(compiled: CompiledBuildContainer, context: ToolContext) -> ToolResult:
    """Write a compiled container graph once when the captured revision still matches."""
    if context.state.candidate_revision != compiled.compiled.base_revision:
        return error(compiled.call, "STALE_COMPILE_RESULT", "Candidate graph changed during compile")
    context.state.graph = compiled.compiled.graph
    container = find_node(compiled.compiled.graph, compiled.container_id)
    content = _build_node_content(
        node_id=compiled.container_id,
        node_type=compiled.node_type,
        title=compiled.title,
        parent=None,
        mode=compiled.mode,
        old_config=compiled.old_config,
        new_config=_node_config(container) if container is not None else {},
        old_parent=None,
        edges=compiled.compiled.graph["edges"],
    )
    return ok(compiled.call, changed=True, content=content)


def build_loop(call: ToolCall, context: ToolContext) -> ToolResult:
    compiled = compile_build_loop(call, context)
    return commit_build_container(compiled, context) if isinstance(compiled, CompiledBuildContainer) else compiled


def build_iteration(call: ToolCall, context: ToolContext) -> ToolResult:
    compiled = compile_build_iteration(call, context)
    return commit_build_container(compiled, context) if isinstance(compiled, CompiledBuildContainer) else compiled


def _prepare_container_write(
    call: ToolCall,
    context: ToolContext,
    parsed: BuildLoopArgs | BuildIterationArgs,
    *,
    node_type: Literal["loop", "iteration"],
) -> tuple[object, str, str, dict[str, object]] | ToolResult:
    if parsed.mode not in _BUILD_MODES:
        return error(call, "INVALID_ARGUMENT", "mode must be create, update, or replace")
    try:
        node_id = validate_mutation_node_id(parsed.id)
    except ValueError as exc:
        return error(call, "INVALID_NODE_ID", str(exc))
    if parsed.parent:
        return _container_error(
            call,
            "NESTED_CONTAINER_UNSUPPORTED",
            "nested containers are not supported",
            path="parent",
        )

    existing = find_node(context.state.graph, node_id)
    if parsed.mode == "create" and existing is not None:
        return error(call, "NODE_EXISTS", f"Node {node_id!r} already exists")
    if parsed.mode in {"update", "replace"} and existing is None:
        return error(call, "NODE_NOT_FOUND", f"Node {node_id!r} does not exist")
    if parsed.mode == "create" and not (parsed.title or "").strip():
        return error(call, "INVALID_ARGUMENT", "title is required when creating a node")
    existing_type = str(existing["data"].get("type") or "") if existing is not None else ""
    if parsed.mode == "update" and existing is not None and existing_type != node_type:
        label = "Loop" if node_type == "loop" else "Iteration"
        return error(call, "INVALID_ARGUMENT", f"update requires an existing {label} node")
    if parsed.mode == "replace" and existing is not None and existing_type == node_type:
        return error(call, "TYPE_UNCHANGED_USE_UPDATE", "replace requires a different type; use update")

    title = (parsed.title or "").strip() or (str(existing["data"].get("title") or node_id) if existing else node_id)
    old_config = _node_config(existing) if existing is not None else {}
    return existing, node_id, title, old_config


def _compile_container_request(
    call: ToolCall,
    context: ToolContext,
    *,
    node_id: str,
    title: str,
    mode: str,
    old_config: dict[str, object],
    kind: Literal["loop", "iteration"],
    intent: LoopBuildIntent | IterationBuildIntent,
    node_type: Literal["loop", "iteration"],
) -> CompiledBuildContainer | ToolResult:
    frozen = deepcopy(context.state.graph)
    request = ContainerCompileRequest(
        kind=kind,
        container_id=node_id,
        intent=intent,
        frozen_graph=frozen,
        base_revision=context.state.candidate_revision,
        existing_child_ids=_stored_child_ids(frozen, node_id),
        tool_entries=tuple(context.env.tool_entries),
        knowledge_entries=tuple(context.env.knowledge_entries),
        installed_tools=context.env.installed_tools,
        generation_mode=context.env.mode,
        title=title,
        compile_cache=context.state.compile_cache,
        builder_client=budgeted_llm_json_client(context.env.llm_client, context.state.model_call_budget),
        builder_input=context.env.builder_input,
    )
    try:
        compiled = compile_container_subgraph(request)
    except RunCancelledError:
        return error(call, "RUN_ABORTED", "Run cancelled before container Builder completed")
    except ModelCallBudgetExceededError:
        return error(call, "MODEL_CALL_BUDGET_EXHAUSTED", "Agent model-call limit reached")
    except ContainerCompileError as exc:
        return _container_error(
            call,
            exc.code,
            exc.detail,
            path=exc.path,
            child_ref=exc.child_ref,
            cause=cast(dict[str, object], exc.cause),
        )
    return CompiledBuildContainer(
        call=call,
        compiled=compiled,
        container_id=node_id,
        title=title,
        mode=mode,
        old_config=old_config,
        node_type=node_type,
    )


def _stored_child_ids(graph: object, container_id: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    nodes = graph["nodes"] if isinstance(graph, dict) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        parent = node.get("parentId") or (node.get("data") or {}).get("parentId")
        if parent != container_id:
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        ref = data.get("assist_ref") if isinstance(data, dict) else None
        node_id = node.get("id")
        if isinstance(ref, str) and ref and isinstance(node_id, str) and node_id:
            mapping[ref] = node_id
    return mapping


def _args_validation_detail(exc: ValidationError) -> str:
    first = exc.errors(include_input=False)[0]
    path = ".".join(str(part) for part in first.get("loc", ()))
    message = str(first.get("msg") or "invalid value")
    return f"{path}: {message}" if path else message


def _container_validation_error(call: ToolCall, exc: ValidationError) -> ToolResult:
    for item in exc.errors(include_input=False):
        message = str(item.get("msg") or "invalid value")
        if "nested containers are not supported" not in message:
            continue
        location = item.get("loc", ())
        path = ".".join(str(part) for part in location)
        child_ref = None
        raw_children = call["arguments"].get("children")
        child_index = next((part for part in location if isinstance(part, int)), None)
        if isinstance(raw_children, list) and isinstance(child_index, int) and child_index < len(raw_children):
            child = raw_children[child_index]
            if isinstance(child, dict) and isinstance(child.get("ref"), str):
                child_ref = child["ref"]
        return _container_error(
            call,
            "NESTED_CONTAINER_UNSUPPORTED",
            "nested containers are not supported",
            path=path or "children",
            child_ref=child_ref,
        )
    return error(call, "INVALID_ARGUMENT", _args_validation_detail(exc))


def _container_error(
    call: ToolCall,
    error_code: str,
    message: str,
    *,
    path: str,
    child_ref: str | None = None,
    cause: dict[str, object] | None = None,
) -> ToolResult:
    return error(
        call,
        error_code,
        message,
        path=path,
        child_ref=child_ref,
        cause=cause or {"error_code": error_code, "error": message},
    )
