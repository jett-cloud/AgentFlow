"""Layered container compile: concurrency, mechanical retry, and in-run cache."""

from __future__ import annotations

import threading
from copy import deepcopy
from typing import Any, cast

import pytest

from core.workflow.generator.agent.tools.tool_context import ToolTurnState
from core.workflow.generator.compiler.container_compiler import compile_container_subgraph, compile_topological_layers
from core.workflow.generator.compiler.container_types import (
    CompiledChild,
    ContainerCompileCacheKey,
    ContainerCompileError,
    ContainerCompileRequest,
)
from core.workflow.generator.compiler.intents.container_intent import (
    StandardContainerChildIntent,
    parse_loop_build_intent,
)
from core.workflow.generator.graph.graph_ops import empty_graph, find_node, upsert_node
from core.workflow.generator.graph.types import MinimalGraphDict


def _standard_child(ref: str, *, objective: str | None = None) -> StandardContainerChildIntent:
    return StandardContainerChildIntent.model_validate(
        {
            "kind": "standard",
            "ref": ref,
            "node_type": "llm",
            "intent": {
                "objective": objective or f"compile {ref}",
                "inputs": [],
                "outputs": [{"name": "text"}],
            },
        }
    )


def _dummy_compiled(ref: str) -> CompiledChild:
    return CompiledChild(
        ref=ref,
        node={
            "id": f"loop1_{ref}",
            "parentId": "loop1",
            "data": {
                "type": "assigner",
                "title": ref,
                "assist_ref": ref,
                "isInLoop": True,
                "version": "2",
                "items": [
                    {
                        "variable_selector": ["loop1", "acc"],
                        "input_type": "constant",
                        "operation": "over-write",
                        "value": ref,
                    }
                ],
            },
        },
    )


def test_same_layer_children_enter_compile_together() -> None:
    barrier = threading.Barrier(2, timeout=5)
    entered: dict[str, threading.Event] = {"a": threading.Event(), "b": threading.Event(), "c": threading.Event()}
    started_c_while_ab_held = threading.Event()
    ab_released = threading.Event()

    def compile_child(child: StandardContainerChildIntent) -> CompiledChild:
        entered[child.ref].set()
        if child.ref in {"a", "b"}:
            barrier.wait()
            if entered["c"].is_set():
                started_c_while_ab_held.set()
            ab_released.wait(timeout=5)
            return _dummy_compiled(child.ref)
        assert entered["a"].wait(timeout=5)
        assert entered["b"].wait(timeout=5)
        return _dummy_compiled(child.ref)

    layers = (
        (_standard_child("a"), _standard_child("b")),
        (_standard_child("c"),),
    )

    def run() -> None:
        compiled = compile_topological_layers(layers, compile_child=compile_child, max_workers=4)
        assert [item.ref for item in compiled] == ["a", "b", "c"]

    worker = threading.Thread(target=run)
    worker.start()
    assert entered["a"].wait(timeout=5)
    assert entered["b"].wait(timeout=5)
    assert not entered["c"].is_set()
    ab_released.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert entered["c"].is_set()
    assert not started_c_while_ab_held.is_set()


def _loop_request(
    children: list[dict[str, object]],
    *,
    edges: list[dict[str, object]] | None = None,
    compile_cache: dict[ContainerCompileCacheKey, CompiledChild] | None = None,
    resource_snapshot_hash: str = "resources-v1",
    frozen_graph: MinimalGraphDict | None = None,
) -> ContainerCompileRequest:
    intent = parse_loop_build_intent(
        {
            "loop_count": 3,
            "loop_variables": [{"label": "acc", "var_type": "string", "value_type": "constant", "value": ""}],
            "children": children,
            "edges": edges or [],
            "break_conditions": [
                {"id": "c1", "variable_selector": ["acc"], "comparison_operator": "is", "value": "done"}
            ],
            "outputs": [{"name": "acc", "type": "string"}],
        }
    )
    return ContainerCompileRequest(
        kind="loop",
        container_id="loop1",
        intent=intent,
        frozen_graph=frozen_graph or empty_graph(),
        base_revision=0,
        existing_child_ids={},
        tool_entries=(),
        knowledge_entries=(),
        installed_tools=None,
        generation_mode="workflow",
        title="loop",
        compile_cache=compile_cache,
        resource_snapshot_hash=resource_snapshot_hash,
    )


