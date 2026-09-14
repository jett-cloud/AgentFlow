from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from core.workflow.generator.agent.tools.tool_context import PendingPlanNode
from core.workflow.generator.agent.tools.tool_mutate import pending_plan_nodes_from_calls
from core.workflow.generator.agent.tools.tool_results import RETRYABLE_BY_ERROR_CODE
from core.workflow.generator.agent.tools.tools import TOOL_SCHEMAS, ToolContext, dispatch
from core.workflow.generator.agent.types import ToolCall
from core.workflow.generator.graph.graph_ops import empty_graph, find_node, upsert_node
from tests.unit_tests.core.workflow.generator.agent.conftest import set_env


@pytest.mark.parametrize("node_id", ["node-1", "node.1", "node 1", "节点1"])
def test_build_tool_node_rejects_runtime_unsafe_ids(tool_context: ToolContext, node_id: str) -> None:
    _enable_image_tools(tool_context)
    _start_with_files(tool_context)
    result = dispatch(_call("build_tool_node", **_create_args(id=node_id)), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_NODE_ID"
    assert find_node(tool_context.state.graph, node_id) is None


class _ExplodingLLM:
    def iter_json(self, *, messages, stage):
        raise AssertionError("Tool compilation must not call the node-builder LLM")


def _call(name: str, **arguments: object) -> ToolCall:
    return {"id": "c1", "name": name, "arguments": arguments}


def _schema(name: str) -> dict[str, object]:
    return {item["name"]: dict(item) for item in TOOL_SCHEMAS}[name]


def _image_entry(**changes: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "provider_name": "image/provider",
        "provider_type": "builtin",
        "plugin_id": "image/provider",
        "tool_name": "generate",
        "tool_label": "Generate",
        "description": "Generate an image",
        "parameters": (
            {"name": "prompt", "type": "string", "form": "llm", "required": True},
            {"name": "image", "type": "file", "form": "llm", "required": True},
            {"name": "size", "type": "select", "form": "form", "required": False, "default": "2K"},
        ),
        "parameter_names": ("prompt", "image", "size"),
        "output_names": ("files",),
        "outputs": ({"name": "files", "type": "array[file]"},),
    }
    entry.update(changes)
    return entry


def _enable_image_tools(context: ToolContext, entry: dict[str, object] | None = None) -> None:
    tool_entry = entry or _image_entry()
    set_env(
        context,
        tools_available=True,
        installed_tools={(str(tool_entry["provider_name"]), str(tool_entry["tool_name"]))},
        tool_entries=[tool_entry],
        llm_client=_ExplodingLLM(),
    )


def _start_with_files(context: ToolContext) -> None:
    context.state.graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="开始",
        desc="",
        config={
            "variables": [
                {"variable": "image", "type": "file"},
                {"variable": "images", "type": "array[file]"},
                {"variable": "texts", "type": "array[string]"},
            ]
        },
    )


def _with_iteration(context: ToolContext, *, iterator_input_type: str) -> None:
    _start_with_files(context)
    context.state.graph = upsert_node(
        context.state.graph,
        node_id="iter1",
        node_type="iteration",
        title="逐条",
        desc="",
        config={"iterator_input_type": iterator_input_type},
    )


def _item_tool_args(*, item_param: str, extra: dict[str, object] | None = None) -> dict[str, object]:
    arguments: dict[str, object] = {
        "prompt": {"kind": "constant", "value": "draw it"},
        item_param: {"kind": "variable", "selector": ["iter1", "item"]},
    }
    if extra:
        arguments.update(extra)
    return _create_args(parent="iter1", arguments=arguments)


def _create_args(**changes: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "mode": "create",
        "id": "tool_1",
        "title": "生成",
        "tool": {"provider_name": "image/provider", "tool_name": "generate"},
        "arguments": {
            "prompt": {"kind": "constant", "value": "draw it"},
            "image": {"kind": "variable", "selector": ["start", "image"]},
        },
    }
    arguments.update(changes)
    return arguments


