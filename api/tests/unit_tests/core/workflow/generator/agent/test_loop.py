import threading
import time
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from core.workflow.generator.agent.compaction import TokenLimits
from core.workflow.generator.agent.loop import iter_agent_events
from core.workflow.generator.agent.protocol.turn import _parse_turn
from core.workflow.generator.agent.scheduling import creates as create_scheduler
from core.workflow.generator.agent.state import reducer as state_reducer
from core.workflow.generator.agent.state.reducer import _graph_diff, _summary
from core.workflow.generator.agent.tools.tool_mutate import CompiledBuildNode
from core.workflow.generator.agent.tools.tools import ToolContext, compile_build_node
from core.workflow.generator.agent.tools.tools import dispatch as real_dispatch
from core.workflow.generator.agent.types import AgentMessage, AgentSession
from core.workflow.generator.graph.graph_ops import connect, empty_graph, find_node, upsert_node
from core.workflow.generator.pipeline.planner_context_values import PlannerContextLimitError
from tests.unit_tests.core.workflow.generator.node_fixtures import builder_config, node_config


def _intent(objective: str, *outputs: str, inputs: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "objective": objective,
        "inputs": inputs or [],
        "outputs": [{"name": name} for name in outputs],
    }


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


@pytest.mark.parametrize("streaming", [True, False])
def test_protocol_leak_retries_and_executes_only_fresh_native_call(loop_harness, streaming: bool) -> None:
    leak = '正在处理。{"id":"call_bad","name":"delete_node","arguments":{"node_id":"start"}</｜｜DSML｜｜invoke>'
    native = {"id": "call_good", "name": "read_graph", "arguments": {}}
    seen_prompts = []

    class RetryingInvoker:
        def invoke(self, messages):
            seen_prompts.append(messages)
            return [{"text": leak}, {"tool_calls": [native]}, {"text": "已读取。"}][len(seen_prompts) - 1]

        def iter_chunks(self, messages):
            if not streaming:
                return None
            seen_prompts.append(messages)
            turns = [
                [_stream_chunk(text=char) for char in leak],
                [_stream_chunk(tool_calls=[native])],
                [_stream_chunk(text="已读取。")],
            ]
            return iter(turns[len(seen_prompts) - 1])

    loop_harness.kwargs["invoker"] = RetryingInvoker()
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert loop_harness.dispatch_order == ["read_graph"]
    assert len(seen_prompts) == 3
    assert "MODEL_OUTPUT_PROTOCOL_ERROR" in str(seen_prompts[1])
    public = "".join(
        str(payload.get("text") or payload.get("delta") or "")
        for name, payload in events
        if name in {"message", "message.delta"}
    )
    assert "DSML" not in public
    assert "call_bad" not in public
    assert all("call_bad" not in str(message.payload) for message in loop_harness.session.messages)
    assistant_messages = [
        message
        for message in loop_harness.session.messages
        if message.role == "assistant" and message.event_type == "message"
    ]
    retry_notices = [
        message
        for message in assistant_messages
        if message.payload.get("text") == "模型返回的工具调用格式无效，本次调用未执行，正在自动重试。"
    ]
    assert len(retry_notices) == 1
    assert len({message.sequence for message in assistant_messages}) == len(assistant_messages)
    assert loop_harness.session.candidate_revision == 0


def test_protocol_retry_budget_ends_with_explicit_error(loop_harness) -> None:
    for _ in range(3):
        loop_harness.invoker.queue_text("<｜DSML｜tool_calls>broken")
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert events[-1][0] == "error"
    assert events[-1][1]["termination_reason"] == "model_protocol_error"
    assert not loop_harness.dispatch_order
    assert all(name not in {"done", "turn_complete", "waiting_user"} for name, _ in events)


@pytest.mark.parametrize("arguments", ['{"id":', "[1]", 42])
def test_invalid_blocking_arguments_retry_without_dispatch(loop_harness: SimpleNamespace, arguments: object) -> None:
    loop_harness.invoker.queue_tool_calls([{"id": "bad", "name": "read_graph", "arguments": arguments}])
    loop_harness.invoker.queue_tool_calls([{"id": "good", "name": "read_graph", "arguments": {}}])
    loop_harness.invoker.queue_text("已读取。")

    events = list(iter_agent_events(**loop_harness.kwargs))

    assert loop_harness.dispatch_order == ["read_graph"]
    assert [payload["id"] for name, payload in events if name == "tool_call"] == ["good"]


def test_protocol_retry_can_commit_requested_start_update(loop_harness: SimpleNamespace) -> None:
    keep = {"variable": "eval_count", "label": "评测数量", "type": "number", "required": True}
    remove = {"variable": "source_query", "label": "检索词", "type": "text-input", "required": True}
    graph = upsert_node(
        _connected_start_end(),
        node_id="start",
        node_type="start",
        title="开始",
        desc="",
        config={"variables": [keep, remove]},
    )
    loop_harness.context.state.graph = graph
    loop_harness.session.candidate_graph = graph
    loop_harness.context.env = replace(
        loop_harness.context.env,
        llm_client=_FakeLLM({"variables": [keep]}),
    )
    loop_harness.invoker.queue_text('我来删除。{"name":"build_node","arguments":{"id":"start"}</｜｜DSML｜｜invoke>')
    loop_harness.invoker.queue_tool_calls(
        [
            {"id": "read", "name": "read_node", "arguments": {"id": "start"}},
            {
                "id": "update",
                "name": "build_node",
                "arguments": {
                    "id": "start",
                    "mode": "update",
                    "intent": _intent("删除 source_query，保留 eval_count。"),
                },
            },
        ]
    )
    loop_harness.invoker.queue_text("已删除 `source_query`。")

    events = list(iter_agent_events(**loop_harness.kwargs))

    assert loop_harness.dispatch_order == ["read_node", "build_node"]
    start = find_node(loop_harness.session.candidate_graph, "start")
    assert start is not None
    assert [item["variable"] for item in start["data"]["variables"]] == ["eval_count"]
    assert loop_harness.session.candidate_revision == 1
    assert all(name not in {"error", "waiting_user"} for name, _ in events)


def test_streamed_held_text_matches_persisted_message(loop_harness: SimpleNamespace) -> None:
    text = "已保留 `eval_count`，删除 `source_query`。"
    invoker = StreamingFakeInvoker()
    invoker.queue_chunks([_stream_chunk(text=char) for char in text])
    loop_harness.kwargs["invoker"] = invoker

    events = list(iter_agent_events(**loop_harness.kwargs))

    deltas = [payload for name, payload in events if name == "message.delta"]
    assert "".join(payload["delta"] for payload in deltas) == text
    assert [payload["delta_index"] for payload in deltas] == list(range(len(deltas)))
    stored = [message for message in loop_harness.session.messages if message.role == "assistant"]
    assert len(stored) == 1
    assert stored[0].payload["text"] == text
    assert all(payload["message_id"] == stored[0].payload["message_id"] for payload in deltas)


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
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
    return connect(graph, source="start", target="end")


@pytest.fixture
def loop_harness(tool_context: ToolContext, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:

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

    monkeypatch.setattr(state_reducer, "dispatch", tracking_dispatch)

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


def test_empty_graph_first_call_has_skill_catalogue_without_bodies(loop_harness) -> None:
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
    contents = [str(getattr(message, "content", "") or "") for message in captured[0]]
    joined = "\n".join(contents)
    assert "# Available skills" in joined
    assert "create-from-scratch" in joined
    assert "# Active skills" not in joined
    assert "# Create from scratch" not in joined
    assert contents[-1].startswith("# Current situation")
    assert "active_skills: none" in contents[-1]


def _capture_prompt_contents(loop_harness) -> list[list[str]]:
    captured: list[list[str]] = []
    inner = loop_harness.invoker.invoke

    def capture(messages: object = None, **kwargs: object) -> dict[str, Any]:
        captured.append([str(getattr(message, "content", "") or "") for message in (messages or [])])
        return inner(messages, **kwargs)

    loop_harness.invoker.invoke = capture
    return captured


def test_activate_skills_stops_sibling_build_node_without_revision(loop_harness) -> None:
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "a",
                "name": "activate_skills",
                "arguments": {"names": ["create-from-scratch"]},
            },
            {
                "id": "b",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "n1",
                    "type": "llm",
                    "title": "模型",
                    "intent": _intent("写一段说明"),
                },
            },
        ]
    )
    loop_harness.invoker.queue_text("先这样")
    events = list(iter_agent_events(**loop_harness.kwargs))
    names = [name for name, _ in events]
    assert loop_harness.dispatch_order == ["activate_skills"]
    assert loop_harness.session.candidate_revision == 0
    assert find_node(loop_harness.context.state.graph, "n1") is None
    assert "waiting_user" not in names
    assert names[-1] == "turn_complete"


