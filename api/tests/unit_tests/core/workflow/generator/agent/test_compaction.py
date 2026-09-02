from collections.abc import Sequence
from typing import Any

import pytest

from core.workflow.generator.agent.compaction import (
    TokenLimits,
    _fit_compactor_window,
    _segment_token_estimate,
    assemble_prompt,
    slim_segment,
)
from core.workflow.generator.agent.types import AgentMessage, AgentMessageEventType, AgentMessageRole, AgentSession
from core.workflow.generator.planner_context import PlannerContextLimitError
from graphon.model_runtime.entities.message_entities import AssistantPromptMessage, ToolPromptMessage


def _limits(*, input_limit: int = 1000, compactor_input_limit: int = 400) -> TokenLimits:
    return TokenLimits(
        input_limit=input_limit,
        compact_trigger=int(input_limit * 0.8),
        compact_target=int(input_limit * 0.7),
        compactor_input_limit=compactor_input_limit,
    )


def _valid_state(**overrides: object) -> dict[str, object]:
    state: dict[str, object] = {
        "objective": ["构建 RAG 测试工作流"],
        "user_constraints": [],
        "confirmed_facts": [],
        "decisions": [],
        "rejected_approaches": [],
        "important_resources": [],
        "pending_work": [],
        "reloadable_details": [],
    }
    state.update(overrides)
    return state


def _trigger_counter(msgs: list) -> int:
    text = "\n".join(getattr(m, "content", "") or "" for m in msgs)
    if "[COMPACTED HISTORY]" in text:
        return 50
    return 900


def _message(
    sequence: int,
    event_type: AgentMessageEventType,
    role: AgentMessageRole,
    payload: dict[str, Any],
    *,
    status: str = "completed",
) -> AgentMessage:
    return AgentMessage(
        sequence=sequence,
        event_type=event_type,
        role=role,
        status=status,
        payload=payload,
    )


def _session(
    messages: Sequence[AgentMessage],
    *,
    compacted_until_sequence: int | None = None,
    compacted_state: dict[str, Any] | None = None,
) -> AgentSession:
    return AgentSession(
        messages=list(messages),
        candidate_graph=None,
        candidate_revision=0,
        candidate_base_hash=None,
        compacted_until_sequence=compacted_until_sequence,
        compacted_state=compacted_state,
        generation_mode="workflow",
        last_validation=None,
    )


@pytest.fixture
def session_with_messages() -> AgentSession:
    return _session(
        [
            _message(1, "message", "user", {"text": "做 RAG 测试工作流"}),
            _message(2, "message", "assistant", {"text": "先读检索节点"}),
            _message(3, "message", "user", {"text": "继续"}),
        ]
    )


@pytest.fixture
def session_with_read_node_payload() -> AgentSession:
    return _session(
        [
            _message(1, "message", "user", {"text": "检查检索节点"}),
            _message(
                2,
                "tool_call",
                "assistant",
                {"id": "call_read", "name": "read_node", "arguments": {"id": "kr"}},
            ),
            _message(
                3,
                "tool_result",
                "assistant",
                {
                    "tool_call_id": "call_read",
                    "name": "read_node",
                    "content": {
                        "id": "kr",
                        "type": "knowledge-retrieval",
                        "title": "检索",
                        "config": {"blob": "6000-token-config"},
                    },
                },
            ),
        ]
    )


@pytest.fixture
def session_over_trigger() -> AgentSession:
    """Five-plus messages with a huge read_node result outside the last two model turns."""
    return _session(_session_over_trigger_messages())


def test_below_80_percent_keeps_raw_history_and_does_not_call_compactor(session_with_messages) -> None:
    calls: list[int] = []

    def compact(**kwargs: object) -> dict[str, object]:
        calls.append(1)
        raise AssertionError("must not compact")

    assembly = assemble_prompt(
        session=session_with_messages,
        situation_text="# Current situation\ncandidate_revision: 1",
        system_text="system",
        limits=_limits(input_limit=10_000),
        token_counter=lambda msgs: 100,
        compact=compact,
    )
    rendered = "\n".join(getattr(m, "content", "") for m in assembly.messages)
    assert "[COMPRESSED]" not in rendered
    assert "# Current situation" in rendered
    assert rendered.strip().endswith("candidate_revision: 1") or rendered.rstrip().endswith("1")


