from copy import deepcopy

import pytest

from core.workflow.generator.graph.graph_ops import (
    ContainerReplaceError,
    connect,
    empty_graph,
    find_node,
    replace_container_subgraph,
    upsert_node,
)
from core.workflow.generator.graph.types import MinimalGraphEdgeDict, MinimalGraphNodeDict


def _graph_with_loop(*, external_child_edge: bool = False, end_reads_acc: bool = True) -> dict:
    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={})
    graph = upsert_node(
        graph,
        node_id="loop1",
        node_type="loop",
        title="累计",
        desc="",
        config={"loop_variables": [{"label": "acc", "var_type": "string", "value_type": "constant", "value": ""}]},
    )
    loop_node = find_node(graph, "loop1")
    assert loop_node is not None
    loop_node["position"] = {"x": 40.0, "y": 80.0}  # type: ignore[typeddict-unknown-key]
    graph = upsert_node(
        graph,
        node_id="child_old",
        node_type="llm",
        title="旧子节点",
        desc="",
        config={"prompt_template": [{"text": "{{#loop1.acc#}}"}]},
        parent="loop1",
    )
    end_config: dict[str, object] = {}
    if end_reads_acc:
        end_config = {"outputs": [{"value_selector": ["loop1", "acc"]}]}
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=end_config)
    graph = connect(graph, source="start", target="loop1")
    graph = connect(graph, source="loop1", target="end")
    if external_child_edge:
        graph = connect(graph, source="start", target="child_old")
    return graph


def _new_child() -> MinimalGraphNodeDict:
    return {
        "id": "child_new",
        "parentId": "loop1",
        "data": {"type": "llm", "title": "新子节点", "desc": "", "prompt_template": [{"text": "ok"}]},
    }


def _snapshot(graph: dict) -> dict:
    return deepcopy(graph)


def test_legal_replace_keeps_container_id_position_and_external_edges() -> None:
    graph = _graph_with_loop()
    original = _snapshot(graph)
    replacement_nodes: tuple[MinimalGraphNodeDict, ...] = (_new_child(),)
    replacement_edges: tuple[MinimalGraphEdgeDict, ...] = ()

    updated = replace_container_subgraph(
        graph,
        container_id="loop1",
        replacement_nodes=replacement_nodes,
        replacement_edges=replacement_edges,
        exposed_outputs=frozenset({"acc"}),
    )

    assert updated is not graph
    assert graph == original
    container = find_node(updated, "loop1")
    assert container is not None
    assert container["id"] == "loop1"
    assert container.get("position") == {"x": 40.0, "y": 80.0}
    assert find_node(updated, "child_old") is None
    assert find_node(updated, "child_new") is not None
    assert find_node(updated, "start") is not None
    assert {(edge["source"], edge["target"]) for edge in updated["edges"]} == {("start", "loop1"), ("loop1", "end")}


def test_rejects_external_direct_child_edge_and_leaves_old_children() -> None:
    graph = _graph_with_loop(external_child_edge=True)
    original = _snapshot(graph)

    with pytest.raises(ContainerReplaceError):
        replace_container_subgraph(
            graph,
            container_id="loop1",
            replacement_nodes=(_new_child(),),
            replacement_edges=(),
            exposed_outputs=frozenset({"acc"}),
        )

    assert graph == original
    assert find_node(graph, "child_old") is not None


def test_rejects_external_direct_child_selector_and_leaves_old_children() -> None:
    graph = _graph_with_loop()
    end = find_node(graph, "end")
    assert end is not None
    end["data"]["outputs"] = [{"value_selector": ["child_old", "text"]}]
    original = _snapshot(graph)

    with pytest.raises(ContainerReplaceError):
        replace_container_subgraph(
            graph,
            container_id="loop1",
            replacement_nodes=(_new_child(),),
            replacement_edges=(),
            exposed_outputs=frozenset({"acc"}),
        )

    assert graph == original
    assert find_node(graph, "child_old") is not None


def test_rejects_deleting_externally_used_container_output() -> None:
    graph = _graph_with_loop(end_reads_acc=True)
    original = _snapshot(graph)

    with pytest.raises(ContainerReplaceError):
        replace_container_subgraph(
            graph,
            container_id="loop1",
            replacement_nodes=(_new_child(),),
            replacement_edges=(),
            exposed_outputs=frozenset({"other"}),
        )

    assert graph == original
    assert find_node(graph, "child_old") is not None
    assert find_node(graph, "end") is not None