def test_activate_skills_drops_sibling_build_node_that_precedes_it(loop_harness) -> None:
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "b",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "n1",
                    "type": "llm",
                    "title": "模型",
                    "intent": _intent("写一段说明"),
                },
            },
            {
                "id": "a",
                "name": "activate_skills",
                "arguments": {"names": ["create-from-scratch"]},
            },
        ]
    )
    loop_harness.invoker.queue_text("先这样")

    events = list(iter_agent_events(**loop_harness.kwargs))

    assert loop_harness.dispatch_order == ["activate_skills"]
    assert loop_harness.session.candidate_revision == 0
    assert find_node(loop_harness.context.state.graph, "n1") is None
    assert "waiting_user" not in {name for name, _ in events}
    assert events[-1][0] == "turn_complete"


def test_second_model_call_injects_active_skill_bodies(loop_harness) -> None:
    captured = _capture_prompt_contents(loop_harness)
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "a",
                "name": "activate_skills",
                "arguments": {"names": ["create-from-scratch", "bind-resources"]},
            }
        ]
    )
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    assert len(captured) >= 2
    first = "\n".join(captured[0])
    second_tail = captured[1][-1]
    assert "# Available skills" in first
    assert "# Active skills" not in first
    assert second_tail.startswith("# Active skills")
    assert "## create-from-scratch" in second_tail
    assert "## bind-resources" in second_tail
    create_at = second_tail.index("## create-from-scratch")
    bind_at = second_tail.index("## bind-resources")
    assert create_at < bind_at
    assert "active_skills: create-from-scratch, bind-resources" in captured[1][-2]


def test_switching_skills_replaces_active_tail(loop_harness) -> None:
    captured = _capture_prompt_contents(loop_harness)
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "a1",
                "name": "activate_skills",
                "arguments": {
                    "names": ["create-from-scratch", "bind-resources", "build-container", "repair-validation"]
                },
            }
        ]
    )
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "a2",
                "name": "activate_skills",
                "arguments": {"names": ["verify-and-finish", "repair-validation"]},
            }
        ]
    )
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    third_tail = captured[2][-1]
    assert third_tail.startswith("# Active skills")
    assert "## repair-validation" in third_tail
    assert "## build-container" in captured[1][-1]
    assert "## verify-and-finish" in third_tail
    assert "## build-container" not in third_tail
    assert "## bind-resources" not in third_tail
    assert "## create-from-scratch" not in third_tail


def test_compaction_after_activation_still_injects_skill_bodies(loop_harness) -> None:
    captured = _capture_prompt_contents(loop_harness)
    loop_harness.kwargs["compact"] = lambda **kwargs: {
        "objective": ["构建 RAG 测试工作流"],
        "user_constraints": [],
        "confirmed_facts": [],
        "decisions": [],
        "rejected_approaches": [],
        "important_resources": [],
        "pending_work": [],
        "reloadable_details": [],
    }
    loop_harness.kwargs["token_limits"] = TokenLimits(
        input_limit=1000,
        compact_trigger=1,
        compact_target=1,
        compactor_input_limit=400,
    )
    loop_harness.kwargs["token_counter"] = lambda msgs: 900
    loop_harness.limits.max_model_calls = 12
    loop_harness.invoker.queue_tool_calls(
        [{"id": "a", "name": "activate_skills", "arguments": {"names": ["create-from-scratch"]}}]
    )
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    assert captured[1][-1].startswith("# Active skills")
    assert "## create-from-scratch" in captured[1][-1]


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
    prose = [
        item for item in loop_harness.session.messages if item.event_type == "message" and item.role == "assistant"
    ]
    assert prose[-1].payload["text"] == "正在创建"
    assert prose[-1].payload["reasoning"] == "先读图"
    prompt_texts = []
    for message in loop_harness.session.messages:
        prompt_texts.append(str(message.payload.get("text") or ""))
        prompt_texts.append(str(message.payload.get("reasoning") or ""))
    # Session stores reasoning, but it must not be treated as public narration.
    assert prose[-1].payload["reasoning"] == "先读图"
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
    prose = [
        item for item in loop_harness.session.messages if item.event_type == "message" and item.role == "assistant"
    ]
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
        payload.get("text") or payload.get("delta") for name, payload in events if name in {"message.delta", "message"}
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


def test_builder_model_call_counts_toward_shared_run_budget(loop_harness) -> None:
    loop_harness.limits.max_model_calls = 2
    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    loop_harness.invoker.queue_tool_calls([_create_call("create", "llm1")])
    loop_harness.invoker.queue_text("Created.")

    events = list(iter_agent_events(**loop_harness.kwargs))

    assert events[-1][0] == "error"
    assert events[-1][1]["termination_reason"] == "max_model_calls"
    assert events[-1][1]["usage"]["model_calls"] == 2
    assert loop_harness.invoker.invoke_count == 1


def test_container_child_builder_counts_toward_shared_run_budget(loop_harness) -> None:
    loop_harness.limits.max_model_calls = 2
    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    call = _loop_create_call("loop-call", "loop1")
    call["arguments"]["logical_operator"] = "and"
    call["arguments"]["children"] = [
        {
            "kind": "standard",
            "ref": "step",
            "node_type": "llm",
            "intent": _intent("Generate one answer", "text"),
        }
    ]
    loop_harness.invoker.queue_tool_calls([call])
    loop_harness.invoker.queue_text("Created.")

    events = list(iter_agent_events(**loop_harness.kwargs))

    assert events[-1][0] == "error", [
        events,
        [message.payload for message in loop_harness.session.messages if message.event_type == "tool_result"],
    ]
    assert events[-1][1]["termination_reason"] == "max_model_calls"
    assert events[-1][1]["usage"]["model_calls"] == 2
    assert loop_harness.invoker.invoke_count == 1
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
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
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

    original = state_reducer.dispatch

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

    monkeypatch.setattr(state_reducer, "dispatch", flaky)
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
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def iter_json(self, *, messages, stage):
        yield from ()
        return {"config": builder_config(messages, self.config)}


class _QueuedFakeLLM:
    def __init__(self, configs: list[dict[str, Any]]) -> None:
        self.configs = list(configs)

    def iter_json(self, *, messages, stage):
        yield from ()
        return {"config": builder_config(messages, self.configs.pop(0))}


class _RecordingLoopLLM:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.user_prompts: list[str] = []
        self.config = config or {}

    def iter_json(self, *, messages, stage):
        self.user_prompts.append(str(messages[-1].content))
        yield from ()
        return {"config": builder_config(messages, self.config)}


def _create_call(call_id: str, node_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "name": "build_node",
        "arguments": {"mode": "create", "id": node_id, "type": "llm", "title": node_id, "intent": _intent("建节点")},
    }


def _tool_create_call(call_id: str, node_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "name": "build_tool_node",
        "arguments": {
            "mode": "create",
            "id": node_id,
            "title": node_id,
            "tool": {"provider_name": "text/provider", "tool_name": "summarize"},
            "arguments": {"prompt": {"kind": "constant", "value": "hi"}},
        },
    }


def _agent_create_call(call_id: str, node_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "name": "build_agent_node",
        "arguments": {
            "mode": "create",
            "id": node_id,
            "title": node_id,
            "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
            "instruction": "answer",
            "inputs": [],
            "outputs": [{"name": "text"}],
        },
    }


def _loop_create_call(call_id: str, node_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "name": "build_loop",
        "arguments": {
            "mode": "create",
            "id": node_id,
            "title": node_id,
            "loop_count": 1,
            "loop_variables": [{"label": "acc", "var_type": "string", "value_type": "constant", "value": ""}],
            "children": [],
            "edges": [],
            "break_conditions": [],
            "outputs": [{"name": "acc", "type": "string"}],
        },
    }


def _compiled_loop_stub(call, context):
    from core.workflow.generator.agent.tools.tool_build_container import CompiledBuildContainer
    from core.workflow.generator.compiler.container_types import CompiledContainer

    node_id = str(call["arguments"]["id"])
    graph = upsert_node(
        deepcopy(context.state.graph),
        node_id=node_id,
        node_type="loop",
        title=str(call["arguments"]["title"]),
        desc="",
        config={"loop_count": 1, "start_node_id": f"{node_id}start"},
    )
    return CompiledBuildContainer(
        call=call,
        compiled=CompiledContainer(graph=graph, base_revision=context.state.candidate_revision),
        container_id=node_id,
        title=str(call["arguments"]["title"]),
        mode="create",
        old_config={},
        node_type="loop",
    )


