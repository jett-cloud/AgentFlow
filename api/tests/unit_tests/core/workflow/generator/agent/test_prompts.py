from dataclasses import replace

from core.workflow.generator.agent.compaction import TokenLimits, assemble_prompt
from core.workflow.generator.agent.prompts import render_current_situation
from core.workflow.generator.agent.types import AgentMessage, AgentSession


def _limits(*, input_limit: int = 1000) -> TokenLimits:
    return TokenLimits(
        input_limit=input_limit,
        compact_trigger=int(input_limit * 0.8),
        compact_target=int(input_limit * 0.7),
        compactor_input_limit=400,
    )


def _session_with_config_node(*, message_count: int = 3) -> AgentSession:
    messages = [
        AgentMessage(
            sequence=1,
            event_type="message",
            role="user",
            status="completed",
            payload={"text": "做 RAG 测试工作流"},
        ),
        AgentMessage(
            sequence=2,
            event_type="tool_call",
            role="assistant",
            status="completed",
            payload={"id": "call_read", "name": "read_node", "arguments": {"id": "kr"}},
        ),
        AgentMessage(
            sequence=3,
            event_type="tool_result",
            role="assistant",
            status="completed",
            payload={
                "tool_call_id": "call_read",
                "name": "read_node",
                "content": {"id": "kr", "config": {"blob": "6000-token-config"}},
            },
        ),
        AgentMessage(
            sequence=4,
            event_type="tool_call",
            role="assistant",
            status="completed",
            payload={"id": "call_search", "name": "search_datasets", "arguments": {"query": "kb"}},
        ),
        AgentMessage(
            sequence=5,
            event_type="tool_result",
            role="assistant",
            status="completed",
            payload={"tool_call_id": "call_search", "name": "search_datasets", "content": {"hits": []}},
        ),
        AgentMessage(
            sequence=6,
            event_type="message",
            role="assistant",
            status="completed",
            payload={"text": "下一步校验"},
        ),
    ]
    graph = {
        "nodes": [
            {
                "id": "kr",
                "data": {
                    "type": "knowledge-retrieval",
                    "title": "检索",
                    "query_template": "secret-config-value",
                    "dataset_ids": ["ds-secret"],
                    "catalogue": "tenant-catalogue-must-not-leak",
                },
            },
            {
                "id": "start",
                "data": {"type": "start", "title": "开始"},
            },
        ],
        "edges": [{"source": "start", "target": "kr"}],
        "viewport": {"x": 0.0, "y": 0.0, "zoom": 0.7},
    }
    return AgentSession(
        messages=messages[:message_count] if message_count < len(messages) else messages,
        candidate_graph=graph,
        candidate_revision=3,
        candidate_base_hash="abc123",
        compacted_until_sequence=None,
        compacted_state=None,
        generation_mode="workflow",
        last_validation=None,
    )


def test_current_situation_omits_node_config_and_catalogue() -> None:
    session = _session_with_config_node()
    text = render_current_situation(session)
    assert "secret-config-value" not in text
    assert "ds-secret" not in text
    assert "tenant-catalogue-must-not-leak" not in text
    assert "catalogue" not in text.lower()
    assert "kr" in text
    assert "knowledge-retrieval" in text
    assert "检索" in text
    assert "candidate_revision: 3" in text
    assert "# Current situation" in text


def test_current_situation_stays_at_tail_below_and_above_trigger() -> None:
    session = _session_with_config_node()
    situation = render_current_situation(session)

    below = assemble_prompt(
        session=session,
        situation_text=situation,
        system_text="system",
        limits=_limits(input_limit=10_000),
        token_counter=lambda msgs: 100,
        compact=None,
    )
    below_text = "\n".join(getattr(m, "content", "") or "" for m in below.messages)
    assert below_text.rstrip().endswith(situation.rstrip())
    assert "[COMPRESSED]" not in below_text

    def compact(*, compacted_state: dict | None, segment: list, **kwargs: object) -> dict[str, object]:
        return {
            "objective": ["构建 RAG 测试工作流"],
            "user_constraints": [],
            "confirmed_facts": [],
            "decisions": [],
            "rejected_approaches": [],
            "important_resources": [],
            "pending_work": [],
            "reloadable_details": [],
        }

    above = assemble_prompt(
        session=session,
        situation_text=situation,
        system_text="system",
        limits=_limits(input_limit=1000),
        token_counter=lambda msgs: (
            50 if any("[COMPACTED HISTORY]" in (getattr(m, "content", "") or "") for m in msgs) else 900
        ),
        compact=compact,
    )
    above_text = "\n".join(getattr(m, "content", "") or "" for m in above.messages)
    assert above_text.rstrip().endswith(situation.rstrip())
    assert "[COMPRESSED]" not in above_text


