"""Native streaming assembler: text deltas immediately, tool JSON only when complete."""

from types import SimpleNamespace

import pytest

from core.workflow.generator.agent.protocol.stream import StreamTurnAssembler, assemble_stream_turn


@pytest.mark.parametrize("chunk_size", [1, 7, 1000])
def test_leaked_protocol_never_reaches_public_stream(chunk_size: int) -> None:
    text = (
        '我来修改。\n{"id":"call_00","name":"build_node","arguments":{"id":"node_start"}'
        "</｜｜DSML｜｜parameter></｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>"
    )
    events, turn = assemble_stream_turn(
        [_chunk(text=text[i : i + chunk_size]) for i in range(0, len(text), chunk_size)]
    )
    public = "".join(event[1]["delta"] for event in events if event[0] == "text")
    assert public == turn["text"] == "我来修改。\n"
    assert turn["tool_calls"] == []
    assert turn["protocol_error"] is True


def test_code_examples_and_regular_json_remain_literal() -> None:
    text = '示例：`{"name":"build_node","arguments":{}}`\n```xml\n<｜DSML｜tool_calls>\n```\n{"value":42}'
    events, turn = assemble_stream_turn([_chunk(text=char) for char in text])
    assert turn["text"] == text
    assert "".join(event[1]["delta"] for event in events if event[0] == "text") == text
    assert turn["tool_calls"] == []
    assert not turn.get("protocol_error")


def _chunk(
    *, text: str = "", tool_calls: list[dict] | None = None, reasoning_content: str | None = None
) -> SimpleNamespace:
    calls = []
    for item in tool_calls or []:
        function = SimpleNamespace(name=item.get("name") or "", arguments=item.get("arguments") or "")
        calls.append(SimpleNamespace(id=item.get("id") or "", index=item.get("index"), function=function))
    message = SimpleNamespace(content=text, tool_calls=calls, reasoning_content=reasoning_content)
    return SimpleNamespace(delta=SimpleNamespace(message=message, finish_reason=None))


def test_text_chunks_emit_deltas_before_turn_finishes() -> None:
    assembler = StreamTurnAssembler(message_id="msg-1")
    first = assembler.push(_chunk(text="正在"))
    second = assembler.push(_chunk(text="创建"))
    turn = assembler.finish()
    assert first == [("text", {"delta": "正在", "message_id": "msg-1", "delta_index": 0})]
    assert second == [("text", {"delta": "创建", "message_id": "msg-1", "delta_index": 1})]
    assert turn["text"] == "正在创建"
    assert turn["tool_calls"] == []
    assert turn["stream_mode"] == "native"


def test_fragmented_tool_arguments_do_not_dispatch_until_json_is_complete() -> None:
    assembler = StreamTurnAssembler(message_id="msg-1")
    assert assembler.push(_chunk(tool_calls=[{"index": 0, "id": "c1", "name": "read_graph", "arguments": ""}])) == []
    assert assembler.push(_chunk(tool_calls=[{"index": 0, "arguments": "{"}])) == []
    assert assembler.push(_chunk(tool_calls=[{"index": 0, "arguments": "}"}])) == []
    turn = assembler.finish()
    assert turn["tool_calls"] == [{"id": "c1", "name": "read_graph", "arguments": {}}]


def test_incomplete_tool_json_is_dropped_not_dispatched() -> None:
    assembler = StreamTurnAssembler(message_id="msg-1")
    assembler.push(_chunk(tool_calls=[{"index": 0, "id": "c1", "name": "read_graph", "arguments": '{"id":'}]))
    turn = assembler.finish()
    assert turn["tool_calls"] == []
    assert turn["protocol_error"] is True


def test_native_call_is_preserved_without_executing_text_duplicate() -> None:
    events, turn = assemble_stream_turn(
        [
            _chunk(text='准备读取。{"name":"read_graph","arguments":{}}'),
            _chunk(tool_calls=[{"index": 0, "id": "native", "name": "read_graph", "arguments": "{}"}]),
        ]
    )
    assert turn["tool_calls"] == [{"id": "native", "name": "read_graph", "arguments": {}}]
    assert turn["protocol_error"] is True
    assert "".join(payload["delta"] for kind, payload in events if kind == "text") == "准备读取。"


def test_invalid_native_call_rejects_entire_batch_before_dispatch() -> None:
    _, turn = assemble_stream_turn(
        [
            _chunk(
                tool_calls=[
                    {"index": 0, "id": "good", "name": "read_graph", "arguments": "{}"},
                    {"index": 1, "id": "bad", "name": "build_node", "arguments": '{"id":'},
                ]
            ),
        ]
    )
    assert turn["tool_calls"] == []
    assert turn["protocol_error"] is True


