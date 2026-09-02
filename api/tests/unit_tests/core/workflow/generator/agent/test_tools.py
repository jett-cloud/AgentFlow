from dataclasses import replace

from core.workflow.generator.agent.graph_ops import connect, empty_graph, find_node, upsert_node
from core.workflow.generator.agent.tools import (
    RETRYABLE_BY_ERROR_CODE,
    ToolContext,
    commit_build_node,
    compile_build_node,
    dispatch,
)
from core.workflow.generator.agent.types import ToolCall


def _set_env(context: ToolContext, **changes: object) -> None:
    context.env = replace(context.env, **changes)


def _call(name: str, **arguments: object) -> ToolCall:
    return {"id": "c1", "name": name, "arguments": arguments}


def _connected_start_end():
    graph = upsert_node(
        empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={"variables": []}
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    return connect(graph, source="start", target="end")


def test_read_graph_omits_node_config(tool_context) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="kr",
        node_type="knowledge-retrieval",
        title="检索",
        desc="",
        config={"dataset_ids": ["ds-1"]},
    )
    result = dispatch(_call("read_graph"), tool_context)
    assert result["ok"] is True
    assert result["changed"] is False
    node = result["content"]["nodes"][0]
    assert "config" not in node
    assert node["id"] == "kr"
    assert "dataset_ids" not in node


def test_build_node_update_rejects_type(tool_context) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(), node_id="kr", node_type="knowledge-retrieval", title="检索", desc="", config={}
    )
    result = dispatch(
        _call("build_node", mode="update", id="kr", type="llm", purpose="改成 LLM"),
        tool_context,
    )
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert result["retryable"] is True
    assert tool_context.state.graph["nodes"][0]["data"]["type"] == "knowledge-retrieval"


