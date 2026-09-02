import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from core.workflow.generator.agent.compaction import TokenLimits
from core.workflow.generator.agent.graph_ops import connect, empty_graph, find_node, upsert_node
from core.workflow.generator.agent.loop import _graph_diff, _parse_turn, _summary, iter_agent_events
from core.workflow.generator.agent.tools import ToolContext
from core.workflow.generator.agent.tools import dispatch as real_dispatch
from core.workflow.generator.agent.types import AgentMessage, AgentSession
from core.workflow.generator.planner_context import PlannerContextLimitError


class FakeInvoker:
    """Queued model turns for the in-memory loop. An empty queue is a blank response."""

    def __init__(self) -> None:
        self._queue: list[dict[str, Any]] = []
        self.invoke_count = 0

    def queue_text(self, text: str) -> None:
        self._queue.append({"text": text})

    def queue_tool_calls(self, calls: list[dict[str, Any]]) -> None:
        self._queue.append({"tool_calls": calls})

    def queue_json(self, action: dict[str, Any]) -> None:
        self._queue.append(action)

    def queue_text_and_tool_calls(self, text: str, calls: list[dict[str, Any]]) -> None:
        self._queue.append({"text": text, "tool_calls": calls})

    def invoke(self, messages: object = None, **kwargs: object) -> dict[str, Any]:
        self.invoke_count += 1
        if not self._queue:
            return {"text": ""}
        return self._queue.pop(0)


class StreamingFakeInvoker:
    """Yields Graphon-shaped chunks. Does not implement a blocking complete turn."""

    def __init__(self) -> None:
        self._chunks: list[object] = []
        self.invoke_count = 0

    def queue_chunks(self, chunks: list[object]) -> None:
        self._chunks = list(chunks)

    def invoke(self, messages: object = None, **kwargs: object) -> dict[str, Any]:
        raise AssertionError("streaming invoker must be consumed via iter_chunks")

    def iter_chunks(self, messages: object = None, **kwargs: object) -> Iterator[object]:
        self.invoke_count += 1
        chunks = self._chunks
        self._chunks = []
        return iter(chunks)


def _stream_chunk(*, text: str = "", tool_calls: list[dict[str, Any]] | None = None) -> SimpleNamespace:
    calls = []
    for item in tool_calls or []:
        function = SimpleNamespace(name=item.get("name") or "", arguments=item.get("arguments") or "")
        calls.append(SimpleNamespace(id=item.get("id") or "", index=item.get("index"), function=function))
    message = SimpleNamespace(content=text, tool_calls=calls)
    return SimpleNamespace(delta=SimpleNamespace(message=message, finish_reason=None))


class FakeCancellation:
    def __init__(self) -> None:
        self._reason: str | None = None

    def abort(self, reason: str) -> None:
        self._reason = reason

    def reason(self) -> str | None:
        return self._reason


class FakeLimits:
    def __init__(self) -> None:
        self.max_model_calls = 8
        self.max_tool_calls: int | None = None
        self.max_total_tokens: int | None = None
        self.max_elapsed_time: float | None = None


