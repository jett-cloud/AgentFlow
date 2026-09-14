from core.workflow.generator.graph.graph_ops import (
    connect,
    delete_node,
    disconnect,
    empty_graph,
    find_node,
    read_node_view,
    render_compact_graph,
    upsert_node,
)


def test_empty_graph_has_no_nodes_and_default_viewport():
    graph = empty_graph()

    assert graph["nodes"] == []
    assert graph["edges"] == []
    assert graph["viewport"] == {"x": 0.0, "y": 0.0, "zoom": 0.7}


def test_upsert_node_adds_node_without_mutating_input():
    graph = empty_graph()

    updated = upsert_node(
        graph,
        node_id="start",
        node_type="start",
        title="开始",
        desc="接收输入",
        config={"variables": []},
    )

    assert graph["nodes"] == []
    assert len(updated["nodes"]) == 1
    node = updated["nodes"][0]
    assert node["id"] == "start"
    assert node["data"]["type"] == "start"
    assert node["data"]["title"] == "开始"
    assert node["data"]["desc"] == "接收输入"
    assert node["data"]["variables"] == []
    # The minimal shape is load-bearing: graph_postprocessor is the only place
    # allowed to add ReactFlow's node "type" and "position".
    assert set(updated["nodes"][0]) == {"id", "data"}


def test_upsert_node_replaces_config_of_existing_node_and_keeps_order():
    graph = upsert_node(empty_graph(), node_id="a", node_type="llm", title="A", desc="", config={"prompt": "old"})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config={})

    updated = upsert_node(graph, node_id="a", node_type="llm", title="A2", desc="", config={"prompt": "new"})

    assert [node["id"] for node in updated["nodes"]] == ["a", "b"]
    assert updated["nodes"][0]["data"]["title"] == "A2"
    assert updated["nodes"][0]["data"]["prompt"] == "new"


def test_upsert_node_ignores_reserved_keys_supplied_in_config():
    graph = upsert_node(
        empty_graph(),
        node_id="a",
        node_type="llm",
        title="真实标题",
        desc="真实描述",
        config={"type": "spoofed", "title": "spoofed", "desc": "spoofed", "prompt": "real"},
    )

    data = graph["nodes"][0]["data"]
    assert data["type"] == "llm"
    assert data["title"] == "真实标题"
    assert data["desc"] == "真实描述"
    assert data["prompt"] == "real"


def test_find_node_returns_none_for_unknown_id():
    graph = upsert_node(empty_graph(), node_id="a", node_type="llm", title="A", desc="", config={})

    assert find_node(graph, "a") is not None
    assert find_node(graph, "missing") is None


def test_connect_adds_edge_and_is_idempotent():
    graph = upsert_node(empty_graph(), node_id="a", node_type="start", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config={})

    connected = connect(graph, source="a", target="b")
    reconnected = connect(connected, source="a", target="b")

    assert graph["edges"] == []
    assert len(reconnected["edges"]) == 1
    assert reconnected["edges"][0]["source"] == "a"
    assert reconnected["edges"][0]["target"] == "b"
    # No edge id and no ReactFlow edge "type" — graph_postprocessor adds those.
    assert set(reconnected["edges"][0]) == {"source", "target"}


def test_connect_treats_an_empty_source_handle_as_no_handle():
    graph = upsert_node(empty_graph(), node_id="a", node_type="start", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config={})

    graph = connect(graph, source="a", target="b", source_handle="")
    graph = connect(graph, source="a", target="b", source_handle="")

    assert len(graph["edges"]) == 1
    assert set(graph["edges"][0]) == {"source", "target"}


def test_connect_matches_an_empty_source_handle_against_a_handleless_edge():
    graph = upsert_node(empty_graph(), node_id="a", node_type="start", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config={})

    graph = connect(graph, source="a", target="b")
    graph = connect(graph, source="a", target="b", source_handle="")

    assert len(graph["edges"]) == 1


