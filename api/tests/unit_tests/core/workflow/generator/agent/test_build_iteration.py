from copy import deepcopy

from core.workflow.generator.agent.tools.tool_build_container import compile_build_iteration
from core.workflow.generator.agent.tools.tools import TOOL_SCHEMAS, ToolContext, dispatch
from core.workflow.generator.agent.types import ToolCall
from core.workflow.generator.graph.graph_ops import connect, empty_graph, find_node, upsert_node
from tests.unit_tests.core.workflow.generator.agent.conftest import set_env


def _call(**arguments: object) -> ToolCall:
    return {"id": "c1", "name": "build_iteration", "arguments": arguments}


def _image_entry() -> dict[str, object]:
    return {
        "provider_name": "image/provider",
        "provider_type": "builtin",
        "plugin_id": "image/provider",
        "tool_name": "process",
        "tool_label": "Process image",
        "description": "Process one image",
        "parameters": ({"name": "image", "type": "file", "form": "llm", "required": True},),
        "parameter_names": ("image",),
        "output_names": ("file",),
        "outputs": ({"name": "file", "type": "file"},),
    }


def _boolean_entry() -> dict[str, object]:
    return {
        "provider_name": "flag/provider",
        "provider_type": "builtin",
        "plugin_id": "flag/provider",
        "tool_name": "flag",
        "tool_label": "Flag",
        "description": "Return a boolean",
        "parameters": ({"name": "prompt", "type": "string", "form": "llm", "required": True},),
        "parameter_names": ("prompt",),
        "output_names": ("ok",),
        "outputs": ({"name": "ok", "type": "boolean"},),
    }


def _enable_image_tool(context: ToolContext, *extra: dict[str, object]) -> None:
    entries = [_image_entry(), *extra]
    set_env(
        context,
        tools_available=True,
        installed_tools={(str(entry["provider_name"]), str(entry["tool_name"])) for entry in entries},
        tool_entries=list(entries),
    )


def _start_images_config() -> dict[str, object]:
    return {
        "variables": [
            {
                "variable": "images",
                "label": "Images",
                "type": "file-list",
                "required": False,
                "allowed_file_types": ["image"],
                "allowed_file_upload_methods": ["local_file"],
            },
            {"variable": "query", "label": "Query", "type": "text-input", "required": False},
        ]
    }


def _outer_graph(*, iteration_exists: bool = True, end_reads: str = "output") -> dict:
    graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="开始",
        desc="",
        config=_start_images_config(),
    )
    if iteration_exists:
        graph = upsert_node(
            graph,
            node_id="iter1",
            node_type="iteration",
            title="逐张处理",
            desc="",
            config={
                "iterator_selector": ["start", "images"],
                "iterator_input_type": "array[file]",
                "output_selector": ["iter1_old", "file"],
                "output_type": "array[file]",
            },
        )
        graph = upsert_node(
            graph,
            node_id="iter1_old",
            node_type="tool",
            title="旧子节点",
            desc="",
            config={},
            parent="iter1",
        )
    graph = upsert_node(
        graph,
        node_id="end",
        node_type="end",
        title="结束",
        desc="",
        config={
            "outputs": [
                {
                    "variable": "result",
                    "value_selector": ["iter1", end_reads],
                    "value_type": "array[file]",
                }
            ]
        },
    )
    if iteration_exists:
        graph = connect(graph, source="start", target="iter1")
        graph = connect(graph, source="iter1", target="end")
    else:
        graph["edges"] = [
            {"source": "start", "target": "iter1"},
            {"source": "iter1", "target": "end"},
        ]
    return graph


def _worker_child(*, selector: list[str] | None = None) -> dict[str, object]:
    return {
        "kind": "tool",
        "ref": "worker",
        "intent": {
            "binding": {"provider_name": "image/provider", "tool_name": "process"},
            "arguments": {"image": {"kind": "variable", "selector": selector or ["iter1", "item"]}},
        },
    }


def _min_iteration_args(**changes: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "mode": "update",
        "id": "iter1",
        "title": "逐张处理",
        "iterator_selector": ["start", "images"],
        "iterator_input_type": "array[file]",
        "output_selector": ["worker", "file"],
        "children": [_worker_child()],
        "edges": [],
        "outputs": [{"name": "output", "type": "array[file]"}],
        "is_parallel": False,
        "parallel_nums": 10,
        "error_handle_mode": "terminated",
        "flatten_output": True,
    }
    arguments.update(changes)
    return arguments


def test_tool_schemas_contains_build_iteration() -> None:
    schema = {item["name"]: dict(item) for item in TOOL_SCHEMAS}["build_iteration"]
    parameters = schema["parameters"]
    assert set(parameters["required"]) >= {
        "mode",
        "id",
        "iterator_selector",
        "iterator_input_type",
        "output_selector",
        "children",
    }
    assert parameters["additionalProperties"] is False
    assert "build_iteration" in {item["name"] for item in TOOL_SCHEMAS}


