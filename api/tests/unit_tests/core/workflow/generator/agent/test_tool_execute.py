from collections.abc import Mapping
from copy import deepcopy

import pytest

from core.workflow.generator.acceptance.evidence import (
    AcceptanceMode,
    FailedNodeTrace,
    GraphExecutionTrace,
    canonical_graph_hash,
)
from core.workflow.generator.agent.tools import tool_execute
from core.workflow.generator.agent.tools.tools import ToolContext, dispatch
from core.workflow.generator.agent.types import ToolCall
from core.workflow.generator.graph.graph_ops import connect, empty_graph, upsert_node
from core.workflow.generator.graph.types import MinimalGraphDict
from tests.unit_tests.core.workflow.generator.agent.conftest import set_env
from tests.unit_tests.core.workflow.generator.node_fixtures import node_config


class _FakeExecutor:
    def __init__(
        self,
        *,
        failed: list[FailedNodeTrace] | None = None,
        node_outputs: dict[str, dict[str, object]] | None = None,
        graph_outputs: dict[str, object] | None = None,
    ) -> None:
        self.failed = failed or []
        self.node_outputs = node_outputs or {}
        self.graph_outputs = graph_outputs or {}
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        graph: MinimalGraphDict,
        mode: AcceptanceMode,
        start_inputs: Mapping[str, object],
    ) -> GraphExecutionTrace:
        self.calls.append({"graph": deepcopy(graph), "mode": mode, "start_inputs": dict(start_inputs)})
        trace = GraphExecutionTrace()
        trace.extend(self.failed)
        trace.executed_node_ids = {node["id"] for node in graph["nodes"]}
        trace.node_outputs = deepcopy(self.node_outputs)
        trace.graph_outputs = dict(self.graph_outputs)
        return trace


def _call(name: str, **arguments: object) -> ToolCall:
    return {"id": "c1", "name": name, "arguments": arguments}


def _graph(*, with_llm: bool = True) -> MinimalGraphDict:
    graph = upsert_node(
        empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={"variables": []}
    )
    upstream = "start"
    if with_llm:
        graph = upsert_node(graph, node_id="llm", node_type="llm", title="分析", desc="", config=node_config("llm"))
        graph = connect(graph, source="start", target="llm")
        upstream = "llm"
    graph = upsert_node(
        graph,
        node_id="code",
        node_type="code",
        title="格式化",
        desc="",
        config=node_config("code", {"outputs": {"result": {"type": "string", "children": None}}}),
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={"outputs": []})
    graph = connect(graph, source=upstream, target="code")
    return connect(graph, source="code", target="end")


@pytest.fixture
def prepared(monkeypatch: pytest.MonkeyPatch, tool_context: ToolContext) -> ToolContext:
    monkeypatch.setattr(
        tool_execute, "prepare_candidate_for_execution", lambda call, context, *, purpose: (None, False)
    )
    tool_context.state.graph = _graph()
    return tool_context


def test_run_workflow_without_executor_is_unavailable(prepared: ToolContext) -> None:
    result = dispatch(_call("run_workflow"), prepared)
    assert result["error_code"] == "CAPABILITY_UNAVAILABLE"


def test_invalid_graph_is_rejected_before_execution(tool_context: ToolContext) -> None:
    executor = _FakeExecutor()
    set_env(tool_context, execute_graph=executor)
    result = dispatch(_call("run_workflow"), tool_context)
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_NODE_CONFIG"
    assert executor.calls == []


def test_live_run_requires_consent_in_always_ask(prepared: ToolContext) -> None:
    executor = _FakeExecutor()
    set_env(prepared, execute_graph=executor)
    result = dispatch(_call("run_workflow", level="live"), prepared)
    assert result["error_code"] == "LIVE_RUN_REQUIRES_CONSENT"
    assert result["retryable"] is True
    assert executor.calls == []


def test_live_run_reserves_the_grant_for_the_current_hash(prepared: ToolContext) -> None:
    executor = _FakeExecutor(graph_outputs={"result": "ok"})
    reserved: list[tuple[int, str]] = []
    set_env(
        prepared,
        execute_graph=executor,
        authorize_live_acceptance=lambda revision, graph_hash: reserved.append((revision, graph_hash)) or True,
    )
    result = dispatch(_call("run_workflow", level="live", start_inputs={"q": "hi"}), prepared)
    assert result["ok"] is True
    assert reserved == [(prepared.state.candidate_revision, canonical_graph_hash(prepared.state.graph))]
    assert executor.calls[0]["mode"] == "live"
    assert executor.calls[0]["start_inputs"] == {"q": "hi"}
    assert result["content"]["verification_level"] == "live"
    assert result["content"]["graph_outputs"] == {"result": "ok"}


