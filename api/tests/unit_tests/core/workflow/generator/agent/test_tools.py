from copy import deepcopy
from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from core.workflow.generator.acceptance.evidence import canonical_graph_hash
from core.workflow.generator.agent.tools.tool_build_tool import CompiledToolNode
from core.workflow.generator.agent.tools.tool_mutate import CompiledBuildNode, pending_plan_nodes_from_calls
from core.workflow.generator.agent.tools.tools import (
    RETRYABLE_BY_ERROR_CODE,
    PendingPlanNode,
    ToolContext,
    commit_build_node,
    compile_build_node,
    compile_build_tool_node,
    dispatch,
    relayout_graph,
)
from core.workflow.generator.agent.types import ToolCall
from core.workflow.generator.graph.graph_ops import connect, empty_graph, find_node, upsert_node
from tests.unit_tests.core.workflow.generator.node_fixtures import builder_config, node_config


def _set_env(context: ToolContext, **changes: object) -> None:
    context.env = replace(context.env, **changes)


def _call(name: str, **arguments: object) -> ToolCall:
    return {"id": "c1", "name": name, "arguments": arguments}


def _intent(objective: str, *outputs: str, inputs: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "objective": objective,
        "inputs": inputs or [],
        "outputs": [{"name": name} for name in outputs],
    }


def _connected_start_end():
    graph = upsert_node(
        empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={"variables": []}
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
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
        _call("build_node", mode="update", id="kr", type="llm", intent=_intent("改成 LLM")),
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
        _call("build_node", mode="create", id="kr", type="llm", title="评判", intent=_intent("新建")),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "NODE_EXISTS"
    assert result["changed"] is False


def test_disconnect_noop_when_edge_absent(tool_context) -> None:
    tool_context.state.graph = upsert_node(empty_graph(), node_id="a", node_type="start", title="A", desc="", config={})
    tool_context.state.graph = upsert_node(
        tool_context.state.graph, node_id="b", node_type="end", title="B", desc="", config=node_config("end")
    )
    result = dispatch(_call("disconnect", source="a", target="b"), tool_context)
    assert result["ok"] is True
    assert result["changed"] is False
    assert result["content"]["reason"] == "edge_not_present"


def test_disconnect_ambiguous_without_handle(tool_context) -> None:
    graph = upsert_node(empty_graph(), node_id="a", node_type="if-else", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config=node_config("end"))
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
    assert RETRYABLE_BY_ERROR_CODE["DUPLICATE_BATCH_NODE_ID"] is True
    assert RETRYABLE_BY_ERROR_CODE["AMBIGUOUS_EDGE"] is True
    assert RETRYABLE_BY_ERROR_CODE["INVALID_ARGUMENT"] is True
    assert RETRYABLE_BY_ERROR_CODE["TYPE_UNCHANGED_USE_UPDATE"] is True
    assert RETRYABLE_BY_ERROR_CODE["UNKNOWN_DATASET"] is True
    assert RETRYABLE_BY_ERROR_CODE["UNKNOWN_TOOL"] is True
    assert RETRYABLE_BY_ERROR_CODE["UNKNOWN_NODE_REFERENCE"] is True
    assert RETRYABLE_BY_ERROR_CODE["UNKNOWN_SKILL"] is True
    assert RETRYABLE_BY_ERROR_CODE["INVALID_CODE_OUTPUT"] is True
    assert RETRYABLE_BY_ERROR_CODE["INVALID_END_OUTPUT"] is True
    assert RETRYABLE_BY_ERROR_CODE["INVALID_AGENT_NODE"] is True
    assert RETRYABLE_BY_ERROR_CODE["AGENT_BINDING_MISSING"] is True
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
        tool_context.state.graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end")
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
        _call("build_node", mode="replace", id="kr", type="knowledge-retrieval", intent=_intent("重建")),
        tool_context,
    )
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["error_code"] == "TYPE_UNCHANGED_USE_UPDATE"
    assert result["retryable"] is True


def test_disconnect_with_handle_removes_only_that_edge(tool_context: ToolContext) -> None:
    graph = upsert_node(empty_graph(), node_id="a", node_type="if-else", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config=node_config("end"))
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


def test_inspect_node_schema_knowledge_retrieval_describes_all_retrieval_modes(tool_context: ToolContext) -> None:
    result = dispatch(_call("inspect_node_schema", node_type="knowledge-retrieval"), tool_context)
    snippet = str(result["content"]["snippet"])

    assert result["ok"] is True
    assert result["changed"] is False
    assert "query_variable_selector" in snippet
    assert "query_attachment_selector" in snippet
    assert "single_retrieval_config" in snippet
    assert "reranking_model" in snippet
    assert "weighted_score" in snippet
    assert "weights" in snippet
    assert "metadata_filtering_mode" in snippet
    assert "result" in snippet


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
        return {"config": builder_config(messages, self.config)}


class _ExplodingLLM:
    def iter_json(self, *, messages, stage):
        raise AssertionError("Tool compilation must not call the node-builder LLM")


def _image_tool_entry() -> dict[str, object]:
    return {
        "provider_name": "image/provider",
        "provider_type": "builtin",
        "plugin_id": "image/provider",
        "tool_name": "generate",
        "tool_label": "Generate",
        "description": "Generate an image",
        "parameters": (
            {"name": "prompt", "type": "string", "form": "llm", "required": True},
            {"name": "image", "type": "file", "form": "llm", "required": False},
            {"name": "size", "type": "select", "form": "form", "required": False, "default": "2K"},
        ),
        "parameter_names": ("prompt", "image", "size"),
        "output_names": ("files",),
    }


def _image_tool_arguments(*, selector: list[str] | None = None) -> dict[str, object]:
    arguments: dict[str, object] = {"prompt": {"kind": "constant", "value": "draw it"}}
    if selector is not None:
        arguments["image"] = {"kind": "variable", "selector": selector}
    return arguments


def _image_tool_node_kwargs(
    *,
    mode: str = "create",
    node_id: str = "tool_1",
    title: str = "生成",
    selector: list[str] | None = None,
    parent: str | None = None,
    arguments: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "mode": mode,
        "id": node_id,
        "tool": {"provider_name": "image/provider", "tool_name": "generate"},
        "arguments": arguments if arguments is not None else _image_tool_arguments(selector=selector),
    }
    if title is not None:
        payload["title"] = title
    if parent is not None:
        payload["parent"] = parent
    return payload


def test_tool_build_compiles_without_calling_builder_llm(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="开始",
        desc="",
        config={"variables": [{"variable": "image", "type": "file"}]},
    )
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("image/provider", "generate")},
        tool_entries=[_image_tool_entry()],
        llm_client=_ExplodingLLM(),
    )

    result = dispatch(
        _call("build_tool_node", **_image_tool_node_kwargs(selector=["start", "image"])),
        tool_context,
    )

    assert result["ok"] is True
    node = find_node(tool_context.state.graph, "tool_1")
    assert node is not None
    assert node["data"]["tool_parameters"] == {
        "prompt": {"type": "constant", "value": "draw it"},
        "image": {"type": "variable", "value": ["start", "image"]},
        "size": {"type": "constant", "value": "2K"},
    }


def test_tool_build_unknown_output_returns_bounded_selector_candidates(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="开始",
        desc="",
        config={
            "variables": [
                {"variable": "image", "type": "file"},
                {"variable": "query", "type": "paragraph"},
            ]
        },
    )
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("image/provider", "generate")},
        tool_entries=[_image_tool_entry()],
        llm_client=_ExplodingLLM(),
    )

    result = dispatch(
        _call("build_tool_node", **_image_tool_node_kwargs(selector=["start", "missing"])),
        tool_context,
    )

    assert result["error_code"] == "UNKNOWN_OUTPUT"
    assert result["cause"] == {
        "error_code": "UNKNOWN_OUTPUT",
        "error": "变量未声明",
        "selector": ["start", "missing"],
        "available_outputs": ["image", "query"],
    }