def test_connect_keeps_source_handle_and_treats_it_as_part_of_identity():
    graph = upsert_node(empty_graph(), node_id="a", node_type="if-else", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config={})

    graph = connect(graph, source="a", target="b", source_handle="true")
    graph = connect(graph, source="a", target="b", source_handle="false")

    assert len(graph["edges"]) == 2
    assert {edge.get("sourceHandle") for edge in graph["edges"]} == {"true", "false"}


def test_delete_node_drops_incident_edges():
    graph = upsert_node(empty_graph(), node_id="a", node_type="start", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="llm", title="B", desc="", config={})
    graph = upsert_node(graph, node_id="c", node_type="end", title="C", desc="", config={})
    graph = connect(graph, source="a", target="b")
    graph = connect(graph, source="b", target="c")

    updated = delete_node(graph, "b")

    assert [node["id"] for node in graph["nodes"]] == ["a", "b", "c"]
    assert len(graph["edges"]) == 2
    assert [node["id"] for node in updated["nodes"]] == ["a", "c"]
    assert updated["edges"] == []


def test_disconnect_removes_only_the_named_edge():
    graph = upsert_node(empty_graph(), node_id="a", node_type="start", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="llm", title="B", desc="", config={})
    graph = upsert_node(graph, node_id="c", node_type="end", title="C", desc="", config={})
    graph = connect(graph, source="a", target="b")
    graph = connect(graph, source="b", target="c")

    updated, match_count = disconnect(graph, source="a", target="b")

    assert match_count == 1
    assert len(updated["edges"]) == 1
    assert updated["edges"][0]["source"] == "b"


def test_disconnect_without_handle_is_noop_when_zero_matches():
    graph = upsert_node(empty_graph(), node_id="a", node_type="start", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config={})

    updated, match_count = disconnect(graph, source="a", target="b")

    assert match_count == 0
    assert updated["edges"] == []
    assert graph["edges"] == []


def test_disconnect_without_handle_leaves_ambiguous_edges_and_reports_count():
    graph = upsert_node(empty_graph(), node_id="a", node_type="if-else", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config={})
    graph = connect(graph, source="a", target="b", source_handle="true")
    graph = connect(graph, source="a", target="b", source_handle="false")

    updated, match_count = disconnect(graph, source="a", target="b")

    assert match_count == 2
    assert len(graph["edges"]) == 2
    assert len(updated["edges"]) == 2
    assert {edge.get("sourceHandle") for edge in updated["edges"]} == {"true", "false"}


def test_disconnect_with_source_handle_removes_only_that_edge():
    graph = upsert_node(empty_graph(), node_id="a", node_type="if-else", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config={})
    graph = connect(graph, source="a", target="b", source_handle="true")
    graph = connect(graph, source="a", target="b", source_handle="false")

    updated, match_count = disconnect(graph, source="a", target="b", source_handle="true")

    assert match_count == 1
    assert len(graph["edges"]) == 2
    assert [edge.get("sourceHandle") for edge in updated["edges"]] == ["false"]


def test_render_compact_graph_uses_declared_outputs_for_legacy_aggregator():
    graph = upsert_node(empty_graph(), node_id="agg", node_type="variable-assigner", title="聚合", desc="", config={})

    rendered = render_compact_graph(graph)

    assert rendered["nodes"][0]["outputs"] == ["output"]
    assert "config" not in rendered["nodes"][0]


def test_render_compact_graph_exposes_confirmed_typed_variable_declarations():
    graph = upsert_node(
        empty_graph(),
        node_id="code1",
        node_type="code",
        title="Parse",
        desc="",
        config={"outputs": {"items": {"type": "array[object]", "children": None}}},
    )

    rendered = render_compact_graph(graph)

    assert rendered["nodes"][0]["variables"] == [
        {
            "selector": ["code1", "items"],
            "type": "array[object]",
            "scope": "workflow",
            "confirmed": True,
        }
    ]