def _connected_start_end() -> dict[str, Any]:
    graph = upsert_node(
        empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={"variables": []}
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    return connect(graph, source="start", target="end")


@pytest.fixture
def loop_harness(tool_context: ToolContext, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    import core.workflow.generator.agent.loop as loop_mod

    session = AgentSession(
        messages=[
            AgentMessage(
                sequence=1,
                event_type="message",
                role="user",
                status="completed",
                payload={"text": "做 RAG 测试工作流"},
            )
        ],
        candidate_graph=tool_context.state.graph,
        candidate_revision=tool_context.state.candidate_revision,
        candidate_base_hash=None,
        compacted_until_sequence=None,
        compacted_state=None,
        generation_mode="workflow",
        last_validation=None,
    )
    invoker = FakeInvoker()
    cancellation = FakeCancellation()
    limits = FakeLimits()
    dispatch_order: list[str] = []
    graphs_seen: list[object] = []

    def tracking_dispatch(call: dict[str, Any], context: ToolContext) -> Any:
        dispatch_order.append(call["name"])
        graphs_seen.append(context.state.graph)
        return real_dispatch(call, context)

    monkeypatch.setattr(loop_mod, "dispatch", tracking_dispatch)

    harness = SimpleNamespace(
        session=session,
        context=tool_context,
        invoker=invoker,
        cancellation=cancellation,
        limits=limits,
        dispatch_order=dispatch_order,
        graphs_seen=graphs_seen,
    )
    harness.kwargs = {
        "session": session,
        "context": tool_context,
        "invoker": invoker,
        "cancellation": cancellation,
        "limits": limits,
    }
    return harness


def test_empty_graph_injects_create_playbook_after_situation(loop_harness) -> None:
    captured: list[list[object]] = []
    inner = loop_harness.invoker.invoke

    def capture(messages: object = None, **kwargs: object) -> dict[str, Any]:
        captured.append(list(messages or []))
        return inner(messages, **kwargs)

    loop_harness.invoker.invoke = capture
    loop_harness.invoker.queue_tool_calls(
        [{"id": "c-fail", "name": "fail", "arguments": {"reason": "stop after seeing prompt"}}]
    )
    list(iter_agent_events(**loop_harness.kwargs))
    contents = [getattr(message, "content", "") for message in captured[0]]
    assert any("# Playbooks" in str(text) and "create-from-scratch" in str(text) for text in contents)
    assert contents[-1].startswith("# Active playbook: create-from-scratch")
    assert "# Current situation" in str(contents[-2])


def test_plain_text_ends_turn_without_apply(loop_harness) -> None:
    loop_harness.invoker.queue_text("已经完成")
    events = list(iter_agent_events(**loop_harness.kwargs))
    names = [name for name, _ in events]
    assert names == ["message", "turn_complete"]
    assert events[0][1]["delta"] == "已经完成"
    assert loop_harness.session.messages[-1].event_type == "message"
    assert loop_harness.invoker.invoke_count == 1


def test_streaming_invoker_yields_reasoning_delta_then_tools(loop_harness) -> None:
    invoker = StreamingFakeInvoker()
    invoker.queue_chunks(
        [
            _stream_chunk(text="<think>先读图</think>正在"),
            _stream_chunk(text="创建"),
            _stream_chunk(
                tool_calls=[{"index": 0, "id": "c1", "name": "read_graph", "arguments": "{}"}],
            ),
        ]
    )
    loop_harness.kwargs["invoker"] = invoker
    events = list(iter_agent_events(**loop_harness.kwargs))
    names = [name for name, _ in events]
    assert names[:4] == ["reasoning.delta", "message.delta", "message.delta", "tool_call"]
    assert events[0][1]["text"] == "先读图"
    assert events[1][1]["text"] == "正在"
    prose = [item for item in loop_harness.session.messages if item.event_type == "message" and item.role == "assistant"]
    assert prose[-1].payload["text"] == "正在创建"
    assert prose[-1].payload["reasoning"] == "先读图"
    prompt_texts = []
    for message in loop_harness.session.messages:
        prompt_texts.append(str(message.payload.get("text") or ""))
        prompt_texts.append(str(message.payload.get("reasoning") or ""))
    # Session stores reasoning, but it must not be treated as public narration.
    assert "先读图" == prose[-1].payload["reasoning"]
    assert "先读图" not in prose[-1].payload["text"]


def test_think_and_tools_without_narration_still_persist_reasoning(loop_harness) -> None:
    loop_harness.invoker.queue_text_and_tool_calls(
        "<think>只改图</think>",
        [{"id": "a", "name": "read_graph", "arguments": {}}],
    )
    events = list(iter_agent_events(**loop_harness.kwargs))
    names = [name for name, _ in events]
    assert names[0] == "reasoning.delta"
    assert "tool_call" in names
    prose = [item for item in loop_harness.session.messages if item.event_type == "message" and item.role == "assistant"]
    assert prose[-1].payload["text"] == ""
    assert prose[-1].payload["reasoning"] == "只改图"


def test_streaming_invoker_yields_message_delta_before_tool_call(loop_harness) -> None:
    invoker = StreamingFakeInvoker()
    invoker.queue_chunks(
        [
            _stream_chunk(text="正在"),
            _stream_chunk(text="创建"),
            _stream_chunk(
                tool_calls=[{"index": 0, "id": "c1", "name": "read_graph", "arguments": "{}"}],
            ),
        ]
    )
    loop_harness.kwargs["invoker"] = invoker
    events = list(iter_agent_events(**loop_harness.kwargs))
    names = [name for name, _ in events]
    assert names[:4] == ["message.delta", "message.delta", "tool_call", "tool_result"]
    first = events[0][1]
    second = events[1][1]
    assert first["text"] == "正在"
    assert first["delta_index"] == 0
    assert second["text"] == "创建"
    assert second["delta_index"] == 1
    assert first["message_id"] == second["message_id"]
    assert first["stream_mode"] == "native"
    assert events[2][1]["name"] == "read_graph"


def test_cancel_during_stream_does_not_dispatch_incomplete_tool_json(loop_harness) -> None:
    invoker = StreamingFakeInvoker()
    cancellation = loop_harness.cancellation

    def iter_chunks(messages: object = None, **kwargs: object) -> Iterator[object]:
        invoker.invoke_count += 1
        yield _stream_chunk(text="正在")
        yield _stream_chunk(
            tool_calls=[{"index": 0, "id": "c1", "name": "read_graph", "arguments": '{"id":'}],
        )
        yield _stream_chunk(tool_calls=[{"index": 0, "arguments": '"n1"'}])
        cancellation.abort("user_abort")
        yield _stream_chunk(
            text="不该出现",
            tool_calls=[{"index": 0, "arguments": "}"}],
        )

    invoker.iter_chunks = iter_chunks  # type: ignore[method-assign]
    loop_harness.kwargs["invoker"] = invoker
    events = list(iter_agent_events(**loop_harness.kwargs))
    names = [name for name, _ in events]
    assert "aborted" in names
    assert "tool_call" not in names
    assert "tool_result" not in names
    assert loop_harness.dispatch_order == []
    assert events[-1][1]["termination_reason"] == "user_abort"
    deltas = [
        payload.get("text") or payload.get("delta")
        for name, payload in events
        if name in {"message.delta", "message"}
    ]
    assert "不该出现" not in deltas
    assert "正在" in deltas


def test_native_multi_tool_calls_dispatch_serially(loop_harness) -> None:
    loop_harness.invoker.queue_tool_calls(
        [
            {"id": "a", "name": "read_graph", "arguments": {}},
            {"id": "b", "name": "read_node", "arguments": {"id": "kr"}},
        ]
    )
    list(iter_agent_events(**loop_harness.kwargs))
    assert loop_harness.dispatch_order == ["read_graph", "read_node"]
    # 第二次 dispatch 见到第一次之后的 graph


def test_rejected_finish_continues(loop_harness) -> None:
    loop_harness.invoker.queue_tool_calls([{"id": "f", "name": "finish", "arguments": {"summary": "好了"}}])
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "a",
                "name": "ask_user",
                "arguments": {"questions": [{"id": "q", "question": "x", "kind": "text"}]},
            }
        ]
    )
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert ("done" not in {n for n, _ in events}) or False
    assert any(n == "waiting_user" for n, _ in events)


