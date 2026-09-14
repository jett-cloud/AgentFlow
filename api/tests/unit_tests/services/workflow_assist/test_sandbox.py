from core.workflow.generator.graph.graph_ops import connect, empty_graph, upsert_node
from services.workflow_assist.effect_policy import (
    classify_effect,
)
from services.workflow_assist.sandbox import WorkflowAssistAcceptanceRunner


def test_partial_coverage_summary_does_not_deny_execution():
    from core.workflow.generator.acceptance.evidence import GraphExecutionTrace

    trace = GraphExecutionTrace()
    trace.executed_node_ids.add("start")
    runner = WorkflowAssistAcceptanceRunner(execute_graph=lambda graph, mode, inputs: trace)
    attempt = runner.run(graph=_start_end(), revision=1, graph_hash="h", case_ids=["default"], mode="simulated")[0]
    assert attempt["executed"]
    assert attempt["executed_node_ids"] == ["start"]
    assert attempt["unverified_nodes"] == ["end"]
    assert "executed=false" not in attempt["trace_summary"]


def test_live_blocks_http_before_executor() -> None:
    from unittest.mock import Mock

    execute = Mock(return_value=[])
    runner = WorkflowAssistAcceptanceRunner(execute_graph=execute)
    graph = {"nodes": [{"id": "http", "data": {"type": "http-request"}}], "edges": []}
    result = runner.run(graph=graph, revision=1, graph_hash="h", case_ids=["default"], mode="live")[0]
    execute.assert_not_called()
    assert not result["passed"]
    assert not result["executed"]


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


