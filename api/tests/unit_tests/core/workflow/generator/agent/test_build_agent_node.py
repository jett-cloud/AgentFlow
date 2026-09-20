import pytest
from jsonschema import Draft202012Validator

from core.workflow.generator.agent.tools.tools import TOOL_SCHEMAS, ToolContext, dispatch
from core.workflow.generator.agent.types import ToolCall
from core.workflow.generator.graph.graph_ops import empty_graph, find_node, upsert_node
from tests.unit_tests.core.workflow.generator.agent.conftest import set_env


class _ExplodingLLM:
    def iter_json(self, *, messages, stage):
        raise AssertionError("Agent compilation must not call the node-builder LLM")


def _call(name: str, **arguments: object) -> ToolCall:
    return {"id": "c1", "name": name, "arguments": arguments}


def _schema(name: str) -> dict[str, object]:
    return {item["name"]: dict(item) for item in TOOL_SCHEMAS}[name]


def _builtin_entry() -> dict[str, object]:
    return {
        "provider_name": "web/search",
        "provider_type": "builtin",
        "plugin_id": "",
        "tool_name": "search",
        "tool_label": "Search",
        "description": "Search the web",
        "parameters": ({"name": "query", "type": "string", "form": "llm", "required": True},),
        "parameter_names": ("query",),
        "output_names": ("text",),
        "outputs": ({"name": "text", "type": "string"},),
    }


def _mcp_entry() -> dict[str, object]:
    return {
        "provider_name": "github-official",
        "provider_type": "mcp",
        "plugin_id": "",
        "tool_name": "get_file_contents",
        "tool_label": "Get file",
        "description": "Read a GitHub file",
        "parameters": ({"name": "path", "type": "string", "form": "llm", "required": True},),
        "parameter_names": ("path",),
    }


def _enable_catalogues(context: ToolContext) -> None:
    builtin = _builtin_entry()
    mcp = _mcp_entry()
    set_env(
        context,
        tools_available=True,
        installed_tools={
            (str(builtin["provider_name"]), str(builtin["tool_name"])),
            (str(mcp["provider_name"]), str(mcp["tool_name"])),
        },
        tool_entries=[builtin, mcp],
        knowledge_available=True,
        installed_dataset_ids={"ds-live"},
        knowledge_entries=[{"id": "ds-live", "name": "Live", "description": "Live docs"}],
        llm_client=_ExplodingLLM(),
    )


def _start_query(context: ToolContext) -> None:
    context.state.graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="开始",
        desc="",
        config={"variables": [{"variable": "query", "type": "string"}]},
    )


def _create_args(**changes: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "mode": "create",
        "id": "agent_1",
        "title": "助手",
        "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
        "instruction": "调查问题",
        "inputs": [{"source": ["start", "query"], "role": "question"}],
        "outputs": [{"name": "result", "type": "string"}],
        "tools": [{"provider_name": "web/search", "tool_name": "search"}],
        "mcp_tools": [{"provider_name": "github-official", "tool_name": "get_file_contents"}],
        "knowledge": {"operation": "replace", "sets": [{"name": "Product docs", "dataset_ids": ["ds-live"]}]},
    }
    arguments.update(changes)
    return arguments


def test_tool_schemas_contains_build_agent_node_with_required_fields() -> None:
    schema = _schema("build_agent_node")
    parameters = schema["parameters"]
    properties = parameters["properties"]

    assert set(parameters["required"]) >= {"mode", "id", "model", "instruction", "inputs", "outputs"}
    assert parameters["additionalProperties"] is False
    assert properties["mode"]["enum"] == ["create", "update", "replace"]
    assert set(properties) >= {
        "mode",
        "id",
        "title",
        "model",
        "instruction",
        "inputs",
        "outputs",
        "tools",
        "mcp_tools",
        "knowledge",
    }
    assert properties["model"]["additionalProperties"] is False
    assert set(properties["model"]["required"]) == {"provider", "name"}
    assert properties["tools"]["items"]["additionalProperties"] is False
    assert properties["mcp_tools"]["items"]["additionalProperties"] is False

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