def test_max_model_calls_while_using_tools_is_error_not_done(loop_harness) -> None:
    loop_harness.limits.max_model_calls = 1
    loop_harness.invoker.queue_tool_calls([{"id": "a", "name": "read_graph", "arguments": {}}])
    loop_harness.invoker.queue_tool_calls([{"id": "b", "name": "read_graph", "arguments": {}}])
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert events[-1][0] == "error"
    assert events[-1][1]["termination_reason"] == "max_model_calls"
    assert events[-1][1]["usage"]["model_calls"] == 1
    assert "done" not in {name for name, _ in events}


def test_three_empty_responses_are_empty_response_error(loop_harness) -> None:
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert events[-1][0] == "error"
    assert events[-1][1]["termination_reason"] == "empty_response"
    assert "done" not in {name for name, _ in events}
    assert loop_harness.invoker.invoke_count == 3


def test_narration_with_tools_does_not_end_the_turn(loop_harness) -> None:
    loop_harness.invoker.queue_text_and_tool_calls(
        "先读图",
        [{"id": "a", "name": "read_graph", "arguments": {}}],
    )
    loop_harness.invoker.queue_tool_calls([{"id": "x", "name": "fail", "arguments": {"reason": "停"}}])
    events = list(iter_agent_events(**loop_harness.kwargs))
    names = [name for name, _ in events]
    assert names[0] == "message"
    assert "turn_complete" not in names
    assert names[-1] == "failed"
    assert loop_harness.invoker.invoke_count == 2


def test_json_fallback_uses_same_dispatch(loop_harness) -> None:
    loop_harness.invoker.queue_json(
        {"name": "ask_user", "arguments": {"questions": [{"id": "q", "question": "x", "kind": "text"}]}}
    )
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert loop_harness.dispatch_order == ["ask_user"]
    assert any(n == "waiting_user" for n, _ in events)