def _start_tool_end():
    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={})
    graph = upsert_node(
        graph,
        node_id="tool",
        node_type="tool",
        title="工具",
        desc="",
        config={
            "provider_id": "search",
            "provider_type": "builtin",
            "tool_name": "search",
            "tool_parameters": {"query": {"type": "constant", "value": "q"}},
        },
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    graph = connect(graph, source="start", target="tool")
    return connect(graph, source="tool", target="end")


def test_classify_effect_splits_local_metered_and_simulate() -> None:
    assert classify_effect("code") == "local_execute"
    assert classify_effect("template-transform") == "local_execute"
    assert classify_effect("assigner") == "local_execute"
    assert classify_effect("variable-aggregator") == "local_execute"
    assert classify_effect("list-operator") == "local_execute"
    assert classify_effect("llm") == "metered"
    assert classify_effect("tool") == "simulate_always"
    assert classify_effect("http-request") == "simulate_always"
    assert classify_effect("iteration-start") == "local_execute"
    assert classify_effect("loop-start") == "local_execute"
    assert classify_effect("loop-end") == "local_execute"


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
    assert attempts[0]["executed"] is False
    assert attempts[0]["unexecuted_node_ids"] == ["end", "llm", "start"]
    assert attempts[0]["business_verified"] is False
    assert attempts[0]["status"] == "simulated"
    assert "llm" in attempts[0]["unverified_nodes"]
    assert attempts[0]["evidence"][0]["source"] == "sandbox"
    assert attempts[0]["evidence"][0]["passed"] is True
    assert attempts[0]["evidence"][0]["observed"]["executed"] is False


def test_runtime_output_contract_checks_code_and_terminal_types() -> None:
    from core.workflow.generator.acceptance.evidence import GraphExecutionTrace

    graph = _start_code_end()
    code = next(node for node in graph["nodes"] if node["id"] == "code")
    code["data"]["outputs"] = {"result": {"type": "number"}}
    end = next(node for node in graph["nodes"] if node["id"] == "end")
    end["data"]["outputs"] = [{"variable": "answer", "value_selector": ["code", "result"], "value_type": "number"}]
    trace = GraphExecutionTrace()
    trace.executed_node_ids.update({"start", "code", "end"})
    trace.node_outputs = {"code": {"result": "wrong"}}
    trace.graph_outputs = {"answer": "wrong"}
    runner = WorkflowAssistAcceptanceRunner(execute_graph=lambda graph, mode, inputs: trace)

    attempt = runner.run(graph=graph, revision=1, graph_hash="h", case_ids=["default"], mode="simulated")[0]

    assert attempt["passed"] is False
    assert attempt["runtime_contract_passed"] is False
    assert {item["path"] for item in attempt["assertions"]} == {"code.result", "outputs.answer"}
    assert all(item["passed"] is False for item in attempt["assertions"])
    assert all(item["kind"] == "output_type" for item in attempt["assertions"])


def test_business_assertion_is_distinct_from_runtime_success() -> None:
    from core.workflow.generator.acceptance.evidence import GraphExecutionTrace

    trace = GraphExecutionTrace()
    trace.executed_node_ids.update({"start", "end"})
    trace.graph_outputs = {"answer": "hello world"}
    runner = WorkflowAssistAcceptanceRunner(
        execute_graph=lambda graph, mode, inputs: trace,
        acceptance_cases=[
            {
                "case_id": "default",
                "inputs": {"query": "hello"},
                "assertions": [{"path": ["answer"], "operator": "contains", "expected": "world"}],
            }
        ],
    )

    attempt = runner.run(graph=_start_end(), revision=1, graph_hash="h", case_ids=["default"], mode="live")[0]

    assert attempt["passed"] is True
    assert attempt["executed"] is True
    assert attempt["runtime_contract_passed"] is True
    assert attempt["business_verified"] is True
    assert attempt["assertions"][-1]["kind"] == "business"


def test_registered_cases_run_with_server_owned_inputs_and_assertions() -> None:
    from core.workflow.generator.acceptance.evidence import GraphExecutionTrace

    seen_inputs: list[dict[str, object]] = []

    def execute(graph, mode, inputs):
        seen_inputs.append(dict(inputs))
        trace = GraphExecutionTrace()
        trace.executed_node_ids.update({"start", "end"})
        trace.graph_outputs = {"answer": inputs["query"]}
        return trace

    runner = WorkflowAssistAcceptanceRunner(
        execute_graph=execute,
        acceptance_cases=[
            {
                "case_id": "normal",
                "inputs": {"query": "approved"},
                "assertions": [{"path": ["answer"], "operator": "equals", "expected": "approved"}],
            },
            {
                "case_id": "failure",
                "inputs": {"query": "rejected"},
                "assertions": [{"path": ["answer"], "operator": "equals", "expected": "approved"}],
            },
        ],
    )

    attempts = runner.run(
        graph=_start_end(),
        revision=1,
        graph_hash="h",
        case_ids=["normal", "failure"],
        mode="live",
    )

    assert seen_inputs == [{"query": "approved"}, {"query": "rejected"}]
    assert [attempt["passed"] for attempt in attempts] == [True, False]
    assert [attempt["business_verified"] for attempt in attempts] == [True, False]


def test_advanced_chat_answer_checks_terminal_output_type() -> None:
    from core.workflow.generator.acceptance.evidence import GraphExecutionTrace

    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="Start", desc="", config={})
    graph = upsert_node(
        graph,
        node_id="answer",
        node_type="answer",
        title="Answer",
        desc="",
        config={"answer": "{{#start.query#}}"},
    )
    graph = connect(graph, source="start", target="answer")
    trace = GraphExecutionTrace()
    trace.executed_node_ids.update({"start", "answer"})
    trace.graph_outputs = {"answer": {"unexpected": True}}
    runner = WorkflowAssistAcceptanceRunner(execute_graph=lambda graph, mode, inputs: trace)

    attempt = runner.run(graph=graph, revision=1, graph_hash="h", case_ids=["default"], mode="simulated")[0]

    assert attempt["passed"] is False
    assertion = next(item for item in attempt["assertions"] if item["path"] == "outputs.answer")
    assert assertion["expected"] == "string"
    assert assertion["actual"] == "object"


def test_simulated_acceptance_does_not_execute_tool_nodes() -> None:
    from unittest.mock import Mock

    execute = Mock(return_value=[])
    runner = WorkflowAssistAcceptanceRunner(execute_graph=execute)
    attempts = runner.run(
        graph=_start_tool_end(),
        revision=1,
        graph_hash="abc",
        case_ids=["default"],
        mode="simulated",
    )
    execute.assert_not_called()
    assert runner.tool_calls == 0
    assert attempts[0]["passed"] is True
    assert attempts[0]["executed"] is False
    assert "tool" in attempts[0]["unverified_nodes"]


def test_simulated_acceptance_marks_agent_unverified() -> None:
    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={})
    graph = upsert_node(graph, node_id="agent_1", node_type="agent", title="助手", desc="", config={})
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    graph = connect(graph, source="start", target="agent_1")
    graph = connect(graph, source="agent_1", target="end")
    runner = WorkflowAssistAcceptanceRunner()
    attempts = runner.run(
        graph=graph,
        revision=1,
        graph_hash="abc",
        case_ids=["default"],
        mode="simulated",
    )
    assert attempts[0]["executed"] is False
    assert "agent_1" in attempts[0]["unverified_nodes"]