def test_independent_specialized_creates_compile_in_parallel_and_commit_in_order(
    loop_harness, monkeypatch: pytest.MonkeyPatch
) -> None:

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    barrier = threading.Barrier(2, timeout=5)
    compile_order: list[str] = []
    commit_order: list[str] = []
    lock = threading.Lock()

    def compile_tool(call, context):
        with lock:
            compile_order.append(call["arguments"]["id"])
        barrier.wait()
        return {
            "tool_call_id": call["id"],
            "name": call["name"],
            "ok": True,
            "changed": False,
            "content": {"id": call["arguments"]["id"]},
            "error": None,
            "error_code": None,
            "retryable": False,
        }

    def compile_agent(call, context):
        with lock:
            compile_order.append(call["arguments"]["id"])
        barrier.wait()
        return {
            "tool_call_id": call["id"],
            "name": call["name"],
            "ok": True,
            "changed": False,
            "content": {"id": call["arguments"]["id"]},
            "error": None,
            "error_code": None,
            "retryable": False,
        }

    real_commit_tool = create_scheduler.commit_build_tool_node
    real_commit_agent = create_scheduler.commit_build_agent_node

    def remember_tool(compiled, context):
        commit_order.append(compiled["content"]["id"] if isinstance(compiled, dict) else "tool")
        if isinstance(compiled, dict):
            return compiled
        return real_commit_tool(compiled, context)

    def remember_agent(compiled, context):
        commit_order.append(compiled["content"]["id"] if isinstance(compiled, dict) else "agent")
        if isinstance(compiled, dict):
            return compiled
        return real_commit_agent(compiled, context)

    monkeypatch.setattr(create_scheduler, "compile_build_tool_node", compile_tool)
    monkeypatch.setattr(create_scheduler, "compile_build_agent_node", compile_agent)
    monkeypatch.setattr(create_scheduler, "commit_build_tool_node", remember_tool)
    monkeypatch.setattr(create_scheduler, "commit_build_agent_node", remember_agent)

    loop_harness.invoker.queue_tool_calls([_tool_create_call("c1", "t1"), _agent_create_call("c2", "a1")])
    loop_harness.invoker.queue_text("先这样")
    events = list(iter_agent_events(**loop_harness.kwargs))
    names = [name for name, _ in events]
    call_indexes = [index for index, name in enumerate(names) if name == "tool_call"]
    result_indexes = [index for index, name in enumerate(names) if name == "tool_result"]
    assert max(call_indexes) < min(result_indexes)
    assert compile_order == ["t1", "a1"] or set(compile_order) == {"t1", "a1"}
    assert commit_order == ["t1", "a1"]


def test_dependent_container_and_child_compile_serially(loop_harness, monkeypatch: pytest.MonkeyPatch) -> None:

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    compile_started: list[str] = []
    lock = threading.Lock()
    child_started_during_loop = threading.Event()
    loop_holding = threading.Event()
    release_loop = threading.Event()

    def compile_loop(call, context):
        with lock:
            compile_started.append(call["arguments"]["id"])
        loop_holding.set()
        assert release_loop.wait(timeout=5)
        if "child" in compile_started:
            child_started_during_loop.set()
        return {
            "tool_call_id": call["id"],
            "name": call["name"],
            "ok": True,
            "changed": False,
            "content": {"id": call["arguments"]["id"]},
            "error": None,
            "error_code": None,
            "retryable": False,
        }

    def compile_node(call, context):
        with lock:
            compile_started.append(call["arguments"]["id"])
        return {
            "tool_call_id": call["id"],
            "name": call["name"],
            "ok": True,
            "changed": False,
            "content": {"id": call["arguments"]["id"]},
            "error": None,
            "error_code": None,
            "retryable": False,
        }

    monkeypatch.setattr(create_scheduler, "compile_build_loop", compile_loop)
    monkeypatch.setattr(create_scheduler, "compile_build_node", compile_node)
    loop_harness.invoker.queue_tool_calls(
        [
            _loop_create_call("c1", "loop1"),
            {
                "id": "c2",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "child",
                    "type": "llm",
                    "title": "步骤",
                    "parent": "loop1",
                    "intent": _intent("run the step", "text"),
                },
            },
        ]
    )
    loop_harness.invoker.queue_text("先这样")

    def run() -> None:
        list(iter_agent_events(**loop_harness.kwargs))

    worker = threading.Thread(target=run)
    worker.start()
    assert loop_holding.wait(timeout=5)
    assert compile_started == ["loop1"]
    release_loop.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert compile_started == ["loop1", "child"]
    assert not child_started_during_loop.is_set()


def test_container_create_commits_once_and_bumps_revision_by_one(loop_harness, monkeypatch: pytest.MonkeyPatch) -> None:

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    commits: list[str] = []
    real_commit = create_scheduler.commit_build_container

    def counting_commit(compiled, context):
        commits.append(compiled.container_id)
        return real_commit(compiled, context)

    def fake_compile(call, context):
        return _compiled_loop_stub(call, context)

    monkeypatch.setattr(create_scheduler, "compile_build_loop", fake_compile)
    monkeypatch.setattr(create_scheduler, "commit_build_container", counting_commit)
    before = loop_harness.context.state.candidate_revision
    loop_harness.invoker.queue_tool_calls([_loop_create_call("c1", "loop1")])
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    assert commits == ["loop1"]
    assert loop_harness.context.state.candidate_revision == before + 1


def test_two_loop_creates_commit_in_order_without_stale_revision(loop_harness, monkeypatch: pytest.MonkeyPatch) -> None:

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    monkeypatch.setattr(create_scheduler, "compile_build_loop", _compiled_loop_stub)
    loop_harness.invoker.queue_tool_calls([_loop_create_call("c1", "loop1"), _loop_create_call("c2", "loop2")])
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    results = [message.payload for message in loop_harness.session.messages if message.event_type == "tool_result"]
    assert [item.get("error_code") for item in results if item.get("name") == "build_loop"] == [None, None]
    assert find_node(loop_harness.context.state.graph, "loop1") is not None
    assert find_node(loop_harness.context.state.graph, "loop2") is not None
    assert loop_harness.context.state.candidate_revision == 2


def test_node_then_loop_create_does_not_stale(loop_harness, monkeypatch: pytest.MonkeyPatch) -> None:

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    monkeypatch.setattr(create_scheduler, "compile_build_loop", _compiled_loop_stub)
    loop_harness.invoker.queue_tool_calls([_create_call("c1", "n1"), _loop_create_call("c2", "loop1")])
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    loop_results = [
        message.payload
        for message in loop_harness.session.messages
        if message.event_type == "tool_result" and message.payload.get("name") == "build_loop"
    ]
    assert loop_results
    assert loop_results[0].get("error_code") is None
    assert find_node(loop_harness.context.state.graph, "n1") is not None
    assert find_node(loop_harness.context.state.graph, "loop1") is not None


def test_update_creates_stay_serial(loop_harness, monkeypatch: pytest.MonkeyPatch) -> None:

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    seen: list[str] = []

    def tracking_dispatch(call, context):
        seen.append(f"{call['name']}:{call['arguments'].get('mode')}:{call['arguments'].get('id')}")
        return {
            "tool_call_id": call["id"],
            "name": call["name"],
            "ok": True,
            "changed": False,
            "content": {},
            "error": None,
            "error_code": None,
            "retryable": False,
        }

    compiles: list[str] = []

    def tracking_compile(call, context):
        compiles.append(call["arguments"]["id"])
        return {
            "tool_call_id": call["id"],
            "name": call["name"],
            "ok": True,
            "changed": False,
            "content": {"id": call["arguments"]["id"]},
            "error": None,
            "error_code": None,
            "retryable": False,
        }

    monkeypatch.setattr(state_reducer, "dispatch", tracking_dispatch)
    monkeypatch.setattr(create_scheduler, "compile_build_node", tracking_compile)
    loop_harness.invoker.queue_tool_calls(
        [
            {**_create_call("c1", "n1"), "arguments": {**_create_call("c1", "n1")["arguments"], "mode": "update"}},
            _create_call("c2", "n2"),
        ]
    )
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    assert seen == ["build_node:update:n1"]
    assert compiles == ["n2"]


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

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    windows: list[tuple[float, float]] = []
    active = 0
    max_active = 0
    lock = threading.Lock()
    real_compile = create_scheduler.compile_build_node

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

    monkeypatch.setattr(create_scheduler, "compile_build_node", delayed_compile)
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

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    real_compile = create_scheduler.compile_build_node

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

    monkeypatch.setattr(create_scheduler, "compile_build_node", fail_second)
    loop_harness.invoker.queue_tool_calls([_create_call("c1", "n1"), _create_call("c2", "n2")])
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    assert find_node(loop_harness.context.state.graph, "n1") is not None
    assert find_node(loop_harness.context.state.graph, "n2") is None