def test_last_finish_stays_none_when_only_validate_graph_passed() -> None:
    session = replace(
        _session_with_config_node(),
        candidate_revision=3,
        last_validation={"valid": True, "validated_revision": 3, "errors": []},
    )
    text = render_current_situation(session)
    assert "last_finish: none" in text
    assert "last_validation: ok @3" in text
    assert "last_acceptance: none" in text


def test_last_finish_is_success_only_after_accepted_finish() -> None:
    base = _session_with_config_node()
    session = replace(
        base,
        candidate_revision=3,
        last_validation={"valid": True, "validated_revision": 3, "errors": []},
        messages=[
            *base.messages,
            AgentMessage(
                sequence=7,
                event_type="tool_call",
                role="assistant",
                status="completed",
                payload={"id": "call_finish", "name": "finish", "arguments": {"summary": "完成"}},
            ),
            AgentMessage(
                sequence=8,
                event_type="tool_result",
                role="assistant",
                status="completed",
                payload={
                    "tool_call_id": "call_finish",
                    "name": "finish",
                    "ok": True,
                    "changed": False,
                    "content": {"valid": True, "errors": [], "summary": "完成"},
                    "error": None,
                    "error_code": None,
                    "retryable": False,
                },
            ),
        ],
    )
    text = render_current_situation(session)
    assert "last_finish: success (not applied)" in text
    assert "last_validation: ok @3" in text


def test_last_validation_error_label_includes_count_revision_and_codes() -> None:
    session = replace(
        _session_with_config_node(),
        candidate_revision=4,
        last_validation={
            "valid": False,
            "validated_revision": 4,
            "errors": [
                {"code": "MISSING_END", "node_id": "start", "detail": "no end"},
                {"code": "UNKNOWN_DATASET", "node_id": "kr", "detail": "bad ds"},
            ],
        },
    )
    text = render_current_situation(session)
    assert "last_validation: 2 errors @4 (MISSING_END@start, UNKNOWN_DATASET@kr)" in text
    assert "last_finish: none" in text
    assert "last_acceptance: none" in text


def test_last_acceptance_failed_label_includes_nodes() -> None:
    session = replace(
        _session_with_config_node(),
        candidate_revision=4,
        last_acceptance={
            "passed": False,
            "revision": 4,
            "reason": "ASSERTION_FAILED",
            "failed_nodes": [{"id": "end", "type": "end", "error": "missing output"}],
        },
    )
    text = render_current_situation(session)
    assert "last_acceptance: 1 failed @4 (ASSERTION_FAILED) (end:missing output)" in text


def test_current_situation_lists_hard_bound_references_and_selected_node() -> None:
    session = replace(
        _session_with_config_node(),
        selected_node="n-drag",
        referenced_nodes=[{"id": "n1", "label": "知识库检索"}],
        referenced_tools=[{"id": "time/current_time", "label": "当前时间"}],
        referenced_datasets=[{"id": "ds-uuid", "label": "产品文档"}],
    )
    text = render_current_situation(session)
    assert "selected_node: n-drag" in text
    assert "referenced_nodes: n1 (知识库检索)" in text
    assert "referenced_tools: time/current_time (当前时间)" in text
    assert "referenced_datasets: ds-uuid (产品文档)" in text


def test_turn_complete_last_run_is_not_labeled_aborted() -> None:
    session = replace(_session_with_config_node(), last_run="turn_complete")
    text = render_current_situation(session)
    assert "last_run: turn_complete" in text
    assert "aborted" not in text


def test_system_prompt_hard_binds_referenced_ids() -> None:
    from core.workflow.generator.agent.loop import SYSTEM_PROMPT

    assert "referenced_nodes" in SYSTEM_PROMPT
    assert "referenced_tools" in SYSTEM_PROMPT
    assert "referenced_datasets" in SYSTEM_PROMPT
    assert "build_node must use those exact ids" in SYSTEM_PROMPT
    assert "search_tools" in SYSTEM_PROMPT
    assert "search_datasets" in SYSTEM_PROMPT
    assert "ask_user" in SYSTEM_PROMPT
    assert "Plain text never finishes" not in SYSTEM_PROMPT
    assert "no tool_calls" in SYSTEM_PROMPT
    assert "<think>" in SYSTEM_PROMPT
    assert "do not put tool-call JSON inside think" in SYSTEM_PROMPT


def test_system_prompt_encourages_batched_creates() -> None:
    from core.workflow.generator.agent.loop import SYSTEM_PROMPT
    from core.workflow.generator.agent.prompts import render_active_skill

    playbook = render_active_skill("create-from-scratch")
    combined = f"{SYSTEM_PROMPT}\n{playbook}"
    assert "必须" not in combined
    assert "Prefer emitting multiple" in playbook
    assert "build_node(mode=create)" in playbook
    assert "native multi-tool" in playbook