def test_invalid_tool_update_is_atomic_and_does_not_call_builder_llm(tool_context: ToolContext) -> None:
    config = {
        "provider_id": "image/provider",
        "provider_name": "image/provider",
        "provider_type": "builtin",
        "tool_name": "generate",
        "tool_label": "Generate",
        "tool_node_version": "2",
        "tool_parameters": {
            "prompt": {"type": "constant", "value": "old"},
            "size": {"type": "constant", "value": "1K"},
        },
        "tool_configurations": {"size": "1K"},
    }
    tool_context.state.graph = upsert_node(
        empty_graph(), node_id="tool_1", node_type="tool", title="生成", desc="", config=config
    )
    before = deepcopy(tool_context.state.graph)
    tool_context.state.graph_hash = canonical_graph_hash(tool_context.state.graph)
    revision_before = tool_context.state.candidate_revision
    hash_before = tool_context.state.graph_hash
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("image/provider", "generate")},
        tool_entries=[_image_tool_entry()],
        llm_client=_ExplodingLLM(),
    )

    result = dispatch(
        _call(
            "build_tool_node",
            **_image_tool_node_kwargs(
                mode="update",
                title="生成",
                selector=["missing", "image"],
            ),
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_NODE_REFERENCE"
    assert result["changed"] is False
    assert tool_context.state.graph == before
    assert tool_context.state.candidate_revision == revision_before
    assert tool_context.state.graph_hash == hash_before

    repaired = dispatch(
        _call("build_tool_node", **_image_tool_node_kwargs(mode="update", title="生成")),
        tool_context,
    )

    assert repaired["ok"] is True
    assert tool_context.state.candidate_revision == revision_before
    node = find_node(tool_context.state.graph, "tool_1")
    assert node is not None
    assert node["data"]["tool_parameters"]["prompt"] == {"type": "constant", "value": "draw it"}


def test_tool_build_unknown_schema_returns_structured_capability_observation(tool_context: ToolContext) -> None:
    entry = _image_tool_entry()
    del entry["parameters"]
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("image/provider", "generate")},
        tool_entries=[entry],
        llm_client=_ExplodingLLM(),
    )

    result = dispatch(
        _call("build_tool_node", **_image_tool_node_kwargs(title="Generate")),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "CAPABILITY_UNAVAILABLE"
    assert result["content"] is None
    assert find_node(tool_context.state.graph, "tool_1") is None


def test_unexpected_tool_compiler_exception_becomes_observation_without_commit(
    tool_context: ToolContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(**kwargs: object) -> dict[str, object]:
        raise RuntimeError("internal compiler failure")

    monkeypatch.setattr("core.workflow.generator.agent.tools.tool_build_tool.compile_tool_node_config", boom)
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("image/provider", "generate")},
        tool_entries=[_image_tool_entry()],
        llm_client=_ExplodingLLM(),
    )

    result = dispatch(
        _call("build_tool_node", **_image_tool_node_kwargs(title="Generate")),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "CAPABILITY_UNAVAILABLE"
    assert result["error"] == "Tool compiler failed"
    assert find_node(tool_context.state.graph, "tool_1") is None


def _tool_graph(parameters: dict[str, object]):
    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="Start", desc="", config={})
    graph = upsert_node(
        graph,
        node_id="tool_1",
        node_type="tool",
        title="Generate",
        desc="",
        config={
            "provider_id": "image/provider",
            "provider_name": "image/provider",
            "provider_type": "builtin",
            "tool_name": "generate",
            "tool_label": "Generate",
            "tool_parameters": parameters,
            "tool_configurations": {},
        },
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="End", desc="", config=node_config("end"))
    return connect(connect(graph, source="start", target="tool_1"), source="tool_1", target="end")


def test_agent_validation_uses_complete_tool_schema_for_required_parameters(tool_context: ToolContext) -> None:
    tool_context.state.graph = _tool_graph({})
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("image/provider", "generate")},
        tool_entries=[_image_tool_entry()],
    )

    result = dispatch(_call("validate_graph"), tool_context)

    assert result["ok"] is True
    assert result["content"]["valid"] is False
    assert any(
        issue["code"] == "INVALID_NODE_CONFIG" and "prompt" in issue["detail"] for issue in result["content"]["errors"]
    )


def test_agent_relayout_uses_tool_schema_defaults(tool_context: ToolContext) -> None:
    tool_context.state.graph = _tool_graph({"prompt": {"type": "constant", "value": "draw"}})
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("image/provider", "generate")},
        tool_entries=[_image_tool_entry()],
    )

    relayout_graph(tool_context)

    node = find_node(tool_context.state.graph, "tool_1")
    assert node is not None
    assert node["data"]["tool_parameters"]["size"] == {"type": "constant", "value": "2K"}


def test_update_omitting_title_and_parent_keeps_old(tool_context: ToolContext) -> None:
    graph = upsert_node(empty_graph(), node_id="iter1", node_type="iteration", title="循环", desc="", config={})
    graph = upsert_node(
        graph, node_id="kr", node_type="knowledge-retrieval", title="检索", desc="", config={"dataset_ids": ["ds-1"]}
    )
    graph["nodes"][1]["parentId"] = "iter1"
    tool_context.state.graph = graph
    _set_env(
        tool_context,
        llm_client=_FakeLLM(
            {
                "dataset_ids": ["ds-2"],
                "query_variable_selector": ["start", "query"],
                "retrieval_mode": "multiple",
                "multiple_retrieval_config": {"top_k": 3, "reranking_enable": False},
            }
        ),
    )

    result = dispatch(_call("build_node", mode="update", id="kr", intent=_intent("换库")), tool_context)
    node = find_node(tool_context.state.graph, "kr")

    assert result["ok"] is True
    assert result["changed"] is True
    assert "config" not in result["content"]
    assert "nodes" not in result["content"]
    assert "dataset_binding" in result["content"]["effects"]
    assert node is not None
    assert node["data"]["title"] == "检索"
    assert node.get("parentId") == "iter1"


