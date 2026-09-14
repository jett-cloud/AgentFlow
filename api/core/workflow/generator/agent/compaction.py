"""Assemble the workflow-agent prompt and advance a compaction checkpoint.

The conversation's message rows are the source of truth and are never rewritten.
``assemble_prompt`` builds a *copy* for the model: system, optional
``[COMPACTED HISTORY]``, raw messages after the watermark, CurrentSituation,
and an optional skill body at the tail. ``[COMPRESSED]`` is Level 1 only —
it appears on a segment copy fed to the Compactor, never in the live prompt.

Token budget matches ``PlannerContextSession.start``:
``input_limit = context_window - output_reserve - 2% safety``. Compaction
starts at 80% of that limit and folds until 70% or no older legal segment
remains. If the live prompt still exceeds ``input_limit``, the copy omits
``[COMPACTED HISTORY]`` and may hard-drop the oldest legal prefix; the
message log is never rewritten.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

from core.workflow.generator.agent.types import AgentMessage, AgentSession
from core.workflow.generator.pipeline.planner_context_values import PlannerContextLimitError
from graphon.model_runtime.entities.message_entities import (
    AssistantPromptMessage,
    SystemPromptMessage,
    ToolPromptMessage,
    UserPromptMessage,
)

COMPACTED_STATE_KEYS = (
    "objective",
    "user_constraints",
    "confirmed_facts",
    "decisions",
    "rejected_approaches",
    "important_resources",
    "pending_work",
    "reloadable_details",
)

_LEVEL1_TOOLS = frozenset(
    {
        "read_node",
        "read_graph",
        "inspect_node_schema",
        "search_datasets",
        "search_tools",
        "inspect_tool",
        "validate_graph",
        "run_acceptance",
        "inspect_attempt",
    }
)
_NEVER_SLIM_TOOLS = frozenset(
    {
        "ask_user",
        "build_node",
        "connect",
        "disconnect",
        "delete_node",
        "finish",
        "fail",
        "activate_skills",
    }
)
_PROTECTED_INVOCATIONS = 2


@dataclass(frozen=True)
class TokenLimits:
    input_limit: int
    compact_trigger: int  # 80% * input_limit
    compact_target: int  # 70% * input_limit
    compactor_input_limit: int


@dataclass(frozen=True)
class PromptAssembly:
    messages: list[object]  # PromptMessage
    prompt_tokens: int
    compacted_until_sequence: int | None
    compacted_state: dict[str, object] | None


def compute_input_limit(*, context_window: int, output_reserve: int) -> int:
    """Return the planner-identical input budget: window - reserve - 2% safety."""
    safety_margin = max(256, math.ceil(context_window * 0.02))
    return max(context_window - output_reserve - safety_margin, 0)


def assemble_prompt(
    *,
    session: AgentSession,
    situation_text: str,
    system_text: str,
    limits: TokenLimits,
    token_counter: Callable[[list[object]], int],
    compact: Callable[..., dict[str, object]] | None = None,
    skill_text: str = "",
) -> PromptAssembly:
    """Build the live prompt. May fold a checkpoint; never mutates ``session.messages``.

    Below 80% of ``input_limit`` this is a no-op on C / watermark. At or above
    80% the oldest legal segment is Level-1 slimmed (copy only) and passed to
    ``compact``. On schema failure the fat prompt is kept when it still fits.
    When nothing more can fold and tokens still exceed ``input_limit``, omit
    ``[COMPACTED HISTORY]`` then hard-drop the oldest legal prefix (no Compactor,
    no holes, last two turns stay). Only a protected tail that still overflows
    raises ``PlannerContextLimitError`` (Level 3).
    """
    watermark = session.compacted_until_sequence
    state = session.compacted_state
    assembly = _assemble(
        session=session,
        situation_text=situation_text,
        system_text=system_text,
        token_counter=token_counter,
        watermark=watermark,
        compacted_state=state,
        skill_text=skill_text,
    )
    if assembly.prompt_tokens < limits.compact_trigger:
        return assembly

    while assembly.prompt_tokens > limits.compact_target:
        folded = _fold_once(
            session=session,
            watermark=watermark,
            compacted_state=state,
            limits=limits,
            compact=compact,
            situation_text=situation_text,
        )
        if folded is None:
            break
        watermark, state = folded
        assembly = _assemble(
            session=session,
            situation_text=situation_text,
            system_text=system_text,
            token_counter=token_counter,
            watermark=watermark,
            compacted_state=state,
            skill_text=skill_text,
        )

    if assembly.prompt_tokens > limits.input_limit:
        assembly = _assemble(
            session=session,
            situation_text=situation_text,
            system_text=system_text,
            token_counter=token_counter,
            watermark=watermark,
            compacted_state=None,
            skill_text=skill_text,
        )
        assembly = PromptAssembly(
            messages=assembly.messages,
            prompt_tokens=assembly.prompt_tokens,
            compacted_until_sequence=watermark,
            compacted_state=state,
        )

    hard_dropped = False
    while assembly.prompt_tokens > limits.input_limit:
        segment = _oldest_legal_segment(session.messages, watermark)
        if not segment:
            break
        watermark = segment[-1].sequence
        hard_dropped = True
        dropped = _assemble(
            session=session,
            situation_text=situation_text,
            system_text=system_text,
            token_counter=token_counter,
            watermark=watermark,
            compacted_state=None,
            skill_text=skill_text,
        )
        assembly = PromptAssembly(
            messages=dropped.messages,
            prompt_tokens=dropped.prompt_tokens,
            compacted_until_sequence=watermark,
            compacted_state=None,
        )

    if assembly.prompt_tokens > limits.input_limit:
        raise PlannerContextLimitError(prompt_tokens=assembly.prompt_tokens, input_limit=limits.input_limit)
    if hard_dropped:
        return assembly
    return PromptAssembly(
        messages=assembly.messages,
        prompt_tokens=assembly.prompt_tokens,
        compacted_until_sequence=watermark,
        compacted_state=state,
    )


def slim_segment(messages: Sequence[AgentMessage]) -> list[AgentMessage]:
    """Return copies with reloadable tool_result payloads replaced by Level 1 templates.

    Only ``read_node`` / ``read_graph`` / ``inspect_node_schema`` / ``inspect_tool`` /
    ``search_*`` / ``validate_graph`` / ``run_acceptance`` / ``inspect_attempt`` results are slimmed.
    prose, and mutation / finish / fail results stay intact. Input messages are
    not mutated.
    """
    calls_by_id = _tool_calls_by_id(messages)
    slimmed: list[AgentMessage] = []
    for message in messages:
        copied = _copy_message(message)
        if copied.event_type != "tool_result":
            slimmed.append(copied)
            continue
        name = str(copied.payload.get("name") or "")
        if not _is_level1_tool(name):
            slimmed.append(copied)
            continue
        call_id = copied.payload.get("tool_call_id")
        call = calls_by_id.get(call_id) if isinstance(call_id, str) else None
        payload = deepcopy(copied.payload)
        payload["content"] = _level1_template(name, payload, call)
        slimmed.append(replace(copied, payload=payload))
    return slimmed


def render_compacted_history(state: dict[str, object]) -> str:
    """Deterministic ``[COMPACTED HISTORY]`` block from the 8-key checkpoint."""
    lines = ["[COMPACTED HISTORY]"]
    for key in COMPACTED_STATE_KEYS:
        lines.append(f"{key}:")
        items = state.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if key == "reloadable_details" and isinstance(item, dict):
                lines.append(f"- tool={item.get('tool', '')} args_hint={item.get('args_hint', '')}")
            else:
                lines.append(f"- {item}")
    return "\n".join(lines)


def _assemble(
    *,
    session: AgentSession,
    situation_text: str,
    system_text: str,
    token_counter: Callable[[list[object]], int],
    watermark: int | None,
    compacted_state: dict[str, object] | None,
    skill_text: str = "",
) -> PromptAssembly:
    messages: list[object] = [SystemPromptMessage(content=system_text)]
    if watermark is not None and compacted_state is not None:
        messages.append(UserPromptMessage(content=render_compacted_history(compacted_state)))
    for message in session.messages:
        if watermark is not None and message.sequence <= watermark:
            continue
        messages.append(_to_prompt_message(message))
    messages.append(UserPromptMessage(content=situation_text))
    if skill_text:
        messages.append(UserPromptMessage(content=skill_text))
    return PromptAssembly(
        messages=messages,
        prompt_tokens=token_counter(messages),
        compacted_until_sequence=watermark,
        compacted_state=deepcopy(compacted_state) if compacted_state is not None else None,
    )


def _fold_once(
    *,
    session: AgentSession,
    watermark: int | None,
    compacted_state: dict[str, object] | None,
    limits: TokenLimits,
    compact: Callable[..., dict[str, object]] | None,
    situation_text: str,
) -> tuple[int, dict[str, object]] | None:
    if compact is None:
        return None
    segment = _oldest_legal_segment(session.messages, watermark)
    if not segment:
        return None
    slimmed = _fit_compactor_window(slim_segment(segment), limits.compactor_input_limit)
    if not slimmed:
        return None
    new_state = compact(compacted_state=compacted_state, segment=slimmed, situation_text=situation_text)
    if not _is_valid_compacted_state(new_state):
        return None
    new_watermark = slimmed[-1].sequence
    if watermark is not None and new_watermark <= watermark:
        return None
    return new_watermark, deepcopy(new_state)


def _oldest_legal_segment(messages: Sequence[AgentMessage], watermark: int | None) -> list[AgentMessage]:
    """Contiguous prefix after the watermark, stopping before the protected suffix.

    Protected: last two model turns (and their tool_results), pending
    ``ask_user``, and in-flight tool_calls. Stopping at the first protected
    message keeps the live prompt free of holes.
    """
    protected = _protected_sequences(messages)
    segment: list[AgentMessage] = []
    for message in messages:
        if watermark is not None and message.sequence <= watermark:
            continue
        if message.sequence in protected:
            break
        segment.append(message)
    return segment


def _protected_sequences(messages: Sequence[AgentMessage]) -> set[int]:
    """Return sequences that must stay in the live prompt, not the folded prefix.

    Protects the last two *model turns*, not the last two tool_call rows.
    Native multi-tool emits several tool_call rows from one invocation:
    consecutive tool_calls before their results are one turn; a tool_call
    immediately after a tool_result (or an assistant prose message) starts a
    new turn. Pending ``ask_user`` and in-flight tool_calls are always
    excluded, even when they are older than those two turns.
    """
    protected: set[int] = set()
    turns = _model_turns(messages)
    for turn in turns[-_PROTECTED_INVOCATIONS:]:
        protected.update(message.sequence for message in turn)

    result_ids = {message.payload.get("tool_call_id") for message in messages if message.event_type == "tool_result"}
    for message in messages:
        if message.event_type != "tool_call":
            continue
        call_id = message.payload.get("id")
        in_flight = isinstance(call_id, str) and call_id not in result_ids
        pending_ask = message.payload.get("name") == "ask_user" and message.status == "pending"
        if in_flight or pending_ask:
            protected.add(message.sequence)
    return protected


def _model_turns(messages: Sequence[AgentMessage]) -> list[list[AgentMessage]]:
    """Group assistant rows into model invocations (turns).

    A new turn starts at an assistant prose message, or at a tool_call that
    does not continue the current in-flight batch.
    """
    turns: list[list[AgentMessage]] = []
    current: list[AgentMessage] = []
    pending_ids: set[str] = set()

    def flush() -> None:
        nonlocal current, pending_ids
        if current:
            turns.append(current)
        current = []
        pending_ids = set()

    for message in messages:
        if message.event_type == "message" and message.role == "assistant":
            flush()
            turns.append([message])
            continue
        if message.event_type == "tool_call":
            if not pending_ids:
                flush()
            current.append(message)
            call_id = message.payload.get("id")
            if isinstance(call_id, str) and call_id:
                pending_ids.add(call_id)
            continue
        if message.event_type == "tool_result" and current:
            current.append(message)
            call_id = message.payload.get("tool_call_id")
            if isinstance(call_id, str):
                pending_ids.discard(call_id)
    flush()
    return turns


def _fit_compactor_window(segment: list[AgentMessage], limit: int) -> list[AgentMessage]:
    """Shorten from the newest end if the slimmed copy exceeds the Compactor window.

    After popping for size, walk back so the prefix ends on closed tool pairs:
    no tool_call in C without its result, and no result left in the raw window
    whose call was folded. Estimates Compactor input from prompt text, not the
    live ``token_counter`` (tests inject COMPACTED-HISTORY-aware stubs).
    """
    fitted = list(segment)
    while len(fitted) > 1 and _segment_token_estimate(fitted) > limit:
        fitted.pop()
    return _close_tool_pairs(fitted)


def _close_tool_pairs(fitted: list[AgentMessage]) -> list[AgentMessage]:
    closed = list(fitted)
    while closed and not _tool_pairs_closed(closed):
        closed.pop()
    return closed


def _tool_pairs_closed(messages: Sequence[AgentMessage]) -> bool:
    call_ids = {
        message.payload.get("id")
        for message in messages
        if message.event_type == "tool_call" and isinstance(message.payload.get("id"), str)
    }
    result_ids = {
        message.payload.get("tool_call_id")
        for message in messages
        if message.event_type == "tool_result" and isinstance(message.payload.get("tool_call_id"), str)
    }
    return call_ids == result_ids


def _segment_token_estimate(segment: Sequence[AgentMessage]) -> int:
    """Count converted prompt text. ``len(str(segment))//4`` undercounts Chinese."""
    parts = [_prompt_message_text(_to_prompt_message(message)) for message in segment]
    return max(1, len("\n".join(parts)))