def test_build_agent_node_rejects_extra_fields_at_runtime(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)

    result = dispatch(_call("build_agent_node", **_create_args(), intent={"objective": "nope"}), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert find_node(tool_context.state.graph, "agent_1") is None


def test_build_agent_node_missing_model_is_invalid_argument(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)
    args = _create_args()
    del args["model"]

    result = dispatch(_call("build_agent_node", **args), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert find_node(tool_context.state.graph, "agent_1") is None


def test_build_agent_node_rejects_runtime_unsafe_id(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)

    result = dispatch(_call("build_agent_node", **_create_args(id="agent-1")), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_NODE_ID"
    assert find_node(tool_context.state.graph, "agent-1") is None


def test_build_agent_node_rejects_unknown_model(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)

    result = dispatch(
        _call(
            "build_agent_node",
            **_create_args(model={"provider": "missing", "name": "ghost", "mode": "chat"}),
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_MODEL"
    assert find_node(tool_context.state.graph, "agent_1") is None


def test_build_agent_node_rejects_unavailable_model_catalogue(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)
    set_env(tool_context, models_available=False, agent_model_entries=())

    result = dispatch(_call("build_agent_node", **_create_args()), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "CAPABILITY_UNAVAILABLE"
    assert find_node(tool_context.state.graph, "agent_1") is None


@pytest.mark.parametrize("binding_field", ["tools", "mcp_tools"])
def test_build_agent_node_rejects_binding_without_parameter_schema(
    tool_context: ToolContext,
    binding_field: str,
) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)
    entry = _builtin_entry() if binding_field == "tools" else _mcp_entry()
    entry.pop("parameters")
    other_entry = _mcp_entry() if binding_field == "tools" else _builtin_entry()
    set_env(tool_context, tool_entries=[entry, other_entry])
    selected_binding = [{"provider_name": entry["provider_name"], "tool_name": entry["tool_name"]}]
    changes = {binding_field: selected_binding}
    if binding_field == "tools":
        changes["mcp_tools"] = []
    else:
        changes["tools"] = []

    result = dispatch(_call("build_agent_node", **_create_args(**changes)), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "TOOL_SCHEMA_UNAVAILABLE"
    assert find_node(tool_context.state.graph, "agent_1") is None


def test_build_agent_node_unavailable_input_selector_is_rejected(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)

    result = dispatch(
        _call(
            "build_agent_node",
            **_create_args(inputs=[{"source": ["start", "missing"], "role": "question"}]),
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] in {"UNKNOWN_OUTPUT", "REFERENCE_NOT_AVAILABLE", "UNKNOWN_NODE_REFERENCE"}
    assert find_node(tool_context.state.graph, "agent_1") is None


def test_build_agent_node_unknown_builtin_tool_is_unknown_tool(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)

    result = dispatch(
        _call(
            "build_agent_node",
            **_create_args(tools=[{"provider_name": "missing", "tool_name": "nope"}]),
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_TOOL"
    assert find_node(tool_context.state.graph, "agent_1") is None


def test_build_agent_node_unknown_mcp_is_unknown_tool(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)

    result = dispatch(
        _call(
            "build_agent_node",
            **_create_args(mcp_tools=[{"provider_name": "missing-mcp", "tool_name": "list"}]),
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_TOOL"
    assert find_node(tool_context.state.graph, "agent_1") is None


def test_build_agent_node_unknown_dataset_is_unknown_dataset(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)

    result = dispatch(
        _call(
            "build_agent_node",
            **_create_args(
                knowledge={"operation": "replace", "sets": [{"name": "Docs", "dataset_ids": ["ds-missing"]}]}
            ),
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_DATASET"
    assert find_node(tool_context.state.graph, "agent_1") is None


def test_build_agent_node_duplicate_bindings_are_invalid_argument(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)
    binding = {"provider_name": "web/search", "tool_name": "search"}

    result = dispatch(
        _call("build_agent_node", **_create_args(tools=[binding, binding], mcp_tools=[])),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert find_node(tool_context.state.graph, "agent_1") is None


def test_build_agent_node_knowledge_replace_empty_set_is_invalid_argument(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)

    result = dispatch(
        _call("build_agent_node", **_create_args(knowledge={"operation": "replace", "sets": []})),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert find_node(tool_context.state.graph, "agent_1") is None


def test_build_agent_node_binds_tool_mcp_and_knowledge_together(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)

    result = dispatch(_call("build_agent_node", **_create_args()), tool_context)
    node = find_node(tool_context.state.graph, "agent_1")

    assert result["ok"] is True
    assert result["changed"] is True
    assert node is not None
    data = node["data"]
    assert data["type"] == "agent"
    assert data["version"] == "2"
    assert data["agent_node_kind"] == "dify_agent"
    assert data["agent_binding"] == {"binding_type": "inline_agent"}
    assert data["agent_task"]
    assert data["model"]["provider"] == "openai"
    assert data["model"]["name"] == "gpt-4o"
    tools = data["dify_tools"]
    assert {item["provider_type"] for item in tools} == {"builtin", "mcp"}
    assert any(item["provider_id"] == "web/search" and item["tool_name"] == "search" for item in tools)
    assert any(item["provider_id"] == "github-official" and item["tool_name"] == "get_file_contents" for item in tools)
    search = next(item for item in tools if item["tool_name"] == "search")
    assert "query" in str(search.get("parameters") or search.get("description") or "")
    assert [dataset["id"] for item in data["knowledge"]["sets"] for dataset in item["datasets"]] == ["ds-live"]
    assert all(item["data"].get("type") != "knowledge-retrieval" for item in tool_context.state.graph["nodes"])


def test_build_agent_node_does_not_write_sibling_knowledge_retrieval(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)

    dispatch(_call("build_agent_node", **_create_args()), tool_context)
    types = [str(node["data"].get("type")) for node in tool_context.state.graph["nodes"]]

    assert "agent" in types
    assert "knowledge-retrieval" not in types
    node = find_node(tool_context.state.graph, "agent_1")
    assert node is not None
    assert "ds-live" in str(node["data"].get("knowledge"))


def test_build_agent_node_compiles_nested_declared_output_shape(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)

    result = dispatch(
        _call(
            "build_agent_node",
            **_create_args(
                outputs=[
                    {
                        "name": "result",
                        "type": "object",
                        "children": {
                            "answer": {"type": "string"},
                            "evidence": {
                                "type": "array[object]",
                                "children": {"source": {"type": "string"}},
                            },
                        },
                    }
                ]
            ),
        ),
        tool_context,
    )
    node = find_node(tool_context.state.graph, "agent_1")

    assert result["ok"] is True
    assert node is not None
    assert node["data"]["agent_declared_outputs"] == [
        {
            "name": "result",
            "type": "object",
            "children": [
                {"name": "answer", "type": "string"},
                {
                    "name": "evidence",
                    "type": "array",
                    "array_item": {
                        "type": "object",
                        "children": [{"name": "source", "type": "string"}],
                    },
                },
            ],
        }
    ]


def test_build_agent_node_update_omits_knowledge_and_preserves_it(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)
    created = dispatch(_call("build_agent_node", **_create_args()), tool_context)
    assert created["ok"] is True
    old_knowledge = find_node(tool_context.state.graph, "agent_1")["data"]["knowledge"]

    result = dispatch(
        _call(
            "build_agent_node",
            mode="update",
            id="agent_1",
            model={"provider": "openai", "name": "gpt-4.1"},
            instruction="改写任务",
            inputs=[{"source": ["start", "query"], "role": "question"}],
            outputs=[{"name": "result", "type": "string"}],
            tools=[],
            mcp_tools=[],
        ),
        tool_context,
    )
    node = find_node(tool_context.state.graph, "agent_1")

    assert result["ok"] is True
    assert node["data"]["knowledge"] == old_knowledge
    assert node["data"]["model"]["name"] == "gpt-4.1"
    assert node["data"]["agent_task"].startswith("改写任务")
    assert node["data"]["dify_tools"] == []


def test_build_agent_node_update_clear_removes_knowledge(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)
    assert dispatch(_call("build_agent_node", **_create_args()), tool_context)["ok"] is True

    result = dispatch(
        _call(
            "build_agent_node",
            mode="update",
            id="agent_1",
            model={"provider": "openai", "name": "gpt-4o"},
            instruction="调查问题",
            inputs=[{"source": ["start", "query"], "role": "question"}],
            outputs=[{"name": "result", "type": "string"}],
            tools=[],
            mcp_tools=[],
            knowledge={"operation": "clear"},
        ),
        tool_context,
    )
    node = find_node(tool_context.state.graph, "agent_1")

    assert result["ok"] is True
    assert node["data"]["knowledge"] == {"sets": []}


def test_build_agent_node_create_strips_invented_binding_ids(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)

    result = dispatch(_call("build_agent_node", **_create_args()), tool_context)
    node = find_node(tool_context.state.graph, "agent_1")

    assert result["ok"] is True
    binding = node["data"]["agent_binding"]
    assert "agent_id" not in binding
    assert "current_snapshot_id" not in binding
    assert node["data"]["assist_binding_manifest"] == {
        "binding_id": "agent_1",
        "tool_keys": [["web/search", "search"], ["github-official", "get_file_contents"]],
        "dataset_ids": ["ds-live"],
    }


def test_build_agent_node_update_restores_trusted_binding_ids(tool_context: ToolContext) -> None:
    _enable_catalogues(tool_context)
    _start_query(tool_context)
    tool_context.state.graph = upsert_node(
        tool_context.state.graph,
        node_id="agent_1",
        node_type="agent",
        title="助手",
        desc="",
        config={
            "version": "2",
            "agent_node_kind": "dify_agent",
            "agent_task": "旧任务",
            "agent_binding": {
                "binding_type": "inline_agent",
                "agent_id": "real-agent",
                "current_snapshot_id": "real-snap",
            },
            "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
        },
    )

    result = dispatch(
        _call(
            "build_agent_node",
            mode="update",
            id="agent_1",
            model={"provider": "openai", "name": "gpt-4o"},
            instruction="新任务",
            inputs=[{"source": ["start", "query"], "role": "question"}],
            outputs=[],
            tools=[],
            mcp_tools=[],
        ),
        tool_context,
    )
    node = find_node(tool_context.state.graph, "agent_1")

    assert result["ok"] is True
    assert node["data"]["agent_binding"]["agent_id"] == "real-agent"
    assert node["data"]["agent_binding"]["current_snapshot_id"] == "real-snap"


def test_build_node_still_rejects_agent_type(tool_context: ToolContext) -> None:
    result = dispatch(
        _call(
            "build_node",
            mode="create",
            id="agent_1",
            type="agent",
            title="助手",
            intent={"objective": "调查"},
        ),
        tool_context,
    )
    assert result["ok"] is False
    assert result["error_code"] == "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE"
    assert find_node(tool_context.state.graph, "agent_1") is None