def test_build_node_rejects_runtime_unsafe_id(tool_context: ToolContext) -> None:
    result = dispatch(
        _call("build_node", mode="create", id="node-1", type="llm", title="模型", intent=_intent("回答")),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_NODE_ID"
    assert find_node(tool_context.state.graph, "node-1") is None


def test_compile_build_node_does_not_write_graph_until_commit(tool_context: ToolContext) -> None:
    _set_env(tool_context, llm_client=_FakeLLM({}))
    call = _call("build_node", mode="create", id="llm1", type="llm", title="模型", intent=_intent("写一段说明"))
    before = len(tool_context.state.graph["nodes"])

    compiled = compile_build_node(call, tool_context)

    assert find_node(tool_context.state.graph, "llm1") is None
    assert len(tool_context.state.graph["nodes"]) == before

    result = commit_build_node(compiled, tool_context)

    assert result["ok"] is True
    assert result["changed"] is True
    assert find_node(tool_context.state.graph, "llm1") is not None


def test_create_runtime_valid_llm_with_empty_prompt_does_not_commit(tool_context: ToolContext) -> None:
    _set_env(tool_context, llm_client=_FakeLLM({"prompt_template": [{"role": "user", "text": "  "}]}))
    before = deepcopy(tool_context.state.graph)
    revision_before = tool_context.state.candidate_revision

    result = dispatch(
        _call("build_node", mode="create", id="llm1", type="llm", title="模型", intent=_intent("总结输入")),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_NODE_CONFIG"
    assert result["changed"] is False
    assert "prompt_template" in str(result["error"])
    assert tool_context.state.graph == before
    assert tool_context.state.candidate_revision == revision_before


def test_failed_empty_llm_create_can_be_repaired_with_same_id(tool_context: ToolContext) -> None:
    call = _call("build_node", mode="create", id="llm1", type="llm", title="模型", intent=_intent("总结输入"))
    _set_env(tool_context, llm_client=_FakeLLM({"prompt_template": [{"role": "user", "text": ""}]}))

    failed = dispatch(call, tool_context)

    _set_env(
        tool_context,
        llm_client=_FakeLLM({"prompt_template": [{"role": "user", "text": "总结输入。"}]}),
    )
    repaired = dispatch(call, tool_context)

    assert failed["ok"] is False
    assert repaired["ok"] is True
    assert repaired["changed"] is True
    node = find_node(tool_context.state.graph, "llm1")
    assert node is not None
    assert node["data"]["prompt_template"][0]["text"] == "总结输入。"


def test_update_runtime_valid_http_with_empty_url_is_atomic(tool_context: ToolContext) -> None:
    old_config = {
        "method": "get",
        "url": "https://example.com/old",
        "authorization": {"type": "no-auth", "config": None},
        "headers": "",
        "params": "",
        "body": {"type": "none", "data": []},
    }
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="request",
        node_type="http-request",
        title="请求",
        desc="",
        config=old_config,
    )
    tool_context.state.graph_hash = canonical_graph_hash(tool_context.state.graph)
    graph_before = deepcopy(tool_context.state.graph)
    revision_before = tool_context.state.candidate_revision
    hash_before = tool_context.state.graph_hash
    invalid_config = {**old_config, "url": "  "}
    _set_env(tool_context, llm_client=_FakeLLM(invalid_config))

    result = dispatch(_call("build_node", mode="update", id="request", intent=_intent("更换请求地址")), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_NODE_CONFIG"
    assert result["changed"] is False
    assert "url" in str(result["error"])
    assert tool_context.state.graph == graph_before
    assert tool_context.state.candidate_revision == revision_before
    assert tool_context.state.graph_hash == hash_before


def test_create_invalid_code_output_does_not_commit(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        llm_client=_FakeLLM({"outputs": {"questions": {"type": "array"}}}),
    )
    result = dispatch(
        _call("build_node", mode="create", id="node_parse", type="code", title="解析", intent=_intent("解析问题")),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_CODE_OUTPUT"
    assert result["retryable"] is True
    assert "questions" in str(result["error"])
    assert "'array'" in str(result["error"])
    assert find_node(tool_context.state.graph, "node_parse") is None


def test_update_invalid_code_output_keeps_old_config(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="node_parse",
        node_type="code",
        title="解析",
        desc="",
        config={"outputs": {"questions": {"type": "array[object]"}}},
    )
    _set_env(
        tool_context,
        llm_client=_FakeLLM({"outputs": {"questions": {"type": "array"}}}),
    )
    result = dispatch(_call("build_node", mode="update", id="node_parse", intent=_intent("改输出类型")), tool_context)
    node = find_node(tool_context.state.graph, "node_parse")
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_CODE_OUTPUT"
    assert result["retryable"] is True
    assert node is not None
    assert node["data"]["outputs"]["questions"]["type"] == "array[object]"


def test_create_incomplete_code_does_not_commit(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        llm_client=_FakeLLM(
            {
                "variables": [],
                "code_language": "python3",
                "code": "  ",
                "outputs": {"result": {"type": "string", "children": None}},
            }
        ),
    )

    result = dispatch(
        _call("build_node", mode="create", id="node_code", type="code", title="执行代码", intent=_intent("执行代码")),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_NODE_CONFIG"
    assert result["retryable"] is True
    assert "code" in str(result["error"])
    assert find_node(tool_context.state.graph, "node_code") is None


def test_update_incomplete_code_binding_keeps_old_config(tool_context: ToolContext) -> None:
    old_config = {
        "variables": [{"variable": "query", "value_selector": ["start", "query"]}],
        "code_language": "python3",
        "code": "def main(query: str):\n    return {'result': query}",
        "outputs": {"result": {"type": "string", "children": None}},
    }
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="node_code",
        node_type="code",
        title="执行代码",
        desc="",
        config=old_config,
    )
    graph_before = deepcopy(tool_context.state.graph)
    _set_env(
        tool_context,
        llm_client=_FakeLLM(
            {
                **old_config,
                "variables": [{"variable": "query", "value_selector": []}],
            }
        ),
    )

    result = dispatch(
        _call("build_node", mode="update", id="node_code", intent=_intent("更换输入")),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_NODE_CONFIG"
    assert "variables[0].value_selector" in str(result["error"])
    assert tool_context.state.graph == graph_before


def test_create_incomplete_template_transform_does_not_commit(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        llm_client=_FakeLLM(
            {
                "template": "你好 {{ name }}",
                "variables": [{"variable": "name", "value_selector": ["start"]}],
            }
        ),
    )

    result = dispatch(
        _call(
            "build_node",
            mode="create",
            id="node_template",
            type="template-transform",
            title="模板转换",
            intent=_intent("拼接问候"),
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_NODE_CONFIG"
    assert result["retryable"] is True
    assert "variables[0].value_selector" in str(result["error"])
    assert find_node(tool_context.state.graph, "node_template") is None


def test_update_incomplete_template_transform_keeps_old_config(tool_context: ToolContext) -> None:
    old_config = {
        "template": "你好 {{ name }}",
        "variables": [{"variable": "name", "value_selector": ["start", "name"]}],
    }
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="node_template",
        node_type="template-transform",
        title="模板转换",
        desc="",
        config=old_config,
    )
    graph_before = deepcopy(tool_context.state.graph)
    _set_env(
        tool_context,
        llm_client=_FakeLLM(
            {
                **old_config,
                "variables": [
                    {"variable": "name", "value_selector": ["start", "name"]},
                    {"variable": "name", "value_selector": ["start", "other"]},
                ],
            }
        ),
    )

    result = dispatch(
        _call("build_node", mode="update", id="node_template", intent=_intent("增加变量")),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_NODE_CONFIG"
    assert "variables[1].variable" in str(result["error"])
    assert tool_context.state.graph == graph_before


def test_create_strips_invented_agent_binding_ids(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        llm_client=_FakeLLM(
            {
                "version": "2",
                "agent_node_kind": "dify_agent",
                "agent_task": "调查问题",
                "agent_binding": {
                    "binding_type": "inline_agent",
                    "agent_id": "fake-agent",
                    "current_snapshot_id": "fake-snap",
                },
                "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
            }
        ),
    )
    result = dispatch(
        _call("build_node", mode="create", id="agent_1", type="agent", title="助手", intent=_intent("调查")),
        tool_context,
    )
    node = find_node(tool_context.state.graph, "agent_1")
    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert node is None


def _hydrated_agent_config() -> dict:
    return {
        "version": "2",
        "agent_node_kind": "dify_agent",
        "agent_task": "调查问题",
        "agent_binding": {
            "binding_type": "inline_agent",
            "agent_id": "real-agent",
            "current_snapshot_id": "real-snap",
        },
        "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
    }


def _many_tool_entries() -> list[dict[str, object]]:
    return [
        {
            "provider_name": f"provider-{index:03d}",
            "provider_type": "builtin",
            "plugin_id": "",
            "tool_name": f"tool-{index:03d}",
            "tool_label": f"Tool {index:03d}",
            "description": f"Capability needle-{index:03d} " + "long description " * 10,
            "parameters": tuple(
                {
                    "name": f"argument_{item}",
                    "type": "string",
                    "form": "llm",
                    "required": False,
                    "description": "long parameter description " * 8,
                }
                for item in range(4)
            ),
        }
        for index in range(100)
    ]


class _CaptureAgentBuilderLLM:
    def __init__(self, config: dict[str, object]) -> None:
        self.config = config
        self.prompts: list[str] = []

    def iter_json(self, *, messages, stage):
        self.prompts.append("\n".join(str(message.content) for message in messages))
        yield from ()
        return {"config": builder_config(messages, self.config)}


def _agent_config_with_tool(provider_name: str, tool_name: str) -> dict[str, object]:
    config = _hydrated_agent_config()
    config["agent_binding"] = {"binding_type": "inline_agent"}
    config["dify_tools"] = [
        {
            "provider_type": "builtin",
            "provider_id": provider_name,
            "tool_name": tool_name,
            "credential_type": "unauthorized",
        }
    ]
    return config


def test_agent_builder_receives_only_explicitly_selected_tool_from_uncapped_snapshot(
    tool_context: ToolContext,
) -> None:
    entries = _many_tool_entries()
    target = entries[-1]
    client = _CaptureAgentBuilderLLM(_agent_config_with_tool(str(target["provider_name"]), str(target["tool_name"])))
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={(str(entry["provider_name"]), str(entry["tool_name"])) for entry in entries},
        tool_entries=entries,
        llm_client=client,
    )

    search = dispatch(_call("search_tools", query="needle-099"), tool_context)
    result = dispatch(
        _call(
            "build_node",
            mode="create",
            id="agent_1",
            type="agent",
            title="Agent",
            intent={
                "objective": "Use the selected capability",
                "tool_bindings": [
                    {
                        "provider_name": target["provider_name"],
                        "tool_name": target["tool_name"],
                    }
                ],
            },
        ),
        tool_context,
    )

    assert search["content"]["hits"][0]["binding"] == {
        "provider_name": "provider-099",
        "tool_name": "tool-099",
    }
    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert result["changed"] is False


def test_agent_builder_without_tool_bindings_has_no_available_tools_section(tool_context: ToolContext) -> None:
    client = _CaptureAgentBuilderLLM(_agent_config_with_tool("unused", "unused"))
    client.config.pop("dify_tools")
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("provider-000", "tool-000")},
        tool_entries=_many_tool_entries(),
        llm_client=client,
    )

    result = dispatch(
        _call(
            "build_node",
            mode="create",
            id="agent_1",
            type="agent",
            title="Agent",
            intent={"objective": "Answer without tools"},
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"


def _agent_knowledge_intent(*dataset_ids: str, operation: str = "replace") -> dict[str, object]:
    knowledge: dict[str, object] = {"operation": operation}
    if operation == "replace":
        knowledge["sets"] = [{"name": "Product docs", "dataset_ids": list(dataset_ids)}]
    return {"objective": "Answer with internal knowledge", "agent_knowledge": knowledge}


def test_agent_knowledge_is_compiled_after_builder_output_is_discarded(tool_context: ToolContext) -> None:
    builder_config = _hydrated_agent_config()
    builder_config["agent_binding"] = {"binding_type": "inline_agent"}
    builder_config["knowledge"] = {"sets": []}
    _set_env(
        tool_context,
        knowledge_available=True,
        installed_dataset_ids={"ds-live"},
        knowledge_entries=[{"id": "ds-live", "name": "Live", "description": "Live docs"}],
        llm_client=_FakeLLM(builder_config),
    )

    result = dispatch(
        _call(
            "build_node",
            mode="create",
            id="agent_1",
            type="agent",
            title="Agent",
            intent=_agent_knowledge_intent("ds-live"),
        ),
        tool_context,
    )

    node = find_node(tool_context.state.graph, "agent_1")
    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert node is None


def test_agent_update_without_knowledge_intent_preserves_old_projection(tool_context: ToolContext) -> None:
    old_config = _hydrated_agent_config()
    old_config["knowledge"] = {
        "sets": [
            {
                "id": "ks-old",
                "name": "Old",
                "datasets": [{"id": "ds-old"}],
                "query": {"mode": "generated_query"},
                "retrieval": {"mode": "multiple", "top_k": 4, "reranking_enable": False},
            }
        ]
    }
    tool_context.state.graph = upsert_node(
        empty_graph(), node_id="agent_1", node_type="agent", title="Agent", desc="", config=old_config
    )
    builder_config = _hydrated_agent_config()
    builder_config["agent_task"] = "更新任务"
    builder_config["knowledge"] = {"sets": []}
    _set_env(tool_context, llm_client=_FakeLLM(builder_config))

    result = dispatch(_call("build_node", mode="update", id="agent_1", intent=_intent("更新任务")), tool_context)

    node = find_node(tool_context.state.graph, "agent_1")
    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert node is not None
    assert node["data"]["knowledge"] == old_config["knowledge"]


def test_agent_create_without_knowledge_intent_drops_builder_knowledge(tool_context: ToolContext) -> None:
    builder_config = _hydrated_agent_config()
    builder_config["agent_binding"] = {"binding_type": "inline_agent"}
    builder_config["knowledge"] = {"sets": []}
    _set_env(tool_context, llm_client=_FakeLLM(builder_config))

    result = dispatch(
        _call("build_node", mode="create", id="agent_1", type="agent", title="Agent", intent=_intent("Answer")),
        tool_context,
    )

    node = find_node(tool_context.state.graph, "agent_1")
    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert node is None


def test_agent_knowledge_clear_writes_empty_sets(tool_context: ToolContext) -> None:
    builder_config = _hydrated_agent_config()
    builder_config["agent_binding"] = {"binding_type": "inline_agent"}
    _set_env(
        tool_context,
        knowledge_available=True,
        installed_dataset_ids=set(),
        knowledge_entries=[],
        llm_client=_FakeLLM(builder_config),
    )

    result = dispatch(
        _call(
            "build_node",
            mode="create",
            id="agent_1",
            type="agent",
            title="Agent",
            intent=_agent_knowledge_intent(operation="clear"),
        ),
        tool_context,
    )

    node = find_node(tool_context.state.graph, "agent_1")
    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert node is None


def test_unknown_agent_knowledge_dataset_is_rejected_before_builder(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        knowledge_available=True,
        installed_dataset_ids={"ds-live"},
        knowledge_entries=[{"id": "ds-live", "name": "Live", "description": ""}],
        llm_client=_ExplodingLLM(),
    )

    result = dispatch(
        _call(
            "build_node",
            mode="create",
            id="agent_1",
            type="agent",
            title="Agent",
            intent=_agent_knowledge_intent("ds-stale"),
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert find_node(tool_context.state.graph, "agent_1") is None


def test_agent_knowledge_preflight_uses_catalogue_entries_as_the_authoritative_snapshot(
    tool_context: ToolContext,
) -> None:
    _set_env(
        tool_context,
        knowledge_available=True,
        installed_dataset_ids={"ds-stale"},
        knowledge_entries=[],
        llm_client=_ExplodingLLM(),
    )

    result = dispatch(
        _call(
            "build_node",
            mode="create",
            id="agent_1",
            type="agent",
            title="Agent",
            intent=_agent_knowledge_intent("ds-stale"),
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert find_node(tool_context.state.graph, "agent_1") is None


def test_explicit_agent_knowledge_requires_available_catalogue(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        knowledge_available=False,
        installed_dataset_ids=None,
        knowledge_entries=[],
        llm_client=_ExplodingLLM(),
    )

    result = dispatch(
        _call(
            "build_node",
            mode="create",
            id="agent_1",
            type="agent",
            title="Agent",
            intent=_agent_knowledge_intent("ds-live"),
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert find_node(tool_context.state.graph, "agent_1") is None


def test_unknown_agent_tool_binding_is_rejected_before_builder_and_commit(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("provider-000", "tool-000")},
        tool_entries=_many_tool_entries(),
        llm_client=_ExplodingLLM(),
    )

    result = dispatch(
        _call(
            "build_node",
            mode="create",
            id="agent_1",
            type="agent",
            title="Agent",
            intent={
                "objective": "Use a missing tool",
                "tool_bindings": [{"provider_name": "missing", "tool_name": "tool"}],
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert find_node(tool_context.state.graph, "agent_1") is None


def test_update_keeps_trusted_agent_binding_ids(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="agent_1",
        node_type="agent",
        title="助手",
        desc="",
        config=_hydrated_agent_config(),
    )
    _set_env(
        tool_context,
        llm_client=_FakeLLM(
            {
                "version": "2",
                "agent_node_kind": "dify_agent",
                "agent_task": "改写任务",
                "agent_binding": {
                    "binding_type": "inline_agent",
                    "agent_id": "fake-agent",
                    "current_snapshot_id": "fake-snap",
                },
                "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
            }
        ),
    )
    result = dispatch(_call("build_node", mode="update", id="agent_1", intent=_intent("改任务")), tool_context)
    node = find_node(tool_context.state.graph, "agent_1")
    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert node is not None
    assert node["data"]["agent_binding"]["agent_id"] == "real-agent"


def test_create_invalid_agent_node_does_not_commit(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        llm_client=_FakeLLM(
            {
                "agent_task": "调查问题",
                "agent_binding": {"binding_type": "inline_agent"},
            }
        ),
    )
    result = dispatch(
        _call("build_node", mode="create", id="agent_1", type="agent", title="助手", intent=_intent("调查")),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert result["retryable"] is True
    assert find_node(tool_context.state.graph, "agent_1") is None


def test_short_objective_is_accepted(tool_context: ToolContext) -> None:
    _set_env(tool_context, llm_client=_FakeLLM({}))
    result = dispatch(
        _call("build_node", mode="create", id="llm1", type="llm", title="模型", intent=_intent("换库")),
        tool_context,
    )
    assert result["ok"] is True
    assert result["error_code"] is None
    assert find_node(tool_context.state.graph, "llm1") is not None


def test_pending_plan_outputs_come_directly_from_structured_intent() -> None:
    pending = pending_plan_nodes_from_calls(
        [
            _call(
                "build_node",
                mode="create",
                id="parse",
                type="code",
                title="Parse",
                intent=_intent("parse the payload", "query", "files"),
            )
        ]
    )

    assert pending[0].purpose == "parse the payload"
    assert pending[0].provisional_outputs == ("query", "files")


class _RecordingLLM:
    def __init__(self) -> None:
        self.user_prompts: list[str] = []

    def iter_json(self, *, messages, stage):
        self.user_prompts.append(str(messages[-1].content))
        yield from ()
        return {
            "config": builder_config(
                messages,
                {"prompt_template": [{"role": "user", "text": "{{#start.query#}}"}]},
            )
        }


def test_pending_start_outputs_appear_in_sibling_builder_plan(tool_context: ToolContext) -> None:
    import json

    client = _RecordingLLM()
    _set_env(tool_context, llm_client=client)
    start_purpose = (
        "Objective: accept the user's search question. Inputs: none Outputs: query "
        "Behavior: one required paragraph input. Variable references: none "
        "Resource bindings: none Configuration constraints: variable=query, required=true "
        "Fields to preserve: none"
    )
    tool_context.state.pending_plan_nodes = (
        PendingPlanNode(
            id="start",
            type="start",
            title="开始",
            purpose=start_purpose,
            parent=None,
            provisional_outputs=("query",),
        ),
        PendingPlanNode(
            id="llm1",
            type="llm",
            title="回答",
            purpose="answer the query",
            parent=None,
            provisional_outputs=("text",),
        ),
    )
    compiled = compile_build_node(
        _call(
            "build_node",
            mode="create",
            id="llm1",
            type="llm",
            title="回答",
            intent=_intent(
                "answer the query",
                "text",
                inputs=[{"source": ["start", "query"], "role": "query"}],
            ),
        ),
        tool_context,
    )
    assert isinstance(compiled, CompiledBuildNode)
    marker = "# Normalized plan and topology"
    _, _, rest = client.user_prompts[0].partition(marker)
    plan = json.loads(rest.strip().split("\n\n", 1)[0])
    start = next(node for node in plan["nodes"] if node["id"] == "start")
    assert start["outputs"] == ["query"]
    assert start["outputs_kind"] == "provisional"


def test_tool_compile_accepts_a_variable_from_a_same_batch_sibling(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("image/provider", "generate")},
        tool_entries=[_image_tool_entry()],
        llm_client=_ExplodingLLM(),
    )
    tool_context.state.pending_plan_nodes = (
        PendingPlanNode(
            id="describe",
            type="llm",
            title="Describe",
            purpose="describe the image",
            parent=None,
            provisional_outputs=("text",),
        ),
        PendingPlanNode(
            id="generate",
            type="tool",
            title="Generate",
            purpose="generate the image",
            parent=None,
            provisional_outputs=("files",),
        ),
    )

    compiled = compile_build_tool_node(
        _call(
            "build_tool_node",
            mode="create",
            id="generate",
            title="Generate",
            tool={"provider_name": "image/provider", "tool_name": "generate"},
            arguments={"prompt": {"kind": "variable", "selector": ["describe", "text"]}},
        ),
        tool_context,
    )

    assert isinstance(compiled, CompiledToolNode)
    assert compiled.config["tool_parameters"]["prompt"] == {
        "type": "variable",
        "value": ["describe", "text"],
    }


def test_tool_compile_preserves_nested_iteration_item_selector(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="iteration",
        node_type="iteration",
        title="Iteration",
        desc="",
        config={"iterator_input_type": "array[file]"},
    )
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("image/provider", "generate")},
        tool_entries=[_image_tool_entry()],
        llm_client=_ExplodingLLM(),
    )

    compiled = compile_build_tool_node(
        _call(
            "build_tool_node",
            **_image_tool_node_kwargs(
                node_id="generate",
                title="Generate",
                parent="iteration",
                selector=["iteration", "item", "source_image"],
            ),
        ),
        tool_context,
    )

    assert isinstance(compiled, CompiledToolNode)
    assert compiled.config["tool_parameters"]["image"] == {
        "type": "variable",
        "value": ["iteration", "item", "source_image"],
    }


def test_tool_compile_accepts_pending_iteration_item_from_a_child(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("image/provider", "generate")},
        tool_entries=[_image_tool_entry()],
        llm_client=_ExplodingLLM(),
    )
    tool_context.state.pending_plan_nodes = (
        PendingPlanNode(
            id="iteration",
            type="iteration",
            title="Iteration",
            purpose="iterate images",
            parent=None,
            provisional_outputs=("output",),
            iterator_input_type="array[file]",
        ),
        PendingPlanNode(
            id="generate",
            type="tool",
            title="Generate",
            purpose="generate the image",
            parent="iteration",
            provisional_outputs=("files",),
        ),
    )

    compiled = compile_build_tool_node(
        _call(
            "build_tool_node",
            **_image_tool_node_kwargs(
                node_id="generate",
                title="Generate",
                parent="iteration",
                selector=["iteration", "item", "source_image"],
            ),
        ),
        tool_context,
    )

    assert isinstance(compiled, CompiledToolNode)
    assert compiled.config["tool_parameters"]["image"] == {
        "type": "variable",
        "value": ["iteration", "item", "source_image"],
    }


def test_tool_compile_rejects_pending_iteration_item_from_outside_the_container(
    tool_context: ToolContext,
) -> None:
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("image/provider", "generate")},
        tool_entries=[_image_tool_entry()],
        llm_client=_ExplodingLLM(),
    )
    tool_context.state.pending_plan_nodes = (
        PendingPlanNode(
            id="iteration",
            type="iteration",
            title="Iteration",
            purpose="iterate images",
            parent=None,
            provisional_outputs=("output",),
        ),
        PendingPlanNode(
            id="generate",
            type="tool",
            title="Generate",
            purpose="generate the image",
            parent=None,
            provisional_outputs=("files",),
        ),
    )

    compiled = compile_build_tool_node(
        _call(
            "build_tool_node",
            mode="create",
            id="generate",
            title="Generate",
            tool={"provider_name": "image/provider", "tool_name": "generate"},
            arguments=_image_tool_arguments(selector=["iteration", "item", "source_image"]),
        ),
        tool_context,
    )

    assert not isinstance(compiled, CompiledToolNode)
    assert compiled["error_code"] == "PRIVATE_CONTAINER_REFERENCE"


def test_tool_compile_rejects_a_self_reference_through_pending_outputs(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("image/provider", "generate")},
        tool_entries=[_image_tool_entry()],
        llm_client=_ExplodingLLM(),
    )
    tool_context.state.pending_plan_nodes = (
        PendingPlanNode(
            id="generate",
            type="tool",
            title="Generate",
            purpose="generate the image",
            parent=None,
            provisional_outputs=("files",),
        ),
    )

    compiled = compile_build_tool_node(
        _call(
            "build_tool_node",
            **_image_tool_node_kwargs(
                node_id="generate",
                title="Generate",
                selector=["generate", "files"],
            ),
        ),
        tool_context,
    )

    assert not isinstance(compiled, CompiledToolNode)
    assert compiled["error_code"] == "UNKNOWN_OUTPUT"
    import json

    client = _RecordingLLM()
    _set_env(tool_context, llm_client=client)
    graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="开始",
        desc="",
        config={"variables": [{"variable": "query", "label": "问题", "type": "paragraph"}]},
    )
    tool_context.state.graph = graph
    compiled = compile_build_node(
        _call("build_node", mode="create", id="llm1", type="llm", title="回答", intent=_intent("answer", "text")),
        tool_context,
    )
    assert isinstance(compiled, CompiledBuildNode)
    marker = "# Normalized plan and topology"
    _, _, rest = client.user_prompts[0].partition(marker)
    plan = json.loads(rest.strip().split("\n\n", 1)[0])
    start = next(node for node in plan["nodes"] if node["id"] == "start")
    assert start["outputs"] == ["query"]
    assert start["outputs_kind"] == "confirmed"


def test_pending_container_parent_allows_child_compile(tool_context: ToolContext) -> None:
    _set_env(tool_context, llm_client=_FakeLLM({}))
    tool_context.state.pending_plan_nodes = (
        PendingPlanNode(
            id="iter1",
            type="iteration",
            title="循环",
            purpose="Outputs: output",
            parent=None,
            provisional_outputs=("output",),
        ),
        PendingPlanNode(
            id="child",
            type="llm",
            title="步骤",
            purpose="Outputs: text",
            parent="iter1",
            provisional_outputs=("text",),
        ),
    )
    compiled = compile_build_node(
        _call(
            "build_node",
            mode="create",
            id="child",
            type="llm",
            title="步骤",
            intent=_intent("step", "text"),
            parent="iter1",
        ),
        tool_context,
    )
    assert isinstance(compiled, CompiledBuildNode)
    assert compiled.parent == "iter1"
    assert find_node(tool_context.state.graph, "child") is None


def test_pending_parent_after_child_is_invalid_parent(tool_context: ToolContext) -> None:
    _set_env(tool_context, llm_client=_FakeLLM({}))
    tool_context.state.pending_plan_nodes = (
        PendingPlanNode(
            id="child",
            type="llm",
            title="步骤",
            purpose="Outputs: text",
            parent="iter1",
            provisional_outputs=("text",),
        ),
        PendingPlanNode(
            id="iter1",
            type="iteration",
            title="循环",
            purpose="Outputs: output",
            parent=None,
            provisional_outputs=("output",),
        ),
    )
    child = compile_build_node(
        _call(
            "build_node",
            mode="create",
            id="child",
            type="llm",
            title="步骤",
            intent=_intent("step", "text"),
            parent="iter1",
        ),
        tool_context,
    )
    parent = compile_build_node(
        _call(
            "build_node", mode="create", id="iter1", type="iteration", title="循环", intent=_intent("loop", "output")
        ),
        tool_context,
    )
    assert child["ok"] is False
    assert child["error_code"] == "INVALID_PARENT"
    assert parent["error_code"] == "CONTAINER_REQUIRES_BUILD_ITERATION"


def test_update_empty_parent_moves_node_out_of_container(tool_context: ToolContext) -> None:
    graph = upsert_node(empty_graph(), node_id="iter1", node_type="iteration", title="循环", desc="", config={})
    graph = upsert_node(graph, node_id="kr", node_type="knowledge-retrieval", title="检索", desc="", config={})
    graph["nodes"][1]["parentId"] = "iter1"
    graph["nodes"][1]["data"]["parentId"] = "iter1"
    tool_context.state.graph = graph
    _set_env(
        tool_context,
        llm_client=_FakeLLM(
            {
                "dataset_ids": ["ds-1"],
                "query_variable_selector": ["start", "query"],
                "retrieval_mode": "multiple",
                "multiple_retrieval_config": {"top_k": 3, "reranking_enable": False},
            }
        ),
    )
    result = dispatch(_call("build_node", mode="update", id="kr", intent=_intent("移出循环"), parent=""), tool_context)
    node = find_node(tool_context.state.graph, "kr")

    assert result["ok"] is True
    assert node is not None
    assert "parentId" not in node
    assert "parentId" not in node["data"]
    assert "parent" in result["content"]["effects"]


def test_replace_does_not_delete_edges(tool_context: ToolContext) -> None:
    graph = upsert_node(empty_graph(), node_id="a", node_type="start", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config=node_config("end"))
    graph = connect(graph, source="a", target="b")
    tool_context.state.graph = graph
    _set_env(tool_context, llm_client=_FakeLLM({"prompt_template": [{"role": "user", "text": "处理输入。"}]}))

    result = dispatch(_call("build_node", mode="replace", id="a", type="llm", intent=_intent("改成 LLM")), tool_context)

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
        _call("build_node", mode="update", id="kr", intent=_intent("挪进不存在的容器"), parent="missing"),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_PARENT"
    assert result["changed"] is False
    assert result["retryable"] is True


def test_connect_already_exists_is_noop(tool_context: ToolContext) -> None:
    graph = upsert_node(empty_graph(), node_id="a", node_type="start", title="A", desc="", config={})
    graph = upsert_node(graph, node_id="b", node_type="end", title="B", desc="", config=node_config("end"))
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
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
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
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="loop1",
        node_type="loop",
        title="循环",
        desc="",
        config=node_config("loop"),
    )
    assert (
        dispatch(
            _call(
                "build_node",
                mode="create",
                id="inner_a",
                type="llm",
                title="处理",
                intent=_intent("循环里第一步"),
                parent="loop1",
            ),
            tool_context,
        )["ok"]
        is True
    )
    assert (
        dispatch(
            _call(
                "build_node",
                mode="create",
                id="inner_b",
                type="end",
                title="结束",
                intent=_intent("循环里第二步"),
                parent="loop1",
            ),
            tool_context,
        )["ok"]
        is True
    )
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
        _call(
            "build_node",
            mode="create",
            id="kr",
            type="knowledge-retrieval",
            title="检索",
            intent=_intent("绑 ds-stale"),
        ),
        tool_context,
    )
    # 用 mock builder 返回 dataset_ids=["ds-stale"]；见步骤 3 的 fake client
    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_DATASET"
    assert result["changed"] is False


def test_dataset_discovery_distinguishes_no_match_from_empty_catalogue(tool_context: ToolContext) -> None:
    entries = [{"id": "ds-beads", "name": "拼豆颜色.txt...", "description": "拼豆颜色资料"}]
    _set_env(tool_context, knowledge_entries=entries, knowledge_available=True)

    missed = dispatch(_call("search_datasets", query="rag 知识库 测试"), tool_context)
    assert missed["content"]["hits"] == []
    assert missed["content"]["catalogue_count"] == 1
    listed = dispatch(_call("search_datasets", query=""), tool_context)
    assert listed["content"]["hits"] == entries

    _set_env(tool_context, knowledge_entries=[], knowledge_available=True)
    empty = dispatch(_call("search_datasets", query=""), tool_context)
    assert empty["content"]["catalogue_count"] == 0
    _set_env(tool_context, knowledge_available=False)
    unavailable = dispatch(_call("search_datasets", query=""), tool_context)
    assert unavailable["content"]["available"] is False
    assert unavailable["content"]["catalogue_count"] is None


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
        _call(
            "build_node", mode="create", id="kr", type="knowledge-retrieval", title="检索", intent=_intent("绑 ds-live")
        ),
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
        llm_client=_FakeLLM(
            {
                "dataset_ids": ["ds-stale"],
                "query_variable_selector": ["start", "query"],
                "retrieval_mode": "multiple",
                "multiple_retrieval_config": {"top_k": 3, "reranking_enable": False},
            }
        ),
    )
    result = dispatch(
        _call(
            "build_node",
            mode="create",
            id="kr",
            type="knowledge-retrieval",
            title="检索",
            intent=_intent("绑 ds-stale"),
        ),
        tool_context,
    )
    assert result["ok"] is True
    assert result["error_code"] is None


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
    assert any(hit["binding"]["tool_name"] == "google_search" for hit in search["content"]["hits"])
    assert all(hit["binding"]["tool_name"] != "deleted_search" for hit in search["content"]["hits"])

    _set_env(tool_context, llm_client=_FakeLLM({"provider_name": "stale-provider", "tool_name": "stale_tool"}))
    result = dispatch(
        _call(
            "build_tool_node",
            mode="create",
            id="t1",
            title="工具",
            tool={"provider_name": "stale-provider", "tool_name": "stale_tool"},
            arguments={},
        ),
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
        _call(
            "build_tool_node",
            mode="create",
            id="t1",
            title="工具",
            tool={"provider_name": "p", "tool_name": "t"},
            arguments={},
        ),
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


def test_search_tools_returns_at_most_twelve_summaries_without_schema_or_internal_fields(
    tool_context: ToolContext,
) -> None:
    entries = [
        {
            "provider_name": "provider",
            "provider_type": "builtin",
            "plugin_id": "private-plugin-id",
            "tool_name": f"search_{index:02d}",
            "tool_label": f"Search {index:02d}",
            "description": "search the web",
            "parameters": ({"name": "query", "type": "string", "form": "llm", "required": True},),
            "parameter_names": ("query",),
        }
        for index in range(20)
    ]
    _set_env(tool_context, tools_available=True, tool_entries=entries)

    result = dispatch(_call("search_tools", query="search"), tool_context)

    assert result["ok"] is True
    assert len(result["content"]["hits"]) == 12
    assert result["content"]["hits"][0] == {
        "binding": {"provider_name": "provider", "tool_name": "search_00"},
        "label": "Search 00",
        "description": "search the web",
    }
    assert all(set(hit) == {"binding", "label", "description"} for hit in result["content"]["hits"])


def test_inspect_tool_returns_one_exact_json_safe_schema_copy(tool_context: ToolContext) -> None:
    entry = {
        "provider_name": "image",
        "provider_type": "builtin",
        "plugin_id": "private-plugin-id",
        "tool_name": "generate",
        "tool_label": "Generate image",
        "description": "Generate one image.",
        "parameters": (
            {"name": "prompt", "type": "string", "form": "llm", "required": True},
            {
                "name": "size",
                "type": "select",
                "form": "form",
                "required": False,
                "default": "2K",
                "options": ({"value": "1K"}, {"value": "2K"}),
            },
        ),
        "output_names": ("files",),
    }
    _set_env(tool_context, tools_available=True, tool_entries=[entry])

    result = dispatch(_call("inspect_tool", provider_name="image", tool_name="generate"), tool_context)

    assert result["ok"] is True
    assert result["changed"] is False
    assert result["content"] == {
        "available": True,
        "binding": {"provider_name": "image", "tool_name": "generate"},
        "provider_type": "builtin",
        "tool_label": "Generate image",
        "description": "Generate one image.",
        "parameters": [
            {"name": "prompt", "type": "string", "form": "llm", "required": True},
            {
                "name": "size",
                "type": "select",
                "form": "form",
                "required": False,
                "default": "2K",
                "options": [{"value": "1K"}, {"value": "2K"}],
            },
        ],
        "output_names": ["files"],
    }
    result["content"]["parameters"][0]["name"] = "mutated"
    assert entry["parameters"][0]["name"] == "prompt"


def test_inspect_tool_rejects_unknown_binding(tool_context: ToolContext) -> None:
    _set_env(tool_context, tools_available=True, tool_entries=[])

    result = dispatch(_call("inspect_tool", provider_name="image", tool_name="missing"), tool_context)

    assert result["ok"] is False
    assert result["changed"] is False
    assert result["error_code"] == "UNKNOWN_TOOL"


def test_inspect_tool_reports_unavailable_catalogue_without_failing(tool_context: ToolContext) -> None:
    _set_env(tool_context, tools_available=False, tool_entries=[])

    result = dispatch(_call("inspect_tool", provider_name="image", tool_name="generate"), tool_context)

    assert result["ok"] is True
    assert result["changed"] is False
    assert result["content"] == {"available": False}


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
    assert search["content"]["hits"] == [
        {
            "binding": {"provider_name": "github-official", "tool_name": "get_file_contents"},
            "label": "Get File",
            "description": "Read a repo file.",
        }
    ]

    _set_env(
        tool_context,
        llm_client=_FakeLLM(
            {
                "version": "2",
                "agent_node_kind": "dify_agent",
                "agent_task": "读取仓库文件",
                "agent_binding": {"binding_type": "inline_agent"},
                "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
                "dify_tools": [
                    {"provider_type": "mcp", "provider_id": "github-official", "tool_name": None},
                ],
            }
        ),
    )
    result = dispatch(
        _call("build_node", mode="create", id="ag1", type="agent", title="助手", intent=_intent("用 MCP 读文件")),
        tool_context,
    )
    node = find_node(tool_context.state.graph, "ag1")
    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert node is None


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
        _call("build_node", mode="create", id="ag1", type="agent", title="助手", intent=_intent("绑未知 MCP")),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert result["changed"] is False
    assert find_node(tool_context.state.graph, "ag1") is None


def test_tool_id_in_dataset_ids_is_unknown_dataset(tool_context: ToolContext) -> None:
    _set_env(
        tool_context,
        knowledge_available=True,
        installed_dataset_ids={"ds-live"},
        tools_available=True,
        installed_tools={("langgenius/google", "google_search")},
        llm_client=_FakeLLM(
            {
                "dataset_ids": ["langgenius/google"],
                "query_variable_selector": ["start", "query"],
                "retrieval_mode": "multiple",
                "multiple_retrieval_config": {"top_k": 3, "reranking_enable": False},
            }
        ),
    )
    result = dispatch(
        _call(
            "build_node", mode="create", id="kr", type="knowledge-retrieval", title="检索", intent=_intent("误绑工具键")
        ),
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


def test_validate_graph_requires_catalogue_for_agent_knowledge(tool_context: ToolContext) -> None:
    config = _hydrated_agent_config()
    config["knowledge"] = {"sets": [{"datasets": [{"id": "ds-live"}]}]}
    tool_context.state.graph = upsert_node(
        empty_graph(), node_id="agent_1", node_type="agent", title="Agent", desc="", config=config
    )
    _set_env(
        tool_context,
        knowledge_available=False,
        installed_dataset_ids=None,
        require_resource_context=True,
    )

    result = dispatch(_call("validate_graph"), tool_context)

    assert result["ok"] is True
    assert any(error["code"] == "CAPABILITY_UNAVAILABLE" for error in result["content"]["errors"])


def test_validate_graph_rejects_unknown_tool_parameter_from_catalogue(tool_context: ToolContext) -> None:
    graph = upsert_node(
        empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={"variables": []}
    )
    graph = upsert_node(
        graph,
        node_id="t1",
        node_type="tool",
        title="搜索",
        desc="",
        config={
            "provider_id": "google",
            "provider_name": "google",
            "tool_name": "search",
            "tool_parameters": {"bogus": {"type": "constant", "value": "x"}},
        },
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
    tool_context.state.graph = connect(connect(graph, source="start", target="t1"), source="t1", target="end")
    _set_env(
        tool_context,
        tools_available=True,
        installed_tools={("google", "search")},
        tool_entries=[
            {
                "provider_name": "google",
                "provider_type": "builtin",
                "plugin_id": "",
                "tool_name": "search",
                "tool_label": "search",
                "description": "",
                "parameter_names": ("q",),
            }
        ],
    )

    rejected = dispatch(_call("validate_graph"), tool_context)
    assert any("bogus" in error["detail"] for error in rejected["content"]["errors"])

    _set_env(tool_context, tool_entries=[])
    skipped = dispatch(_call("validate_graph"), tool_context)
    assert not any("bogus" in error["detail"] for error in skipped["content"]["errors"])


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


def test_finish_rejects_old_candidate_with_empty_human_input_form(tool_context: ToolContext) -> None:
    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={})
    graph = upsert_node(
        graph,
        node_id="review",
        node_type="human-input",
        title="审核",
        desc="",
        config={
            "delivery_methods": [{"type": "webapp", "enabled": True}],
            "form_content": "  ",
            "inputs": [],
            "user_actions": [{"id": "approve", "title": "批准", "button_style": "primary"}],
        },
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
    tool_context.state.graph = connect(connect(graph, source="start", target="review"), source="review", target="end")

    result = dispatch(_call("finish", summary="已完成"), tool_context)

    assert result["ok"] is False
    assert result["content"]["valid"] is False
    assert any(
        error["code"] == "INVALID_NODE_CONFIG" and "form_content" in error["detail"]
        for error in result["content"]["errors"]
    )


def test_repeated_after_repair_requires_changed_true(tool_context) -> None:
    first = dispatch(_call("validate_graph"), tool_context)
    second = dispatch(_call("validate_graph"), tool_context)
    assert first["content"]["repeated_after_repair"] is False
    assert second["content"]["repeated_after_repair"] is False


def test_validate_graph_error_items_have_code_node_id_detail(tool_context: ToolContext) -> None:
    result = dispatch(_call("validate_graph"), tool_context)
    error = result["content"]["errors"][0]
    assert set(error) >= {"code", "node_id", "detail"}


def test_relayout_preserves_start_type_and_validate_reports_document_extractor_conflict(
    tool_context: ToolContext,
) -> None:
    graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="开始",
        desc="",
        config={"variables": [{"variable": "document", "label": "Document", "type": "paragraph"}]},
    )
    graph = upsert_node(
        graph,
        node_id="extract",
        node_type="document-extractor",
        title="文档提取",
        desc="",
        config={"variable_selector": ["start", "document"]},
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
    graph = connect(graph, source="start", target="extract")
    tool_context.state.graph = connect(graph, source="extract", target="end")

    relayout_graph(tool_context)
    start = find_node(tool_context.state.graph, "start")
    result = dispatch(_call("validate_graph"), tool_context)

    assert start is not None
    assert start["data"]["variables"][0]["type"] == "paragraph"
    assert result["content"]["valid"] is False
    assert any(
        error["code"] == "INVALID_NODE_CONFIG" and error.get("node_id") == "extract"
        for error in result["content"]["errors"]
    )


def test_repeated_after_repair_true_only_after_changed_mutation(tool_context: ToolContext) -> None:
    graph = upsert_node(empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={})
    graph = upsert_node(graph, node_id="llm", node_type="llm", title="模型", desc="", config={})
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
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
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config=node_config("end"))
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


def _connected_start_agent_end():
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
    graph = connect(graph, source="start", target="agent_1")
    return connect(graph, source="agent_1", target="end")


def test_validate_graph_accepts_unhydrated_inline_agent(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_agent_end()
    result = dispatch(_call("validate_graph"), tool_context)
    assert result["ok"] is True
    assert result["content"]["valid"] is True
    assert not any(error["code"] == "AGENT_BINDING_MISSING" for error in result["content"]["errors"])


def test_finish_rejects_unhydrated_agent_when_hydrate_is_injected(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_agent_end()

    def hydrate(graph):
        return graph

    _set_env(tool_context, hydrate_graph=hydrate)
    result = dispatch(_call("finish", summary="未绑定"), tool_context)
    assert result["ok"] is False
    assert result["content"]["valid"] is False
    assert any(error["code"] == "AGENT_BINDING_MISSING" for error in result["content"]["errors"])


def _hydrate_agent_ids(graph):
    updated = deepcopy(graph)
    for node in updated["nodes"]:
        data = node.get("data") if isinstance(node, dict) else None
        if not isinstance(data, dict) or data.get("type") != "agent":
            continue
        binding = dict(data.get("agent_binding") or {})
        binding["binding_type"] = "inline_agent"
        binding["agent_id"] = "agent-live"
        binding["current_snapshot_id"] = "snap-live"
        data["agent_binding"] = binding
    return updated


def test_run_acceptance_hydrates_before_evidence(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_agent_end()
    runner = _FakeAcceptanceRunner()
    _set_env(tool_context, hydrate_graph=_hydrate_agent_ids, acceptance_runner=runner)
    result = dispatch(_call("run_acceptance"), tool_context)
    node = find_node(tool_context.state.graph, "agent_1")
    assert result["ok"] is True
    assert result["changed"] is True
    assert node is not None
    assert node["data"]["agent_binding"]["agent_id"] == "agent-live"
    assert runner.calls[0]["revision"] == tool_context.state.candidate_revision
    assert runner.calls[0]["graph_hash"] == canonical_graph_hash(tool_context.state.graph)
    assert runner.calls[0]["graph_hash"] == result["content"]["graph_hash"]


def test_finish_after_acceptance_does_not_invalidate_hydrated_evidence(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_agent_end()
    runner = _FakeAcceptanceRunner()
    _set_env(tool_context, hydrate_graph=_hydrate_agent_ids, acceptance_runner=runner)
    accepted = dispatch(_call("run_acceptance"), tool_context)
    graph_hash = accepted["content"]["graph_hash"]
    result = dispatch(_call("finish", summary="已验收"), tool_context)
    assert result["ok"] is True
    assert result["content"]["valid"] is True
    assert "acceptance" not in result["content"]
    node = find_node(tool_context.state.graph, "agent_1")
    assert node is not None
    assert node["data"]["agent_binding"]["agent_id"] == "agent-live"
    assert tool_context.state.attempts["att-1"]["graph_hash"] == graph_hash


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

    monkeypatch.setattr("core.workflow.generator.agent.tools.tool_lifecycle.run_graph_validator", boom)
    result = dispatch(_call("validate_graph"), tool_context)
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["error_code"] == "CAPABILITY_UNAVAILABLE"


def test_finish_validator_exception_is_ok_false(tool_context: ToolContext, monkeypatch) -> None:
    tool_context.state.graph = _connected_start_end()

    def boom(**kwargs):
        raise RuntimeError("validator down")

    monkeypatch.setattr("core.workflow.generator.agent.tools.tool_lifecycle.run_graph_validator", boom)
    result = dispatch(_call("finish", summary="做好了"), tool_context)
    assert result["ok"] is False
    assert result["error_code"] == "CAPABILITY_UNAVAILABLE"
    assert result["content"] is None


class _FakeAcceptanceRunner:
    def __init__(self, *, passed: bool = True, failed_nodes: list | None = None, executed: bool = True) -> None:
        self.passed = passed
        self.failed_nodes = failed_nodes or []
        self.executed = executed
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
                "executed": self.executed,
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
    assert result["content"]["executed"] is True
    assert result["content"]["mode"] == "simulated"
    assert result["content"]["unverified_nodes"] == ["llm"]
    assert result["content"]["attempt_id"] == "att-1"
    assert "att-1" in tool_context.state.attempts
    assert runner.calls[0]["mode"] == "simulated"


def test_acceptance_evidence_is_bound_to_contract_run_and_validation_version(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_end()
    tool_context.state.contract_protocol_version = 1
    tool_context.state.contract_revision = 2
    tool_context.state.contract_hash = "a" * 64
    tool_context.state.candidate_base_hash = "b" * 64
    _set_env(
        tool_context,
        acceptance_runner=_FakeAcceptanceRunner(),
        run_id="run-1",
        run_epoch=3,
    )

    result = dispatch(_call("run_acceptance"), tool_context)

    assert result["ok"] is True
    attempt = tool_context.state.attempts["att-1"]
    assert attempt["contract_revision"] == 2
    assert attempt["contract_hash"] == "a" * 64
    assert attempt["app_mode"] == "workflow"
    assert attempt["candidate_base_hash"] == "b" * 64
    assert attempt["run_id"] == "run-1"
    assert attempt["epoch"] == 3
    assert attempt["validation_version"] == 1


def test_run_acceptance_surfaces_executed_false(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_end()
    runner = _FakeAcceptanceRunner(executed=False)
    _set_env(tool_context, acceptance_runner=runner)
    result = dispatch(_call("run_acceptance"), tool_context)
    assert result["ok"] is True
    assert result["content"]["passed"] is True
    assert result["content"]["executed"] is False


def test_run_acceptance_surfaces_execution_and_business_verification_separately(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_end()
    runner = _FakeAcceptanceRunner(executed=False)
    _set_env(tool_context, acceptance_runner=runner)

    result = dispatch(_call("run_acceptance"), tool_context)

    assert result["content"]["unexecuted_node_ids"] == []
    assert result["content"]["business_verified"] is False


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


def test_legacy_acceptance_binds_candidate_base_hash_for_finish(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_end()
    tool_context.state.candidate_base_hash = "b" * 64
    _set_env(tool_context, acceptance_runner=_FakeAcceptanceRunner())

    dispatch(_call("run_acceptance"), tool_context)
    result = dispatch(_call("finish", summary="已搭好"), tool_context)

    assert tool_context.state.contract_protocol_version is None
    assert tool_context.state.attempts["att-1"]["candidate_base_hash"] == "b" * 64
    assert result["ok"] is True


def test_finish_is_idempotent_for_the_accepted_revision(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_end()
    _set_env(tool_context, acceptance_runner=_FakeAcceptanceRunner())
    dispatch(_call("run_acceptance"), tool_context)
    revision = tool_context.state.candidate_revision
    assert dispatch(_call("finish", summary="done"), tool_context)["ok"]
    assert tool_context.state.candidate_revision == revision
    assert dispatch(_call("finish", summary="done"), tool_context)["ok"]


def test_missing_llm_model_preflight_never_hydrates_or_runs(tool_context: ToolContext) -> None:
    from unittest.mock import Mock

    tool_context.state.graph = _connected_start_end()
    tool_context.state.graph = upsert_node(
        tool_context.state.graph, node_id="llm", node_type="llm", title="LLM", desc="", config={}
    )
    tool_context.state.graph = connect(tool_context.state.graph, source="start", target="llm")
    tool_context.state.graph = connect(tool_context.state.graph, source="llm", target="end")
    hydrate = Mock(side_effect=AssertionError("invalid graph must not hydrate"))
    runner = _FakeAcceptanceRunner()
    _set_env(tool_context, hydrate_graph=hydrate, acceptance_runner=runner)
    acceptance = dispatch(_call("run_acceptance"), tool_context)
    assert not acceptance["ok"]
    assert acceptance["retryable"]
    assert any(e["code"] == "INVALID_NODE_CONFIG" and "model" in e["detail"] for e in acceptance["content"]["errors"])
    assert not dispatch(_call("finish", summary="done"), tool_context)["ok"]
    hydrate.assert_not_called()
    assert runner.calls == []


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
    tool_context.state.graph = _connected_start_end()
    runner = _FakeAcceptanceRunner()
    _set_env(tool_context, acceptance_runner=runner)
    _set_env(tool_context, authorize_live_acceptance=lambda revision, graph_hash: True)
    result = dispatch(_call("run_acceptance", mode="live"), tool_context)
    assert result["ok"] is True
    assert runner.calls[0]["mode"] == "live"


def test_live_acceptance_rejected_grant_never_calls_runner(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_end()
    runner = _FakeAcceptanceRunner()
    _set_env(tool_context, acceptance_runner=runner, authorize_live_acceptance=lambda revision, graph_hash: False)
    result = dispatch(_call("run_acceptance", mode="live"), tool_context)
    assert result["error_code"] == "LIVE_RUN_REQUIRES_CONSENT"
    assert runner.calls == []


def test_live_acceptance_cannot_expand_one_grant_to_multiple_cases(tool_context: ToolContext) -> None:
    tool_context.state.graph = _connected_start_end()
    runner = _FakeAcceptanceRunner()
    authorize = MagicMock(return_value=True)
    _set_env(tool_context, acceptance_runner=runner, authorize_live_acceptance=authorize)
    result = dispatch(_call("run_acceptance", mode="live", case_ids=["first", "second"]), tool_context)
    assert result["error_code"] == "LIVE_RUN_REQUIRES_CONSENT"
    authorize.assert_not_called()
    assert runner.calls == []


def test_activate_skills_single_and_multiple_preserve_order(tool_context: ToolContext) -> None:
    graph_before = tool_context.state.graph
    revision_before = tool_context.state.candidate_revision
    single = dispatch(_call("activate_skills", names=["create-from-scratch"]), tool_context)
    assert single["ok"] is True
    assert single["changed"] is False
    assert single["content"]["active_skills"] == ["create-from-scratch"]
    combo = dispatch(
        _call("activate_skills", names=["create-from-scratch", "bind-resources"]),
        tool_context,
    )
    assert combo["ok"] is True
    assert combo["changed"] is False
    assert combo["content"]["active_skills"] == ["create-from-scratch", "bind-resources"]
    assert tool_context.state.graph is graph_before
    assert tool_context.state.candidate_revision == revision_before


def test_activate_skills_empty_array_clears(tool_context: ToolContext) -> None:
    result = dispatch(_call("activate_skills", names=[]), tool_context)
    assert result["ok"] is True
    assert result["changed"] is False
    assert result["content"]["active_skills"] == []


def test_activate_skills_rejects_duplicates_unknown_and_over_limit(tool_context: ToolContext) -> None:
    duplicate = dispatch(
        _call("activate_skills", names=["create-from-scratch", "create-from-scratch"]),
        tool_context,
    )
    assert duplicate["ok"] is False
    assert duplicate["error_code"] == "INVALID_ARGUMENT"
    assert "create-from-scratch" in str(duplicate["error"])

    unknown = dispatch(_call("activate_skills", names=["not-a-skill"]), tool_context)
    assert unknown["ok"] is False
    assert unknown["error_code"] == "UNKNOWN_SKILL"
    assert unknown["retryable"] is True
    assert "not-a-skill" in str(unknown["error"])
    assert "create-from-scratch" in str(unknown["error"])

    too_many = dispatch(
        _call(
            "activate_skills",
            names=[
                "create-from-scratch",
                "bind-resources",
                "edit-local-node",
                "repair-validation",
                "build-container",
            ],
        ),
        tool_context,
    )
    assert too_many["ok"] is False
    assert too_many["error_code"] == "INVALID_ARGUMENT"

    not_array = dispatch(_call("activate_skills", names="create-from-scratch"), tool_context)
    assert not_array["ok"] is False
    assert not_array["error_code"] == "INVALID_ARGUMENT"
