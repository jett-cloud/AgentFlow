"""Compile dependency layers concurrently and commit in call order; discard siblings after retryable failure."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import cast

from configs import dify_config
from core.workflow.generator.agent.run_limits import (
    AgentCancellation,
    _aborted,
)
from core.workflow.generator.agent.state.reducer import (
    _append,
    _apply_revision,
    _result_event,
    _result_row,
)
from core.workflow.generator.agent.tools.tool_build_agent import (
    CompiledAgentNode,
    commit_build_agent_node,
    compile_build_agent_node,
)
from core.workflow.generator.agent.tools.tool_build_container import (
    CompiledBuildContainer,
    commit_build_container,
    compile_build_iteration,
    compile_build_loop,
)
from core.workflow.generator.agent.tools.tool_build_tool import (
    CompiledToolNode,
    commit_build_tool_node,
    compile_build_tool_node,
)
from core.workflow.generator.agent.tools.tool_results import error
from core.workflow.generator.agent.tools.tools import (
    CompiledBuildNode,
    ToolContext,
    commit_build_node,
    compile_build_node,
    duplicate_create_ids,
    note_graph_mutation,
    pending_plan_nodes_from_calls,
)
from core.workflow.generator.agent.types import (
    AgentEvent,
    AgentSession,
    ToolCall,
    ToolResult,
)
from core.workflow.generator.contracts.workflow_contract import workflow_plan_mutation_error
from core.workflow.generator.graph.types import MinimalGraphDict

logger = logging.getLogger(__name__)


_COMPILABLE_CREATE_TOOLS = frozenset(
    {
        "build_node",
        "build_tool_node",
        "build_agent_node",
        "build_loop",
        "build_iteration",
    }
)


def _is_compilable_create(call: ToolCall) -> bool:
    if call["name"] not in _COMPILABLE_CREATE_TOOLS:
        return False
    arguments = call.get("arguments")
    mode = arguments.get("mode") if isinstance(arguments, dict) else None
    return mode == "create"


def _call_argument_str(call: ToolCall, key: str) -> str | None:
    arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
    value = arguments.get(key) if isinstance(arguments, dict) else None
    if isinstance(value, str) and value:
        return value
    return None


_GRAPH_REPLACING_CREATES = frozenset({"build_loop", "build_iteration"})


def _structured_selector_sources(value: object, *, field_name: str | None = None) -> set[str]:
    """Return producer ids from explicit selector fields in a build request.

    Free-form objective, prompt, and template text are deliberately ignored:
    scheduling facts come from typed selectors, not strings that merely mention
    a variable. Invalid payloads remain the owning builder's validation error.
    """
    sources: set[str] = set()
    if isinstance(value, dict):
        if value.get("value_type") == "variable":
            selector = value.get("value")
            if isinstance(selector, (list, tuple)) and len(selector) >= 2:
                source = selector[0]
                if isinstance(source, str) and source:
                    sources.add(source)
        for key, item in value.items():
            sources.update(_structured_selector_sources(item, field_name=str(key)))
        return sources
    is_selector = field_name in {"source", "selector"} or bool(field_name and field_name.endswith("_selector"))
    if is_selector and isinstance(value, (list, tuple)) and len(value) >= 2:
        source = value[0]
        if isinstance(source, str) and source:
            sources.add(source)
        return sources
    if isinstance(value, list):
        for item in value:
            sources.update(_structured_selector_sources(item, field_name=field_name))
    return sources


def _create_data_dependencies(call: ToolCall) -> set[str]:
    arguments = call.get("arguments")
    return _structured_selector_sources(arguments if isinstance(arguments, dict) else {})


def _creates_conflict(left: ToolCall, right: ToolCall) -> bool:
    """True when two creates must compile serially.

    Besides structural conflicts, a typed selector creates a producer-consumer
    boundary. This lets the producer commit before the consumer receives its
    immutable, confirmed variable view.
    """
    if left["name"] in _GRAPH_REPLACING_CREATES or right["name"] in _GRAPH_REPLACING_CREATES:
        return True
    left_id = _call_argument_str(left, "id")
    right_id = _call_argument_str(right, "id")
    left_parent = _call_argument_str(left, "parent")
    right_parent = _call_argument_str(right, "parent")
    if left_id and left_id == right_parent:
        return True
    if right_id and right_id == left_parent:
        return True
    if left_parent and left_parent == right_parent:
        return True
    if left_id and left_id in _create_data_dependencies(right):
        return True
    if right_id and right_id in _create_data_dependencies(left):
        return True
    return False


def _compile_mutation(call: ToolCall, context: ToolContext) -> object:
    if call["name"] == "build_tool_node":
        return compile_build_tool_node(call, context)
    if call["name"] == "build_agent_node":
        return compile_build_agent_node(call, context)
    if call["name"] == "build_loop":
        return compile_build_loop(call, context)
    if call["name"] == "build_iteration":
        return compile_build_iteration(call, context)
    return compile_build_node(call, context)


def _commit_mutation(call: ToolCall, compiled: object, context: ToolContext) -> ToolResult:
    if isinstance(compiled, dict) and compiled.get("ok") is False:
        return cast(ToolResult, compiled)
    if call["name"] == "build_tool_node":
        return commit_build_tool_node(cast(CompiledToolNode, compiled), context)
    if call["name"] == "build_agent_node":
        return commit_build_agent_node(cast(CompiledAgentNode, compiled), context)
    if call["name"] in {"build_loop", "build_iteration"}:
        if isinstance(compiled, dict) and "ok" in compiled:
            return cast(ToolResult, compiled)
        return commit_build_container(cast(CompiledBuildContainer, compiled), context)
    if isinstance(compiled, CompiledBuildNode):
        return commit_build_node(compiled, context)
    if isinstance(compiled, dict) and "ok" in compiled:
        return cast(ToolResult, compiled)
    raise TypeError(f"unsupported compiled mutation: {type(compiled)!r}")


def _is_retryable_failure(result: ToolResult) -> bool:
    return result["ok"] is False and result["retryable"] is True


def _create_compile_workers(batch_size: int) -> int:
    configured = int(dify_config.WORKFLOW_GENERATOR_NODE_BUILDER_MAX_WORKERS)
    return max(1, min(configured, batch_size))


def _after_graph_mutation(context: ToolContext, result: ToolResult) -> None:
    if not result["changed"]:
        return
    note_graph_mutation(context)


def _run_parallel_creates(
    session: AgentSession,
    context: ToolContext,
    calls: list[ToolCall],
    start_graph: MinimalGraphDict,
    cancellation: AgentCancellation,
) -> tuple[list[AgentEvent], bool, list[ToolResult]]:
    events: list[AgentEvent] = []
    results: list[ToolResult] = []
    for call in calls:
        payload = {"id": call["id"], "name": call["name"], "arguments": call["arguments"]}
        _append(
            session,
            event_type="tool_call",
            role="assistant",
            status="completed",
            payload=payload,
        )
        events.append(("tool_call", payload))

    duplicate_ids = duplicate_create_ids(calls)
    compiled_slots: list[object | None] = [None] * len(calls)
    try:
        context.state.pending_plan_nodes = pending_plan_nodes_from_calls(calls)
        positions_by_id = {
            node_id: index
            for index, call in enumerate(calls)
            if (node_id := _call_argument_str(call, "id")) is not None and node_id not in duplicate_ids
        }
        submit_indexes: list[int] = []
        submit_calls: list[ToolCall] = []
        for index, call in enumerate(calls):
            arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            node_id = arguments.get("id")
            if plan_error := workflow_plan_mutation_error(call, context):
                compiled_slots[index] = plan_error
            elif isinstance(node_id, str) and node_id in duplicate_ids:
                compiled_slots[index] = error(
                    call,
                    "DUPLICATE_BATCH_NODE_ID",
                    f"Duplicate create id {node_id!r} in the same batch",
                )
            elif later_dependencies := sorted(
                dependency
                for dependency in _create_data_dependencies(call)
                if positions_by_id.get(dependency, -1) > index
            ):
                compiled_slots[index] = error(
                    call,
                    "DEPENDENCY_ORDER_REQUIRED",
                    (
                        f"Create {node_id!r} depends on later producer(s) {later_dependencies!r}; "
                        "submit producers before consumers"
                    ),
                    cause={
                        "consumer_id": node_id if isinstance(node_id, str) else "",
                        "later_producer_ids": later_dependencies,
                    },
                )
            else:
                submit_indexes.append(index)
                submit_calls.append(call)
        preflight_failures = [index for index, compiled in enumerate(compiled_slots) if compiled is not None]
        if preflight_failures:
            first_failure = min(preflight_failures)
            kept = [
                (index, call) for index, call in zip(submit_indexes, submit_calls, strict=True) if index < first_failure
            ]
            submit_indexes = [index for index, _call in kept]
            submit_calls = [call for _index, call in kept]
        next_commit = 0

        def abort_uncommitted(aborted: AgentEvent) -> tuple[list[AgentEvent], bool, list[ToolResult]]:
            reason = str(aborted[1].get("termination_reason") or "aborted")
            for pending_call in calls[next_commit:]:
                result = error(pending_call, "RUN_ABORTED", f"Run aborted before commit: {reason}")
                results.append(result)
                _append(
                    session,
                    event_type="tool_result",
                    role="assistant",
                    status="completed",
                    payload=_result_row(result),
                )
                events.append(("tool_result", _result_event(result, context)))
            events.append(aborted)
            return events, True, results

        if submit_calls:
            workers = _create_compile_workers(len(submit_calls))
            wave_calls = list(submit_calls)
            wave_indexes = list(submit_indexes)
            batch_node_ids = frozenset(positions_by_id)
            dependencies_by_local = {
                local: _create_data_dependencies(call) & batch_node_ids for local, call in enumerate(wave_calls)
            }
            committed_successful_ids: set[str] = set()
            failed_ids: set[str] = set()
            remaining = list(range(len(wave_calls)))
            while remaining:
                if aborted := _aborted(cancellation):
                    return abort_uncommitted(aborted)
                context.state.pending_plan_nodes = pending_plan_nodes_from_calls(calls[next_commit:])
                dependency_failed: list[int] = []
                eligible: list[int] = []
                for local in remaining:
                    failed_dependencies = dependencies_by_local[local] & failed_ids
                    if failed_dependencies:
                        call = wave_calls[local]
                        compiled_slots[wave_indexes[local]] = error(
                            call,
                            "DEPENDENCY_FAILED",
                            f"Producer(s) {sorted(failed_dependencies)!r} failed; consumer was not compiled",
                            cause={
                                "consumer_id": _call_argument_str(call, "id") or "",
                                "failed_producer_ids": sorted(failed_dependencies),
                            },
                        )
                        dependency_failed.append(local)
                    elif dependencies_by_local[local] <= committed_successful_ids:
                        eligible.append(local)
                remaining = [local for local in remaining if local not in dependency_failed]
                wave: list[int] = []
                for local in eligible:
                    if any(_creates_conflict(wave_calls[local], wave_calls[item]) for item in wave):
                        continue
                    wave.append(local)
                remaining = [local for local in remaining if local not in wave]
                if not wave:
                    if dependency_failed:
                        continue
                    raise RuntimeError("create dependency scheduler made no progress")
                pool_calls = [wave_calls[local] for local in wave]
                pool_dest = [wave_indexes[local] for local in wave]
                with ThreadPoolExecutor(
                    max_workers=min(workers, max(1, len(pool_calls))),
                    thread_name_prefix="assist-create-compile",
                ) as executor:
                    futures = [executor.submit(_compile_mutation, call, context) for call in pool_calls]
                    for dest, future in zip(pool_dest, futures, strict=True):
                        compiled_slots[dest] = future.result()
                if aborted := _aborted(cancellation):
                    return abort_uncommitted(aborted)
                while next_commit < len(calls) and compiled_slots[next_commit] is not None:
                    compiled = compiled_slots[next_commit]
                    call = calls[next_commit]
                    result = _commit_mutation(call, compiled, context)
                    _after_graph_mutation(context, result)
                    results.append(result)
                    _apply_revision(session, context, call["name"], result)
                    _append(
                        session,
                        event_type="tool_result",
                        role="assistant",
                        status="completed",
                        payload=_result_row(result),
                    )
                    events.append(("tool_result", _result_event(result, context)))
                    committed_id = _call_argument_str(call, "id")
                    if committed_id is not None:
                        if result["ok"]:
                            committed_successful_ids.add(committed_id)
                        else:
                            failed_ids.add(committed_id)
                    next_commit += 1
                    if _is_retryable_failure(result):
                        return events, False, results
        while next_commit < len(calls) and compiled_slots[next_commit] is not None:
            compiled = compiled_slots[next_commit]
            call = calls[next_commit]
            result = _commit_mutation(call, compiled, context)
            _after_graph_mutation(context, result)
            results.append(result)
            _apply_revision(session, context, call["name"], result)
            _append(
                session,
                event_type="tool_result",
                role="assistant",
                status="completed",
                payload=_result_row(result),
            )
            events.append(("tool_result", _result_event(result, context)))
            next_commit += 1
            if _is_retryable_failure(result):
                return events, False, results
    finally:
        context.state.pending_plan_nodes = ()

    return events, False, results