def test_serial_dispatch_sees_mutated_graph(loop_harness) -> None:
    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={})
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    loop_harness.context.state.graph = graph
    loop_harness.session.candidate_graph = graph
    loop_harness.invoker.queue_tool_calls(
        [
            {"id": "a", "name": "connect", "arguments": {"source": "start", "target": "end"}},
            {"id": "b", "name": "read_graph", "arguments": {}},
        ]
    )
    list(iter_agent_events(**loop_harness.kwargs))
    assert loop_harness.dispatch_order == ["connect", "read_graph"]
    first, second = loop_harness.graphs_seen
    assert not any(edge.get("source") == "start" and edge.get("target") == "end" for edge in first["edges"])
    assert any(edge.get("source") == "start" and edge.get("target") == "end" for edge in second["edges"])


def test_retryable_serial_failure_drops_sibling_calls(loop_harness) -> None:
    loop_harness.invoker.queue_tool_calls(
        [
            {"id": "a", "name": "connect", "arguments": {"source": "missing", "target": "also-missing"}},
            {"id": "b", "name": "read_graph", "arguments": {}},
        ]
    )
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    assert loop_harness.dispatch_order == ["connect"]
    assert loop_harness.invoker.invoke_count == 2
    results = [message for message in loop_harness.session.messages if message.event_type == "tool_result"]
    assert len(results) == 1
    assert results[0].payload["name"] == "connect"
    assert results[0].payload["ok"] is False
    assert results[0].payload["error_code"] == "NODE_NOT_FOUND"
    assert results[0].payload["retryable"] is True
    tool_names = [
        message.payload.get("name")
        for message in loop_harness.session.messages
        if message.event_type in {"tool_call", "tool_result"}
    ]
    assert "read_graph" not in tool_names


def test_non_retryable_serial_failure_keeps_sibling_calls(loop_harness, monkeypatch: pytest.MonkeyPatch) -> None:
    import core.workflow.generator.agent.loop as loop_mod

    original = loop_mod.dispatch

    def flaky(call: dict[str, Any], context: ToolContext) -> Any:
        if call.get("id") == "a":
            loop_harness.dispatch_order.append(call["name"])
            loop_harness.graphs_seen.append(context.state.graph)
            return {
                "tool_call_id": call["id"],
                "name": call["name"],
                "ok": False,
                "changed": False,
                "content": None,
                "error": "unavailable",
                "error_code": "CAPABILITY_UNAVAILABLE",
                "retryable": False,
            }
        return original(call, context)

    monkeypatch.setattr(loop_mod, "dispatch", flaky)
    loop_harness.invoker.queue_tool_calls(
        [
            {"id": "a", "name": "read_graph", "arguments": {}},
            {"id": "b", "name": "read_node", "arguments": {"id": "kr"}},
        ]
    )
    list(iter_agent_events(**loop_harness.kwargs))
    assert loop_harness.dispatch_order == ["read_graph", "read_node"]


def test_validate_observation_does_not_drop_siblings(loop_harness) -> None:
    loop_harness.invoker.queue_tool_calls(
        [
            {"id": "a", "name": "validate_graph", "arguments": {}},
            {"id": "b", "name": "read_graph", "arguments": {}},
        ]
    )
    list(iter_agent_events(**loop_harness.kwargs))
    assert loop_harness.dispatch_order == ["validate_graph", "read_graph"]


class _FakeLLM:
    def iter_json(self, *, messages, stage):
        yield from ()
        return {"config": {}}


def _create_call(call_id: str, node_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "name": "build_node",
        "arguments": {"mode": "create", "id": node_id, "type": "llm", "title": node_id, "purpose": "建节点"},
    }


def test_parallel_creates_emit_all_tool_calls_before_first_result(loop_harness) -> None:
    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    loop_harness.invoker.queue_tool_calls(
        [_create_call("c1", "n1"), _create_call("c2", "n2"), _create_call("c3", "n3")]
    )
    loop_harness.invoker.queue_text("先这样")
    events = list(iter_agent_events(**loop_harness.kwargs))
    names = [name for name, _ in events]
    call_indexes = [index for index, name in enumerate(names) if name == "tool_call"]
    result_indexes = [index for index, name in enumerate(names) if name == "tool_result"]
    assert len(call_indexes) == 3
    assert len(result_indexes) == 3
    assert max(call_indexes) < min(result_indexes)
    assert find_node(loop_harness.context.state.graph, "n1") is not None
    assert find_node(loop_harness.context.state.graph, "n2") is not None
    assert find_node(loop_harness.context.state.graph, "n3") is not None


