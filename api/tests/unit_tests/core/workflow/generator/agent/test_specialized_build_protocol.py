"""Main-agent protocol for specialized build tools and container repair rounds."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import core.workflow.generator as generator_pkg
from core.workflow.generator.agent.loop import iter_agent_events
from core.workflow.generator.agent.state import reducer as state_reducer
from core.workflow.generator.agent.tools.tools import ToolContext
from core.workflow.generator.agent.tools.tools import dispatch as real_dispatch
from core.workflow.generator.agent.types import AgentMessage, AgentSession
from core.workflow.generator.graph.graph_ops import find_node
from core.workflow.generator.model_io.llm_response import StageJSONError
from core.workflow.generator.prompts.loader import always_on_system_prompt, read_prompt, skill_body
from tests.unit_tests.core.workflow.generator.agent.test_build_loop import (
    _assigner_child,
    _enable_tools,
    _fetch_child,
    _min_loop_args,
    _outer_graph,
)
from tests.unit_tests.core.workflow.generator.agent.test_loop import FakeCancellation, FakeInvoker, FakeLimits
from tests.unit_tests.core.workflow.generator.node_fixtures import builder_config

_GENERATOR_ROOT = Path(generator_pkg.__file__).resolve().parent
_OLD_BUILD_NODE_TYPE = re.compile(r"build_node.*type.*(tool|agent|loop|iteration)")


def _protocol_corpus() -> str:
    return "\n".join(
        (
            always_on_system_prompt(),
            skill_body("create-from-scratch") or "",
            skill_body("edit-local-node") or "",
            skill_body("repair-validation") or "",
            skill_body("bind-resources") or "",
            skill_body("build-container") or "",
            skill_body("verify-and-finish") or "",
            read_prompt("nodes.md"),
            (_GENERATOR_ROOT / "AGENT.md").read_text(encoding="utf-8"),
        )
    )


def test_system_prompt_routes_ordinary_and_specialized_build_tools() -> None:
    text = always_on_system_prompt()

    assert "build_node" in text
    assert "build_tool_node" in text
    assert "build_agent_node" in text
    assert "build_loop" in text
    assert "build_iteration" in text
    assert "use `build_tool_node`" in text
    assert "use `build_agent_node`" in text
    assert "`build_loop`" in text
    assert "`build_iteration`" in text
    assert "ordinary" in text.lower() or "non-container" in text.lower()


def test_system_prompt_uses_specialized_agent_contract() -> None:
    text = always_on_system_prompt()

    assert "intent.tool_bindings" not in text
    assert "intent.agent_knowledge" not in text
    assert "tools/mcp_tools/knowledge" in text
    assert "build_agent_node" in text


def test_bind_resources_skill_uses_top_level_knowledge() -> None:
    body = skill_body("bind-resources") or ""

    assert "intent.agent_knowledge" not in body
    assert 'knowledge={"operation":"replace"' in body


def test_referenced_resources_use_specialized_build_tools() -> None:
    system = always_on_system_prompt()
    bind = skill_body("bind-resources") or ""
    referenced = system.split("# 4. Construction contract", 1)[1].split("# 5.", 1)[0]
    corpus = _protocol_corpus()

    assert "referenced_nodes" in referenced
    assert "referenced_tools" in referenced
    assert "referenced_datasets" in referenced
    assert "`build_node`" in referenced
    assert "`build_tool_node`" in referenced
    assert "`build_agent_node`" in referenced
    assert "build_node must use those exact ids" not in system
    assert "build_tool_node" in bind
    assert "build_agent_node" in bind
    assert "copy the inspected key into `intent.tool.binding`" not in corpus
    assert "Do not put `intent.tool.binding` on `build_node`" in bind


def test_old_build_node_type_routing_is_gone_from_protocol_docs() -> None:
    corpus = _protocol_corpus()

    assert _OLD_BUILD_NODE_TYPE.search(corpus) is None
    assert "build_node(type=tool" not in corpus
    assert "build_node(type=agent" not in corpus
    assert "build_node(type=loop" not in corpus
    assert "build_node(type=iteration" not in corpus


def test_protocol_requires_search_inspect_refs_and_full_container_resubmit() -> None:
    system = always_on_system_prompt()
    create = skill_body("create-from-scratch") or ""
    repair = skill_body("repair-validation") or ""
    edit = skill_body("edit-local-node") or ""
    combined = "\n".join((system, create, repair, edit))

    assert "inspect_tool" in combined
    assert "search_tools" in combined
    assert "ref" in combined
    assert "Dify envelope" in combined or "Dify envelopes" in combined
    assert "resubmit" in combined.lower() or "重交" in combined or "full container" in combined.lower()
    kids = combined.lower()
    assert "successful child" in kids or "successful children" in kids or "成功 child" in combined


def _loop_harness(tool_context: ToolContext, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:

    session = AgentSession(
        messages=[
            AgentMessage(
                sequence=1,
                event_type="message",
                role="user",
                status="completed",
                payload={"text": "做一个带循环的摘要工作流"},
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
    dispatch_order: list[str] = []

    def tracking_dispatch(call: dict[str, Any], context: ToolContext) -> Any:
        dispatch_order.append(call["name"])
        return real_dispatch(call, context)

    monkeypatch.setattr(state_reducer, "dispatch", tracking_dispatch)
    harness = SimpleNamespace(
        session=session,
        context=tool_context,
        invoker=invoker,
        cancellation=FakeCancellation(),
        limits=FakeLimits(),
        dispatch_order=dispatch_order,
    )
    harness.kwargs = {
        "session": session,
        "context": tool_context,
        "invoker": invoker,
        "cancellation": harness.cancellation,
        "limits": harness.limits,
    }
    return harness


def _tool_results(session: AgentSession) -> list[dict[str, Any]]:
    return [message.payload for message in session.messages if message.event_type == "tool_result"]


def _prompt_blob(messages: object) -> str:
    parts: list[str] = []
    for message in messages or []:
        parts.append(str(getattr(message, "content", "") or ""))
    return "\n".join(parts)


def test_unknown_tool_output_wakes_main_agent_with_available_outputs(
    tool_context: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_tools(tool_context)
    graph = _outer_graph()
    tool_context.state.graph = graph
    harness = _loop_harness(tool_context, monkeypatch)
    harness.session.candidate_graph = graph
    seen_prompts: list[str] = []
    inner = harness.invoker.invoke

    def capture(messages: object = None, **kwargs: object) -> dict[str, Any]:
        seen_prompts.append(_prompt_blob(messages))
        return inner(messages, **kwargs)

    harness.invoker.invoke = capture
    bad = _min_loop_args(children=[_fetch_child(), _assigner_child(source=["fetch", "missing"])])
    good = _min_loop_args()
    harness.invoker.queue_tool_calls([{"id": "loop-bad", "name": "build_loop", "arguments": bad}])
    harness.invoker.queue_tool_calls([{"id": "loop-good", "name": "build_loop", "arguments": good}])
    harness.invoker.queue_tool_calls([{"id": "validate", "name": "validate_graph", "arguments": {}}])
    harness.invoker.queue_text("循环已修好。")

    events = list(iter_agent_events(**harness.kwargs))

    results = _tool_results(harness.session)
    loop_results = [item for item in results if item.get("name") == "build_loop"]
    assert len(loop_results) == 2
    assert loop_results[0]["ok"] is False
    assert loop_results[0]["error_code"] in {"UNKNOWN_OUTPUT", "UNKNOWN_TOOL_OUTPUT"}
    observation = loop_results[0].get("cause") or loop_results[0]
    assert "text" in (observation.get("available_outputs") or [])
    assert "available_outputs" in seen_prompts[1]
    assert "text" in seen_prompts[1]
    assert loop_results[1]["ok"] is True
    validate = next(item for item in results if item.get("name") == "validate_graph")
    assert validate["ok"] is True
    content = validate.get("content") or {}
    assert content.get("valid") is True
    assert find_node(tool_context.state.graph, "loop1_fetch") is not None
    assert events[-1][0] == "turn_complete"
    assert harness.dispatch_order == ["build_loop", "build_loop", "validate_graph"]


def test_tool_child_selector_miss_wakes_main_agent_with_available_outputs(
    tool_context: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_tools(tool_context)
    graph = _outer_graph()
    tool_context.state.graph = graph
    harness = _loop_harness(tool_context, monkeypatch)
    harness.session.candidate_graph = graph
    seen_prompts: list[str] = []
    inner = harness.invoker.invoke

    def capture(messages: object = None, **kwargs: object) -> dict[str, Any]:
        seen_prompts.append(_prompt_blob(messages))
        return inner(messages, **kwargs)

    harness.invoker.invoke = capture
    bad_fetch = {
        "kind": "tool",
        "ref": "fetch",
        "intent": {
            "binding": {"provider_name": "text/provider", "tool_name": "summarize"},
            "arguments": {"prompt": {"kind": "variable", "selector": ["start", "missing"]}},
        },
    }
    bad = _min_loop_args(children=[bad_fetch, _assigner_child()])
    good = _min_loop_args()
    harness.invoker.queue_tool_calls([{"id": "loop-bad", "name": "build_loop", "arguments": bad}])
    harness.invoker.queue_tool_calls([{"id": "loop-good", "name": "build_loop", "arguments": good}])
    harness.invoker.queue_tool_calls([{"id": "validate", "name": "validate_graph", "arguments": {}}])
    harness.invoker.queue_text("工具子节点已修好。")

    events = list(iter_agent_events(**harness.kwargs))

    results = _tool_results(harness.session)
    loop_results = [item for item in results if item.get("name") == "build_loop"]
    assert len(loop_results) == 2
    assert loop_results[0]["ok"] is False
    assert loop_results[0]["error_code"] in {"UNKNOWN_OUTPUT", "UNKNOWN_TOOL_OUTPUT"}
    observation = loop_results[0].get("cause") or loop_results[0]
    assert "query" in (observation.get("available_outputs") or [])
    assert "available_outputs" in seen_prompts[1]
    assert "query" in seen_prompts[1]
    assert loop_results[1]["ok"] is True
    validate = next(item for item in results if item.get("name") == "validate_graph")
    assert validate["ok"] is True
    assert events[-1][0] == "turn_complete"


class _FlakyThenValidBuilder:
    def __init__(self) -> None:
        self.calls = 0

    def iter_json(self, *, messages: object, stage: str) -> Iterator[object]:
        self.calls += 1
        if self.calls == 1:
            raise StageJSONError(stage, "unparseable builder JSON")
        yield from ()
        return {
            "config": builder_config(
                messages,
                {"prompt_template": [{"role": "user", "text": "总结 {{#fetch.text#}}"}]},
            )
        }


def test_mechanical_builder_retry_stays_inside_container(
    tool_context: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_tools(tool_context)
    graph = _outer_graph()
    tool_context.state.graph = graph
    builder = _FlakyThenValidBuilder()
    from dataclasses import replace

    tool_context.env = replace(tool_context.env, llm_client=builder)  # type: ignore[arg-type]
    harness = _loop_harness(tool_context, monkeypatch)
    harness.session.candidate_graph = graph
    args = _min_loop_args(
        children=[
            _fetch_child(),
            {
                "kind": "standard",
                "ref": "note",
                "node_type": "llm",
                "intent": {
                    "objective": "Summarize the fetched text",
                    "inputs": [{"source": ["fetch", "text"], "role": "query"}],
                    "outputs": [{"name": "text"}],
                },
            },
            _assigner_child(source=["note", "text"]),
        ],
        edges=[{"source": "fetch", "target": "note"}, {"source": "note", "target": "write"}],
    )
    harness.invoker.queue_tool_calls([{"id": "loop-1", "name": "build_loop", "arguments": args}])
    harness.invoker.queue_text("循环已编译。")

    list(iter_agent_events(**harness.kwargs))

    loop_calls = [
        message
        for message in harness.session.messages
        if message.event_type == "tool_call" and message.payload.get("name") == "build_loop"
    ]
    loop_results = [item for item in _tool_results(harness.session) if item.get("name") == "build_loop"]
    assert len(loop_calls) == 1
    assert len(loop_results) == 1
    assert loop_results[0]["ok"] is True
    assert builder.calls == 2
    assert harness.invoker.invoke_count == 2
    assert harness.dispatch_order == ["build_loop"]