def test_live_acceptance_counts_metered_nodes() -> None:
    runner = WorkflowAssistAcceptanceRunner(execute_graph=lambda graph, mode, inputs: [])
    runner.run(graph=_start_llm_end(), revision=1, graph_hash="abc", case_ids=["default"], mode="live")
    assert runner.llm_calls == 1
    assert runner.tool_calls == 0


def test_live_acceptance_never_executes_tool_with_unknown_side_effects() -> None:
    from unittest.mock import Mock

    execute = Mock(return_value=[])
    runner = WorkflowAssistAcceptanceRunner(execute_graph=execute)
    runner.run(graph=_start_tool_end(), revision=1, graph_hash="abc", case_ids=["default"], mode="live")
    execute.assert_not_called()
    assert runner.tool_calls == 0
    assert runner.llm_calls == 0


def test_live_acceptance_never_executes_agent_with_bound_tools() -> None:
    from unittest.mock import Mock

    execute = Mock(return_value=[])
    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="Start", desc="", config={})
    graph = upsert_node(
        graph,
        node_id="agent",
        node_type="agent",
        title="Agent",
        desc="",
        config={"dify_tools": [{"provider_id": "mail", "tool_name": "send"}]},
    )
    runner = WorkflowAssistAcceptanceRunner(execute_graph=execute)

    attempt = runner.run(graph=graph, revision=1, graph_hash="h", case_ids=["default"], mode="live")[0]

    execute.assert_not_called()
    assert attempt["passed"] is False
    assert attempt["failed_nodes"][0]["category"] == "policy"


def test_agent_default_outputs_use_runtime_types() -> None:
    from core.workflow.generator.acceptance.evidence import GraphExecutionTrace

    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="Start", desc="", config={})
    graph = upsert_node(graph, node_id="agent", node_type="agent", title="Agent", desc="", config={})
    trace = GraphExecutionTrace()
    trace.executed_node_ids.update({"start", "agent"})
    trace.node_outputs = {"agent": {"text": "ok", "files": [], "json": {}}}
    runner = WorkflowAssistAcceptanceRunner(execute_graph=lambda graph, mode, inputs: trace)

    attempt = runner.run(graph=graph, revision=1, graph_hash="h", case_ids=["default"], mode="live")[0]

    assert attempt["runtime_contract_passed"] is True
    assert all(item["passed"] for item in attempt["assertions"])


def test_local_only_graph_invokes_injected_engine() -> None:
    seen: list[str] = []

    def execute(graph, mode, inputs):
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
    assert attempts[0]["executed"] is True
    assert attempts[0]["unverified_nodes"] == ["code", "end", "start"]
    assert attempts[0]["evidence"][0]["observed"]["executed"] is True


def test_injected_engine_failure_marks_attempt_failed() -> None:
    def execute(graph, mode, inputs):
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


def test_simulated_acceptance_does_not_mutate_candidate_graph() -> None:
    graph = _start_llm_end()
    original_ids = [node["id"] for node in graph["nodes"]]
    runner = WorkflowAssistAcceptanceRunner()
    runner.run(graph=graph, revision=1, graph_hash="abc", case_ids=["default"], mode="simulated")
    assert [node["id"] for node in graph["nodes"]] == original_ids
    assert "position" not in graph["nodes"][0]


def test_live_without_executor_does_not_pretend_to_have_run() -> None:
    runner = WorkflowAssistAcceptanceRunner()
    attempts = runner.run(
        graph=_start_code_end(),
        revision=0,
        graph_hash="h",
        case_ids=["default"],
        mode="live",
    )
    assert attempts[0]["passed"] is True
    assert attempts[0]["status"] == "succeeded"
    assert attempts[0]["executed"] is False
    assert attempts[0]["evidence"][0]["observed"]["executed"] is False


def test_template_transform_graph_is_local_and_invokes_engine() -> None:
    seen: list[str] = []

    def execute(graph, mode, inputs):
        seen.append(mode)
        return []

    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={})
    graph = upsert_node(
        graph,
        node_id="tpl",
        node_type="template-transform",
        title="拼接",
        desc="",
        config={"template": "{{ arg }}", "variables": []},
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    graph = connect(graph, source="start", target="tpl")
    graph = connect(graph, source="tpl", target="end")
    runner = WorkflowAssistAcceptanceRunner(execute_graph=execute)
    attempts = runner.run(graph=graph, revision=0, graph_hash="h", case_ids=["default"], mode="simulated")
    assert seen == ["simulated"]
    assert attempts[0]["executed"] is True
    assert attempts[0]["unverified_nodes"] == ["end", "start", "tpl"]