def test_create_existing_id_is_node_exists(tool_context) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(), node_id="kr", node_type="knowledge-retrieval", title="检索", desc="", config={}
    )
    result = dispatch(
        _call("build_node", mode="create", id="kr", type="llm", title="评判", purpose="新建"),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "NODE_EXISTS"
    assert result["changed"] is False


def test_disconnect_noop_when_edge_absent(tool_context) -> None:
    tool_context.state.graph = upsert_node(empty_graph(), node_id="a", node_type="start", title="A", desc="", config={})
    tool_context.state.graph = upsert_node(
        tool_context.state.graph, node_id="b", node_type="end", title="B", desc="", config={}
    )
    result = dispatch(_call("disconnect", source="a", target="b"), tool_context)
    assert result["ok"] is True
    assert result["changed"] is False
    assert result["content"]["reason"] == "edge_not_present"


def test_disconnect_ambiguous_without_handle(tool_context) -> None:
    graph = upsert_node(empty_graph(), node_id="a", node_type="if-else", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config={})
    graph = connect(graph, source="a", target="b", source_handle="true")
    graph = connect(graph, source="a", target="b", source_handle="false")
    tool_context.state.graph = graph
    result = dispatch(_call("disconnect", source="a", target="b"), tool_context)
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["error_code"] == "AMBIGUOUS_EDGE"
    assert len(tool_context.state.graph["edges"]) == 2


def test_retryable_is_table_driven() -> None:
    assert RETRYABLE_BY_ERROR_CODE["NODE_NOT_FOUND"] is True
    assert RETRYABLE_BY_ERROR_CODE["NODE_EXISTS"] is True
    assert RETRYABLE_BY_ERROR_CODE["INVALID_PARENT"] is True
    assert RETRYABLE_BY_ERROR_CODE["AMBIGUOUS_EDGE"] is True
    assert RETRYABLE_BY_ERROR_CODE["INVALID_ARGUMENT"] is True
    assert RETRYABLE_BY_ERROR_CODE["TYPE_UNCHANGED_USE_UPDATE"] is True
    assert RETRYABLE_BY_ERROR_CODE["UNKNOWN_DATASET"] is True
    assert RETRYABLE_BY_ERROR_CODE["UNKNOWN_TOOL"] is True
    assert RETRYABLE_BY_ERROR_CODE["PERMISSION_DENIED"] is False
    assert RETRYABLE_BY_ERROR_CODE["RESOURCE_FORBIDDEN"] is False
    assert RETRYABLE_BY_ERROR_CODE["UNSUPPORTED_NODE_TYPE"] is False
    assert RETRYABLE_BY_ERROR_CODE["CAPABILITY_UNAVAILABLE"] is False
    assert RETRYABLE_BY_ERROR_CODE["LIVE_RUN_REQUIRES_CONSENT"] is True


def test_read_node_returns_config_without_edges(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="kr",
        node_type="knowledge-retrieval",
        title="检索",
        desc="",
        config={"dataset_ids": ["ds-1"]},
    )
    tool_context.state.graph = upsert_node(
        tool_context.state.graph, node_id="end", node_type="end", title="结束", desc="", config={}
    )
    tool_context.state.graph = connect(tool_context.state.graph, source="kr", target="end")

    result = dispatch(_call("read_node", id="kr"), tool_context)

    assert result["ok"] is True
    assert result["changed"] is False
    assert result["content"]["config"] == {"dataset_ids": ["ds-1"]}
    assert "edges" not in result["content"]


def test_read_node_missing_id_is_node_not_found(tool_context: ToolContext) -> None:
    result = dispatch(_call("read_node", id="missing"), tool_context)

    assert result["ok"] is False
    assert result["changed"] is False
    assert result["error_code"] == "NODE_NOT_FOUND"
    assert result["retryable"] is True


def test_replace_same_type_is_type_unchanged_use_update(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(), node_id="kr", node_type="knowledge-retrieval", title="检索", desc="", config={}
    )
    result = dispatch(
        _call("build_node", mode="replace", id="kr", type="knowledge-retrieval", purpose="重建"),
        tool_context,
    )
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["error_code"] == "TYPE_UNCHANGED_USE_UPDATE"
    assert result["retryable"] is True


def test_disconnect_with_handle_removes_only_that_edge(tool_context: ToolContext) -> None:
    graph = upsert_node(empty_graph(), node_id="a", node_type="if-else", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config={})
    graph = connect(graph, source="a", target="b", source_handle="true")
    graph = connect(graph, source="a", target="b", source_handle="false")
    tool_context.state.graph = graph

    result = dispatch(_call("disconnect", source="a", target="b", source_handle="true"), tool_context)

    assert result["ok"] is True
    assert result["changed"] is True
    assert [edge.get("sourceHandle") for edge in tool_context.state.graph["edges"]] == ["false"]


def test_fail_does_not_change_the_graph(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(empty_graph(), node_id="a", node_type="start", title="A", desc="", config={})
    result = dispatch(_call("fail", reason="租户没有可用知识库"), tool_context)

    assert result["ok"] is True
    assert result["changed"] is False
    assert result["content"]["reason"] == "租户没有可用知识库"
    assert [node["id"] for node in tool_context.state.graph["nodes"]] == ["a"]


def test_inspect_node_schema_returns_the_type_snippet(tool_context: ToolContext) -> None:
    result = dispatch(_call("inspect_node_schema", node_type="llm"), tool_context)

    assert result["ok"] is True
    assert result["changed"] is False
    assert "prompt_template" in str(result["content"]["snippet"])


def test_inspect_node_schema_agent_includes_dify_tools(tool_context: ToolContext) -> None:
    result = dispatch(_call("inspect_node_schema", node_type="agent"), tool_context)

    assert result["ok"] is True
    snippet = str(result["content"]["snippet"])
    assert "dify_tools" in snippet
    assert "mcp" in snippet


def test_validate_graph_and_finish_dispatch_without_crashing(tool_context: ToolContext) -> None:
    validate = dispatch(_call("validate_graph"), tool_context)
    finish = dispatch(_call("finish", summary="已搭好"), tool_context)

    assert validate["name"] == "validate_graph"
    assert validate["changed"] is False
    assert finish["name"] == "finish"


class _FakeLLM:
    def __init__(self, config: dict) -> None:
        self.config = config

    def iter_json(self, *, messages, stage):
        yield from ()
        return {"config": dict(self.config)}


def test_update_omitting_title_and_parent_keeps_old(tool_context: ToolContext) -> None:
    graph = upsert_node(empty_graph(), node_id="iter1", node_type="iteration", title="循环", desc="", config={})
    graph = upsert_node(
        graph, node_id="kr", node_type="knowledge-retrieval", title="检索", desc="", config={"dataset_ids": ["ds-1"]}
    )
    graph["nodes"][1]["parentId"] = "iter1"
    tool_context.state.graph = graph
    _set_env(tool_context, llm_client=_FakeLLM({"dataset_ids": ["ds-2"]}))

    result = dispatch(_call("build_node", mode="update", id="kr", purpose="换库"), tool_context)
    node = find_node(tool_context.state.graph, "kr")

    assert result["ok"] is True
    assert result["changed"] is True
    assert "config" not in result["content"]
    assert "nodes" not in result["content"]
    assert "dataset_binding" in result["content"]["effects"]
    assert node is not None
    assert node["data"]["title"] == "检索"
    assert node.get("parentId") == "iter1"


def test_compile_build_node_does_not_write_graph_until_commit(tool_context: ToolContext) -> None:
    _set_env(tool_context, llm_client=_FakeLLM({}))
    call = _call("build_node", mode="create", id="llm1", type="llm", title="模型", purpose="写一段说明")
    before = len(tool_context.state.graph["nodes"])

    compiled = compile_build_node(call, tool_context)

    assert find_node(tool_context.state.graph, "llm1") is None
    assert len(tool_context.state.graph["nodes"]) == before

    result = commit_build_node(compiled, tool_context)

    assert result["ok"] is True
    assert result["changed"] is True
    assert find_node(tool_context.state.graph, "llm1") is not None


def test_update_empty_parent_unnests_to_top(tool_context: ToolContext) -> None:
    graph = upsert_node(empty_graph(), node_id="iter1", node_type="iteration", title="循环", desc="", config={})
    graph = upsert_node(graph, node_id="kr", node_type="knowledge-retrieval", title="检索", desc="", config={})
    graph["nodes"][1]["parentId"] = "iter1"
    graph["nodes"][1]["data"]["parentId"] = "iter1"
    tool_context.state.graph = graph
    _set_env(tool_context, llm_client=_FakeLLM({}))

    result = dispatch(_call("build_node", mode="update", id="kr", purpose="移出循环", parent=""), tool_context)
    node = find_node(tool_context.state.graph, "kr")

    assert result["ok"] is True
    assert node is not None
    assert "parentId" not in node
    assert "parentId" not in node["data"]
    assert "parent" in result["content"]["effects"]


def test_replace_does_not_delete_edges(tool_context: ToolContext) -> None:
    graph = upsert_node(empty_graph(), node_id="a", node_type="start", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config={})
    graph = connect(graph, source="a", target="b")
    tool_context.state.graph = graph
    _set_env(tool_context, llm_client=_FakeLLM({"prompt_template": []}))

    result = dispatch(_call("build_node", mode="replace", id="a", type="llm", purpose="改成 LLM"), tool_context)

    assert result["ok"] is True
    assert result["changed"] is True
    assert result["content"]["preserved_edge_count"] == 1
    assert result["content"]["requires_revalidation"] is True
    assert len(tool_context.state.graph["edges"]) == 1
    assert tool_context.state.graph["nodes"][0]["data"]["type"] == "llm"
    assert tool_context.state.graph["nodes"][1]["id"] == "b"


def test_invalid_parent_does_not_call_builder(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(), node_id="kr", node_type="knowledge-retrieval", title="检索", desc="", config={}
    )
    result = dispatch(
        _call("build_node", mode="update", id="kr", purpose="挪进不存在的容器", parent="missing"),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_PARENT"
    assert result["changed"] is False
    assert result["retryable"] is True


def test_connect_already_exists_is_noop(tool_context: ToolContext) -> None:
    graph = upsert_node(empty_graph(), node_id="a", node_type="start", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config={})
    tool_context.state.graph = connect(graph, source="a", target="b")

    result = dispatch(_call("connect", source="a", target="b"), tool_context)

    assert result["ok"] is True
    assert result["changed"] is False
    assert result["content"]["reason"] == "edge_already_exists"
    assert len(tool_context.state.graph["edges"]) == 1


def test_connect_missing_endpoint_is_node_not_found(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(empty_graph(), node_id="a", node_type="start", title="A", desc="", config={})

    result = dispatch(_call("connect", source="a", target="missing"), tool_context)

    assert result["ok"] is False
    assert result["changed"] is False
    assert result["error_code"] == "NODE_NOT_FOUND"
    assert tool_context.state.graph["edges"] == []


def _node_xy(node: object) -> tuple[object, object]:
    position = node.get("position") if isinstance(node, dict) else None
    if not isinstance(position, dict):
        return (None, None)
    return (position.get("x"), position.get("y"))


def test_connect_lays_out_top_level_nodes_instead_of_stacking(tool_context: ToolContext) -> None:
    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={})
    graph = upsert_node(graph, node_id="llm", node_type="llm", title="模型", desc="", config={})
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    tool_context.state.graph = graph
    revision_before = tool_context.state.candidate_revision

    first = dispatch(_call("connect", source="start", target="llm"), tool_context)
    second = dispatch(_call("connect", source="llm", target="end"), tool_context)

    points = [_node_xy(node) for node in tool_context.state.graph["nodes"] if not node.get("parentId")]
    assert first["changed"] is True
    assert second["changed"] is True
    assert tool_context.state.candidate_revision == revision_before
    assert None not in {x for x, _ in points}
    assert len(set(points)) == 3


def test_create_inside_loop_spreads_children_and_grows_container(tool_context: ToolContext) -> None:
    _set_env(tool_context, llm_client=_FakeLLM({}))
    assert dispatch(
        _call("build_node", mode="create", id="loop1", type="loop", title="循环", purpose="包一层循环"),
        tool_context,
    )["ok"] is True
    assert dispatch(
        _call(
            "build_node",
            mode="create",
            id="inner_a",
            type="llm",
            title="处理",
            purpose="循环里第一步",
            parent="loop1",
        ),
        tool_context,
    )["ok"] is True
    assert dispatch(
        _call(
            "build_node",
            mode="create",
            id="inner_b",
            type="end",
            title="结束",
            purpose="循环里第二步",
            parent="loop1",
        ),
        tool_context,
    )["ok"] is True
    dispatch(_call("connect", source="inner_a", target="inner_b"), tool_context)

    loop = find_node(tool_context.state.graph, "loop1")
    children = [node for node in tool_context.state.graph["nodes"] if node.get("parentId") == "loop1"]
    points = [_node_xy(node) for node in children]
    start = next(node for node in children if (node.get("data") or {}).get("type") == "loop-start")

    assert loop is not None
    assert len(children) >= 2
    assert None not in {x for x, _ in points}
    assert len(set(points)) == len(children)
    assert any(
        edge.get("source") == start["id"] and edge.get("target") == "inner_a"
        for edge in tool_context.state.graph["edges"]
    )
    padding = 24.0
    max_right = max(
        float(x) + float(node.get("width") or 244)
        for (x, _y), node in zip(points, children, strict=True)
        if isinstance(x, (int, float))
    )
    max_bottom = max(
        float(y) + float(node.get("height") or 100)
        for (_x, y), node in zip(points, children, strict=True)
        if isinstance(y, (int, float))
    )
    assert float(loop.get("width") or 0) >= max(320.0, max_right + padding)
    assert float(loop.get("height") or 0) >= max(200.0, max_bottom + padding)


def test_delete_missing_node_is_noop(tool_context: ToolContext) -> None:
    result = dispatch(_call("delete_node", node_id="missing"), tool_context)

    assert result["ok"] is True
    assert result["changed"] is False
    assert result["content"]["reason"] == "node_not_present"


def test_search_and_build_share_the_run_snapshot(tool_context) -> None:
    _set_env(
        tool_context,
        knowledge_entries=[{"id": "ds-live", "name": "live", "description": ""}],
        installed_dataset_ids={"ds-live"},
        knowledge_available=True,
    )
    search = dispatch(_call("search_datasets", query="live"), tool_context)
    assert any(hit["id"] == "ds-live" for hit in search["content"]["hits"])

    # transcript 里出现过的旧 id 不在 snapshot 中 → 拒绝
    _set_env(tool_context, llm_client=_FakeLLM({"dataset_ids": ["ds-stale"]}))
    result = dispatch(
        _call("build_node", mode="create", id="kr", type="knowledge-retrieval", title="检索", purpose="绑 ds-stale"),
        tool_context,
    )
    # 用 mock builder 返回 dataset_ids=["ds-stale"]；见步骤 3 的 fake client
    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_DATASET"
    assert result["changed"] is False


def test_unavailable_knowledge_catalogue_skips_membership_not_reject_all(tool_context) -> None:
    _set_env(tool_context, knowledge_available=False, installed_dataset_ids=None)
    search = dispatch(_call("search_datasets", query="anything"), tool_context)
    assert search["ok"] is True
    assert search["content"]["available"] is False


def test_empty_knowledge_snapshot_rejects_any_dataset(tool_context: ToolContext) -> None:
    _set_env(tool_context, knowledge_available=True, installed_dataset_ids=set(), knowledge_entries=[])
    search = dispatch(_call("search_datasets", query="live"), tool_context)
    assert search["ok"] is True
    assert search["content"]["available"] is True
    assert search["content"]["hits"] == []

    _set_env(tool_context, llm_client=_FakeLLM({"dataset_ids": ["ds-live"]}))
    result = dispatch(
        _call("build_node", mode="create", id="kr", type="knowledge-retrieval", title="检索", purpose="绑 ds-live"),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_DATASET"
    assert result["retryable"] is True
    assert result["changed"] is False
    assert find_node(tool_context.state.graph, "kr") is None


def test_unavailable_knowledge_catalogue_does_not_reject_stale_ids(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        knowledge_available=False,
        installed_dataset_ids=None,
        llm_client=_FakeLLM({"dataset_ids": ["ds-stale"]}),
    )
    result = dispatch(
        _call("build_node", mode="create", id="kr", type="knowledge-retrieval", title="检索", purpose="绑 ds-stale"),
        tool_context,
    )
    assert result["ok"] is True
    assert result["error_code"] is None
    assert find_node(tool_context.state.graph, "kr") is not None


def test_build_node_rejects_unknown_tool_from_snapshot(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("langgenius/google", "google_search")},
        tool_entries=[
            {
                "provider_name": "langgenius/google",
                "provider_type": "builtin",
                "plugin_id": "langgenius/google",
                "tool_name": "google_search",
                "tool_label": "Google Search",
                "description": "search the web",
            }
        ],
    )
    search = dispatch(_call("search_tools", query="google"), tool_context)
    assert search["ok"] is True
    assert search["content"]["available"] is True
    assert any(hit["tool_name"] == "google_search" for hit in search["content"]["hits"])
    assert all(hit["tool_name"] != "deleted_search" for hit in search["content"]["hits"])

    _set_env(tool_context, llm_client=_FakeLLM({"provider_name": "stale-provider", "tool_name": "stale_tool"}))
    result = dispatch(
        _call("build_node", mode="create", id="t1", type="tool", title="工具", purpose="绑过期工具"),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_TOOL"
    assert result["retryable"] is True
    assert result["changed"] is False
    assert find_node(tool_context.state.graph, "t1") is None


def test_empty_tools_snapshot_rejects_any_tool(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools=set(),
        tool_entries=[],
        llm_client=_FakeLLM({"provider_name": "p", "tool_name": "t"}),
    )
    result = dispatch(
        _call("build_node", mode="create", id="t1", type="tool", title="工具", purpose="绑"),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_TOOL"
    assert result["changed"] is False
    assert find_node(tool_context.state.graph, "t1") is None


def test_unavailable_tools_catalogue_skips_membership_not_reject_all(tool_context: ToolContext) -> None:
    _set_env(tool_context, tools_available=False, installed_tools=None)
    search = dispatch(_call("search_tools", query="anything"), tool_context)
    assert search["ok"] is True
    assert search["content"]["available"] is False
    assert search["content"]["hits"] == []


def test_build_node_accepts_mcp_dify_tools_from_snapshot(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("github-official", "get_file_contents")},
        tool_entries=[
            {
                "provider_name": "github-official",
                "provider_type": "mcp",
                "plugin_id": "",
                "tool_name": "get_file_contents",
                "tool_label": "Get File",
                "description": "Read a repo file.",
            }
        ],
    )
    search = dispatch(_call("search_tools", query="github"), tool_context)
    assert search["ok"] is True
    assert any(hit["provider_type"] == "mcp" for hit in search["content"]["hits"])

    _set_env(
        tool_context,
        llm_client=_FakeLLM(
            {
                "agent_task": "读取仓库文件",
                "agent_binding": {"binding_type": "inline_agent"},
                "dify_tools": [
                    {"provider_type": "mcp", "provider_id": "github-official", "tool_name": None},
                ],
            }
        ),
    )
    result = dispatch(
        _call("build_node", mode="create", id="ag1", type="agent", title="助手", purpose="用 MCP 读文件"),
        tool_context,
    )
    node = find_node(tool_context.state.graph, "ag1")
    assert result["ok"] is True
    assert result["error_code"] is None
    assert node is not None
    assert node["data"]["dify_tools"][0]["provider_id"] == "github-official"
    assert node["data"]["dify_tools"][0]["tool_name"] is None


def test_build_node_rejects_unknown_mcp_dify_tool(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("github-official", "get_file_contents")},
        llm_client=_FakeLLM(
            {
                "agent_task": "读取仓库文件",
                "dify_tools": [
                    {"provider_type": "mcp", "provider_id": "missing-mcp", "tool_name": None},
                ],
            }
        ),
    )
    result = dispatch(
        _call("build_node", mode="create", id="ag1", type="agent", title="助手", purpose="绑未知 MCP"),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_TOOL"
    assert result["changed"] is False
    assert find_node(tool_context.state.graph, "ag1") is None


def test_tool_id_in_dataset_ids_is_unknown_dataset(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        knowledge_available=True,
        installed_dataset_ids={"ds-live"},
        tools_available=True,
        installed_tools={("langgenius/google", "google_search")},
        llm_client=_FakeLLM({"dataset_ids": ["langgenius/google"]}),
    )
    result = dispatch(
        _call("build_node", mode="create", id="kr", type="knowledge-retrieval", title="检索", purpose="误绑工具键"),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_DATASET"
    assert result["changed"] is False
    assert find_node(tool_context.state.graph, "kr") is None


def test_validate_graph_shares_snapshot_skip_on_none(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="kr",
        node_type="knowledge-retrieval",
        title="检索",
        desc="",
        config={"dataset_ids": ["ds-stale"]},
    )
    _set_env(tool_context, knowledge_available=False, installed_dataset_ids=None)
    skipped = dispatch(_call("validate_graph"), tool_context)
    assert skipped["ok"] is True
    assert all(error["code"] != "UNKNOWN_DATASET" for error in skipped["content"]["errors"])

    _set_env(tool_context, knowledge_available=True, installed_dataset_ids={"ds-live"})
    rejected = dispatch(_call("validate_graph"), tool_context)
    assert any(error["code"] == "UNKNOWN_DATASET" for error in rejected["content"]["errors"])


def test_validate_graph_invalid_is_ok_true(tool_context) -> None:
    result = dispatch(_call("validate_graph"), tool_context)  # 空图非法
    assert result["ok"] is True
    assert result["changed"] is False
    assert result["content"]["valid"] is False
    assert result["content"]["errors"]
    assert result["content"]["repeated_after_repair"] is False


def test_finish_rejects_invalid_claim(tool_context) -> None:
    result = dispatch(_call("finish", summary="做好了"), tool_context)
    assert result["ok"] is False
    assert result["content"]["valid"] is False
    assert "errors" in result["content"]


def test_repeated_after_repair_requires_changed_true(tool_context) -> None:
    first = dispatch(_call("validate_graph"), tool_context)
    second = dispatch(_call("validate_graph"), tool_context)
    assert first["content"]["repeated_after_repair"] is False
    assert second["content"]["repeated_after_repair"] is False


def test_validate_graph_error_items_have_code_node_id_detail(tool_context: ToolContext) -> None:
    result = dispatch(_call("validate_graph"), tool_context)
    error = result["content"]["errors"][0]
    assert set(error) >= {"code", "node_id", "detail"}


def test_repeated_after_repair_true_only_after_changed_mutation(tool_context: ToolContext) -> None:
    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={})
    graph = upsert_node(graph, node_id="llm", node_type="llm", title="模型", desc="", config={})
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    tool_context.state.graph = graph

    first = dispatch(_call("validate_graph"), tool_context)
    assert first["content"]["valid"] is False
    assert first["content"]["repeated_after_repair"] is False

    mutated = dispatch(_call("connect", source="llm", target="end"), tool_context)
    assert mutated["changed"] is True

    second = dispatch(_call("validate_graph"), tool_context)
    assert second["content"]["valid"] is False
    assert second["content"]["repeated_after_repair"] is True
    error = second["content"]["errors"][0]
    assert set(error) >= {"code", "node_id", "detail"}


def test_repeated_after_repair_false_when_only_noop_between_validates(tool_context: ToolContext) -> None:
    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={})
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    tool_context.state.graph = graph

    first = dispatch(_call("validate_graph"), tool_context)
    noop = dispatch(_call("disconnect", source="start", target="end"), tool_context)
    assert noop["changed"] is False
    second = dispatch(_call("validate_graph"), tool_context)
    assert first["content"]["repeated_after_repair"] is False
    assert second["content"]["repeated_after_repair"] is False


def test_fail_does_not_hydrate_or_validate(tool_context: ToolContext) -> None:
    calls: list[object] = []

    def hydrate(graph):
        calls.append(graph)
        return graph

    _set_env(tool_context, hydrate_graph=hydrate)
    tool_context.state.graph = upsert_node(empty_graph(), node_id="a", node_type="start", title="A", desc="", config={})
    before = tool_context.state.graph
    result = dispatch(_call("fail", reason="做不到"), tool_context)

    assert result["ok"] is True
    assert result["changed"] is False
    assert calls == []
    assert tool_context.state.graph is before
    assert result["content"]["reason"] == "做不到"


def test_finish_accepts_valid_aligned_claim(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_end()
    result = dispatch(_call("finish", summary="已搭好"), tool_context)
    assert result["ok"] is True
    assert result["changed"] is True
    assert result["content"]["valid"] is True
    assert result["content"]["errors"] == []
    assert result["content"]["summary"] == "已搭好"
    start = next(node for node in tool_context.state.graph["nodes"] if node["id"] == "start")
    end = next(node for node in tool_context.state.graph["nodes"] if node["id"] == "end")
    assert start["position"]["x"] < end["position"]["x"]


def test_finish_hydrate_mutation_sets_changed_and_updates_graph(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_end()

    def hydrate(graph):
        updated = upsert_node(
            graph, node_id="start", node_type="start", title="已绑定", desc="", config={"variables": []}
        )
        return connect(updated, source="start", target="end")

    _set_env(tool_context, hydrate_graph=hydrate)
    result = dispatch(_call("finish", summary="已 hydrate"), tool_context)

    assert result["ok"] is True
    assert result["changed"] is True
    assert result["content"]["valid"] is True
    assert tool_context.state.candidate_revision == 2
    node = find_node(tool_context.state.graph, "start")
    assert node is not None
    assert node["data"]["title"] == "已绑定"


def test_finish_rejected_claim_does_not_fake_valid(tool_context: ToolContext) -> None:
    result = dispatch(_call("finish", summary="做好了"), tool_context)
    assert result["ok"] is False
    assert result["content"]["valid"] is False
    assert result["content"]["errors"]
    error = result["content"]["errors"][0]
    assert set(error) >= {"code", "node_id", "detail"}


def test_validate_graph_validator_exception_is_ok_false(tool_context: ToolContext, monkeypatch) -> None:
    def boom(**kwargs):
        raise RuntimeError("validator down")

    monkeypatch.setattr("core.workflow.generator.agent.tool_lifecycle.run_graph_validator", boom)
    result = dispatch(_call("validate_graph"), tool_context)
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["error_code"] == "CAPABILITY_UNAVAILABLE"


def test_finish_validator_exception_is_ok_false(tool_context: ToolContext, monkeypatch) -> None:
    tool_context.state.graph = _connected_start_end()

    def boom(**kwargs):
        raise RuntimeError("validator down")

    monkeypatch.setattr("core.workflow.generator.agent.tool_lifecycle.run_graph_validator", boom)
    result = dispatch(_call("finish", summary="做好了"), tool_context)
    assert result["ok"] is False
    assert result["error_code"] == "CAPABILITY_UNAVAILABLE"
    assert result["content"] is None


class _FakeAcceptanceRunner:
    def __init__(self, *, passed: bool = True, failed_nodes: list | None = None) -> None:
        self.passed = passed
        self.failed_nodes = failed_nodes or []
        self.calls: list[dict] = []

    def run(self, *, graph, revision, graph_hash, case_ids, mode):
        self.calls.append(
            {"revision": revision, "graph_hash": graph_hash, "case_ids": case_ids, "mode": mode, "graph": graph}
        )
        return [
            {
                "attempt_id": "att-1",
                "revision": revision,
                "graph_hash": graph_hash,
                "case_id": case_ids[0],
                "passed": self.passed,
                "status": "simulated" if mode == "simulated" else "succeeded",
                "failed_nodes": self.failed_nodes,
                "evidence": [],
                "trace_summary": "ok" if self.passed else "node failed",
                "unverified_nodes": ["llm"] if mode == "simulated" else [],
            }
        ]


def test_run_acceptance_without_runner_is_unavailable(tool_context: ToolContext) -> None:
    result = dispatch(_call("run_acceptance"), tool_context)
    assert result["ok"] is False
    assert result["error_code"] == "CAPABILITY_UNAVAILABLE"


def test_live_acceptance_without_consent_does_not_run(tool_context: ToolContext) -> None:
    runner = _FakeAcceptanceRunner()
    _set_env(tool_context, acceptance_runner=runner)
    result = dispatch(_call("run_acceptance", mode="live"), tool_context)
    assert result["ok"] is False
    assert result["error_code"] == "LIVE_RUN_REQUIRES_CONSENT"
    assert result["retryable"] is True
    assert runner.calls == []


def test_simulated_acceptance_stores_attempt_and_unverified_nodes(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_end()
    runner = _FakeAcceptanceRunner()
    _set_env(tool_context, acceptance_runner=runner)
    result = dispatch(_call("run_acceptance"), tool_context)
    assert result["ok"] is True
    assert result["content"]["passed"] is True
    assert result["content"]["mode"] == "simulated"
    assert result["content"]["unverified_nodes"] == ["llm"]
    assert result["content"]["attempt_id"] == "att-1"
    assert "att-1" in tool_context.state.attempts
    assert runner.calls[0]["mode"] == "simulated"


def test_inspect_attempt_returns_failed_nodes(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_end()
    runner = _FakeAcceptanceRunner(passed=False, failed_nodes=[{"id": "code-1", "type": "code", "error": "boom"}])
    _set_env(tool_context, acceptance_runner=runner)
    dispatch(_call("run_acceptance"), tool_context)
    result = dispatch(_call("inspect_attempt", attempt_id="att-1"), tool_context)
    assert result["ok"] is True
    assert result["content"]["failed_nodes"][0]["id"] == "code-1"


def test_inspect_attempt_unknown_id_is_invalid(tool_context: ToolContext) -> None:
    result = dispatch(_call("inspect_attempt", attempt_id="missing"), tool_context)
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert result["retryable"] is True


def test_finish_with_runner_rejects_without_evidence(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_end()
    _set_env(tool_context, acceptance_runner=_FakeAcceptanceRunner())
    result = dispatch(_call("finish", summary="已搭好"), tool_context)
    assert result["ok"] is False
    assert result["content"]["valid"] is True
    assert result["content"]["acceptance"]["reason"] == "NO_EVIDENCE"


def test_finish_with_runner_accepts_after_passing_acceptance(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_end()
    _set_env(tool_context, acceptance_runner=_FakeAcceptanceRunner())
    dispatch(_call("run_acceptance"), tool_context)
    result = dispatch(_call("finish", summary="已搭好"), tool_context)
    assert result["ok"] is True
    assert result["content"]["valid"] is True


def test_finish_with_runner_rejects_failed_acceptance(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_end()
    _set_env(
        tool_context,
        acceptance_runner=_FakeAcceptanceRunner(
            passed=False, failed_nodes=[{"id": "end", "type": "end", "error": "no output"}]
        ),
    )
    dispatch(_call("run_acceptance"), tool_context)
    result = dispatch(_call("finish", summary="好了"), tool_context)
    assert result["ok"] is False
    assert result["content"]["acceptance"]["reason"] == "ASSERTION_FAILED"
    assert result["content"]["acceptance"]["failed_nodes"][0]["id"] == "end"


def test_live_acceptance_with_consent_runs(tool_context: ToolContext) -> None:
    runner = _FakeAcceptanceRunner()
    _set_env(tool_context, acceptance_runner=runner)
    _set_env(tool_context, live_run_authorized=True)
    result = dispatch(_call("run_acceptance", mode="live"), tool_context)
    assert result["ok"] is True
    assert runner.calls[0]["mode"] == "live"