def _assigner_payload(ref: str, *, role: str = "acc") -> dict[str, object]:
    return {
        "kind": "standard",
        "ref": ref,
        "node_type": "assigner",
        "intent": {
            "objective": f"write {ref}",
            "inputs": [{"source": ["start", "query"], "role": role}],
        },
    }


def test_builder_protocol_error_retries_only_that_child(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[str] = []

    def fake_compile(child: Any, context: Any) -> CompiledChild:
        attempts.append(child.ref)
        if child.ref == "writer" and attempts.count("writer") == 1:
            raise ContainerCompileError(
                "INVALID_JSON",
                "Builder returned unparseable JSON",
                path="children.writer",
                child_ref="writer",
                mechanical_retry=True,
            )
        return _dummy_compiled(child.ref)

    monkeypatch.setattr("core.workflow.generator.compiler.container_children.compile_container_child", fake_compile)
    monkeypatch.setattr(
        "core.workflow.generator.compiler.container_compiler.validate_compiled_container", lambda *_args: None
    )
    request = _loop_request(
        [
            _assigner_payload("keep"),
            _assigner_payload("writer"),
        ]
    )
    frozen = deepcopy(request.frozen_graph)

    compile_container_subgraph(request)

    assert attempts.count("keep") == 1
    assert attempts.count("writer") == 2
    assert request.frozen_graph == frozen


@pytest.mark.parametrize(
    "code",
    ["UNKNOWN_TOOL_OUTPUT", "VARIABLE_TYPE_MISMATCH", "PRIVATE_CONTAINER_REFERENCE"],
)
def test_semantic_errors_are_not_retried(monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    attempts: list[str] = []

    def fake_compile(child: Any, context: Any) -> CompiledChild:
        attempts.append(child.ref)
        if child.ref == "bad":
            raise ContainerCompileError(code, f"{code} boom", path="children.bad", child_ref="bad")
        return _dummy_compiled(child.ref)

    monkeypatch.setattr("core.workflow.generator.compiler.container_children.compile_container_child", fake_compile)
    request = _loop_request([_assigner_payload("ok"), _assigner_payload("bad")])

    with pytest.raises(ContainerCompileError) as excinfo:
        compile_container_subgraph(request)

    assert excinfo.value.code == code
    assert excinfo.value.mechanical_retry is False
    assert attempts.count("bad") == 1


def test_cross_call_cache_reuses_unchanged_children(monkeypatch: pytest.MonkeyPatch) -> None:
    compile_calls: list[str] = []
    validate_calls = 0

    def counting_compile(child: Any, context: Any) -> CompiledChild:
        compile_calls.append(child.ref)
        if child.ref == "c" and compile_calls.count("c") == 1:
            raise ContainerCompileError(
                "UNKNOWN_TOOL_OUTPUT",
                "missing tool output",
                path="children.c",
                child_ref="c",
            )
        return _dummy_compiled(child.ref)

    def counting_validate(graph: Any, request: Any, ref_map: Any) -> None:
        nonlocal validate_calls
        validate_calls += 1

    monkeypatch.setattr("core.workflow.generator.compiler.container_children.compile_container_child", counting_compile)
    monkeypatch.setattr(
        "core.workflow.generator.compiler.container_compiler.validate_compiled_container", counting_validate
    )

    cache: dict[ContainerCompileCacheKey, CompiledChild] = {}
    first_children = [_assigner_payload("a"), _assigner_payload("b"), _assigner_payload("c")]
    first = _loop_request(first_children, compile_cache=cache)
    with pytest.raises(ContainerCompileError) as first_exc:
        compile_container_subgraph(first)
    assert first_exc.value.code == "UNKNOWN_TOOL_OUTPUT"
    assert compile_calls == ["a", "b", "c"]

    second_children = [
        _assigner_payload("a"),
        _assigner_payload("b"),
        _assigner_payload("c", role="other"),
    ]
    second = _loop_request(second_children, compile_cache=cache)
    compile_container_subgraph(second)

    assert compile_calls == ["a", "b", "c", "c"]
    assert validate_calls == 1


def test_cache_misses_when_resource_or_upstream_signature_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    compile_calls: list[str] = []

    def counting_compile(child: Any, context: Any) -> CompiledChild:
        compile_calls.append(child.ref)
        return _dummy_compiled(child.ref)

    monkeypatch.setattr("core.workflow.generator.compiler.container_children.compile_container_child", counting_compile)
    monkeypatch.setattr(
        "core.workflow.generator.compiler.container_compiler.validate_compiled_container", lambda *_args: None
    )

    cache: dict[ContainerCompileCacheKey, CompiledChild] = {}
    children = [
        _assigner_payload("a"),
        {
            "kind": "standard",
            "ref": "b",
            "node_type": "assigner",
            "intent": {
                "objective": "join a",
                "inputs": [{"source": ["a", "text"], "role": "acc"}],
            },
        },
    ]
    edges = [{"source": "a", "target": "b"}]
    first = _loop_request(children, edges=edges, compile_cache=cache)
    compile_container_subgraph(first)
    assert compile_calls == ["a", "b"]

    same = _loop_request(children, edges=edges, compile_cache=cache)
    compile_container_subgraph(same)
    assert compile_calls == ["a", "b"]

    resource_changed = _loop_request(
        children,
        edges=edges,
        compile_cache=cache,
        resource_snapshot_hash="resources-v2",
    )
    compile_container_subgraph(resource_changed)
    assert compile_calls == ["a", "b", "a", "b"]

    compile_calls.clear()
    cache.clear()
    compile_container_subgraph(_loop_request(children, edges=edges, compile_cache=cache))
    assert compile_calls == ["a", "b"]
    compile_calls.clear()
    mutated = deepcopy(children)
    cast(dict[str, object], mutated[0]["intent"])["outputs"] = [{"name": "text", "type": "number"}]
    compile_container_subgraph(_loop_request(mutated, edges=edges, compile_cache=cache))
    assert "b" in compile_calls


def test_container_cache_key_includes_resolved_child_id(monkeypatch: pytest.MonkeyPatch) -> None:
    compile_calls: list[str] = []

    def counting_compile(child: Any, context: Any) -> CompiledChild:
        compile_calls.append(context.ref_map[child.ref])
        compiled = _dummy_compiled(child.ref)
        compiled.node["id"] = context.ref_map[child.ref]
        return compiled

    monkeypatch.setattr("core.workflow.generator.compiler.container_children.compile_container_child", counting_compile)
    monkeypatch.setattr(
        "core.workflow.generator.compiler.container_compiler.validate_compiled_container", lambda *_args: None
    )
    cache: dict[ContainerCompileCacheKey, CompiledChild] = {}
    child = _assigner_payload("worker")

    compile_container_subgraph(_loop_request([child], compile_cache=cache))
    occupied = upsert_node(
        empty_graph(),
        node_id="loop1_worker",
        node_type="template-transform",
        title="occupied",
        desc="",
        config={"template": "occupied", "variables": []},
    )
    second = compile_container_subgraph(_loop_request([child], compile_cache=cache, frozen_graph=occupied))

    assert compile_calls == ["loop1_worker", "loop1_worker_2"]
    compiled_child = find_node(second.graph, "loop1_worker_2")
    assert compiled_child is not None
    assert compiled_child["data"]["assist_ref"] == "worker"


def test_turn_state_holds_compile_cache() -> None:
    key = ContainerCompileCacheKey(
        container_id="loop1",
        child_ref="a",
        resolved_node_id="loop1_a",
        intent_hash="i",
        resource_snapshot_hash="r",
        upstream_signature="u",
    )
    state = ToolTurnState(graph=empty_graph(), compile_cache={key: _dummy_compiled("a")})
    assert key in state.compile_cache
    cached = state.compile_cache[key]
    assert "credential" not in str(cached.node).lower()
    assert "api_key" not in str(cached.node).lower()