def test_tool_schemas_contains_build_tool_node_with_required_fields() -> None:
    schema = _schema("build_tool_node")
    parameters = schema["parameters"]
    properties = parameters["properties"]

    assert set(parameters["required"]) >= {"mode", "id", "tool", "arguments"}
    assert parameters["additionalProperties"] is False
    assert properties["mode"]["enum"] == ["create", "update", "replace"]
    assert set(properties) >= {"mode", "id", "title", "tool", "arguments"}
    assert properties["tool"]["additionalProperties"] is False
    assert set(properties["tool"]["required"]) == {"provider_name", "tool_name"}
    assert properties["arguments"]["additionalProperties"]["oneOf"]

    create_required: list[str] | None = None
    for clause in parameters.get("allOf", []):
        mode_schema = clause.get("if", {}).get("properties", {}).get("mode", {})
        if mode_schema.get("const") == "create":
            create_required = clause.get("then", {}).get("required")
            break
    assert create_required is not None
    assert "title" in create_required

    validator = Draft202012Validator(parameters)
    assert validator.is_valid(_create_args())
    extra_errors = list(validator.iter_errors({**_create_args(), "intent": {"objective": "nope"}}))
    assert extra_errors


def test_build_tool_node_rejects_extra_fields_at_runtime(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    _start_with_files(tool_context)

    result = dispatch(_call("build_tool_node", **_create_args(), intent={"objective": "nope"}), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert find_node(tool_context.state.graph, "tool_1") is None


def test_build_node_create_and_replace_tool_require_build_tool_node(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    created = dispatch(
        _call(
            "build_node",
            mode="create",
            id="tool_1",
            type="tool",
            title="生成",
            intent={
                "objective": "生成图片",
                "tool": {
                    "binding": {"provider_name": "image/provider", "tool_name": "generate"},
                    "arguments": {},
                },
            },
        ),
        tool_context,
    )
    assert created["ok"] is False
    assert created["error_code"] == "TOOL_NODE_REQUIRES_BUILD_TOOL_NODE"
    assert created["changed"] is False
    assert find_node(tool_context.state.graph, "tool_1") is None

    tool_context.state.graph = upsert_node(
        empty_graph(), node_id="llm1", node_type="llm", title="模型", desc="", config={}
    )
    replaced = dispatch(
        _call(
            "build_node",
            mode="replace",
            id="llm1",
            type="tool",
            intent={
                "objective": "改成工具",
                "tool": {
                    "binding": {"provider_name": "image/provider", "tool_name": "generate"},
                    "arguments": {},
                },
            },
        ),
        tool_context,
    )
    assert replaced["error_code"] == "TOOL_NODE_REQUIRES_BUILD_TOOL_NODE"
    assert find_node(tool_context.state.graph, "llm1")["data"]["type"] == "llm"


def test_build_node_update_existing_tool_requires_build_tool_node(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(), node_id="tool_1", node_type="tool", title="生成", desc="", config={}
    )
    result = dispatch(
        _call("build_node", mode="update", id="tool_1", intent={"objective": "改参数"}),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "TOOL_NODE_REQUIRES_BUILD_TOOL_NODE"
    assert result["changed"] is False


def test_build_node_rejects_agent_loop_and_iteration(tool_context: ToolContext) -> None:
    cases = (
        ("agent", "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"),
        ("loop", "CONTAINER_REQUIRES_BUILD_LOOP"),
        ("iteration", "CONTAINER_REQUIRES_BUILD_ITERATION"),
    )
    for node_type, code in cases:
        result = dispatch(
            _call(
                "build_node",
                mode="create",
                id=f"{node_type}_1",
                type=node_type,
                title=node_type,
                intent={"objective": "专用节点"},
            ),
            tool_context,
        )
        assert result["ok"] is False
        assert result["error_code"] == code
        assert result["changed"] is False
        assert find_node(tool_context.state.graph, f"{node_type}_1") is None


def test_build_tool_node_resolves_exact_catalogue_entry(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    _start_with_files(tool_context)

    result = dispatch(_call("build_tool_node", **_create_args()), tool_context)

    node = find_node(tool_context.state.graph, "tool_1")
    assert result["ok"] is True
    assert result["changed"] is True
    assert node is not None
    assert node["data"]["provider_name"] == "image/provider"
    assert node["data"]["tool_name"] == "generate"
    assert node["data"]["tool_parameters"]["image"] == {"type": "variable", "value": ["start", "image"]}
    assert node["data"]["tool_parameters"]["prompt"] == {"type": "constant", "value": "draw it"}


def test_build_tool_node_unknown_tool_is_unknown_tool(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    _start_with_files(tool_context)

    result = dispatch(
        _call(
            "build_tool_node",
            **_create_args(tool={"provider_name": "missing", "tool_name": "nope"}),
        ),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_TOOL"
    assert result["retryable"] is True
    assert find_node(tool_context.state.graph, "tool_1") is None


def test_build_tool_node_missing_parameter_schema_is_capability_unavailable(tool_context: ToolContext) -> None:
    entry = _image_entry()
    del entry["parameters"]
    _enable_image_tools(tool_context, entry)
    _start_with_files(tool_context)

    result = dispatch(_call("build_tool_node", **_create_args()), tool_context)
    assert result["ok"] is False
    assert result["error_code"] == "CAPABILITY_UNAVAILABLE"
    assert find_node(tool_context.state.graph, "tool_1") is None


def test_build_tool_node_unknown_argument_is_invalid_node_config(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    _start_with_files(tool_context)

    result = dispatch(
        _call(
            "build_tool_node",
            **_create_args(
                arguments={
                    "prompt": {"kind": "constant", "value": "draw it"},
                    "image": {"kind": "variable", "selector": ["start", "image"]},
                    "bogus": {"kind": "constant", "value": "x"},
                }
            ),
        ),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_NODE_CONFIG"
    assert "bogus" in str(result["error"])


def test_build_tool_node_missing_required_file_is_invalid_node_config(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    _start_with_files(tool_context)

    result = dispatch(
        _call(
            "build_tool_node",
            **_create_args(arguments={"prompt": {"kind": "constant", "value": "draw it"}}),
        ),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_NODE_CONFIG"
    assert "image" in str(result["error"])


def test_build_tool_node_accepts_legal_upstream_file(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    _start_with_files(tool_context)

    result = dispatch(_call("build_tool_node", **_create_args()), tool_context)
    node = find_node(tool_context.state.graph, "tool_1")
    assert result["ok"] is True
    assert node is not None
    assert node["data"]["tool_parameters"]["image"] == {"type": "variable", "value": ["start", "image"]}


def test_build_tool_node_rejects_array_file_into_file(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    _start_with_files(tool_context)

    result = dispatch(
        _call(
            "build_tool_node",
            **_create_args(
                arguments={
                    "prompt": {"kind": "constant", "value": "draw it"},
                    "image": {"kind": "variable", "selector": ["start", "images"]},
                }
            ),
        ),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "VARIABLE_TYPE_MISMATCH"
    assert find_node(tool_context.state.graph, "tool_1") is None


def test_build_tool_node_rejects_bare_node_output_string(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    _start_with_files(tool_context)

    result = dispatch(
        _call(
            "build_tool_node",
            **_create_args(
                arguments={
                    "prompt": {"kind": "constant", "value": "draw it"},
                    "image": "start.image",
                }
            ),
        ),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert find_node(tool_context.state.graph, "tool_1") is None


def test_build_tool_node_names_only_upstream_tool_output_is_schema_unavailable(tool_context: ToolContext) -> None:
    producer = {
        "provider_name": "files/provider",
        "provider_type": "builtin",
        "plugin_id": "files/provider",
        "tool_name": "list_files",
        "tool_label": "List",
        "description": "List files",
        "parameters": (),
        "parameter_names": (),
        "output_names": ("files",),
    }
    consumer = _image_entry()
    set_env(
        tool_context,
        tools_available=True,
        installed_tools={
            ("files/provider", "list_files"),
            ("image/provider", "generate"),
        },
        tool_entries=[producer, consumer],
        llm_client=_ExplodingLLM(),
    )
    graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="开始",
        desc="",
        config={"variables": [{"variable": "query", "type": "string"}]},
    )
    graph = upsert_node(
        graph,
        node_id="lister",
        node_type="tool",
        title="列出",
        desc="",
        config={
            "provider_id": "files/provider",
            "provider_name": "files/provider",
            "tool_name": "list_files",
        },
    )
    tool_context.state.graph = graph

    result = dispatch(
        _call(
            "build_tool_node",
            **_create_args(
                arguments={
                    "prompt": {"kind": "constant", "value": "draw it"},
                    "image": {"kind": "variable", "selector": ["lister", "files"]},
                }
            ),
        ),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "TOOL_OUTPUT_SCHEMA_UNAVAILABLE"
    assert find_node(tool_context.state.graph, "tool_1") is None


def test_build_tool_node_update_changed_binding_does_not_inherit_old_params(tool_context: ToolContext) -> None:
    other = {
        "provider_name": "other/provider",
        "provider_type": "builtin",
        "plugin_id": "other/provider",
        "tool_name": "draw",
        "tool_label": "Draw",
        "description": "Draw",
        "parameters": (
            {"name": "prompt", "type": "string", "form": "llm", "required": True},
            {"name": "image", "type": "file", "form": "llm", "required": True},
        ),
        "parameter_names": ("prompt", "image"),
        "output_names": ("files",),
        "outputs": ({"name": "files", "type": "array[file]"},),
    }
    set_env(
        tool_context,
        tools_available=True,
        installed_tools={("image/provider", "generate"), ("other/provider", "draw")},
        tool_entries=[_image_entry(), other],
        llm_client=_ExplodingLLM(),
    )
    _start_with_files(tool_context)
    created = dispatch(_call("build_tool_node", **_create_args()), tool_context)
    assert created["ok"] is True
    before = deepcopy(find_node(tool_context.state.graph, "tool_1")["data"])

    result = dispatch(
        _call(
            "build_tool_node",
            mode="update",
            id="tool_1",
            tool={"provider_name": "other/provider", "tool_name": "draw"},
            arguments={
                "prompt": {"kind": "constant", "value": "new prompt"},
                "image": {"kind": "variable", "selector": ["start", "image"]},
            },
        ),
        tool_context,
    )
    node = find_node(tool_context.state.graph, "tool_1")
    assert result["ok"] is True
    assert node is not None
    assert node["data"]["provider_name"] == "other/provider"
    assert node["data"]["tool_name"] == "draw"
    assert "size" not in node["data"]["tool_parameters"]
    assert "size" not in node["data"].get("tool_configurations", {})
    assert before["tool_name"] == "generate"
    assert "size" in before["tool_parameters"]


def test_compile_build_tool_node_does_not_write_until_commit(tool_context: ToolContext) -> None:
    from core.workflow.generator.agent.tools.tool_build_tool import (
        CompiledToolNode,
        commit_build_tool_node,
        compile_build_tool_node,
    )

    _enable_image_tools(tool_context)
    _start_with_files(tool_context)
    call = _call("build_tool_node", **_create_args())

    compiled = compile_build_tool_node(call, tool_context)
    assert isinstance(compiled, CompiledToolNode)
    assert find_node(tool_context.state.graph, "tool_1") is None

    result = commit_build_tool_node(compiled, tool_context)
    assert result["ok"] is True
    assert find_node(tool_context.state.graph, "tool_1") is not None


def test_new_specialized_error_codes_are_retryable() -> None:
    for code in (
        "TOOL_NODE_REQUIRES_BUILD_TOOL_NODE",
        "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE",
        "CONTAINER_REQUIRES_BUILD_LOOP",
        "CONTAINER_REQUIRES_BUILD_ITERATION",
        "VARIABLE_TYPE_MISMATCH",
        "UNKNOWN_OUTPUT",
        "TOOL_OUTPUT_SCHEMA_UNAVAILABLE",
    ):
        assert RETRYABLE_BY_ERROR_CODE[code] is True


def test_build_tool_node_accepts_array_file_iteration_item(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    _with_iteration(tool_context, iterator_input_type="array[file]")

    result = dispatch(_call("build_tool_node", **_item_tool_args(item_param="image")), tool_context)

    node = find_node(tool_context.state.graph, "tool_1")
    assert result["ok"] is True
    assert node is not None
    assert node["data"]["tool_parameters"]["image"] == {"type": "variable", "value": ["iter1", "item"]}


def test_build_tool_node_rejects_array_string_iteration_item_for_file(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    _with_iteration(tool_context, iterator_input_type="array[string]")

    result = dispatch(_call("build_tool_node", **_item_tool_args(item_param="image")), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "VARIABLE_TYPE_MISMATCH"
    assert find_node(tool_context.state.graph, "tool_1") is None


def test_build_tool_node_accepts_array_string_iteration_item_for_string(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    _with_iteration(tool_context, iterator_input_type="array[string]")

    result = dispatch(
        _call(
            "build_tool_node",
            **_item_tool_args(
                item_param="prompt",
                extra={"image": {"kind": "variable", "selector": ["start", "image"]}},
            ),
        ),
        tool_context,
    )

    node = find_node(tool_context.state.graph, "tool_1")
    assert result["ok"] is True
    assert node is not None
    assert node["data"]["tool_parameters"]["prompt"] == {"type": "variable", "value": ["iter1", "item"]}


def test_build_tool_node_accepts_nested_array_file_iteration_item(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    _with_iteration(tool_context, iterator_input_type="array[file]")

    result = dispatch(
        _call(
            "build_tool_node",
            **_create_args(
                parent="iter1",
                arguments={
                    "prompt": {"kind": "constant", "value": "draw it"},
                    "image": {"kind": "variable", "selector": ["iter1", "item", "source_image"]},
                },
            ),
        ),
        tool_context,
    )

    assert result["ok"] is True
    node = find_node(tool_context.state.graph, "tool_1")
    assert node is not None
    assert node["data"]["tool_parameters"]["image"] == {
        "type": "variable",
        "value": ["iter1", "item", "source_image"],
    }


def test_build_tool_node_rejects_nested_array_string_iteration_item_for_file(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    _with_iteration(tool_context, iterator_input_type="array[string]")

    result = dispatch(
        _call(
            "build_tool_node",
            **_create_args(
                parent="iter1",
                arguments={
                    "prompt": {"kind": "constant", "value": "draw it"},
                    "image": {"kind": "variable", "selector": ["iter1", "item", "source_image"]},
                },
            ),
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "VARIABLE_TYPE_MISMATCH"


def _pending_iteration_and_tool(*, iterator_input_type: str) -> tuple[PendingPlanNode, ...]:
    return pending_plan_nodes_from_calls(
        [
            {
                "id": "c0",
                "name": "build_iteration",
                "arguments": {
                    "id": "iter1",
                    "title": "逐条",
                    "iterator_selector": ["start", "texts"],
                    "iterator_input_type": iterator_input_type,
                    "output_selector": ["tool_1", "files"],
                    "children": [],
                },
            },
            {
                "id": "c1",
                "name": "build_tool_node",
                "arguments": {"id": "tool_1", "parent": "iter1", "title": "生成"},
            },
        ]
    )


def test_build_tool_node_accepts_pending_array_file_iteration_item(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    _start_with_files(tool_context)
    tool_context.state.pending_plan_nodes = _pending_iteration_and_tool(iterator_input_type="array[file]")

    result = dispatch(_call("build_tool_node", **_item_tool_args(item_param="image")), tool_context)

    assert result["ok"] is True
    node = find_node(tool_context.state.graph, "tool_1")
    assert node is not None
    assert node["data"]["tool_parameters"]["image"] == {"type": "variable", "value": ["iter1", "item"]}


def test_build_tool_node_rejects_pending_array_string_iteration_item_for_file(tool_context: ToolContext) -> None:
    _enable_image_tools(tool_context)
    _start_with_files(tool_context)
    tool_context.state.pending_plan_nodes = _pending_iteration_and_tool(iterator_input_type="array[string]")

    result = dispatch(_call("build_tool_node", **_item_tool_args(item_param="image")), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "VARIABLE_TYPE_MISMATCH"
    assert find_node(tool_context.state.graph, "tool_1") is None