def test_assemble_prompt_omits_stored_reasoning_from_model_history() -> None:
    session = _session(
        [
            _message(1, "message", "user", {"text": "做 RAG"}),
            _message(
                2,
                "message",
                "assistant",
                {"text": "开始改图", "reasoning": "先读检索节点再接线"},
            ),
        ]
    )
    assembly = assemble_prompt(
        session=session,
        situation_text="# Current situation",
        system_text="system",
        limits=_limits(input_limit=10_000),
        token_counter=lambda msgs: 10,
    )
    rendered = "\n".join(str(getattr(item, "content", "") or "") for item in assembly.messages)
    assert "开始改图" in rendered
    assert "先读检索节点再接线" not in rendered


def test_assemble_appends_active_skill_after_situation(session_with_messages) -> None:
    assembly = assemble_prompt(
        session=session_with_messages,
        situation_text="# Current situation\ncandidate_revision: 1",
        system_text="system",
        limits=_limits(input_limit=10_000),
        token_counter=lambda msgs: 100,
        skill_text="# Active playbook: create-from-scratch\nread_graph first",
    )
    contents = [getattr(m, "content", "") for m in assembly.messages]
    assert contents[-2] == "# Current situation\ncandidate_revision: 1"
    assert contents[-1] == "# Active playbook: create-from-scratch\nread_graph first"


def test_level1_does_not_rewrite_live_prompt(session_with_read_node_payload) -> None:
    assembly = assemble_prompt(
        session=session_with_read_node_payload,
        situation_text="sit",
        system_text="system",
        limits=_limits(input_limit=10_000),
        token_counter=lambda msgs: 100,
        compact=None,
    )
    rendered = "\n".join(getattr(m, "content", "") for m in assembly.messages)
    assert "6000-token-config" in rendered
    assert "[COMPRESSED]" not in rendered


def test_checkpoint_advances_watermark_and_hides_folded_raw_text(session_over_trigger) -> None:
    original_rows = list(session_over_trigger.messages)

    def compact(*, compacted_state: dict | None, segment: list, **kwargs: object) -> dict[str, object]:
        assert "[COMPRESSED]" in str(segment)
        return {
            "objective": ["构建 RAG 测试工作流"],
            "user_constraints": [],
            "confirmed_facts": [],
            "decisions": [],
            "rejected_approaches": [],
            "important_resources": [],
            "pending_work": [],
            "reloadable_details": [{"tool": "read_node", "args_hint": "kr"}],
        }

    def counter(msgs: list) -> int:
        text = "\n".join(getattr(m, "content", "") for m in msgs)
        if "[COMPACTED HISTORY]" in text:
            return 50
        return 900

    assembly = assemble_prompt(
        session=session_over_trigger,
        situation_text="sit",
        system_text="system",
        limits=_limits(input_limit=1000),
        token_counter=counter,
        compact=compact,
    )
    rendered = "\n".join(getattr(m, "content", "") for m in assembly.messages)
    assert "[COMPACTED HISTORY]" in rendered
    assert "[COMPRESSED]" not in rendered
    assert assembly.compacted_until_sequence == 3
    assert session_over_trigger.messages == original_rows  # 消息行未改


def test_cold_start_compactor_sees_segment_only(session_over_trigger) -> None:
    session_over_trigger.compacted_state = None
    session_over_trigger.compacted_until_sequence = None
    seen: dict[str, object] = {}

    def compact(*, compacted_state: dict | None, segment: list, **kwargs: object) -> dict[str, object]:
        seen["state"] = compacted_state
        seen["segment_len"] = len(segment)
        return {
            k: []
            for k in (
                "objective",
                "user_constraints",
                "confirmed_facts",
                "decisions",
                "rejected_approaches",
                "important_resources",
                "pending_work",
            )
        } | {"reloadable_details": []}

    assemble_prompt(
        session=session_over_trigger,
        situation_text="sit",
        system_text="system",
        limits=_limits(input_limit=1000),
        token_counter=lambda msgs: 50 if any("[COMPACTED HISTORY]" in getattr(m, "content", "") for m in msgs) else 900,
        compact=compact,
    )
    assert seen["state"] is None
    assert seen["segment_len"] > 0


def test_compactor_schema_failure_invokes_fat_prompt_when_under_limit(session_over_trigger) -> None:
    def compact(**kwargs: object) -> dict[str, object]:
        return {"objective": "not-a-list"}  # 非法

    assembly = assemble_prompt(
        session=session_over_trigger,
        situation_text="sit",
        system_text="system",
        limits=_limits(input_limit=1000),
        token_counter=lambda msgs: 850,
        compact=compact,
    )
    assert assembly.compacted_until_sequence == session_over_trigger.compacted_until_sequence
    rendered = "\n".join(getattr(m, "content", "") for m in assembly.messages)
    assert "[COMPRESSED]" not in rendered