def test_parallel_creates_compile_windows_overlap(loop_harness, monkeypatch: pytest.MonkeyPatch) -> None:
    import core.workflow.generator.agent.loop as loop_mod

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    windows: list[tuple[float, float]] = []
    active = 0
    max_active = 0
    lock = threading.Lock()
    real_compile = loop_mod.compile_build_node

    def delayed_compile(call, context):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        started = time.monotonic()
        time.sleep(0.05)
        try:
            return real_compile(call, context)
        finally:
            windows.append((started, time.monotonic()))
            with lock:
                active -= 1

    monkeypatch.setattr(loop_mod, "compile_build_node", delayed_compile)
    loop_harness.invoker.queue_tool_calls(
        [_create_call("c1", "n1"), _create_call("c2", "n2"), _create_call("c3", "n3")]
    )
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    assert max_active == 3
    assert len(windows) == 3
    starts = [start for start, _end in windows]
    ends = [end for _start, end in windows]
    assert max(starts) < min(ends)


def test_parallel_create_keeps_first_node_when_second_compile_fails(
    loop_harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.workflow.generator.agent.loop as loop_mod

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    real_compile = loop_mod.compile_build_node

    def fail_second(call, context):
        if call["arguments"].get("id") == "n2":
            return {
                "tool_call_id": call["id"],
                "name": call["name"],
                "ok": False,
                "changed": False,
                "content": None,
                "error": "Node builder failed",
                "error_code": "CAPABILITY_UNAVAILABLE",
                "retryable": False,
            }
        return real_compile(call, context)

    monkeypatch.setattr(loop_mod, "compile_build_node", fail_second)
    loop_harness.invoker.queue_tool_calls([_create_call("c1", "n1"), _create_call("c2", "n2")])
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    assert find_node(loop_harness.context.state.graph, "n1") is not None
    assert find_node(loop_harness.context.state.graph, "n2") is None


def test_retryable_create_batch_failure_drops_later_siblings(
    loop_harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.workflow.generator.agent.loop as loop_mod

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    real_compile = loop_mod.compile_build_node

    def fail_first(call, context):
        if call["arguments"].get("id") == "n1":
            return {
                "tool_call_id": call["id"],
                "name": call["name"],
                "ok": False,
                "changed": False,
                "content": None,
                "error": "Node n1 already exists",
                "error_code": "NODE_EXISTS",
                "retryable": True,
            }
        return real_compile(call, context)

    monkeypatch.setattr(loop_mod, "compile_build_node", fail_first)
    loop_harness.invoker.queue_tool_calls(
        [
            _create_call("c1", "n1"),
            _create_call("c2", "n2"),
            {"id": "edge", "name": "connect", "arguments": {"source": "n1", "target": "n2"}},
        ]
    )
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    assert "connect" not in loop_harness.dispatch_order
    assert loop_harness.invoker.invoke_count == 2
    tool_names = [
        message.payload.get("name")
        for message in loop_harness.session.messages
        if message.event_type in {"tool_call", "tool_result"}
    ]
    assert "connect" not in tool_names


def test_fail_yields_failed_not_done(loop_harness) -> None:
    loop_harness.invoker.queue_tool_calls([{"id": "x", "name": "fail", "arguments": {"reason": "做不到"}}])
    events = list(iter_agent_events(**loop_harness.kwargs))
    names = {n for n, _ in events}
    assert "failed" in names
    assert "done" not in names
    assert events[-1][0] == "failed"
    assert events[-1][1]["reason"] == "做不到"


def test_accepted_finish_yields_done_with_diff(loop_harness) -> None:
    loop_harness.context.state.graph = _connected_start_end()
    loop_harness.session.candidate_graph = loop_harness.context.state.graph
    loop_harness.invoker.queue_tool_calls([{"id": "f", "name": "finish", "arguments": {"summary": "已搭好"}}])
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert events[-1][0] == "done"
    payload = events[-1][1]
    assert payload["summary"] == "已搭好"
    assert "diff" in payload
    assert set(payload["diff"]) >= {"added", "removed", "updated"}
    assert "validation" in payload
    assert payload["validation"]["ok"] is True
    start = next(node for node in payload["graph"]["nodes"] if node["id"] == "start")
    end = next(node for node in payload["graph"]["nodes"] if node["id"] == "end")
    assert start["position"]["x"] < end["position"]["x"]


def test_user_abort_is_aborted_not_done(loop_harness) -> None:
    loop_harness.cancellation.abort("user_abort")
    loop_harness.invoker.queue_text("已经完成")
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert events[-1][0] == "aborted"
    assert events[-1][1]["termination_reason"] == "user_abort"
    assert "done" not in {n for n, _ in events}


def test_transport_disconnect_is_not_user_abort(loop_harness) -> None:
    loop_harness.cancellation.abort("transport_disconnect")
    loop_harness.invoker.queue_text("已经完成")
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert events[-1][0] == "aborted"
    assert events[-1][1]["termination_reason"] == "transport_disconnect"
    assert events[-1][1]["termination_reason"] != "user_abort"


def test_superseded_by_new_turn_is_aborted(loop_harness) -> None:
    loop_harness.cancellation.abort("superseded_by_new_turn")
    loop_harness.invoker.queue_text("已经完成")
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert events[-1][0] == "aborted"
    assert events[-1][1]["termination_reason"] == "superseded_by_new_turn"


def test_context_limit_is_error_not_done(loop_harness, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**kwargs: object) -> None:
        raise PlannerContextLimitError(prompt_tokens=99_000, input_limit=1000)

    monkeypatch.setattr("core.workflow.generator.agent.loop.assemble_prompt", boom)
    loop_harness.invoker.queue_text("再想一步")
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert events[-1][0] == "error"
    assert events[-1][1]["termination_reason"] == "context_limit"
    assert "done" not in {n for n, _ in events}


def test_rejected_finish_emits_tool_result_ok_false(loop_harness) -> None:
    loop_harness.invoker.queue_tool_calls([{"id": "f", "name": "finish", "arguments": {"summary": "好了"}}])
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "a",
                "name": "ask_user",
                "arguments": {"questions": [{"id": "q", "question": "x", "kind": "text"}]},
            }
        ]
    )
    events = list(iter_agent_events(**loop_harness.kwargs))
    results = [payload for name, payload in events if name == "tool_result"]
    assert results
    assert results[0]["ok"] is False
    assert results[0]["name"] == "finish"