def test_think_blocks_are_not_emitted_as_public_deltas() -> None:
    assembler = StreamTurnAssembler(message_id="msg-1")
    hidden = assembler.push(_chunk(text="<think>内部推理</think>"))
    mixed = assembler.push(_chunk(text="<think>跳过</think>正在创建"))
    turn = assembler.finish()
    assert hidden == [("reasoning", {"delta": "内部推理", "message_id": "msg-1", "delta_index": 0})]
    assert mixed == [
        ("reasoning", {"delta": "跳过", "message_id": "msg-1", "delta_index": 1}),
        ("text", {"delta": "正在创建", "message_id": "msg-1", "delta_index": 0}),
    ]
    assert turn["text"] == "正在创建"
    assert turn["reasoning"] == "内部推理跳过"


def test_unclosed_think_swallows_until_close_tag() -> None:
    assembler = StreamTurnAssembler(message_id="msg-1")
    unclosed = assembler.push(_chunk(text="<think>还没说完"))
    closed = assembler.push(_chunk(text="<think>跳过</think>正在创建"))
    turn = assembler.finish()
    assert unclosed == [("reasoning", {"delta": "还没说完", "message_id": "msg-1", "delta_index": 0})]
    assert closed[0][0] == "reasoning"
    assert "正在创建" not in closed[0][1]["delta"]
    assert ("text", {"delta": "正在创建", "message_id": "msg-1", "delta_index": 0}) in closed
    assert turn["text"] == "正在创建"
    assert "正在创建" not in turn["reasoning"]


def test_think_body_split_across_chunks_is_not_public() -> None:
    assembler = StreamTurnAssembler(message_id="msg-1")
    assert assembler.push(_chunk(text="<think>")) == []
    first = assembler.push(_chunk(text="我先分析一下"))
    second = assembler.push(_chunk(text="这个问题..."))
    assert assembler.push(_chunk(text="</think>")) == []
    visible = assembler.push(_chunk(text="最终答案"))
    turn = assembler.finish()
    assert first == [("reasoning", {"delta": "我先分析一下", "message_id": "msg-1", "delta_index": 0})]
    assert second == [("reasoning", {"delta": "这个问题...", "message_id": "msg-1", "delta_index": 1})]
    assert visible == [("text", {"delta": "最终答案", "message_id": "msg-1", "delta_index": 0})]
    assert turn["text"] == "最终答案"
    assert turn["reasoning"] == "我先分析一下这个问题..."


def test_think_tags_split_across_chunks_hold_ambiguous_suffix() -> None:
    assembler = StreamTurnAssembler(message_id="msg-1")
    first = assembler.push(_chunk(text="hello <thi"))
    second = assembler.push(_chunk(text="nk>secret"))
    third = assembler.push(_chunk(text="</think> world"))
    turn = assembler.finish()
    assert first == [("text", {"delta": "hello ", "message_id": "msg-1", "delta_index": 0})]
    assert second == [("reasoning", {"delta": "secret", "message_id": "msg-1", "delta_index": 0})]
    assert third == [("text", {"delta": " world", "message_id": "msg-1", "delta_index": 1})]
    assert turn["text"] == "hello  world"
    assert turn["reasoning"] == "secret"


def test_provider_reasoning_content_is_captured_without_duplicating_think() -> None:
    assembler = StreamTurnAssembler(message_id="msg-1")
    events = assembler.push(_chunk(text="<think>计划</think>可见", reasoning_content="计划"))
    turn = assembler.finish()
    kinds = [kind for kind, _ in events]
    assert kinds.count("reasoning") == 1
    assert ("reasoning", {"delta": "计划", "message_id": "msg-1", "delta_index": 0}) in events
    assert ("text", {"delta": "可见", "message_id": "msg-1", "delta_index": 0}) in events
    assert turn["reasoning"] == "计划"
    assert turn["text"] == "可见"


def test_provider_reasoning_content_without_think_tags() -> None:
    assembler = StreamTurnAssembler(message_id="msg-1")
    events = assembler.push(_chunk(text="可见", reasoning_content="内部"))
    turn = assembler.finish()
    assert events[0] == ("reasoning", {"delta": "内部", "message_id": "msg-1", "delta_index": 0})
    assert events[1] == ("text", {"delta": "可见", "message_id": "msg-1", "delta_index": 0})
    assert turn["reasoning"] == "内部"


def test_reasoning_is_capped_at_32kib() -> None:
    assembler = StreamTurnAssembler(message_id="msg-1")
    body = "测" * 20_000
    assembler.push(_chunk(text=f"<think>{body}</think>"))
    turn = assembler.finish()
    encoded = turn["reasoning"].encode("utf-8")
    assert len(encoded) <= 32 * 1024
    assert turn["reasoning"].endswith("…[truncated]")


def test_blocking_result_is_fallback_stream_mode() -> None:
    result = SimpleNamespace(
        message=SimpleNamespace(
            content="一次性说明",
            tool_calls=[],
            get_text_content=lambda: "一次性说明",
        )
    )
    events, turn = assemble_stream_turn([], blocking_result=result)
    assert events == [("text", {"delta": "一次性说明", "message_id": turn["message_id"], "delta_index": 0})]
    assert turn["stream_mode"] == "fallback"
    assert turn["text"] == "一次性说明"