def test_parallel_duplicate_create_ids_do_not_compile(loop_harness) -> None:
    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    loop_harness.invoker.queue_tool_calls(
        [_create_call("c1", "n1"), _create_call("c2", "n1"), _create_call("c3", "n3")]
    )
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    results = [message for message in loop_harness.session.messages if message.event_type == "tool_result"]
    dupes = [message for message in results if message.payload.get("error_code") == "DUPLICATE_BATCH_NODE_ID"]
    assert len(dupes) == 1
    assert find_node(loop_harness.context.state.graph, "n1") is None
    assert find_node(loop_harness.context.state.graph, "n3") is None
    assert [message.payload.get("tool_call_id") for message in results] == ["c1"]
    assert loop_harness.context.state.pending_plan_nodes == ()


def test_parallel_container_then_child_commits_both(loop_harness, monkeypatch: pytest.MonkeyPatch) -> None:

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]

    monkeypatch.setattr(create_scheduler, "compile_build_loop", _compiled_loop_stub)
    loop_harness.invoker.queue_tool_calls(
        [
            _loop_create_call("c1", "iter1"),
            {
                "id": "c2",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "child",
                    "type": "llm",
                    "title": "步骤",
                    "intent": _intent("run the step", "text"),
                    "parent": "iter1",
                },
            },
        ]
    )
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    child = find_node(loop_harness.context.state.graph, "child")
    assert find_node(loop_harness.context.state.graph, "iter1") is not None
    assert child is not None
    assert child.get("parentId") == "iter1"
    assert loop_harness.context.state.pending_plan_nodes == ()


def test_iteration_scope_selector_does_not_create_self_dependency(
    loop_harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    iteration_call = {
        "id": "iteration-call",
        "name": "build_iteration",
        "arguments": {
            "mode": "create",
            "id": "iter1",
            "title": "逐条处理",
            "iterator_selector": ["parse_cases", "cases"],
            "iterator_input_type": "array[object]",
            "output_selector": ["judge", "text"],
            "children": [
                {
                    "kind": "llm",
                    "ref": "judge",
                    "intent": {
                        "inputs": [{"role": "query", "source": ["iter1", "item"]}],
                        "outputs": [{"name": "text", "type": "string"}],
                    },
                }
            ],
            "edges": [],
            "outputs": [{"name": "output", "type": "array[string]"}],
            "is_parallel": False,
            "parallel_nums": 10,
            "error_handle_mode": "terminated",
            "flatten_output": True,
        },
    }

    monkeypatch.setattr(create_scheduler, "compile_build_iteration", _compiled_loop_stub)
    loop_harness.invoker.queue_tool_calls([iteration_call])
    loop_harness.invoker.queue_text("先这样")

    list(iter_agent_events(**loop_harness.kwargs))

    assert find_node(loop_harness.context.state.graph, "iter1") is not None
    results = [message.payload for message in loop_harness.session.messages if message.event_type == "tool_result"]
    assert [result["tool_call_id"] for result in results] == ["iteration-call"]


def test_parallel_child_before_container_drops_later_container(loop_harness, monkeypatch: pytest.MonkeyPatch) -> None:

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]

    monkeypatch.setattr(create_scheduler, "compile_build_loop", _compiled_loop_stub)
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "c1",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "child",
                    "type": "llm",
                    "title": "步骤",
                    "intent": _intent("run the step", "text"),
                    "parent": "iter1",
                },
            },
            _loop_create_call("c2", "iter1"),
        ]
    )
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    results = [message for message in loop_harness.session.messages if message.event_type == "tool_result"]
    child_result = next(message for message in results if message.payload.get("tool_call_id") == "c1")
    assert child_result.payload.get("error_code") == "INVALID_PARENT"
    assert find_node(loop_harness.context.state.graph, "child") is None
    assert find_node(loop_harness.context.state.graph, "iter1") is None
    assert not any(message.payload.get("tool_call_id") == "c2" for message in results)


def test_pending_plan_nodes_cleared_after_builder_error(loop_harness, monkeypatch: pytest.MonkeyPatch) -> None:

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    real_compile = create_scheduler.compile_build_node

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

    monkeypatch.setattr(create_scheduler, "compile_build_node", fail_second)
    loop_harness.invoker.queue_tool_calls([_create_call("c1", "n1"), _create_call("c2", "n2")])
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    assert loop_harness.context.state.pending_plan_nodes == ()


def test_pending_plan_nodes_cleared_after_unexpected_compile_error(
    loop_harness, monkeypatch: pytest.MonkeyPatch
) -> None:

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]

    def explode(call, context):
        raise RuntimeError("boom")

    monkeypatch.setattr(create_scheduler, "compile_build_node", explode)
    loop_harness.invoker.queue_tool_calls([_create_call("c1", "n1"), _create_call("c2", "n2")])
    with pytest.raises(RuntimeError, match="boom"):
        list(iter_agent_events(**loop_harness.kwargs))
    assert loop_harness.context.state.pending_plan_nodes == ()


def test_next_build_does_not_see_previous_pending(loop_harness) -> None:
    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    loop_harness.invoker.queue_tool_calls([_create_call("c1", "n1"), _create_call("c2", "n2")])
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    assert loop_harness.context.state.pending_plan_nodes == ()
    compiled = compile_build_node(
        {
            "id": "c3",
            "name": "build_node",
            "arguments": {"mode": "create", "id": "n3", "type": "llm", "title": "n3", "intent": _intent("建节点")},
        },
        loop_harness.context,
    )
    assert isinstance(compiled, CompiledBuildNode)
    assert loop_harness.context.state.pending_plan_nodes == ()


def test_same_turn_consumer_builder_sees_confirmed_producer_outputs(loop_harness) -> None:
    import json

    client = _RecordingLoopLLM()
    loop_harness.context.env = replace(loop_harness.context.env, llm_client=client)  # type: ignore[arg-type]
    start_purpose = (
        "Objective: accept the user's search question. Inputs: none Outputs: query "
        "Behavior: one required paragraph input. Variable references: none "
        "Resource bindings: none Configuration constraints: none Fields to preserve: none"
    )
    llm_purpose = (
        "Objective: answer. Inputs: {{#start.query#}} Outputs: text Behavior: use retrieval. "
        "Variable references: {{#start.query#}} Resource bindings: none "
        "Configuration constraints: none Fields to preserve: none"
    )
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "c1",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "start",
                    "type": "start",
                    "title": "开始",
                    "intent": {
                        **_intent(start_purpose, "query"),
                        "structure": {
                            "kind": "start",
                            "variables": [{"name": "query", "label": "Query", "type": "paragraph", "required": True}],
                        },
                    },
                },
            },
            {
                "id": "c2",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "llm1",
                    "type": "llm",
                    "title": "回答",
                    "intent": _intent(
                        llm_purpose,
                        "text",
                        inputs=[{"source": ["start", "query"], "role": "query"}],
                    ),
                },
            },
        ]
    )
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    assert any("id=llm1, type=llm" in prompt for prompt in client.user_prompts), [
        client.user_prompts,
        [message.payload for message in loop_harness.session.messages if message.event_type == "tool_result"],
    ]
    llm_prompt = next(prompt for prompt in client.user_prompts if "id=llm1, type=llm" in prompt)
    marker = "# Normalized plan and topology"
    _, _, rest = llm_prompt.partition(marker)
    plan = json.loads(rest.strip().split("\n\n", 1)[0])
    start = next(node for node in plan["nodes"] if node["id"] == "start")
    assert start["outputs"] == ["query"]
    assert start["outputs_kind"] == "confirmed"


def test_same_turn_forward_dependency_requests_producer_first_without_mutation(loop_harness) -> None:
    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    original = deepcopy(loop_harness.context.state.graph)
    consumer = {
        "id": "consumer-call",
        "name": "build_node",
        "arguments": {
            "mode": "create",
            "id": "llm1",
            "type": "llm",
            "title": "Answer",
            "intent": _intent(
                "Answer the question",
                "text",
                inputs=[{"source": ["start", "query"], "role": "query"}],
            ),
        },
    }
    producer = {
        "id": "producer-call",
        "name": "build_node",
        "arguments": {
            "mode": "create",
            "id": "start",
            "type": "start",
            "title": "Start",
            "intent": {
                **_intent("Accept the question", "query"),
                "structure": {
                    "kind": "start",
                    "variables": [{"name": "query", "label": "Query", "type": "paragraph"}],
                },
            },
        },
    }
    loop_harness.invoker.queue_tool_calls([consumer, producer])
    loop_harness.invoker.queue_text("I will submit the producer first.")

    list(iter_agent_events(**loop_harness.kwargs))

    results = [message.payload for message in loop_harness.session.messages if message.event_type == "tool_result"]
    assert [result["tool_call_id"] for result in results] == ["consumer-call"]
    assert results[0]["error_code"] == "DEPENDENCY_ORDER_REQUIRED"
    assert results[0]["cause"]["later_producer_ids"] == ["start"]
    assert loop_harness.context.state.graph == original
    assert loop_harness.session.candidate_revision == 0


