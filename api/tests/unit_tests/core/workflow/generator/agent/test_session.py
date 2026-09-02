from types import SimpleNamespace

import pytest

from core.workflow.generator.agent.session import InvalidAgentMessageError, apply_user_turn, restore_session


def _row(*, sequence: int, event_type: str, role: str, status: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(sequence=sequence, event_type=event_type, role=role, status=status, payload=payload)


def test_pending_ask_user_becomes_tool_result_on_next_text() -> None:
    rows = [
        _row(sequence=1, event_type="message", role="user", status="completed", payload={"text": "做 RAG 测试工作流"}),
        _row(
            sequence=2,
            event_type="tool_call",
            role="assistant",
            status="pending",
            payload={
                "id": "call_1",
                "name": "ask_user",
                "arguments": {"questions": [{"id": "q1", "question": "知识库怎么指定", "kind": "text"}]},
            },
        ),
    ]
    session = restore_session(rows, candidate_state={}, generation_mode="workflow")
    updated = apply_user_turn(session, "运行时传入")

    assert updated.messages[-1].event_type == "tool_result"
    assert updated.messages[-1].payload["tool_call_id"] == "call_1"
    assert updated.messages[-2].status == "completed"
    assert [m.event_type for m in updated.messages] == ["message", "tool_call", "tool_result"]


def test_execute_keeps_history_and_candidate() -> None:
    rows = [
        _row(sequence=1, event_type="message", role="user", status="completed", payload={"text": "做 RAG 测试工作流"}),
        _row(sequence=2, event_type="message", role="assistant", status="completed", payload={"text": "已建检索节点"}),
    ]
    graph = {"nodes": [{"id": "kr", "data": {"type": "knowledge-retrieval", "title": "检索"}}], "edges": []}
    session = restore_session(
        rows,
        candidate_state={"graph": graph, "revision": 3, "base_hash": "abc"},
        generation_mode="workflow",
    )
    updated = apply_user_turn(session, "执行")

    assert updated.candidate_revision == 3
    assert updated.candidate_graph["nodes"][0]["id"] == "kr"
    assert updated.messages[-1].payload["text"] == "执行"
    assert len(updated.messages) == 3


def test_apply_user_turn_stores_references_on_the_user_payload() -> None:
    rows = [
        _row(sequence=1, event_type="message", role="user", status="completed", payload={"text": "做 RAG 测试工作流"}),
    ]
    session = restore_session(rows, candidate_state={}, generation_mode="workflow")
    references = [{"kind": "node", "id": "n1", "label": "知识库检索"}]
    updated = apply_user_turn(session, "把 知识库检索 接到 LLM", references)

    assert updated.messages[-1].payload == {
        "text": "把 知识库检索 接到 LLM",
        "references": references,
    }


def test_malformed_row_raises_instead_of_inventing_session() -> None:
    rows = [
        _row(sequence=1, event_type="message", role="user", status="completed", payload={"text": "ok"}),
        _row(sequence=2, event_type="not_a_real_event", role="assistant", status="completed", payload={}),
    ]

    with pytest.raises(InvalidAgentMessageError):
        restore_session(rows, candidate_state={}, generation_mode="workflow")