def test_always_execute_runs_live_without_a_grant_and_ignores_stale_decline(prepared: ToolContext) -> None:
    executor = _FakeExecutor()
    set_env(
        prepared,
        execute_graph=executor,
        execution_consent_mode="always_execute",
        live_consent_declined_hash=canonical_graph_hash(prepared.state.graph),
    )
    result = dispatch(_call("run_workflow", level="live"), prepared)
    assert result["ok"] is True
    assert executor.calls[0]["mode"] == "live"


def test_declined_hash_denies_live_in_always_ask_even_with_a_grant(prepared: ToolContext) -> None:
    executor = _FakeExecutor()
    set_env(
        prepared,
        execute_graph=executor,
        authorize_live_acceptance=lambda revision, graph_hash: True,
        live_consent_declined_hash=canonical_graph_hash(prepared.state.graph),
    )
    result = dispatch(_call("run_workflow", level="live"), prepared)
    assert result["error_code"] == "EXECUTION_CONSENT_DENIED"
    assert result["retryable"] is False
    assert executor.calls == []


def test_mock_run_rewrites_external_nodes_and_stays_simulated(prepared: ToolContext) -> None:
    executor = _FakeExecutor(node_outputs={"llm": {"text": "差评"}, "code": {"result": "差评!"}})
    set_env(prepared, execute_graph=executor)
    result = dispatch(_call("run_workflow", level="mock", mocks={"llm": {"text": "差评"}}), prepared)
    assert result["ok"] is True
    sent = executor.calls[0]
    assert sent["mode"] == "simulated"
    sent_graph = sent["graph"]
    assert isinstance(sent_graph, dict)
    assert next(node for node in sent_graph["nodes"] if node["id"] == "llm")["data"]["type"] == "code"
    content = result["content"]
    assert content["verification_level"] == "mock"
    assert content["mocked_outputs"]["llm"]["text"] == "差评"
    assert "llm" not in content["node_outputs"]
    assert content["node_outputs"]["code"] == {"result": "差评!"}
    assert prepared.state.last_node_outputs["llm"]["text"] == "差评"


def test_local_only_graph_skips_the_gate(prepared: ToolContext) -> None:
    prepared.state.graph = _graph(with_llm=False)
    executor = _FakeExecutor()
    set_env(prepared, execute_graph=executor)
    result = dispatch(_call("run_workflow", level="live"), prepared)
    assert result["ok"] is True
    assert executor.calls[0]["mode"] == "simulated"
    assert result["content"]["verification_level"] == "local_only"


def test_engine_failure_is_returned_to_the_agent_not_completed(prepared: ToolContext) -> None:
    failed: list[FailedNodeTrace] = [
        {"id": "code", "type": "code", "error": "Acceptance execution failed (runtime)", "category": "runtime"}
    ]
    set_env(prepared, execute_graph=_FakeExecutor(failed=failed))
    result = dispatch(_call("run_workflow"), prepared)
    assert result["ok"] is True
    assert result["content"]["passed"] is False
    assert result["content"]["failed_nodes"] == failed


def test_mock_errors_and_bad_arguments_are_reported(prepared: ToolContext) -> None:
    set_env(prepared, execute_graph=_FakeExecutor())
    assert dispatch(_call("run_workflow", level="fast"), prepared)["error_code"] == "INVALID_ARGUMENT"
    assert (
        dispatch(_call("run_workflow", level="live", mocks={"llm": {"text": "x"}}), prepared)["error_code"]
        == "INVALID_ARGUMENT"
    )
    assert (
        dispatch(_call("run_workflow", mocks={"llm": {"text": 3}}), prepared)["error_code"]
        == "INVALID_MOCK_OUTPUT"
    )


def test_large_outputs_are_clipped(prepared: ToolContext) -> None:
    set_env(prepared, execute_graph=_FakeExecutor(node_outputs={"code": {"result": "x" * 5000}}))
    content = dispatch(_call("run_workflow"), prepared)["content"]
    assert content["node_outputs"]["code"]["result"]["truncated"] is True
