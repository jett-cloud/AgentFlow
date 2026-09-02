"""In-memory workflow-assist tool loop.

``iter_agent_events`` is the fenced run: assemble a prompt, invoke the model,
dispatch tools, and yield ``AgentEvent`` tuples. Consecutive ``build_node``
creates in one model turn compile in a thread pool and commit in call order;
every other tool stays serial. A ``ok=false`` ``retryable`` result drops the
remaining sibling calls in that reply; the loop re-invokes so the model sees
the observation before deciding again. It mutates the in-memory ``AgentSession``
(append-only messages, candidate graph / revision) and never writes the
database or SSE — that is Task 8.

A reply with no ``tool_calls`` ends the turn (``turn_complete``). That is not
Apply-ready. ``finish.ok`` is the only path to ``done``. ``ask_user`` success
ends the iterator with ``waiting_user``. ``fail`` success yields ``failed``.
Cancellation yields ``aborted`` with the caller's ``termination_reason`` (do
not rewrite ``transport_disconnect`` as ``user_abort``). Empty responses,
spent fuses, and context overflow yield ``error``, never ``done``.

Revision: finish bumps ``context.state.candidate_revision`` when hydrate mutates.
After other mutating tools this loop adds 1; after ``finish`` it copies the
context revision and does not add 1 again.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import Any, Protocol, cast

from configs import dify_config
from core.workflow.generator.agent.compaction import TokenLimits, assemble_prompt
from core.workflow.generator.agent.prompts import render_active_skill, render_current_situation, select_playbook
from core.workflow.generator.agent.stream import StreamTurnAssembler, iter_complete_tool_calls
from core.workflow.generator.agent.tools import (
    CompiledBuildNode,
    ToolContext,
    commit_build_node,
    compile_build_node,
    dispatch,
    note_graph_mutation,
)
from core.workflow.generator.agent.types import (
    AgentEvent,
    AgentMessage,
    AgentMessageEventType,
    AgentMessageRole,
    AgentSession,
    MinimalGraphDict,
    ToolCall,
    ToolResult,
)
from core.workflow.generator.llm_response import extract_reasoning_blocks, strip_reasoning_blocks
from core.workflow.generator.planner_context import PlannerContextLimitError
from core.workflow.generator.prompts.loader import always_on_system_prompt

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = always_on_system_prompt()

_EMPTY_RESPONSE_LIMIT = 3
_FUSE_MESSAGES = {
    "max_model_calls": "Agent model-call limit reached",
    "max_tool_calls": "Agent tool-call limit reached",
    "max_total_tokens": "Agent token limit reached",
    "max_elapsed_time": "Agent elapsed-time limit reached",
    "empty_response": "Agent received empty model responses",
}

_DEFAULT_TOKEN_LIMITS = TokenLimits(
    input_limit=100_000,
    compact_trigger=80_000,
    compact_target=70_000,
    compactor_input_limit=40_000,
)


class AgentModelInvoker(Protocol):
    """Produces one model turn from an assembled prompt.

    ``iter_chunks`` is optional. Invokers without it, or that return ``None``,
    keep the blocking ``invoke`` path. Streaming invokers yield provider chunks
    and the loop emits ``message.delta`` before any tool dispatch.
    """

    def invoke(self, messages: list[object]) -> object: ...

    def iter_chunks(self, messages: list[object]) -> Iterator[object] | None:
        return None


class AgentCancellation(Protocol):
    """Read-only abort signal for one agent run. Values are §3.4 reasons."""

    def reason(self) -> str | None: ...


class AgentRunLimits(Protocol):
    """Runaway thresholds. ``max_model_calls`` is required and must be a positive int."""

    max_model_calls: int


def iter_agent_events(
    session: AgentSession,
    context: ToolContext,
    invoker: AgentModelInvoker,
    cancellation: AgentCancellation,
    limits: AgentRunLimits,
    *,
    compact: Callable[..., dict[str, object]] | None = None,
    system_text: str | None = None,
    token_counter: Callable[[list[object]], int] | None = None,
    token_limits: TokenLimits | None = None,
) -> Iterator[AgentEvent]:
    """Run one in-memory agent turn until a terminal event.

    ``limits`` is the only source of fuse thresholds (``max_model_calls`` at
    minimum and required as a positive int). Compactor calls count toward
    ``max_model_calls`` when ``compact`` is supplied. Cancellation is checked
    before each model call and before the next tool. Consecutive ``build_node``
    creates in one turn compile concurrently and commit in order. A retryable
    tool failure drops remaining sibling calls and continues the model loop.
    A reply with no tool calls yields ``turn_complete``. ``finish.ok`` is the
    only path to ``done``.
    Consecutive empty invoker responses stop at ``empty_response``.
    """
    max_model_calls = _require_max_model_calls(limits)
    _sync_context(session, context)
    start_graph = deepcopy(context.state.graph)
    started_at = time.monotonic()
    usage = {"model_calls": 0, "tool_calls": 0, "tokens": 0}
    json_seq = 0
    empty_streak = 0

    def counted_compact(**kwargs: Any) -> dict[str, object]:
        usage["model_calls"] += 1
        assert compact is not None
        return compact(**kwargs)

    wrapped_compact = counted_compact if compact is not None else None

    while True:
        aborted = _aborted(cancellation)
        if aborted is not None:
            yield aborted
            return
        fuse = _guard_reason(limits, usage, started_at, max_model_calls=max_model_calls)
        if fuse is not None:
            yield _error_event(fuse, _FUSE_MESSAGES[fuse], usage)
            return

        try:
            assembly = assemble_prompt(
                session=session,
                situation_text=render_current_situation(session),
                system_text=system_text or SYSTEM_PROMPT,
                limits=token_limits or _token_limits_from(limits),
                token_counter=token_counter or _cheap_token_counter,
                compact=wrapped_compact,
                skill_text=render_active_skill(select_playbook(session)),
            )
        except PlannerContextLimitError as exc:
            logger.warning("Workflow agent: context limit reached")
            yield (
                "error",
                {"message": str(exc), "errors": [], "termination_reason": "context_limit"},
            )
            return

        session.compacted_until_sequence = assembly.compacted_until_sequence
        session.compacted_state = assembly.compacted_state
        usage["tokens"] = assembly.prompt_tokens
        fuse = _guard_reason(limits, usage, started_at, max_model_calls=max_model_calls)
        if fuse is not None:
            yield _error_event(fuse, _FUSE_MESSAGES[fuse], usage)
            return

        aborted = _aborted(cancellation)
        if aborted is not None:
            yield aborted
            return

        usage["model_calls"] += 1
        streamed = _iter_invoker_chunks(invoker, assembly.messages)
        calls: list[ToolCall] = []
        text: str | None = None
        reasoning: str | None = None
        if streamed is None:
            turn = _invoke(invoker, assembly.messages)
            calls, text = _parse_turn(turn, json_seq)
            json_seq += max(len(calls), 1)
            text, reasoning = _split_public_and_reasoning(text)
            if text or reasoning:
                _append_assistant_prose(session, text=text, reasoning=reasoning)
                if text:
                    yield ("message", {"delta": text})
                elif reasoning:
                    yield (
                        "reasoning.delta",
                        {"text": reasoning, "delta": reasoning},
                    )
        else:
            assembler = StreamTurnAssembler(message_id=f"agent-message-{uuid.uuid4().hex[:12]}")
            for chunk in streamed:
                aborted = _aborted(cancellation)
                if aborted is not None:
                    assembler.finish()
                    yield aborted
                    return
                for kind, payload in assembler.push(chunk):
                    delta = str(payload["delta"])
                    event_name = "reasoning.delta" if kind == "reasoning" else "message.delta"
                    yield cast(
                        AgentEvent,
                        (
                            event_name,
                            {
                                "text": delta,
                                "delta": delta,
                                "message_id": payload["message_id"],
                                "delta_index": payload["delta_index"],
                                "stream_mode": assembler.stream_mode,
                            },
                        ),
                    )
            finished = assembler.finish()
            raw_text = finished.get("text")
            text = raw_text if isinstance(raw_text, str) and raw_text.strip() else None
            raw_reasoning = finished.get("reasoning")
            reasoning = raw_reasoning if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
            calls = list(iter_complete_tool_calls(finished))
            json_seq += max(len(calls), 1)
            if text or reasoning:
                _append_assistant_prose(
                    session,
                    text=text,
                    reasoning=reasoning,
                    message_id=finished.get("message_id"),
                )

        if calls:
            empty_streak = 0
            index = 0
            while index < len(calls):
                aborted = _aborted(cancellation)
                if aborted is not None:
                    yield aborted
                    return
                if _is_create_build(calls[index]):
                    batch: list[ToolCall] = []
                    while index < len(calls) and _is_create_build(calls[index]):
                        aborted = _aborted(cancellation)
                        if aborted is not None:
                            yield aborted
                            return
                        usage["tool_calls"] += 1
                        fuse = _guard_reason(
                            limits, usage, started_at, max_model_calls=max_model_calls, model_already_counted=True
                        )
                        if fuse is not None:
                            if len(batch) >= 2:
                                events, stop, _results = _run_parallel_creates(session, context, batch, start_graph)
                                yield from events
                                if stop:
                                    return
                            elif batch:
                                events, stop, _result = _run_tool(session, context, batch[0], start_graph)
                                yield from events
                                if stop:
                                    return
                            yield _error_event(fuse, _FUSE_MESSAGES[fuse], usage)
                            return
                        batch.append(calls[index])
                        index += 1
                    if len(batch) >= 2:
                        events, stop, results = _run_parallel_creates(session, context, batch, start_graph)
                    else:
                        events, stop, result = _run_tool(session, context, batch[0], start_graph)
                        results = [result]
                    yield from events
                    if stop:
                        return
                    if any(_is_retryable_failure(item) for item in results):
                        break
                    continue
                usage["tool_calls"] += 1
                fuse = _guard_reason(
                    limits, usage, started_at, max_model_calls=max_model_calls, model_already_counted=True
                )
                if fuse is not None:
                    yield _error_event(fuse, _FUSE_MESSAGES[fuse], usage)
                    return
                events, stop, result = _run_tool(session, context, calls[index], start_graph)
                yield from events
                if stop:
                    return
                if _is_retryable_failure(result):
                    break
                index += 1
            continue
        if text:
            aborted = _aborted(cancellation)
            if aborted is not None:
                yield aborted
                return
            yield ("turn_complete", {})
            return
        empty_streak += 1
        if empty_streak >= _EMPTY_RESPONSE_LIMIT:
            yield _error_event("empty_response", _FUSE_MESSAGES["empty_response"], usage)
            return


def _sync_context(session: AgentSession, context: ToolContext) -> None:
    graph = session.candidate_graph
    if isinstance(graph, dict):
        context.state.graph = graph  # type: ignore[assignment]
    context.state.candidate_revision = session.candidate_revision


def _token_limits_from(limits: AgentRunLimits) -> TokenLimits:
    configured = getattr(limits, "token_limits", None)
    if isinstance(configured, TokenLimits):
        return configured
    return _DEFAULT_TOKEN_LIMITS


def _cheap_token_counter(messages: list[object]) -> int:
    return 1


def _require_max_model_calls(limits: AgentRunLimits) -> int:
    value = getattr(limits, "max_model_calls", None)
    if not isinstance(value, int) or value <= 0:
        raise ValueError("limits.max_model_calls must be a positive int")
    return value


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _guard_reason(
    limits: AgentRunLimits,
    usage: dict[str, int],
    started_at: float,
    *,
    max_model_calls: int,
    model_already_counted: bool = False,
) -> str | None:
    """Return the spent fuse name, or None if the run may continue.

    Model-call budget is checked *before* the next invoke: ``usage['model_calls']``
    is the number already made. Tool / token / elapsed checks use current totals.
    ``model_already_counted`` skips the model comparison when we just billed a
    tool call on the same iteration.
    """
    if not model_already_counted and usage["model_calls"] >= max_model_calls:
        return "max_model_calls"
    max_tools = _optional_int(getattr(limits, "max_tool_calls", None))
    if max_tools is not None and usage["tool_calls"] > max_tools:
        return "max_tool_calls"
    max_tokens = _optional_int(getattr(limits, "max_total_tokens", None))
    if max_tokens is not None and usage["tokens"] >= max_tokens:
        return "max_total_tokens"
    max_elapsed = getattr(limits, "max_elapsed_time", None)
    if isinstance(max_elapsed, (int, float)) and max_elapsed > 0:
        if time.monotonic() - started_at >= max_elapsed:
            return "max_elapsed_time"
    return None


def _aborted(cancellation: AgentCancellation) -> AgentEvent | None:
    value = cancellation.reason()
    if isinstance(value, str) and value:
        return ("aborted", {"termination_reason": value})
    return None


def _error_event(termination_reason: str, message: str, usage: dict[str, int]) -> AgentEvent:
    return (
        "error",
        {
            "message": message,
            "errors": [],
            "termination_reason": termination_reason,
            "usage": dict(usage),
        },
    )


def _iter_invoker_chunks(invoker: AgentModelInvoker, messages: list[object]) -> Iterator[object] | None:
    method = getattr(invoker, "iter_chunks", None)
    if not callable(method):
        return None
    chunks = method(messages)
    if chunks is None:
        return None
    return iter(chunks)


def _split_public_and_reasoning(text: str | None) -> tuple[str | None, str | None]:
    if not isinstance(text, str) or not text:
        return None, None
    reasoning = extract_reasoning_blocks(text).strip() or None
    public = strip_reasoning_blocks(text) or None
    return public, reasoning


def _append_assistant_prose(
    session: AgentSession,
    *,
    text: str | None,
    reasoning: str | None,
    message_id: object | None = None,
) -> None:
    payload: dict[str, Any] = {"text": text or ""}
    if isinstance(reasoning, str) and reasoning:
        payload["reasoning"] = reasoning
    if isinstance(message_id, str) and message_id:
        payload["message_id"] = message_id
    _append(
        session,
        event_type="message",
        role="assistant",
        status="completed",
        payload=payload,
    )


def _invoke(invoker: AgentModelInvoker, messages: list[object]) -> object:
    return invoker.invoke(messages)


def _parse_turn(turn: object, json_seq: int) -> tuple[list[ToolCall], str | None]:
    if turn is None:
        return [], None
    if isinstance(turn, str):
        stripped = turn.strip()
        return [], stripped or None
    raw = _turn_mapping(turn)
    text = _turn_text(raw)
    native = raw.get("tool_calls")
    if isinstance(native, list) and native:
        calls = [_normalize_call(item, json_seq + index) for index, item in enumerate(native)]
        return calls, _strip_embedded_tool_json(text)
    if isinstance(raw.get("name"), str) and "arguments" in raw:
        return [_normalize_call(raw, json_seq)], _strip_embedded_tool_json(text)
    return [], text


def _turn_text(raw: dict[str, Any]) -> str | None:
    text = raw.get("text")
    if isinstance(text, str) and text.strip():
        return text
    return None


def _is_tool_call_object(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    name = value.get("name")
    has_name = isinstance(name, str) and bool(name.strip())
    if has_name and "arguments" in value:
        return True
    call_id = value.get("id")
    return has_name and isinstance(call_id, str) and call_id.lower().startswith("call")


def _matching_brace(text: str, start: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _strip_embedded_tool_json(text: str | None) -> str | None:
    if not isinstance(text, str) or not text:
        return None
    output: list[str] = []
    cursor = 0
    while cursor < len(text):
        start = text.find("{", cursor)
        if start < 0:
            output.append(text[cursor:])
            break
        output.append(text[cursor:start])
        end = _matching_brace(text, start)
        if end < 0:
            output.append(text[start:])
            break
        snippet = text[start : end + 1]
        try:
            parsed = json.loads(snippet)
        except json.JSONDecodeError:
            output.append(snippet)
        else:
            if not _is_tool_call_object(parsed):
                output.append(snippet)
        cursor = end + 1
    stripped = "".join(output)
    stripped = "\n".join(line.rstrip() for line in stripped.splitlines())
    while "\n\n\n" in stripped:
        stripped = stripped.replace("\n\n\n", "\n\n")
    stripped = stripped.strip()
    return stripped or None


def _turn_mapping(turn: object) -> dict[str, Any]:
    if isinstance(turn, dict):
        return turn
    mapping: dict[str, Any] = {}
    for key in ("text", "tool_calls", "name", "arguments", "id"):
        if hasattr(turn, key):
            mapping[key] = getattr(turn, key)
    return mapping


def _normalize_call(raw: object, seq: int) -> ToolCall:
    payload = raw if isinstance(raw, dict) else _turn_mapping(raw)
    call_id = payload.get("id")
    if not isinstance(call_id, str) or not call_id:
        call_id = f"json-{seq}-{uuid.uuid4().hex[:8]}"
    name = str(payload.get("name") or "")
    arguments = payload.get("arguments")
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            parsed = {}
        arguments = parsed if isinstance(parsed, dict) else {}
    if not isinstance(arguments, dict):
        arguments = {}
    return {"id": call_id, "name": name, "arguments": arguments}


def _is_create_build(call: ToolCall) -> bool:
    arguments = call.get("arguments")
    mode = arguments.get("mode") if isinstance(arguments, dict) else None
    return call["name"] == "build_node" and mode == "create"


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

    workers = _create_compile_workers(len(calls))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="assist-create-compile") as executor:
        futures = [executor.submit(compile_build_node, call, context) for call in calls]
        compiled_list = [future.result() for future in futures]

    for call, compiled in zip(calls, compiled_list, strict=True):
        if isinstance(compiled, CompiledBuildNode):
            result = commit_build_node(compiled, context)
            _after_graph_mutation(context, result)
        else:
            result = compiled
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
    return events, False, results


def _run_tool(
    session: AgentSession,
    context: ToolContext,
    call: ToolCall,
    start_graph: MinimalGraphDict,
) -> tuple[list[AgentEvent], bool, ToolResult]:
    result = dispatch(call, context)
    _apply_revision(session, context, call["name"], result)
    tool_call_event: AgentEvent = (
        "tool_call",
        {"id": call["id"], "name": call["name"], "arguments": call["arguments"]},
    )

    if call["name"] == "ask_user" and result["ok"]:
        _append(
            session,
            event_type="tool_call",
            role="assistant",
            status="pending",
            payload={"id": call["id"], "name": call["name"], "arguments": call["arguments"]},
        )
        questions = _questions(result, call)
        waiting: AgentEvent = ("waiting_user", {"tool_call_id": call["id"], "questions": questions})
        return [tool_call_event, waiting], True, result

    _append(
        session,
        event_type="tool_call",
        role="assistant",
        status="completed",
        payload={"id": call["id"], "name": call["name"], "arguments": call["arguments"]},
    )
    _append(
        session,
        event_type="tool_result",
        role="assistant",
        status="completed",
        payload=_result_row(result),
    )
    events: list[AgentEvent] = [tool_call_event, ("tool_result", _result_event(result, context))]

    if call["name"] == "fail" and result["ok"]:
        reason = ""
        if isinstance(result["content"], dict):
            value = result["content"].get("reason")
            reason = value if isinstance(value, str) else ""
        if not reason:
            fallback = call["arguments"].get("reason")
            reason = fallback if isinstance(fallback, str) else ""
        events.append(("failed", {"reason": reason}))
        return events, True, result
    if call["name"] == "finish" and result["ok"]:
        events.append(("done", _done_payload(result, context, start_graph, call)))
        return events, True, result
    return events, False, result


def _apply_revision(session: AgentSession, context: ToolContext, name: str, result: ToolResult) -> None:
    if name == "finish":
        session.candidate_revision = context.state.candidate_revision
        session.candidate_graph = context.state.graph
        _remember_validation(session, context, name, result)
        _remember_acceptance(session, context, name, result)
        return
    if result["changed"]:
        session.candidate_revision += 1
        context.state.candidate_revision = session.candidate_revision
        session.candidate_graph = context.state.graph
    _remember_validation(session, context, name, result)
    _remember_acceptance(session, context, name, result)


def _remember_validation(session: AgentSession, context: ToolContext, name: str, result: ToolResult) -> None:
    content = result.get("content")
    if name not in {"finish", "validate_graph"} or not isinstance(content, dict) or "valid" not in content:
        return
    session.last_validation = {
        "valid": content.get("valid"),
        "validated_revision": context.state.last_validation_revision,
        "errors": content.get("errors"),
    }


def _remember_acceptance(session: AgentSession, context: ToolContext, name: str, result: ToolResult) -> None:
    content = result.get("content")
    if name == "run_acceptance" and result.get("error_code") == "LIVE_RUN_REQUIRES_CONSENT":
        session.last_acceptance = {
            "passed": None,
            "reason": "LIVE_RUN_REQUIRES_CONSENT",
            "revision": context.state.candidate_revision,
        }
        return
    if name == "run_acceptance" and isinstance(content, dict) and "passed" in content:
        session.last_acceptance = {
            "passed": content.get("passed"),
            "revision": context.state.candidate_revision,
            "reason": None,
            "failed_nodes": content.get("failed_nodes") or [],
            "attempt_id": content.get("attempt_id"),
        }
        return
    if name == "finish" and isinstance(content, dict):
        acceptance = content.get("acceptance")
        if isinstance(acceptance, dict) and acceptance.get("reason"):
            session.last_acceptance = {
                "passed": False,
                "revision": context.state.candidate_revision,
                "reason": acceptance.get("reason"),
                "failed_nodes": acceptance.get("failed_nodes") or [],
                "attempt_id": acceptance.get("attempt_id"),
            }


def _questions(result: ToolResult, call: ToolCall) -> object:
    content = result.get("content")
    if isinstance(content, dict) and "questions" in content:
        return content["questions"]
    return call["arguments"].get("questions") or []


def _result_row(result: ToolResult) -> dict[str, Any]:
    return {
        "tool_call_id": result["tool_call_id"],
        "name": result["name"],
        "ok": result["ok"],
        "changed": result["changed"],
        "content": result["content"],
        "error": result["error"],
        "error_code": result["error_code"],
        "retryable": result["retryable"],
    }


def _result_event(result: ToolResult, context: ToolContext) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": result["tool_call_id"],
        "name": result["name"],
        "ok": result["ok"],
        "summary": _summary(result),
    }
    content = result.get("content")
    if isinstance(content, dict):
        failed_nodes = content.get("failed_nodes")
        if isinstance(failed_nodes, list) and failed_nodes:
            payload["failed_nodes"] = failed_nodes
        acceptance = content.get("acceptance")
        if isinstance(acceptance, dict):
            payload["acceptance"] = acceptance
            nested = acceptance.get("failed_nodes")
            if isinstance(nested, list) and nested:
                payload["failed_nodes"] = nested
    if result["changed"]:
        payload["graph"] = context.state.graph
    return payload


def _summary(result: ToolResult) -> str:
    content = result.get("content")
    if isinstance(content, dict):
        acceptance = content.get("acceptance")
        if isinstance(acceptance, dict):
            reason = acceptance.get("reason")
            if isinstance(reason, str) and reason:
                nodes = acceptance.get("failed_nodes")
                if isinstance(nodes, list) and nodes and isinstance(nodes[0], dict):
                    node_id = nodes[0].get("id") or "?"
                    error = nodes[0].get("error") or ""
                    return f"{reason} {node_id}:{error}".strip()
                return reason
        if content.get("passed") is False:
            trace = content.get("trace_summary")
            if isinstance(trace, str) and trace:
                return trace
            nodes = content.get("failed_nodes")
            count = len(nodes) if isinstance(nodes, list) else 0
            return f"{count} acceptance failures"
        summary = content.get("summary")
        if isinstance(summary, str) and summary:
            return summary
        reason = content.get("reason")
        if isinstance(reason, str) and reason:
            return reason
        if content.get("valid") is False:
            errors = content.get("errors")
            count = len(errors) if isinstance(errors, list) else 0
            return f"{count} validation errors"
    error = result.get("error")
    if isinstance(error, str) and error:
        return error
    return "" if result["ok"] else "error"


def _done_payload(
    result: ToolResult,
    context: ToolContext,
    start_graph: MinimalGraphDict,
    call: ToolCall,
) -> dict[str, Any]:
    content = result["content"] if isinstance(result["content"], dict) else {}
    summary = content.get("summary")
    if not isinstance(summary, str):
        raw = call["arguments"].get("summary")
        summary = raw if isinstance(raw, str) else ""
    errors = content.get("errors")
    return {
        "graph": context.state.graph,
        "summary": summary,
        "diff": _graph_diff(start_graph, context.state.graph),
        "validation": {"ok": bool(content.get("valid")), "errors": errors if isinstance(errors, list) else []},
    }


def _graph_diff(before: MinimalGraphDict, after: MinimalGraphDict) -> dict[str, list[str]]:
    before_nodes = _nodes_by_id(before)
    after_nodes = _nodes_by_id(after)
    added = sorted(node_id for node_id in after_nodes if node_id not in before_nodes)
    removed = sorted(node_id for node_id in before_nodes if node_id not in after_nodes)
    updated = sorted(
        node_id for node_id in after_nodes if node_id in before_nodes and after_nodes[node_id] != before_nodes[node_id]
    )
    return {"added": added, "removed": removed, "updated": updated}


def _nodes_by_id(graph: MinimalGraphDict) -> dict[str, object]:
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    if not isinstance(nodes, list):
        return {}
    by_id: dict[str, object] = {}
    for node in nodes:
        if isinstance(node, dict):
            node_id = node.get("id")
            if isinstance(node_id, str) and node_id:
                by_id[node_id] = node
    return by_id


def _append(
    session: AgentSession,
    *,
    event_type: AgentMessageEventType,
    role: AgentMessageRole,
    status: str,
    payload: dict[str, Any],
) -> None:
    sequence = session.messages[-1].sequence + 1 if session.messages else 1
    session.messages.append(
        AgentMessage(
            sequence=sequence,
            event_type=event_type,
            role=role,
            status=status,
            payload=payload,
        )
    )