def test_slim_segment_compresses_read_node_copy_only(session_with_read_node_payload) -> None:
    original = list(session_with_read_node_payload.messages)
    slimmed = slim_segment(original)
    assert "[COMPRESSED]" in str(slimmed)
    assert "6000-token-config" not in str(slimmed)
    assert "6000-token-config" in str(original)
    assert original == session_with_read_node_payload.messages


def test_slim_segment_points_acceptance_trace_at_inspect_attempt() -> None:
    session = _session(
        [
            _message(1, "message", "user", {"text": "验收"}),
            _message(2, "tool_call", "assistant", {"id": "call_acc", "name": "run_acceptance", "arguments": {}}),
            _message(
                3,
                "tool_result",
                "assistant",
                {
                    "tool_call_id": "call_acc",
                    "name": "run_acceptance",
                    "content": {
                        "passed": False,
                        "attempt_id": "att-9",
                        "failed_nodes": [{"id": "end", "error": "missing output"}],
                    },
                },
            ),
        ]
    )
    slimmed = slim_segment(session.messages)
    rendered = str(slimmed)
    assert "[COMPRESSED] acceptance attempt att-9 passed=False" in rendered
    assert "inspect_attempt" in rendered
    assert "missing output" not in rendered


def test_over_limit_without_legal_fold_raises_context_limit(session_over_trigger) -> None:
    with pytest.raises(PlannerContextLimitError):
        assemble_prompt(
            session=session_over_trigger,
            situation_text="sit",
            system_text="system",
            limits=_limits(input_limit=1000),
            token_counter=lambda msgs: 2000,
            compact=None,
        )


def _prompt_text(assembly: object) -> str:
    return "\n".join(str(getattr(message, "content", "") or "") for message in assembly.messages)


def test_over_limit_omits_compacted_history_and_keeps_checkpoint(session_over_trigger) -> None:
    original_rows = list(session_over_trigger.messages)
    compact_calls: list[int] = []

    def compact(**kwargs: object) -> dict[str, object]:
        compact_calls.append(1)
        return _valid_state()

    def counter(msgs: list) -> int:
        text = "\n".join(str(getattr(message, "content", "") or "") for message in msgs)
        if "[COMPACTED HISTORY]" in text:
            return 1500
        if "6000-token-config" in text:
            return 2000
        return 400

    assembly = assemble_prompt(
        session=session_over_trigger,
        situation_text="sit",
        system_text="system",
        limits=_limits(input_limit=1000),
        token_counter=counter,
        compact=compact,
    )

    rendered = _prompt_text(assembly)
    assert "[COMPACTED HISTORY]" not in rendered
    assert "6000-token-config" not in rendered
    assert "做 RAG 测试工作流" not in rendered
    assert assembly.compacted_until_sequence == 3
    assert assembly.compacted_state == _valid_state()
    assert compact_calls == [1]
    assert session_over_trigger.messages == original_rows


def test_over_limit_hard_drops_unprotected_prefix_without_compactor() -> None:
    session = _session(
        [
            _message(1, "message", "user", {"text": "EARLY_USER"}),
            _message(2, "tool_call", "assistant", {"id": "c1", "name": "read_node", "arguments": {"id": "kr"}}),
            _message(
                3,
                "tool_result",
                "assistant",
                {"tool_call_id": "c1", "name": "read_node", "content": {"blob": "OLD_BLOB"}},
            ),
            _message(4, "tool_call", "assistant", {"id": "c2", "name": "build_node", "arguments": {"id": "n1"}}),
            _message(
                5,
                "tool_result",
                "assistant",
                {"tool_call_id": "c2", "name": "build_node", "ok": True, "content": {"id": "n1"}},
            ),
            _message(6, "tool_call", "assistant", {"id": "c3", "name": "validate_graph", "arguments": {}}),
            _message(
                7,
                "tool_result",
                "assistant",
                {"tool_call_id": "c3", "name": "validate_graph", "ok": True, "content": {"ok": True}},
            ),
        ]
    )
    def counter(msgs: list) -> int:
        text = "\n".join(str(getattr(message, "content", "") or "") for message in msgs)
        if "EARLY_USER" in text or "OLD_BLOB" in text:
            return 2000
        return 400

    assembly = assemble_prompt(
        session=session,
        situation_text="sit",
        system_text="system",
        limits=_limits(input_limit=1000),
        token_counter=counter,
        compact=None,
    )

    rendered = _prompt_text(assembly)
    assert "EARLY_USER" not in rendered
    assert "OLD_BLOB" not in rendered
    assert "[COMPACTED HISTORY]" not in rendered
    assert assembly.compacted_until_sequence == 3
    assert assembly.compacted_state is None
    assert session.messages[0].payload["text"] == "EARLY_USER"