def test_render_compact_graph_exposes_iteration_item_and_index():
    graph = upsert_node(empty_graph(), node_id="iter1", node_type="iteration", title="逐题", desc="", config={})

    rendered = render_compact_graph(graph)

    assert rendered["nodes"][0]["outputs"] == ["output", "item", "index"]


def test_render_compact_graph_exposes_loop_variable_labels_only():
    graph = upsert_node(
        empty_graph(),
        node_id="loop1",
        node_type="loop",
        title="累计",
        desc="",
        config={"loop_variables": [{"label": "acc", "var_type": "string", "value_type": "constant", "value": ""}]},
    )

    rendered = render_compact_graph(graph)

    assert rendered["nodes"][0]["outputs"] == ["acc"]
    assert "item" not in rendered["nodes"][0]["outputs"]
    assert "output" not in rendered["nodes"][0]["outputs"]


def test_render_compact_graph_omits_config_and_includes_topology():
    graph = upsert_node(
        empty_graph(), node_id="a", node_type="llm", title="判分", desc="用 LLM 打分", config={"prompt": "x"}
    )
    graph = upsert_node(graph, node_id="b", node_type="end", title="结束", desc="", config={})
    graph = connect(graph, source="a", target="b")

    rendered = render_compact_graph(graph)
    node = rendered["nodes"][0]

    assert "config" not in node
    assert "prompt" not in node
    assert node["id"] == "a"
    assert node["type"] == "llm"
    assert node["title"] == "判分"
    assert "outputs" in node
    assert rendered["nodes"][1] == {
        "id": "b",
        "type": "end",
        "title": "结束",
        "outputs": [],
    }
    assert rendered["edges"] == [{"source": "a", "target": "b"}]


def test_render_compact_graph_emits_source_handle_only_for_edges_that_have_one():
    graph = upsert_node(empty_graph(), node_id="a", node_type="if-else", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="llm", title="B", desc="", config={})
    graph = upsert_node(graph, node_id="c", node_type="end", title="C", desc="", config={})
    graph = connect(graph, source="a", target="b", source_handle="true")
    graph = connect(graph, source="b", target="c")

    rendered = render_compact_graph(graph)

    assert rendered["edges"] == [
        {"source": "a", "target": "b", "source_handle": "true"},
        {"source": "b", "target": "c"},
    ]


def test_read_node_view_includes_config_and_omits_edges():
    graph = upsert_node(
        empty_graph(), node_id="a", node_type="llm", title="判分", desc="用 LLM 打分", config={"prompt": "x"}
    )
    graph = upsert_node(graph, node_id="b", node_type="end", title="结束", desc="", config={})
    graph = connect(graph, source="a", target="b")

    view = read_node_view(graph, "a")

    assert view == {
        "id": "a",
        "type": "llm",
        "title": "判分",
        "desc": "用 LLM 打分",
        "config": {"prompt": "x"},
    }
    assert "edges" not in view
    assert read_node_view(graph, "missing") is None


def test_mutating_a_nested_config_in_the_result_leaves_the_input_untouched():
    graph = upsert_node(
        empty_graph(), node_id="a", node_type="llm", title="A", desc="", config={"model": {"name": "gpt-4"}}
    )

    updated = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config={})
    updated["nodes"][0]["data"]["model"]["name"] = "mutated"

    assert graph["nodes"][0]["data"]["model"]["name"] == "gpt-4"


def test_upsert_node_deepcopies_config_so_caller_mutations_do_not_alias():
    config = {"model": {"name": "gpt-4"}, "prompt": ["hello"]}
    graph = upsert_node(empty_graph(), node_id="a", node_type="llm", title="A", desc="", config=config)

    config["model"]["name"] = "mutated"
    config["prompt"].append("world")

    assert graph["nodes"][0]["data"]["model"]["name"] == "gpt-4"
    assert graph["nodes"][0]["data"]["prompt"] == ["hello"]