def test_missing_max_model_calls_raises(loop_harness) -> None:
    del loop_harness.limits.max_model_calls
    with pytest.raises(ValueError, match="max_model_calls"):
        list(iter_agent_events(**loop_harness.kwargs))


def test_non_positive_max_model_calls_raises(loop_harness) -> None:
    loop_harness.limits.max_model_calls = 0
    with pytest.raises(ValueError, match="max_model_calls"):
        list(iter_agent_events(**loop_harness.kwargs))


def test_prose_with_native_tool_calls_is_kept(loop_harness) -> None:
    loop_harness.invoker.queue_text_and_tool_calls(
        "先问一下",
        [
            {
                "id": "a",
                "name": "ask_user",
                "arguments": {"questions": [{"id": "q", "question": "x", "kind": "text"}]},
            }
        ],
    )
    events = list(iter_agent_events(**loop_harness.kwargs))
    names = [name for name, _ in events]
    assert names[0] == "message"
    assert events[0][1]["delta"] == "先问一下"
    assert loop_harness.session.messages[1].event_type == "message"
    assert loop_harness.session.messages[1].payload["text"] == "先问一下"
    assert "waiting_user" in names


def test_terminal_waiting_user_survives_cancellation(loop_harness) -> None:
    class AbortOnceDispatched:
        def reason(self) -> str | None:
            if loop_harness.dispatch_order:
                return "user_abort"
            return None

    loop_harness.kwargs["cancellation"] = AbortOnceDispatched()
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "a",
                "name": "ask_user",
                "arguments": {"questions": [{"id": "q", "question": "x", "kind": "text"}]},
            }
        ]
    )
    events = list(iter_agent_events(**loop_harness.kwargs))
    names = [name for name, _ in events]
    assert "waiting_user" in names
    assert names[-1] == "waiting_user"


def test_mutating_tool_bumps_revision_once(loop_harness) -> None:
    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={})
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    loop_harness.context.state.graph = graph
    loop_harness.session.candidate_graph = graph
    loop_harness.session.candidate_revision = 0
    loop_harness.context.state.candidate_revision = 0
    loop_harness.invoker.queue_tool_calls(
        [{"id": "c", "name": "connect", "arguments": {"source": "start", "target": "end"}}]
    )
    list(iter_agent_events(**loop_harness.kwargs))
    assert loop_harness.session.candidate_revision == 1
    assert loop_harness.context.state.candidate_revision == 1


def test_accepted_finish_does_not_double_bump_revision(loop_harness) -> None:
    loop_harness.context.state.graph = _connected_start_end()
    loop_harness.session.candidate_graph = loop_harness.context.state.graph
    loop_harness.session.candidate_revision = 3
    loop_harness.context.state.candidate_revision = 3
    loop_harness.invoker.queue_tool_calls([{"id": "f", "name": "finish", "arguments": {"summary": "已搭好"}}])
    list(iter_agent_events(**loop_harness.kwargs))
    assert loop_harness.session.candidate_revision == loop_harness.context.state.candidate_revision
    assert loop_harness.context.state.candidate_revision == 4


