"""Drive prompt assembly, model turns and tool batches until an explicit terminal outcome."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Iterator
from copy import deepcopy
from types import MappingProxyType
from typing import Any, Protocol, cast

from core.workflow.generator.agent.compaction import TokenLimits, assemble_prompt
from core.workflow.generator.agent.prompts import active_skill_names, render_active_skills, render_current_situation
from core.workflow.generator.agent.protocol.protocol_text import clean_protocol_text
from core.workflow.generator.agent.protocol.stream import StreamTurnAssembler, iter_complete_tool_calls
from core.workflow.generator.agent.protocol.turn import (
    WorkflowAgentProtocolError,
    _parse_turn,
    _split_public_and_reasoning,
    _turn_mapping,
    _turn_text,
)
from core.workflow.generator.agent.run_limits import (
    _FUSE_MESSAGES,
    AgentCancellation,
    AgentRunLimits,
    _aborted,
    _error_event,
    _guard_reason,
    _require_max_model_calls,
)
from core.workflow.generator.agent.state.reducer import (
    _append_assistant_prose,
    _run_tool,
)
from core.workflow.generator.agent.tools.tools import (
    ToolContext,
)
from core.workflow.generator.agent.types import (
    AgentEvent,
    AgentSession,
    ToolCall,
)
from core.workflow.generator.model_io.budget import ModelCallBudget, ModelCallBudgetExceededError, RunCancelledError
from core.workflow.generator.pipeline.planner_context_values import PlannerContextLimitError
from core.workflow.generator.prompts.loader import always_on_system_prompt

logger = logging.getLogger(__name__)

from core.workflow.generator.agent.scheduling.creates import (
    _is_compilable_create,
    _is_retryable_failure,
    _run_parallel_creates,
)

SYSTEM_PROMPT = always_on_system_prompt()


_EMPTY_RESPONSE_LIMIT = 3


_PROTOCOL_RETRY_LIMIT = 2


_PROTOCOL_RETRY_INSTRUCTION = (
    "\n\nMODEL_OUTPUT_PROTOCOL_ERROR: The preceding model response contained tool protocol in text "
    "or incomplete tool arguments. No inferred text call was executed. Read the latest actual tool results "
    "and candidate state, then reissue the intended operation using the provided tool-call interface "
    "(native tool_calls when available, otherwise the required structured JSON response) "
    "with complete JSON arguments. Do not print tool JSON or DSML in narration."
)


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
    """Run with one shared budget for main, compactor, and nested Builder calls."""
    budget = ModelCallBudget(_require_max_model_calls(limits), cancellation_reason=cancellation.reason)
    context.state.model_call_budget = budget
    try:
        yield from _iter_agent_events(
            session,
            context,
            invoker,
            cancellation,
            limits,
            compact=compact,
            system_text=system_text,
            token_counter=token_counter,
            token_limits=token_limits,
        )
    finally:
        if context.state.model_call_budget is budget:
            context.state.model_call_budget = None


def _iter_agent_events(
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
    budget = context.state.model_call_budget
    if budget is None:
        raise RuntimeError("model-call budget was not initialized")
    usage = {"model_calls": budget.used, "tool_calls": 0, "tokens": 0}
    json_seq = 0
    empty_streak = 0
    protocol_failures = 0

    def counted_compact(**kwargs: Any) -> dict[str, object]:
        budget.reserve()
        usage["model_calls"] = budget.used
        assert compact is not None
        return compact(**kwargs)

    wrapped_compact = counted_compact if compact is not None else None

    while True:
        usage["model_calls"] = budget.used
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
                system_text=(system_text or SYSTEM_PROMPT) + (_PROTOCOL_RETRY_INSTRUCTION if protocol_failures else ""),
                limits=token_limits or _token_limits_from(limits),
                token_counter=token_counter or _cheap_token_counter,
                compact=wrapped_compact,
                skill_text=render_active_skills(active_skill_names(session)),
            )
        except RunCancelledError as exc:
            yield ("aborted", {"termination_reason": str(exc)})
            return
        except ModelCallBudgetExceededError:
            usage["model_calls"] = budget.used
            yield _error_event("max_model_calls", _FUSE_MESSAGES["max_model_calls"], usage)
            return
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

        budget.reserve()
        usage["model_calls"] = budget.used
        streamed = _iter_invoker_chunks(invoker, assembly.messages)
        calls: list[ToolCall] = []
        text: str | None = None
        reasoning: str | None = None
        protocol_error = False
        if streamed is None:
            turn = _invoke(invoker, assembly.messages)
            try:
                calls, text = _parse_turn(turn, json_seq)
            except WorkflowAgentProtocolError:
                protocol_error = True
                text = _turn_text(_turn_mapping(turn))
            json_seq += max(len(calls), 1)
            text, reasoning = _split_public_and_reasoning(text)
            checked = clean_protocol_text(text or "")
            text = checked.text or None
            protocol_error = protocol_error or checked.protocol_error
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
            for _kind, payload in assembler.drain_final_events():
                yield cast(
                    AgentEvent,
                    (
                        "message.delta",
                        {
                            **payload,
                            "text": payload["delta"],
                            "stream_mode": assembler.stream_mode,
                        },
                    ),
                )
            protocol_error = finished.get("protocol_error") is True
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

        if protocol_error and not calls:
            protocol_failures += 1
            if protocol_failures > _PROTOCOL_RETRY_LIMIT:
                yield _error_event(
                    "model_protocol_error",
                    "模型连续返回无效工具调用，本次无效调用未执行。请重试或更换支持工具调用的模型。",
                    usage,
                )
                return
            # Persist a normal assistant notice, not a forged tool result or a
            # new user turn (which would reset activated skills).
            notice = "模型返回的工具调用格式无效，本次调用未执行，正在自动重试。"
            notice_id = f"agent-message-{uuid.uuid4().hex[:12]}"
            _append_assistant_prose(session, text=notice, reasoning=None, message_id=notice_id)
            yield (
                "message.delta",
                {
                    "text": notice,
                    "delta": notice,
                    "message_id": notice_id,
                    "delta_index": 0,
                    "stream_mode": "native",
                },
            )
            continue
        protocol_failures = 0
        if calls:
            activation_call = next((call for call in calls if call["name"] == "activate_skills"), None)
            if activation_call is not None:
                calls = [activation_call]
            empty_streak = 0
            index = 0
            while index < len(calls):
                aborted = _aborted(cancellation)
                if aborted is not None:
                    yield aborted
                    return
                if _is_compilable_create(calls[index]):
                    batch: list[ToolCall] = []
                    while index < len(calls) and _is_compilable_create(calls[index]):
                        aborted = _aborted(cancellation)
                        if aborted is not None:
                            yield aborted
                            return
                        usage["tool_calls"] += 1
                        fuse = _guard_reason(
                            limits, usage, started_at, max_model_calls=max_model_calls, model_already_counted=True
                        )
                        if fuse is not None:
                            if batch:
                                events, stop, _results = _run_parallel_creates(
                                    session, context, batch, start_graph, cancellation
                                )
                                yield from events
                                if stop:
                                    return
                            yield _error_event(fuse, _FUSE_MESSAGES[fuse], usage)
                            return
                        batch.append(calls[index])
                        index += 1
                    events, stop, results = _run_parallel_creates(session, context, batch, start_graph, cancellation)
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
                if calls[index]["name"] == "activate_skills" or _is_retryable_failure(result):
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
    context.state.candidate_base_hash = session.candidate_base_hash
    context.state.contract_protocol_version = session.contract_protocol_version
    context.state.workflow_contract = deepcopy(session.workflow_contract)
    context.state.contract_revision = session.contract_revision
    context.state.contract_hash = session.contract_hash
    context.state.user_turn_evidence = MappingProxyType(
        {
            f"turn:{message.sequence}": text
            for message in session.messages
            if message.role == "user"
            and message.event_type == "message"
            and isinstance((text := message.payload.get("text")), str)
        }
    )


def _token_limits_from(limits: AgentRunLimits) -> TokenLimits:
    configured = getattr(limits, "token_limits", None)
    if isinstance(configured, TokenLimits):
        return configured
    return _DEFAULT_TOKEN_LIMITS


def _cheap_token_counter(messages: list[object]) -> int:
    return 1


def _iter_invoker_chunks(invoker: AgentModelInvoker, messages: list[object]) -> Iterator[object] | None:
    method = getattr(invoker, "iter_chunks", None)
    if not callable(method):
        return None
    chunks = method(messages)
    if chunks is None:
        return None
    return iter(chunks)


def _invoke(invoker: AgentModelInvoker, messages: list[object]) -> object:
    return invoker.invoke(messages)