def test_loop_variable_selector_is_a_same_turn_data_dependency(loop_harness) -> None:
    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    loop_call = _loop_create_call("loop-call", "loop1")
    loop_call["arguments"]["logical_operator"] = "and"
    loop_call["arguments"]["loop_variables"] = [
        {"label": "acc", "var_type": "string", "value_type": "variable", "value": ["start", "query"]}
    ]
    start_call = {
        "id": "start-call",
        "name": "build_node",
        "arguments": {
            "mode": "create",
            "id": "start",
            "type": "start",
            "title": "Start",
            "intent": {
                **_intent("Accept query", "query"),
                "structure": {
                    "kind": "start",
                    "variables": [{"name": "query", "label": "Query", "type": "paragraph"}],
                },
            },
        },
    }
    loop_harness.invoker.queue_tool_calls([loop_call, start_call])
    loop_harness.invoker.queue_text("I will submit Start first.")

    list(iter_agent_events(**loop_harness.kwargs))

    results = [message.payload for message in loop_harness.session.messages if message.event_type == "tool_result"]
    assert [result["tool_call_id"] for result in results] == ["loop-call"]
    assert results[0]["error_code"] == "DEPENDENCY_ORDER_REQUIRED"
    assert find_node(loop_harness.context.state.graph, "loop1") is None
    assert find_node(loop_harness.context.state.graph, "start") is None


def test_three_level_dependency_chain_compiles_only_after_each_producer_commit(loop_harness) -> None:
    import json

    client = _RecordingLoopLLM({"prompt_template": [{"role": "user", "text": "{{#transform.mid#}}"}]})
    loop_harness.context.env = replace(loop_harness.context.env, llm_client=client)  # type: ignore[arg-type]
    start = {
        "id": "start-call",
        "name": "build_node",
        "arguments": {
            "mode": "create",
            "id": "start",
            "type": "start",
            "title": "Start",
            "intent": {
                **_intent("Accept query", "query"),
                "structure": {
                    "kind": "start",
                    "variables": [{"name": "query", "label": "Query", "type": "paragraph"}],
                },
            },
        },
    }
    transform = {
        "id": "transform-call",
        "name": "build_node",
        "arguments": {
            "mode": "create",
            "id": "transform",
            "type": "code",
            "title": "Transform",
            "intent": {
                **_intent(
                    "Normalize query",
                    inputs=[{"source": ["start", "query"], "role": "query"}],
                ),
                "outputs": [{"name": "mid", "type": "string"}],
                "structure": {
                    "kind": "code",
                    "language": "python3",
                    "code": "def main(query: str):\n    return {'mid': query}",
                    "bindings": [{"name": "query", "source": ["start", "query"]}],
                },
            },
        },
    }
    answer = {
        "id": "answer-call",
        "name": "build_node",
        "arguments": {
            "mode": "create",
            "id": "answer",
            "type": "llm",
            "title": "Answer",
            "intent": _intent(
                "Answer with normalized query",
                "text",
                inputs=[{"source": ["transform", "mid"], "role": "query"}],
            ),
        },
    }
    loop_harness.invoker.queue_tool_calls([start, transform, answer])
    loop_harness.invoker.queue_text("Created.")

    list(iter_agent_events(**loop_harness.kwargs))

    assert any("id=answer, type=llm" in prompt for prompt in client.user_prompts), [
        client.user_prompts,
        [message.payload for message in loop_harness.session.messages if message.event_type == "tool_result"],
    ]
    answer_prompt = next(prompt for prompt in client.user_prompts if "id=answer, type=llm" in prompt)
    _, _, plan_text = answer_prompt.partition("# Normalized plan and topology")
    plan = json.loads(plan_text.strip().split("\n\n", 1)[0])
    producer = next(node for node in plan["nodes"] if node["id"] == "transform")
    assert producer["outputs"] == ["mid"]
    assert producer["outputs_kind"] == "confirmed"
    assert loop_harness.session.candidate_revision == 3


def test_same_turn_tool_consumer_uses_confirmed_producer_output_type(loop_harness) -> None:
    producer_entry = {
        "provider_name": "files/provider",
        "provider_type": "builtin",
        "plugin_id": "files/provider",
        "tool_name": "load",
        "tool_label": "Load file",
        "description": "Return a file",
        "parameters": (),
        "parameter_names": (),
        "output_names": ("file",),
        "outputs": ({"name": "file", "type": "file"},),
    }
    consumer_entry = {
        "provider_name": "files/provider",
        "provider_type": "builtin",
        "plugin_id": "files/provider",
        "tool_name": "describe",
        "tool_label": "Describe file",
        "description": "Describe a file",
        "parameters": ({"name": "file", "type": "file", "form": "llm", "required": True},),
        "parameter_names": ("file",),
        "output_names": ("text",),
        "outputs": ({"name": "text", "type": "string"},),
    }
    loop_harness.context.env = replace(
        loop_harness.context.env,
        tools_available=True,
        installed_tools={("files/provider", "load"), ("files/provider", "describe")},
        tool_entries=[producer_entry, consumer_entry],  # type: ignore[list-item]
    )
    producer = {
        "id": "producer-call",
        "name": "build_tool_node",
        "arguments": {
            "mode": "create",
            "id": "producer",
            "title": "Load",
            "tool": {"provider_name": "files/provider", "tool_name": "load"},
            "arguments": {},
        },
    }
    consumer = {
        "id": "consumer-call",
        "name": "build_tool_node",
        "arguments": {
            "mode": "create",
            "id": "consumer",
            "title": "Describe",
            "tool": {"provider_name": "files/provider", "tool_name": "describe"},
            "arguments": {"file": {"kind": "variable", "selector": ["producer", "file"]}},
        },
    }
    loop_harness.invoker.queue_tool_calls([producer, consumer])
    loop_harness.invoker.queue_text("Created.")

    list(iter_agent_events(**loop_harness.kwargs))

    consumer_node = find_node(loop_harness.context.state.graph, "consumer")
    assert consumer_node is not None
    assert consumer_node["data"]["tool_parameters"]["file"] == {
        "type": "variable",
        "value": ["producer", "file"],
    }
    assert loop_harness.session.candidate_revision == 2


def test_failed_producer_prevents_dependent_consumer_compile(loop_harness) -> None:
    class FailingProducerBuilder:
        def __init__(self) -> None:
            self.targets: list[str] = []

        def iter_json(self, *, messages, stage):
            del stage
            prompt = str(messages[-1].content)
            self.targets.append("start" if "id=start, type=start" in prompt else "consumer")
            raise RuntimeError("builder unavailable")
            yield

    client = FailingProducerBuilder()
    loop_harness.context.env = replace(loop_harness.context.env, llm_client=client)  # type: ignore[arg-type]
    producer = {
        "id": "producer-call",
        "name": "build_node",
        "arguments": {
            "mode": "create",
            "id": "start",
            "type": "start",
            "title": "Start",
            "intent": _intent("Accept query", "query"),
        },
    }
    consumer = {
        "id": "consumer-call",
        "name": "build_node",
        "arguments": {
            "mode": "create",
            "id": "consumer",
            "type": "llm",
            "title": "Consumer",
            "intent": _intent(
                "Consume query",
                "text",
                inputs=[{"source": ["start", "query"], "role": "query"}],
            ),
        },
    }
    loop_harness.invoker.queue_tool_calls([producer, consumer])
    loop_harness.invoker.queue_text("Retry later.")

    list(iter_agent_events(**loop_harness.kwargs))

    results = [message.payload for message in loop_harness.session.messages if message.event_type == "tool_result"]
    assert client.targets == ["start"]
    assert [result["error_code"] for result in results] == ["CAPABILITY_UNAVAILABLE", "DEPENDENCY_FAILED"]
    assert loop_harness.session.candidate_revision == 0