def test_protected_tail_still_over_limit_raises_context_limit() -> None:
    session = _session(
        [
            _message(1, "tool_call", "assistant", {"id": "c1", "name": "read_graph", "arguments": {}}),
            _message(
                2,
                "tool_result",
                "assistant",
                {"tool_call_id": "c1", "name": "read_graph", "content": {"blob": "TAIL_BLOB"}},
            ),
            _message(3, "tool_call", "assistant", {"id": "c2", "name": "validate_graph", "arguments": {}}),
            _message(
                4,
                "tool_result",
                "assistant",
                {"tool_call_id": "c2", "name": "validate_graph", "content": {"ok": True}},
            ),
        ]
    )

    with pytest.raises(PlannerContextLimitError):
        assemble_prompt(
            session=session,
            situation_text="sit",
            system_text="system",
            limits=_limits(input_limit=1000),
            token_counter=lambda msgs: 2000,
            compact=lambda **kwargs: _valid_state(),
        )


def _call_and_result_ids(messages: Sequence[AgentMessage]) -> tuple[set[object], set[object]]:
    call_ids = {message.payload.get("id") for message in messages if message.event_type == "tool_call"}
    result_ids = {message.payload.get("tool_call_id") for message in messages if message.event_type == "tool_result"}
    return call_ids, result_ids


def test_fit_window_does_not_split_tool_call_result_pair() -> None:
    segment = [
        _message(1, "message", "user", {"text": "做 RAG"}),
        _message(2, "tool_call", "assistant", {"id": "call_read", "name": "read_node", "arguments": {"id": "kr"}}),
        _message(
            3,
            "tool_result",
            "assistant",
            {"tool_call_id": "call_read", "name": "read_node", "content": {"id": "kr"}},
        ),
    ]
    prefix_tokens = _segment_token_estimate(segment[:2])
    full_tokens = _segment_token_estimate(segment)
    assert prefix_tokens < full_tokens

    fitted = _fit_compactor_window(segment, prefix_tokens)
    call_ids, result_ids = _call_and_result_ids(fitted)
    assert call_ids == result_ids
    assert [message.sequence for message in fitted] == [1]


def test_protects_last_two_turns_not_tool_call_rows() -> None:
    session = _session(
        [
            _message(1, "message", "user", {"text": "做 RAG 测试工作流"}),
            _message(2, "tool_call", "assistant", {"id": "call_prev", "name": "read_node", "arguments": {"id": "kr"}}),
            _message(
                3,
                "tool_result",
                "assistant",
                {"tool_call_id": "call_prev", "name": "read_node", "content": {"id": "kr"}},
            ),
            _message(4, "tool_call", "assistant", {"id": "call_a", "name": "read_graph", "arguments": {}}),
            _message(
                5,
                "tool_call",
                "assistant",
                {"id": "call_b", "name": "inspect_node_schema", "arguments": {"node_type": "llm"}},
            ),
            _message(
                6,
                "tool_result",
                "assistant",
                {"tool_call_id": "call_a", "name": "read_graph", "content": {"nodes": []}},
            ),
            _message(
                7,
                "tool_result",
                "assistant",
                {"tool_call_id": "call_b", "name": "inspect_node_schema", "content": {"type": "llm"}},
            ),
        ]
    )
    seen: list[int] = []

    def compact(*, compacted_state: dict | None, segment: list, **kwargs: object) -> dict[str, object]:
        seen.extend(message.sequence for message in segment)
        return _valid_state()

    assembly = assemble_prompt(
        session=session,
        situation_text="sit",
        system_text="system",
        limits=_limits(input_limit=1000),
        token_counter=_trigger_counter,
        compact=compact,
    )
    assert seen == [1]
    assert assembly.compacted_until_sequence == 1
    assert 2 not in seen
    assert 3 not in seen