def test_finish_hydrate_copies_context_revision(loop_harness) -> None:
    loop_harness.context.state.graph = _connected_start_end()
    loop_harness.session.candidate_graph = loop_harness.context.state.graph
    loop_harness.session.candidate_revision = 0
    loop_harness.context.state.candidate_revision = 0

    def hydrate(graph):
        return upsert_node(graph, node_id="start", node_type="start", title="已绑定", desc="", config={"variables": []})

    loop_harness.context.env = replace(loop_harness.context.env, hydrate_graph=hydrate)
    loop_harness.invoker.queue_tool_calls([{"id": "f", "name": "finish", "arguments": {"summary": "已 hydrate"}}])
    list(iter_agent_events(**loop_harness.kwargs))
    assert loop_harness.context.state.candidate_revision == 2
    assert loop_harness.session.candidate_revision == 2


def test_rejected_finish_does_not_bump_revision(loop_harness) -> None:
    loop_harness.invoker.queue_tool_calls([{"id": "f", "name": "finish", "arguments": {"summary": "好了"}}])
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "a",
                "name": "ask_user",
                "arguments": {"questions": [{"id": "q", "question": "x", "kind": "text"}]},
            }
        ]
    )
    list(iter_agent_events(**loop_harness.kwargs))
    assert loop_harness.session.candidate_revision == 0
    assert loop_harness.context.state.candidate_revision == 0


def test_compact_counts_toward_max_model_calls(loop_harness) -> None:
    loop_harness.limits.max_model_calls = 1
    loop_harness.invoker.queue_text("再想一步")
    compact_calls = {"n": 0}

    def compact(**kwargs: object) -> dict[str, object]:
        compact_calls["n"] += 1
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

    def token_counter(msgs: list[object]) -> int:
        text = "\n".join(getattr(m, "content", "") or "" for m in msgs)
        if "[COMPACTED HISTORY]" in text:
            return 50
        return 900

    events = list(
        iter_agent_events(
            **loop_harness.kwargs,
            compact=compact,
            token_counter=token_counter,
            token_limits=TokenLimits(
                input_limit=1000,
                compact_trigger=800,
                compact_target=700,
                compactor_input_limit=400,
            ),
        )
    )
    assert compact_calls["n"] >= 1
    assert events[-1][0] == "error"
    assert events[-1][1]["termination_reason"] == "max_model_calls"
    assert "message" not in {name for name, _ in events}


def test_embedded_tool_json_is_stripped_from_prose(loop_harness) -> None:
    loop_harness.invoker.queue_text_and_tool_calls(
        '先问一下\n{"id":"call_1","name":"ask_user","arguments":{"questions":[]}}\n',
        [
            {
                "id": "a",
                "name": "ask_user",
                "arguments": {"questions": [{"id": "q", "question": "x", "kind": "text"}]},
            }
        ],
    )
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert events[0][0] == "message"
    assert events[0][1]["delta"] == "先问一下"
    assert "call_1" not in events[0][1]["delta"]
    assert "waiting_user" in {name for name, _ in events}


def test_tool_json_only_message_is_omitted(loop_harness) -> None:
    loop_harness.invoker.queue_text_and_tool_calls(
        '{"id":"call_1","name":"ask_user","arguments":{"questions":[]}}',
        [
            {
                "id": "a",
                "name": "ask_user",
                "arguments": {"questions": [{"id": "q", "question": "x", "kind": "text"}]},
            }
        ],
    )
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert events[0][0] != "message"
    assert all(name != "message" for name, _ in events)
    calls, text = _parse_turn(
        {
            "text": '{"id":"call_1","name":"ask_user","arguments":{}}',
            "tool_calls": [{"id": "a", "name": "ask_user", "arguments": {}}],
        },
        0,
    )
    assert calls
    assert text is None


def test_successful_tool_result_omits_generic_ok_summary(loop_harness) -> None:
    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={})
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    loop_harness.context.state.graph = graph
    loop_harness.session.candidate_graph = graph
    loop_harness.invoker.queue_tool_calls(
        [{"id": "c", "name": "connect", "arguments": {"source": "start", "target": "end"}}]
    )
    events = list(iter_agent_events(**loop_harness.kwargs))
    result = next(payload for name, payload in events if name == "tool_result")
    assert result["ok"] is True
    assert result["summary"] == ""