def _is_valid_compacted_state(value: object) -> bool:
    if not isinstance(value, dict) or set(value.keys()) != set(COMPACTED_STATE_KEYS):
        return False
    return all(isinstance(value[key], list) for key in COMPACTED_STATE_KEYS)


def _is_level1_tool(name: str) -> bool:
    if name in _NEVER_SLIM_TOOLS:
        return False
    return name in _LEVEL1_TOOLS or name.startswith("search_")


def _tool_calls_by_id(messages: Sequence[AgentMessage]) -> dict[str, AgentMessage]:
    calls: dict[str, AgentMessage] = {}
    for message in messages:
        if message.event_type != "tool_call":
            continue
        call_id = message.payload.get("id")
        if isinstance(call_id, str) and call_id:
            calls[call_id] = message
    return calls


def _level1_template(name: str, payload: dict[str, Any], call: AgentMessage | None) -> str:
    args = _call_arguments(call)
    content = payload.get("content")
    content_dict = content if isinstance(content, dict) else {}
    if name == "read_node":
        node_id = content_dict.get("id") or args.get("id") or "?"
        return f"[COMPRESSED] node {node_id}; config evicted; call read_node to reload"
    if name == "inspect_node_schema":
        node_type = args.get("node_type") or args.get("type") or content_dict.get("type") or "?"
        return f"[COMPRESSED] schema for {node_type}; call inspect_node_schema to reload"
    if name == "read_graph":
        nodes = content_dict.get("nodes")
        ids: list[str] = []
        if isinstance(nodes, list):
            ids = [str(node.get("id")) for node in nodes if isinstance(node, dict) and node.get("id")]
        return f"[COMPRESSED] compact graph; {len(ids)} nodes: {', '.join(ids)}; call read_graph to reload"
    if name == "inspect_tool":
        binding = content_dict.get("binding")
        binding_dict = binding if isinstance(binding, dict) else {}
        provider = binding_dict.get("provider_name") or args.get("provider_name") or "?"
        tool = binding_dict.get("tool_name") or args.get("tool_name") or "?"
        return f"[COMPRESSED] inspected tool {provider}/{tool}; schema evicted; call inspect_tool to reload"
    if name.startswith("search_"):
        query = args.get("query") or ""
        hits = content_dict.get("hits")
        count = len(hits) if isinstance(hits, list) else 0
        return f"[COMPRESSED] {name} query={query}; {count} hits evicted; call {name} to reload"
    if name == "validate_graph":
        valid = content_dict.get("valid")
        return f"[COMPRESSED] validation; valid={valid}; codes evicted; call validate_graph to reload"
    if name == "run_acceptance":
        passed = content_dict.get("passed")
        attempt_id = content_dict.get("attempt_id") or "?"
        return (
            f"[COMPRESSED] acceptance attempt {attempt_id} passed={passed}; "
            "trace evicted; call inspect_attempt to reload"
        )
    if name == "inspect_attempt":
        attempt_id = content_dict.get("attempt_id") or args.get("attempt_id") or "?"
        return f"[COMPRESSED] attempt {attempt_id}; call inspect_attempt to reload"
    return f"[COMPRESSED] {name}; call {name} to reload"