def test_cancellation_during_producer_compile_discards_dependency_batch(loop_harness) -> None:
    class CancellingBuilder:
        def __init__(self) -> None:
            self.targets: list[str] = []

        def iter_json(self, *, messages, stage):
            del stage
            prompt = str(messages[-1].content)
            target = "start" if "id=start, type=start" in prompt else "consumer"
            self.targets.append(target)
            if target == "start":
                loop_harness.cancellation.abort("user_abort")
                yield from ()
                return {
                    "config": builder_config(
                        messages,
                        {
                            "variables": [
                                {
                                    "variable": "query",
                                    "label": "Query",
                                    "type": "paragraph",
                                    "required": True,
                                    "max_length": 4096,
                                    "options": [],
                                }
                            ]
                        },
                    )
                }
            raise AssertionError("cancelled dependency consumer must not compile")
            yield

    client = CancellingBuilder()
    loop_harness.context.env = replace(loop_harness.context.env, llm_client=client)  # type: ignore[arg-type]
    producer = {
        "id": "producer-call",
        "name": "build_node",
        "arguments": {
            "mode": "create",
            "id": "start",
            "type": "start",
            "title": "Start",
            "intent": _intent("Accept query", "query"),
        },
    }
    consumer = {
        "id": "consumer-call",
        "name": "build_node",
        "arguments": {
            "mode": "create",
            "id": "consumer",
            "type": "llm",
            "title": "Consumer",
            "intent": _intent(
                "Consume query",
                "text",
                inputs=[{"source": ["start", "query"], "role": "query"}],
            ),
        },
    }
    loop_harness.invoker.queue_tool_calls([producer, consumer])

    events = list(iter_agent_events(**loop_harness.kwargs))

    results = [message.payload for message in loop_harness.session.messages if message.event_type == "tool_result"]
    assert client.targets == ["start"]
    assert [result["error_code"] for result in results] == ["RUN_ABORTED", "RUN_ABORTED"]
    assert events[-1] == ("aborted", {"termination_reason": "user_abort"})
    assert loop_harness.session.candidate_revision == 0
    assert find_node(loop_harness.context.state.graph, "start") is None


def test_retryable_create_batch_failure_drops_later_siblings(loop_harness, monkeypatch: pytest.MonkeyPatch) -> None:

    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    real_compile = create_scheduler.compile_build_node

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

    monkeypatch.setattr(create_scheduler, "compile_build_node", fail_first)
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
    assert find_node(loop_harness.context.state.graph, "n2") is None
    assert loop_harness.context.state.candidate_revision == 0
    assert not any(
        message.event_type == "tool_result" and message.payload.get("tool_call_id") == "c2"
        for message in loop_harness.session.messages
    )


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
    assert events[-1][0] == "done", events[-1]
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
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
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
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
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
    before = upsert_node(before, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
    after = upsert_node(empty_graph(), node_id="start", node_type="start", title="已改", desc="", config={})
    after = upsert_node(after, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
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


def _image_tool_entry() -> dict[str, object]:
    return {
        "provider_name": "image/provider",
        "provider_type": "builtin",
        "plugin_id": "image/provider",
        "tool_name": "generate",
        "tool_label": "图片生成",
        "description": "图片生成 capability",
        "parameters": (
            {"name": "prompt", "type": "string", "form": "llm", "required": True},
            {"name": "image", "type": "file", "form": "llm", "required": False},
            {"name": "size", "type": "select", "form": "form", "required": False, "default": "2K"},
            {"name": "stream", "type": "boolean", "form": "form", "required": False, "default": False},
        ),
        "parameter_names": ("prompt", "image", "size", "stream"),
        "output_names": ("files",),
    }


def _image_tool_intent(*, include_prompt: bool) -> dict[str, object]:
    arguments: dict[str, object] = {
        "image": {"kind": "variable", "selector": ["start", "source_image"]},
    }
    if include_prompt:
        arguments["prompt"] = {"kind": "template", "text": "生成 {{#start.caption#}}"}
    return {
        "objective": "生成图片",
        "tool": {
            "binding": {"provider_name": "image/provider", "tool_name": "generate"},
            "arguments": arguments,
        },
    }


def _image_tool_build_call(
    call_id: str,
    *,
    include_prompt: bool,
    mode: str = "create",
    extra_arguments: dict[str, object] | None = None,
) -> dict[str, object]:
    intent = _image_tool_intent(include_prompt=include_prompt)
    tool = intent["tool"]
    assert isinstance(tool, dict)
    arguments = dict(tool["arguments"]) if isinstance(tool["arguments"], dict) else {}
    if extra_arguments:
        arguments.update(extra_arguments)
    payload: dict[str, object] = {
        "mode": mode,
        "id": "image_1",
        "tool": tool["binding"],
        "arguments": arguments,
    }
    if mode == "create":
        payload["title"] = "图片生成"
    return {"id": call_id, "name": "build_tool_node", "arguments": payload}


class _CountingForbiddenBuilder:
    def __init__(self) -> None:
        self.calls = 0

    def iter_json(self, *, messages, stage):
        self.calls += 1
        raise AssertionError("Tool happy path must not call Node Builder")


def _prepare_image_tool_loop(loop_harness: SimpleNamespace) -> _CountingForbiddenBuilder:
    graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="开始",
        desc="",
        config={
            "variables": [
                {"variable": "source_image", "label": "Source image", "type": "file", "required": True},
                {"variable": "caption", "label": "Caption", "type": "paragraph", "required": True},
            ]
        },
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
    loop_harness.context.state.graph = graph
    loop_harness.session.candidate_graph = graph
    client = _CountingForbiddenBuilder()
    loop_harness.context.env = replace(
        loop_harness.context.env,
        tools_available=True,
        installed_tools={("image/provider", "generate")},
        tool_entries=[_image_tool_entry()],
        llm_client=client,  # type: ignore[arg-type]
    )
    loop_harness.limits.max_model_calls = 12
    return client


def _queue_tool_finish_path(loop_harness: SimpleNamespace) -> None:
    loop_harness.invoker.queue_tool_calls(
        [
            {"id": "edge-1", "name": "connect", "arguments": {"source": "start", "target": "image_1"}},
            {"id": "edge-2", "name": "connect", "arguments": {"source": "image_1", "target": "end"}},
        ]
    )
    loop_harness.invoker.queue_tool_calls([{"id": "validate", "name": "validate_graph", "arguments": {}}])
    loop_harness.invoker.queue_tool_calls(
        [{"id": "finish", "name": "finish", "arguments": {"summary": "图片工作流已完成"}}]
    )


def test_typed_tool_intent_happy_path_finishes_with_terminal_event_and_no_builder_call(loop_harness) -> None:
    client = _prepare_image_tool_loop(loop_harness)
    loop_harness.invoker.queue_tool_calls(
        [{"id": "search", "name": "search_tools", "arguments": {"query": "图片生成"}}]
    )
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "inspect",
                "name": "inspect_tool",
                "arguments": {"provider_name": "image/provider", "tool_name": "generate"},
            }
        ]
    )
    loop_harness.invoker.queue_tool_calls([_image_tool_build_call("build", include_prompt=True)])
    _queue_tool_finish_path(loop_harness)

    events = list(iter_agent_events(**loop_harness.kwargs))

    results = [message.payload for message in loop_harness.session.messages if message.event_type == "tool_result"]
    assert events[-1][0] == "done", (events[-1], results[-2:])
    assert not any(name == "error" and "without a terminal event" in str(payload) for name, payload in events)
    assert client.calls == 0
    node = find_node(loop_harness.context.state.graph, "image_1")
    assert node is not None
    assert node["data"]["tool_parameters"] == {
        "image": {"type": "variable", "value": ["start", "source_image"]},
        "prompt": {"type": "mixed", "value": "生成 {{#start.caption#}}"},
        "size": {"type": "constant", "value": "2K"},
        "stream": {"type": "constant", "value": False},
    }


def test_typed_tool_intent_self_repairs_missing_prompt_with_same_create_id_and_mode(loop_harness) -> None:
    client = _prepare_image_tool_loop(loop_harness)
    for call_id, include_prompt in (("build-bad", False), ("build-fixed", True)):
        loop_harness.invoker.queue_tool_calls([_image_tool_build_call(call_id, include_prompt=include_prompt)])
    _queue_tool_finish_path(loop_harness)

    events = list(iter_agent_events(**loop_harness.kwargs))

    all_results = [message.payload for message in loop_harness.session.messages if message.event_type == "tool_result"]
    assert events[-1][0] == "done", (events[-1], all_results[-2:])
    assert client.calls == 0
    build_results = [
        message.payload
        for message in loop_harness.session.messages
        if message.event_type == "tool_result" and message.payload.get("name") == "build_tool_node"
    ]
    assert [result.get("error_code") for result in build_results] == ["INVALID_NODE_CONFIG", None]
    creates = [
        message.payload["arguments"]
        for message in loop_harness.session.messages
        if message.event_type == "tool_call" and message.payload.get("name") == "build_tool_node"
    ]
    assert [(call["id"], call["mode"]) for call in creates] == [("image_1", "create"), ("image_1", "create")]
    assert sum(node["id"] == "image_1" for node in loop_harness.context.state.graph["nodes"]) == 1