def test_failed_tool_result_keeps_structured_summary() -> None:
    assert (
        _summary(
            {
                "tool_call_id": "c1",
                "name": "validate_graph",
                "ok": False,
                "changed": False,
                "content": {"valid": False, "errors": [{"code": "MISSING_END"}]},
                "error": None,
                "error_code": None,
                "retryable": False,
            }
        )
        == "1 validation errors"
    )
    assert (
        _summary(
            {
                "tool_call_id": "c1",
                "name": "connect",
                "ok": True,
                "changed": True,
                "content": {"id": "e1"},
                "error": None,
                "error_code": None,
                "retryable": False,
            }
        )
        == ""
    )


def test_graph_diff_added_removed_updated() -> None:
    before = upsert_node(empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={})
    before = upsert_node(before, node_id="extra", node_type="llm", title="多余", desc="", config={})
    before = upsert_node(before, node_id="end", node_type="end", title="结束", desc="", config={})
    after = upsert_node(empty_graph(), node_id="start", node_type="start", title="已改", desc="", config={})
    after = upsert_node(after, node_id="end", node_type="end", title="结束", desc="", config={})
    after = upsert_node(after, node_id="llm", node_type="llm", title="模型", desc="", config={})
    diff = _graph_diff(before, after)
    assert diff["added"] == ["llm"]
    assert diff["removed"] == ["extra"]
    assert diff["updated"] == ["start"]


class _PassRunner:
    def run(self, *, graph, revision, graph_hash, case_ids, mode):
        return [
            {
                "attempt_id": "att-1",
                "revision": revision,
                "graph_hash": graph_hash,
                "case_id": case_ids[0],
                "passed": True,
                "status": "simulated",
                "failed_nodes": [],
                "evidence": [],
                "trace_summary": "ok",
                "unverified_nodes": [],
            }
        ]


class _FailThenPassRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, *, graph, revision, graph_hash, case_ids, mode):
        self.calls += 1
        passed = self.calls > 1
        return [
            {
                "attempt_id": f"att-{self.calls}",
                "revision": revision,
                "graph_hash": graph_hash,
                "case_id": case_ids[0],
                "passed": passed,
                "status": "simulated",
                "failed_nodes": [] if passed else [{"id": "end", "type": "end", "error": "missing output"}],
                "evidence": [],
                "trace_summary": "ok" if passed else "end failed",
                "unverified_nodes": [],
            }
        ]


def test_finish_rejected_without_evidence_continues(loop_harness) -> None:
    loop_harness.context.state.graph = _connected_start_end()
    loop_harness.session.candidate_graph = loop_harness.context.state.graph
    loop_harness.context.env = replace(loop_harness.context.env, acceptance_runner=_PassRunner())
    loop_harness.invoker.queue_tool_calls([{"id": "f", "name": "finish", "arguments": {"summary": "好了"}}])
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "a",
                "name": "ask_user",
                "arguments": {"questions": [{"id": "q", "question": "x", "kind": "text"}]},
            }
        ]
    )
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert "done" not in {name for name, _ in events}
    assert any(name == "waiting_user" for name, _ in events)
    finish_results = [payload for name, payload in events if name == "tool_result" and payload.get("name") == "finish"]
    assert finish_results
    assert finish_results[0]["ok"] is False


def test_failed_acceptance_trace_then_repair_then_finish(loop_harness) -> None:
    loop_harness.context.state.graph = _connected_start_end()
    loop_harness.session.candidate_graph = loop_harness.context.state.graph
    runner = _FailThenPassRunner()
    loop_harness.context.env = replace(loop_harness.context.env, acceptance_runner=runner)
    loop_harness.invoker.queue_tool_calls([{"id": "a1", "name": "run_acceptance", "arguments": {}}])
    loop_harness.invoker.queue_tool_calls([{"id": "f1", "name": "finish", "arguments": {"summary": "早了"}}])
    loop_harness.invoker.queue_tool_calls([{"id": "a2", "name": "run_acceptance", "arguments": {}}])
    loop_harness.invoker.queue_tool_calls([{"id": "f2", "name": "finish", "arguments": {"summary": "好了"}}])
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert events[-1][0] == "done"
    first_accept = next(
        payload for name, payload in events if name == "tool_result" and payload.get("name") == "run_acceptance"
    )
    assert first_accept["ok"] is True
    assert first_accept.get("failed_nodes")[0]["id"] == "end"
    assert "missing output" in str(first_accept.get("failed_nodes"))
    assert loop_harness.session.last_acceptance["passed"] is True