def _call_arguments(call: AgentMessage | None) -> dict[str, Any]:
    if call is None:
        return {}
    arguments = call.payload.get("arguments")
    return arguments if isinstance(arguments, dict) else {}


def _copy_message(message: AgentMessage) -> AgentMessage:
    return replace(message, payload=deepcopy(message.payload))


def _to_prompt_message(message: AgentMessage) -> object:
    if message.event_type == "message":
        text = str(message.payload.get("text") or "")
        if message.role == "user":
            return UserPromptMessage(content=text)
        return AssistantPromptMessage(content=text)
    body = _payload_text(message.payload)
    if message.event_type == "tool_result":
        return ToolPromptMessage(
            content=body,
            name=str(message.payload.get("name") or ""),
            tool_call_id=str(message.payload.get("tool_call_id") or ""),
        )
    return AssistantPromptMessage(content=body, tool_calls=[_assistant_tool_call(message)])


def _assistant_tool_call(message: AgentMessage) -> AssistantPromptMessage.ToolCall:
    arguments = message.payload.get("arguments")
    if isinstance(arguments, str):
        args_text = arguments
    else:
        args_text = json.dumps(arguments if isinstance(arguments, dict) else {}, ensure_ascii=False, default=str)
    return AssistantPromptMessage.ToolCall(
        id=str(message.payload.get("id") or ""),
        type="function",
        function=AssistantPromptMessage.ToolCall.ToolCallFunction(
            name=str(message.payload.get("name") or ""),
            arguments=args_text,
        ),
    )


def _prompt_message_text(prompt: object) -> str:
    parts = [str(getattr(prompt, "content", "") or "")]
    for call in getattr(prompt, "tool_calls", None) or []:
        function = getattr(call, "function", None)
        if function is not None:
            parts.append(str(getattr(function, "name", "") or ""))
            parts.append(str(getattr(function, "arguments", "") or ""))
    return "\n".join(parts)


def _payload_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)