def test_non_tool_empty_prompt_is_repaired_once_and_committed_atomically(loop_harness) -> None:
    loop_harness.context.env = replace(
        loop_harness.context.env,
        llm_client=_QueuedFakeLLM(
            [
                {"prompt_template": [{"role": "user", "text": ""}]},
                {"prompt_template": [{"role": "user", "text": "总结输入。"}]},
            ]
        ),
    )
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "build",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "llm_1",
                    "type": "llm",
                    "title": "摘要",
                    "intent": _intent("总结输入"),
                },
            }
        ]
    )
    loop_harness.invoker.queue_text("已修复")

    list(iter_agent_events(**loop_harness.kwargs))

    build_results = [
        message.payload
        for message in loop_harness.session.messages
        if message.event_type == "tool_result" and message.payload.get("name") == "build_node"
    ]
    assert [result.get("error_code") for result in build_results] == [None]
    assert loop_harness.session.candidate_revision == 1
    assert loop_harness.context.state.candidate_revision == 1
    assert sum(node["id"] == "llm_1" for node in loop_harness.context.state.graph["nodes"]) == 1


def test_typed_tool_update_failure_is_atomic_and_revision_advances_only_after_repair(loop_harness) -> None:
    _prepare_image_tool_loop(loop_harness)
    config = {
        "provider_id": "image/provider",
        "provider_name": "image/provider",
        "provider_type": "builtin",
        "tool_name": "generate",
        "tool_label": "图片生成",
        "tool_node_version": "2",
        "tool_parameters": {
            "prompt": {"type": "constant", "value": "old"},
            "size": {"type": "constant", "value": "2K"},
            "stream": {"type": "constant", "value": False},
        },
        "tool_configurations": {"size": "2K", "stream": False},
    }
    graph = upsert_node(
        loop_harness.context.state.graph,
        node_id="image_1",
        node_type="tool",
        title="图片生成",
        desc="",
        config=config,
    )
    loop_harness.context.state.graph = graph
    loop_harness.session.candidate_graph = graph
    loop_harness.context.state.candidate_revision = 4
    loop_harness.session.candidate_revision = 4
    before_node = deepcopy(find_node(graph, "image_1"))
    loop_harness.invoker.queue_tool_calls(
        [
            _image_tool_build_call(
                "bad-update",
                include_prompt=True,
                mode="update",
                extra_arguments={"image": {"kind": "variable", "selector": ["start", "missing"]}},
            )
        ]
    )
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "fixed-update",
                "name": "build_tool_node",
                "arguments": {
                    "mode": "update",
                    "id": "image_1",
                    "tool": {"provider_name": "image/provider", "tool_name": "generate"},
                    "arguments": {"prompt": {"kind": "constant", "value": "new"}},
                },
            }
        ]
    )
    loop_harness.invoker.queue_text("更新完成")

    list(iter_agent_events(**loop_harness.kwargs))

    results = [
        message.payload
        for message in loop_harness.session.messages
        if message.event_type == "tool_result" and message.payload.get("name") == "build_tool_node"
    ]
    assert [result.get("error_code") for result in results] == ["UNKNOWN_OUTPUT", None]
    assert loop_harness.session.candidate_revision == 5
    assert loop_harness.context.state.candidate_revision == 5
    node = find_node(loop_harness.context.state.graph, "image_1")
    assert node is not None
    assert node != before_node
    assert node["data"]["tool_parameters"]["prompt"] == {"type": "constant", "value": "new"}


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


class _ParseThenFixLLM:
    def __init__(self) -> None:
        self.parse_attempts = 0

    def iter_json(self, *, messages, stage):
        yield from ()
        text = str(messages[-1].content)
        if "id=node_parse" in text:
            self.parse_attempts += 1
            if self.parse_attempts == 1:
                return {"config": {"outputs": {"questions": {"type": "array"}}}}
            return {"config": builder_config(messages, {"outputs": {"questions": {"type": "array[object]"}}})}
        return {"config": builder_config(messages)}


def test_invalid_code_create_retries_then_validates_and_finishes(loop_harness) -> None:
    loop_harness.limits.max_model_calls = 12
    graph = upsert_node(
        empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={"variables": []}
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
    loop_harness.context.state.graph = graph
    loop_harness.session.candidate_graph = graph
    loop_harness.context.env = replace(
        loop_harness.context.env,
        llm_client=_ParseThenFixLLM(),  # type: ignore[arg-type]
        acceptance_runner=_PassRunner(),
    )
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "c-ok",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "llm_ok",
                    "type": "llm",
                    "title": "说明",
                    "intent": _intent("写一段说明"),
                },
            },
            {
                "id": "c-bad",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "node_parse",
                    "type": "code",
                    "title": "解析",
                    "intent": _intent("解析问题"),
                },
            },
            {"id": "e1", "name": "connect", "arguments": {"source": "start", "target": "node_parse"}},
        ]
    )
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "c-fix",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "node_parse",
                    "type": "code",
                    "title": "解析",
                    "intent": _intent("questions must be array[object]"),
                },
            },
            {"id": "e2", "name": "connect", "arguments": {"source": "start", "target": "node_parse"}},
            {"id": "e3", "name": "connect", "arguments": {"source": "node_parse", "target": "end"}},
            {"id": "e4", "name": "connect", "arguments": {"source": "start", "target": "llm_ok"}},
            {"id": "e5", "name": "connect", "arguments": {"source": "llm_ok", "target": "end"}},
        ]
    )
    loop_harness.invoker.queue_tool_calls([{"id": "v", "name": "validate_graph", "arguments": {}}])
    loop_harness.invoker.queue_tool_calls([{"id": "a", "name": "run_acceptance", "arguments": {}}])
    loop_harness.invoker.queue_tool_calls([{"id": "f", "name": "finish", "arguments": {"summary": "已搭好"}}])

    events = list(iter_agent_events(**loop_harness.kwargs))
    names = [name for name, _ in events]
    results = [message.payload for message in loop_harness.session.messages if message.event_type == "tool_result"]
    assert "waiting_user" not in names
    assert names[-1] == "done"
    error_index = next(index for index, item in enumerate(results) if item.get("error_code") == "INVALID_CODE_OUTPUT")
    assert results[error_index]["retryable"] is True
    assert not any(item.get("name") == "connect" for item in results[: error_index + 1])
    assert any(item.get("name") == "connect" and item.get("ok") is True for item in results[error_index + 1 :])
    node = find_node(loop_harness.context.state.graph, "node_parse")
    sibling = find_node(loop_harness.context.state.graph, "llm_ok")
    assert sibling is not None
    assert node is not None
    assert node["data"]["outputs"]["questions"]["type"] == "array[object]"
    assert loop_harness.session.last_validation is not None
    assert loop_harness.session.last_validation["valid"] is True


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


def _activate_call(call_id: str, *names: str) -> dict[str, Any]:
    return {"id": call_id, "name": "activate_skills", "arguments": {"names": list(names)}}


def test_skill_lifecycle_empty_graph_create_validate_finish(loop_harness) -> None:
    loop_harness.limits.max_model_calls = 16
    loop_harness.context.env = replace(
        loop_harness.context.env,
        llm_client=_FakeLLM(),  # type: ignore[arg-type]
        acceptance_runner=_PassRunner(),
    )
    loop_harness.invoker.queue_tool_calls([_activate_call("act", "create-from-scratch")])
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "c-start",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "start",
                    "type": "start",
                    "title": "开始",
                    "intent": _intent("accept query"),
                },
            },
            {
                "id": "c-end",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "end",
                    "type": "end",
                    "title": "结束",
                    "intent": _intent("return result"),
                },
            },
        ]
    )
    loop_harness.invoker.queue_tool_calls(
        [{"id": "e1", "name": "connect", "arguments": {"source": "start", "target": "end"}}]
    )
    loop_harness.invoker.queue_tool_calls([{"id": "v", "name": "validate_graph", "arguments": {}}])
    loop_harness.invoker.queue_tool_calls([{"id": "a", "name": "run_acceptance", "arguments": {}}])
    loop_harness.invoker.queue_tool_calls([{"id": "f", "name": "finish", "arguments": {"summary": "已搭好"}}])
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert events[-1][0] == "done"
    assert loop_harness.dispatch_order[0] == "activate_skills"
    assert find_node(loop_harness.context.state.graph, "start") is not None
    assert find_node(loop_harness.context.state.graph, "end") is not None


