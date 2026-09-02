from core.workflow.generator.agent.graph_ops import connect, empty_graph, upsert_node
from core.workflow.generator.agent.session import apply_user_turn
from core.workflow.generator.agent.types import AgentMessage, AgentSession
from services.workflow_assist.effect_policy import (
    LIVE_CONSENT_QUESTION_ID,
    classify_effect,
    live_run_authorized_from_session,
)
from services.workflow_assist.sandbox import WorkflowAssistAcceptanceRunner


def _session(*messages: AgentMessage) -> AgentSession:
    return AgentSession(
        messages=list(messages),
        candidate_graph=None,
        candidate_revision=0,
        candidate_base_hash=None,
        compacted_until_sequence=None,
        compacted_state=None,
        generation_mode="workflow",
        last_validation=None,
    )


def _start_end():
    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={})
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    return connect(graph, source="start", target="end")


def _start_llm_end():
    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={})
    graph = upsert_node(graph, node_id="llm", node_type="llm", title="模型", desc="", config={})
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    graph = connect(graph, source="start", target="llm")
    return connect(graph, source="llm", target="end")


def _start_code_end():
    graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="开始",
        desc="",
        config={"variables": []},
    )
    graph = upsert_node(
        graph,
        node_id="code",
        node_type="code",
        title="计算",
        desc="",
        config={"code": "def main():\n    return {'result': 1}\n", "code_language": "python3"},
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    graph = connect(graph, source="start", target="code")
    return connect(graph, source="code", target="end")


def test_classify_effect_splits_local_metered_and_simulate() -> None:
    assert classify_effect("code") == "local_execute"
    assert classify_effect("llm") == "metered"
    assert classify_effect("tool") == "metered"
    assert classify_effect("http-request") == "simulate_always"


def test_simulated_acceptance_does_not_meter_llm_or_tools() -> None:
    runner = WorkflowAssistAcceptanceRunner()
    attempts = runner.run(
        graph=_start_llm_end(),
        revision=1,
        graph_hash="abc",
        case_ids=["default"],
        mode="simulated",
    )
    assert runner.llm_calls == 0
    assert runner.tool_calls == 0
    assert attempts[0]["passed"] is True
    assert attempts[0]["status"] == "simulated"
    assert "llm" in attempts[0]["unverified_nodes"]
    assert attempts[0]["evidence"][0]["source"] == "sandbox"
    assert attempts[0]["evidence"][0]["passed"] is True


def test_live_acceptance_counts_metered_nodes() -> None:
    runner = WorkflowAssistAcceptanceRunner()
    runner.run(graph=_start_llm_end(), revision=1, graph_hash="abc", case_ids=["default"], mode="live")
    assert runner.llm_calls == 1
    assert runner.tool_calls == 0


def test_local_only_graph_invokes_injected_engine() -> None:
    seen: list[str] = []

    def execute(graph, mode):
        seen.append(mode)
        assert any(node["id"] == "code" for node in graph["nodes"])
        return []

    runner = WorkflowAssistAcceptanceRunner(execute_graph=execute)
    attempts = runner.run(
        graph=_start_code_end(),
        revision=0,
        graph_hash="h",
        case_ids=["default"],
        mode="simulated",
    )
    assert seen == ["simulated"]
    assert attempts[0]["passed"] is True
    assert attempts[0]["unverified_nodes"] == []


def test_injected_engine_failure_marks_attempt_failed() -> None:
    def execute(graph, mode):
        return [{"id": "code", "type": "code", "error": "sandbox timeout"}]

    runner = WorkflowAssistAcceptanceRunner(execute_graph=execute)
    attempts = runner.run(
        graph=_start_code_end(),
        revision=0,
        graph_hash="h",
        case_ids=["default"],
        mode="simulated",
    )
    assert attempts[0]["passed"] is False
    assert attempts[0]["failed_nodes"][0]["id"] == "code"


def test_live_consent_only_from_matching_ask_user_answer() -> None:
    pending = AgentMessage(
        sequence=1,
        event_type="tool_call",
        role="assistant",
        status="pending",
        payload={
            "id": "ask-1",
            "name": "ask_user",
            "arguments": {
                "questions": [
                    {
                        "id": LIVE_CONSENT_QUESTION_ID,
                        "question": "允许实跑吗",
                        "kind": "single_choice",
                    }
                ]
            },
        },
    )
    session = _session(pending)
    answered = apply_user_turn(session, "同意")
    assert live_run_authorized_from_session(answered) is True
    later = apply_user_turn(answered, "继续改图")
    assert live_run_authorized_from_session(later) is False


def test_simulated_acceptance_does_not_mutate_candidate_graph() -> None:
    graph = _start_llm_end()
    original_ids = [node["id"] for node in graph["nodes"]]
    runner = WorkflowAssistAcceptanceRunner()
    runner.run(graph=graph, revision=1, graph_hash="abc", case_ids=["default"], mode="simulated")
    assert [node["id"] for node in graph["nodes"]] == original_ids
    assert "position" not in graph["nodes"][0]


def test_ordinary_user_message_is_not_live_consent() -> None:
    session = apply_user_turn(_session(), "生成一个摘要工作流")
    assert live_run_authorized_from_session(session) is False