def test_pending_ask_user_is_not_in_folded_prefix() -> None:
    session = _session(
        [
            *_session_over_trigger_messages(),
            _message(
                8,
                "tool_call",
                "assistant",
                {"id": "call_ask", "name": "ask_user", "arguments": {"questions": []}},
                status="pending",
            ),
        ]
    )
    seen: list[AgentMessage] = []

    def compact(*, compacted_state: dict | None, segment: list, **kwargs: object) -> dict[str, object]:
        seen.extend(segment)
        return _valid_state()

    assemble_prompt(
        session=session,
        situation_text="sit",
        system_text="system",
        limits=_limits(input_limit=1000),
        token_counter=_trigger_counter,
        compact=compact,
    )
    assert seen
    assert all(message.payload.get("name") != "ask_user" for message in seen)
    assert all(message.sequence != 8 for message in seen)


def test_in_flight_tool_call_is_not_in_folded_prefix() -> None:
    session = _session(
        [
            *_session_over_trigger_messages(),
            _message(8, "tool_call", "assistant", {"id": "call_open", "name": "read_graph", "arguments": {}}),
        ]
    )
    seen: list[AgentMessage] = []

    def compact(*, compacted_state: dict | None, segment: list, **kwargs: object) -> dict[str, object]:
        seen.extend(segment)
        return _valid_state()

    assemble_prompt(
        session=session,
        situation_text="sit",
        system_text="system",
        limits=_limits(input_limit=1000),
        token_counter=_trigger_counter,
        compact=compact,
    )
    assert seen
    assert all(message.payload.get("id") != "call_open" for message in seen)
    assert all(message.sequence != 8 for message in seen)


def test_segment_token_estimate_counts_prompt_text_not_repr_over_four() -> None:
    chinese = "检索节点配置" * 50
    messages = [_message(1, "message", "user", {"text": chinese})]
    estimate = _segment_token_estimate(messages)
    naive = max(1, len(str(messages)) // 4)
    assert estimate >= len(chinese)
    assert estimate > naive


def test_live_prompt_uses_native_tool_calls_and_keeps_content(session_with_read_node_payload) -> None:
    assembly = assemble_prompt(
        session=session_with_read_node_payload,
        situation_text="sit",
        system_text="system",
        limits=_limits(input_limit=10_000),
        token_counter=lambda msgs: 100,
        compact=None,
    )
    tool_call_messages = [message for message in assembly.messages if getattr(message, "tool_calls", None)]
    assert tool_call_messages
    assert isinstance(tool_call_messages[0], AssistantPromptMessage)
    assert tool_call_messages[0].tool_calls[0].function.name == "read_node"
    results = [message for message in assembly.messages if isinstance(message, ToolPromptMessage)]
    assert results
    assert results[0].tool_call_id == "call_read"
    rendered = "\n".join(getattr(m, "content", "") or "" for m in assembly.messages)
    assert "6000-token-config" in rendered
    assert "[COMPRESSED]" not in rendered


def _session_over_trigger_messages() -> list[AgentMessage]:
    return [
        _message(1, "message", "user", {"text": "做 RAG 测试工作流"}),
        _message(2, "tool_call", "assistant", {"id": "call_read", "name": "read_node", "arguments": {"id": "kr"}}),
        _message(
            3,
            "tool_result",
            "assistant",
            {
                "tool_call_id": "call_read",
                "name": "read_node",
                "ok": True,
                "changed": False,
                "content": {
                    "id": "kr",
                    "type": "knowledge-retrieval",
                    "title": "检索",
                    "config": {"blob": "6000-token-config " * 200},
                },
            },
        ),
        _message(
            4,
            "tool_call",
            "assistant",
            {"id": "call_build", "name": "build_node", "arguments": {"mode": "create", "id": "kr"}},
        ),
        _message(
            5,
            "tool_result",
            "assistant",
            {"tool_call_id": "call_build", "name": "build_node", "ok": True, "changed": True, "content": {"id": "kr"}},
        ),
        _message(6, "tool_call", "assistant", {"id": "call_validate", "name": "validate_graph", "arguments": {}}),
        _message(
            7,
            "tool_result",
            "assistant",
            {
                "tool_call_id": "call_validate",
                "name": "validate_graph",
                "ok": True,
                "changed": False,
                "content": {"valid": False, "errors": [{"code": "MISSING_END"}]},
            },
        ),
    ]