def test_skill_lifecycle_bind_resources_passes_exact_dataset_id(loop_harness) -> None:
    client = _RecordingLoopLLM(
        {
            "dataset_ids": ["ds-exact"],
            "query_variable_selector": ["start", "query"],
            "retrieval_mode": "multiple",
        }
    )
    loop_harness.limits.max_model_calls = 16
    loop_harness.session.referenced_datasets = [{"id": "ds-exact", "label": "产品文档"}]
    graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="开始",
        desc="",
        config={"variables": [{"variable": "query", "label": "Query", "type": "paragraph", "required": True}]},
    )
    loop_harness.context.state.graph = graph
    loop_harness.session.candidate_graph = graph
    loop_harness.context.env = replace(
        loop_harness.context.env,
        llm_client=client,  # type: ignore[arg-type]
        knowledge_available=True,
        installed_dataset_ids={"ds-exact"},
        knowledge_entries=[{"id": "ds-exact", "name": "产品文档", "description": ""}],
        acceptance_runner=_PassRunner(),
    )
    loop_harness.invoker.queue_tool_calls([_activate_call("act", "create-from-scratch", "bind-resources")])
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "c-kr",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "kr",
                    "type": "knowledge-retrieval",
                    "title": "检索",
                    "intent": _intent(
                        "retrieve docs with dataset_ids=ds-exact",
                        "result",
                        inputs=[{"source": ["start", "query"], "role": "query"}],
                    ),
                },
            }
        ]
    )
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    assert any("ds-exact" in prompt for prompt in client.user_prompts)


def test_skill_lifecycle_local_edit_reads_then_updates(loop_harness) -> None:
    graph = upsert_node(
        empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={"variables": []}
    )
    graph = upsert_node(graph, node_id="llm1", node_type="llm", title="模型", desc="", config={})
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
    graph = connect(connect(graph, source="start", target="llm1"), source="llm1", target="end")
    loop_harness.context.state.graph = graph
    loop_harness.session.candidate_graph = graph
    loop_harness.session.selected_node = "llm1"
    loop_harness.session.edit_mode = "local"
    loop_harness.context.env = replace(loop_harness.context.env, llm_client=_FakeLLM())  # type: ignore[arg-type]
    loop_harness.invoker.queue_tool_calls([_activate_call("act", "edit-local-node")])
    loop_harness.invoker.queue_tool_calls([{"id": "r", "name": "read_node", "arguments": {"id": "llm1"}}])
    loop_harness.invoker.queue_tool_calls(
        [{"id": "u", "name": "build_node", "arguments": {"mode": "update", "id": "llm1", "intent": _intent("改提示")}}]
    )
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    assert loop_harness.dispatch_order == ["activate_skills", "read_node", "build_node"]
    assert find_node(loop_harness.context.state.graph, "llm1") is not None


def test_skill_lifecycle_invalid_code_activates_repair_and_recreates(loop_harness) -> None:
    graph = upsert_node(
        empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={"variables": []}
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
    loop_harness.context.state.graph = graph
    loop_harness.session.candidate_graph = graph
    loop_harness.limits.max_model_calls = 16
    loop_harness.context.env = replace(
        loop_harness.context.env,
        llm_client=_ParseThenFixLLM(),  # type: ignore[arg-type]
        acceptance_runner=_PassRunner(),
    )
    loop_harness.invoker.queue_tool_calls([_activate_call("act", "create-from-scratch")])
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "c-bad",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "node_parse",
                    "type": "code",
                    "title": "解析",
                    "intent": _intent("解析问题"),
                },
            },
            {"id": "e1", "name": "connect", "arguments": {"source": "start", "target": "node_parse"}},
        ]
    )
    loop_harness.invoker.queue_tool_calls([_activate_call("fix", "repair-validation")])
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "c-fix",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "node_parse",
                    "type": "code",
                    "title": "解析",
                    "intent": _intent("questions must be array[object]"),
                },
            },
            {"id": "e2", "name": "connect", "arguments": {"source": "start", "target": "node_parse"}},
            {"id": "e3", "name": "connect", "arguments": {"source": "node_parse", "target": "end"}},
        ]
    )
    loop_harness.invoker.queue_tool_calls([{"id": "v", "name": "validate_graph", "arguments": {}}])
    loop_harness.invoker.queue_tool_calls([{"id": "a", "name": "run_acceptance", "arguments": {}}])
    loop_harness.invoker.queue_tool_calls([{"id": "f", "name": "finish", "arguments": {"summary": "已修好"}}])
    events = list(iter_agent_events(**loop_harness.kwargs))
    names = [name for name, _ in events]
    results = [message.payload for message in loop_harness.session.messages if message.event_type == "tool_result"]
    assert "waiting_user" not in names
    assert names[-1] == "done"
    assert any(item.get("error_code") == "INVALID_CODE_OUTPUT" for item in results)
    recreates = [
        message.payload
        for message in loop_harness.session.messages
        if message.event_type == "tool_call"
        and message.payload.get("name") == "build_node"
        and message.payload.get("arguments", {}).get("id") == "node_parse"
    ]
    assert [item["arguments"]["mode"] for item in recreates] == ["create", "create"]
    node = find_node(loop_harness.context.state.graph, "node_parse")
    assert node is not None
    assert node["data"]["outputs"]["questions"]["type"] == "array[object]"


def test_skill_lifecycle_repair_can_combine_with_bind_resources(loop_harness) -> None:
    captured = _capture_prompt_contents(loop_harness)
    loop_harness.session.referenced_datasets = [{"id": "ds-exact", "label": "产品文档"}]
    loop_harness.session.last_validation = {
        "valid": False,
        "validated_revision": 1,
        "errors": [{"code": "UNKNOWN_DATASET", "node_id": "kr", "detail": "bad ds"}],
    }
    loop_harness.invoker.queue_tool_calls([_activate_call("act", "repair-validation", "bind-resources")])
    loop_harness.invoker.queue_text("先这样")
    list(iter_agent_events(**loop_harness.kwargs))
    tail = captured[1][-1]
    assert "## repair-validation" in tail
    assert "## bind-resources" in tail
    assert tail.index("## repair-validation") < tail.index("## bind-resources")


def test_skill_lifecycle_invalid_agent_is_rejected_without_repair_skill(loop_harness) -> None:
    loop_harness.context.env = replace(
        loop_harness.context.env,
        llm_client=_FakeLLM(),  # type: ignore[arg-type]
    )
    loop_harness.invoker.queue_tool_calls([_activate_call("act", "create-from-scratch")])
    loop_harness.invoker.queue_tool_calls(
        [
            {
                "id": "c-agent",
                "name": "build_node",
                "arguments": {
                    "mode": "create",
                    "id": "agent_1",
                    "type": "agent",
                    "title": "助手",
                    "intent": _intent("调查问题"),
                },
            }
        ]
    )
    loop_harness.invoker.queue_text("先这样")
    events = list(iter_agent_events(**loop_harness.kwargs))
    results = [message.payload for message in loop_harness.session.messages if message.event_type == "tool_result"]
    create_result = next(item for item in results if item.get("name") == "build_node")
    assert create_result["ok"] is False
    assert create_result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert find_node(loop_harness.context.state.graph, "agent_1") is None
    assert "waiting_user" not in {name for name, _ in events}


def test_skill_lifecycle_agent_v2_finish_hydrates_binding_ids(loop_harness) -> None:
    from copy import deepcopy

    graph = upsert_node(
        empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={"variables": []}
    )
    graph = upsert_node(
        graph,
        node_id="agent_1",
        node_type="agent",
        title="助手",
        desc="",
        config={
            "version": "2",
            "agent_node_kind": "dify_agent",
            "agent_task": "调查问题",
            "agent_binding": {"binding_type": "inline_agent"},
            "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
        },
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
    graph = connect(connect(graph, source="start", target="agent_1"), source="agent_1", target="end")
    loop_harness.context.state.graph = graph
    loop_harness.session.candidate_graph = graph
    loop_harness.limits.max_model_calls = 16

    def hydrate(graph_in):
        updated = deepcopy(graph_in)
        for node in updated["nodes"]:
            data = node.get("data") if isinstance(node, dict) else None
            if not isinstance(data, dict) or data.get("type") != "agent":
                continue
            binding = dict(data.get("agent_binding") or {})
            binding["agent_id"] = "agent-live"
            binding["current_snapshot_id"] = "snap-live"
            data["agent_binding"] = binding
        return updated

    loop_harness.context.env = replace(
        loop_harness.context.env,
        hydrate_graph=hydrate,
    )
    loop_harness.invoker.queue_tool_calls([_activate_call("act", "create-from-scratch")])
    loop_harness.invoker.queue_tool_calls([{"id": "v", "name": "validate_graph", "arguments": {}}])
    loop_harness.invoker.queue_tool_calls([{"id": "f", "name": "finish", "arguments": {"summary": "已 hydrate"}}])
    events = list(iter_agent_events(**loop_harness.kwargs))
    assert events[-1][0] == "done"
    node = find_node(loop_harness.context.state.graph, "agent_1")
    assert node is not None
    assert node["data"]["agent_binding"]["agent_id"] == "agent-live"
    assert node["data"]["agent_binding"]["current_snapshot_id"] == "snap-live"
    assert "fake-agent" not in str(node["data"])