def test_build_iteration_rejects_runtime_unsafe_id(tool_context: ToolContext) -> None:
    _enable_image_tool(tool_context)
    tool_context.state.graph = _outer_graph()

    result = dispatch(_call(**_min_iteration_args(mode="create", id="iter-2", title="迭代")), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_NODE_ID"
    assert find_node(tool_context.state.graph, "iter-2") is None


def test_serial_iteration_maps_item_file_to_aggregated_array_file(tool_context: ToolContext) -> None:
    _enable_image_tool(tool_context)
    tool_context.state.graph = _outer_graph()
    tool_context.state.candidate_revision = 4

    result = dispatch(_call(**_min_iteration_args()), tool_context)

    assert result["ok"] is True
    assert result["changed"] is True
    container = find_node(tool_context.state.graph, "iter1")
    assert container is not None
    data = container["data"]
    assert data["type"] == "iteration"
    assert data["start_node_id"] == "iter1start"
    assert data["iterator_selector"] == ["start", "images"]
    assert data["output_selector"] == ["iter1_worker", "file"]
    assert data["output_type"] == "array[file]"
    assert "loop_variables" not in data or not data.get("loop_variables")
    assert "break_conditions" not in data or not data.get("break_conditions")
    start = find_node(tool_context.state.graph, "iter1start")
    assert start is not None
    assert start.get("parentId") == "iter1"
    assert start["data"]["type"] == "iteration-start"
    worker = find_node(tool_context.state.graph, "iter1_worker")
    assert worker is not None
    assert worker.get("parentId") == "iter1"
    assert worker["data"].get("isInIteration") is True
    image_param = (worker["data"].get("tool_parameters") or {}).get("image") or {}
    assert image_param.get("value") == ["iter1", "item"]
    assert find_node(tool_context.state.graph, "iter1_old") is None
    edges = {(edge["source"], edge["target"]) for edge in tool_context.state.graph["edges"]}
    assert ("iter1start", "iter1_worker") in edges
    assert ("start", "iter1") in edges
    assert ("iter1", "end") in edges
    end = find_node(tool_context.state.graph, "end")
    assert end is not None
    assert end["data"]["outputs"][0]["value_selector"] == ["iter1", "output"]


def test_replace_loop_with_iteration_removes_loop_fields(tool_context: ToolContext) -> None:
    _enable_image_tool(tool_context)
    graph = _outer_graph()
    node = find_node(graph, "iter1")
    assert node is not None
    node["data"] = {
        "type": "loop",
        "title": "旧循环",
        "desc": "保留描述",
        "loop_count": 5,
        "loop_variables": [{"label": "old", "var_type": "string"}],
        "break_conditions": [],
        "logical_operator": "and",
    }
    tool_context.state.graph = graph

    result = dispatch(_call(**_min_iteration_args(mode="replace")), tool_context)

    assert result["ok"] is True
    data = find_node(tool_context.state.graph, "iter1")["data"]
    assert data["type"] == "iteration"
    assert data["desc"] == "保留描述"
    assert "loop_variables" not in data
    assert "break_conditions" not in data
    assert "loop_count" not in data
    assert "logical_operator" not in data


def test_iteration_output_type_must_match_derived_aggregate(tool_context: ToolContext) -> None:
    _enable_image_tool(tool_context)
    tool_context.state.graph = _outer_graph()

    result = dispatch(
        _call(**_min_iteration_args(outputs=[{"name": "output", "type": "array[string]"}])),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "VARIABLE_TYPE_MISMATCH"


def test_compile_build_iteration_does_not_write_the_candidate_graph(tool_context: ToolContext) -> None:
    _enable_image_tool(tool_context)
    tool_context.state.graph = _outer_graph()
    frozen = tool_context.state.graph
    snapshot = deepcopy(frozen)
    tool_context.state.candidate_revision = 2

    compiled = compile_build_iteration(_call(**_min_iteration_args()), tool_context)

    assert not isinstance(compiled, dict)
    assert tool_context.state.graph is frozen
    assert tool_context.state.graph == snapshot
    assert tool_context.state.candidate_revision == 2
    assert compiled.compiled.base_revision == 2
    assert compiled.compiled.graph is not frozen


def test_iterator_claimed_type_mismatch_does_not_mutate_graph(tool_context: ToolContext) -> None:
    _enable_image_tool(tool_context)
    graph = _outer_graph()
    start = find_node(graph, "start")
    assert start is not None
    variables = start["data"]["variables"]
    assert isinstance(variables, list)
    variables.append({"variable": "tags", "label": "Tags", "type": "array[string]", "required": False})
    tool_context.state.graph = graph
    tool_context.state.candidate_revision = 3
    snapshot = tool_context.state.graph
    original = deepcopy(snapshot)

    result = dispatch(
        _call(
            **_min_iteration_args(
                iterator_selector=["start", "tags"],
                iterator_input_type="array[file]",
            )
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "VARIABLE_TYPE_MISMATCH"
    assert tool_context.state.graph is snapshot
    assert tool_context.state.graph == original
    assert tool_context.state.candidate_revision == 3


def test_non_array_iterator_does_not_mutate_graph(tool_context: ToolContext) -> None:
    _enable_image_tool(tool_context)
    tool_context.state.graph = _outer_graph()
    snapshot = tool_context.state.graph
    original = deepcopy(snapshot)

    result = dispatch(_call(**_min_iteration_args(iterator_selector=["start", "query"])), tool_context)

    assert result["ok"] is False
    assert result["error_code"] in {"INVALID_NODE_CONFIG", "VARIABLE_TYPE_MISMATCH"}
    assert tool_context.state.graph is snapshot
    assert tool_context.state.graph == original


def test_outside_ref_to_item_does_not_mutate_graph(tool_context: ToolContext) -> None:
    _enable_image_tool(tool_context)
    tool_context.state.graph = _outer_graph(end_reads="item")
    snapshot = tool_context.state.graph
    original = deepcopy(snapshot)

    result = dispatch(_call(**_min_iteration_args()), tool_context)

    assert result["ok"] is False
    assert result["error_code"] in {"EXTERNAL_REFERENCE_BROKEN", "UNRESOLVED_REFERENCE", "PRIVATE_CONTAINER_REFERENCE"}
    assert tool_context.state.graph is snapshot
    assert tool_context.state.graph == original


def test_inner_ref_to_other_container_item_does_not_mutate_graph(tool_context: ToolContext) -> None:
    _enable_image_tool(tool_context)
    graph = _outer_graph()
    graph = upsert_node(
        graph,
        node_id="other",
        node_type="iteration",
        title="另一容器",
        desc="",
        config={
            "iterator_selector": ["start", "images"],
            "iterator_input_type": "array[file]",
            "output_selector": ["other_child", "file"],
            "output_type": "array[file]",
        },
    )
    tool_context.state.graph = graph
    snapshot = tool_context.state.graph
    original = deepcopy(snapshot)

    result = dispatch(
        _call(**_min_iteration_args(children=[_worker_child(selector=["other", "item"])])),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "PRIVATE_CONTAINER_REFERENCE"
    assert tool_context.state.graph is snapshot
    assert tool_context.state.graph == original


def test_missing_round_output_does_not_mutate_graph(tool_context: ToolContext) -> None:
    _enable_image_tool(tool_context)
    tool_context.state.graph = _outer_graph()
    snapshot = tool_context.state.graph
    original = deepcopy(snapshot)

    result = dispatch(_call(**_min_iteration_args(output_selector=["worker", "missing"])), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_OUTPUT"
    assert tool_context.state.graph is snapshot
    assert tool_context.state.graph == original


def test_iteration_aggregates_boolean_child_output(tool_context: ToolContext) -> None:
    _enable_image_tool(tool_context, _boolean_entry())
    tool_context.state.graph = _outer_graph()
    flag_child = {
        "kind": "tool",
        "ref": "worker",
        "intent": {
            "binding": {"provider_name": "flag/provider", "tool_name": "flag"},
            "arguments": {"prompt": {"kind": "constant", "value": "x"}},
        },
    }

    result = dispatch(
        _call(
            **_min_iteration_args(
                children=[flag_child],
                output_selector=["worker", "ok"],
                outputs=[{"name": "output", "type": "array[boolean]"}],
            )
        ),
        tool_context,
    )

    assert result["ok"] is True
    data = find_node(tool_context.state.graph, "iter1")["data"]
    assert data["output_type"] == "array[boolean]"


def test_nested_container_is_rejected(tool_context: ToolContext) -> None:
    _enable_image_tool(tool_context)
    tool_context.state.graph = _outer_graph()
    snapshot = tool_context.state.graph
    original = deepcopy(snapshot)

    parent_result = dispatch(_call(**_min_iteration_args(parent="start")), tool_context)
    nested_result = dispatch(
        _call(
            **_min_iteration_args(
                children=[
                    {
                        "kind": "standard",
                        "ref": "inner",
                        "node_type": "iteration",
                        "intent": {"objective": "nested", "inputs": [], "outputs": [{"name": "file", "type": "file"}]},
                    }
                ],
                output_selector=["inner", "file"],
            )
        ),
        tool_context,
    )

    assert parent_result["ok"] is False
    assert parent_result["error_code"] == "NESTED_CONTAINER_UNSUPPORTED"
    assert nested_result["ok"] is False
    assert nested_result["error_code"] == "NESTED_CONTAINER_UNSUPPORTED"
    assert tool_context.state.graph is snapshot
    assert tool_context.state.graph == original
