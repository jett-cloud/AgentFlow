from dataclasses import MISSING, fields, replace
from typing import Any

from core.workflow.generator.agent.graph_ops import upsert_node
from core.workflow.generator.agent.tools import (
    TERMINAL_TOOLS,
    TOOL_NAMES,
    TOOL_SCHEMAS,
    ToolContext,
    ToolEnv,
    ToolTurnState,
)

_EXPECTED = {
    "read_graph",
    "read_node",
    "build_node",
    "delete_node",
    "connect",
    "disconnect",
    "inspect_node_schema",
    "validate_graph",
    "search_datasets",
    "search_tools",
    "run_acceptance",
    "inspect_attempt",
    "ask_user",
    "fail",
    "finish",
}

_LEGACY_CONFIG_TOOLS = {"write_node", "upsert_node", "patch_node"}


def _schema(name: str) -> dict[str, Any]:
    # Copied so a test can never mutate the module-level declaration.
    return {schema["name"]: dict(schema) for schema in TOOL_SCHEMAS}[name]


def test_tool_names_match_the_declared_schemas():
    assert TOOL_NAMES == _EXPECTED
    assert {schema["name"] for schema in TOOL_SCHEMAS} == _EXPECTED
    assert len(TOOL_SCHEMAS) == 15


def test_legacy_config_writing_tools_are_not_advertised():
    assert _LEGACY_CONFIG_TOOLS.isdisjoint(TOOL_NAMES)
    for schema in TOOL_SCHEMAS:
        assert schema["name"] not in _LEGACY_CONFIG_TOOLS


def test_tool_names_are_declared_exactly_once():
    # TOOL_NAMES is a frozenset, so a duplicated declaration would collapse
    # silently and leave the dispatcher with an unreachable second schema.
    assert len(TOOL_SCHEMAS) == len(TOOL_NAMES)


def test_every_schema_declares_an_object_parameter_block():
    for schema in TOOL_SCHEMAS:
        assert schema["description"].strip(), schema["name"]
        parameters = schema["parameters"]
        assert parameters["type"] == "object", schema["name"]
        assert isinstance(parameters["properties"], dict), schema["name"]
        assert isinstance(parameters.get("required", []), list), schema["name"]


def test_every_schema_declares_only_the_advertised_keys():
    # Task 6 renders these dicts into the system prompt; an extra key would be
    # advertised to the model without the dispatcher ever enforcing it.
    for schema in TOOL_SCHEMAS:
        assert set(schema) == {"name", "description", "parameters"}, schema["name"]


def test_every_required_property_is_declared():
    for schema in TOOL_SCHEMAS:
        properties = schema["parameters"]["properties"]
        for name in schema["parameters"].get("required", []):
            assert name in properties, f"{schema['name']}.{name}"


def test_every_property_declares_a_json_type():
    def assert_typed(node: dict[str, Any], path: str) -> None:
        assert node.get("type") in {"object", "array", "string"}, path
        for name, child in node.get("properties", {}).items():
            assert_typed(child, f"{path}.{name}")
        items = node.get("items")
        if items is not None:
            assert_typed(items, f"{path}[]")

    for schema in TOOL_SCHEMAS:
        assert_typed(schema["parameters"], schema["name"])


def test_parameterless_tools_declare_an_empty_property_block():
    for name in ("read_graph", "validate_graph"):
        parameters = _schema(name)["parameters"]
        assert parameters["properties"] == {}, name
        assert parameters["required"] == [], name


def test_build_node_schema_has_no_config_and_update_forbids_type():
    parameters = _schema("build_node")["parameters"]
    properties = parameters["properties"]

    assert "config" not in properties
    assert set(parameters["required"]) >= {"mode", "id", "purpose"}
    assert properties["mode"]["enum"] == ["create", "update", "replace"]

    update_then: dict[str, Any] | None = None
    for clause in parameters.get("allOf", []):
        mode_schema = clause.get("if", {}).get("properties", {}).get("mode", {})
        if mode_schema.get("const") == "update":
            update_then = clause.get("then")
            break

    assert update_then is not None
    assert update_then.get("not") == {"required": ["type"]}


def test_single_argument_tools_require_that_argument():
    assert _schema("delete_node")["parameters"]["required"] == ["node_id"]
    assert _schema("read_node")["parameters"]["required"] == ["id"]
    assert _schema("finish")["parameters"]["required"] == ["summary"]
    assert _schema("fail")["parameters"]["required"] == ["reason"]
    assert _schema("ask_user")["parameters"]["required"] == ["questions"]
    assert _schema("inspect_node_schema")["parameters"]["required"] == ["node_type"]
    assert _schema("inspect_attempt")["parameters"]["required"] == ["attempt_id"]
    for name in ("search_datasets", "search_tools"):
        assert _schema(name)["parameters"]["required"] == ["query"], name


def test_connect_declares_an_optional_source_handle():
    parameters = _schema("connect")["parameters"]

    assert "source_handle" in parameters["properties"]
    assert parameters["required"] == ["source", "target"]


def test_disconnect_declares_an_optional_source_handle():
    parameters = _schema("disconnect")["parameters"]

    assert "source_handle" in parameters["properties"]
    assert parameters["required"] == ["source", "target"]


def test_ask_user_declares_the_question_shape_the_frontend_renders():
    question = _schema("ask_user")["parameters"]["properties"]["questions"]["items"]

    assert question["required"] == ["id", "question", "kind"]
    assert question["properties"]["kind"]["enum"] == ["text", "single_choice", "multi_choice"]
    option = question["properties"]["options"]["items"]
    assert option["required"] == ["value", "label"]
    description = _schema("ask_user")["description"].lower()
    assert "single_choice" in description
    assert "language" in description


def test_terminal_tools_are_a_subset_of_all_tools():
    assert {"ask_user", "fail", "finish"} == TERMINAL_TOOLS
    assert TERMINAL_TOOLS <= TOOL_NAMES


def test_tool_context_requires_every_field_a_tool_may_touch():
    env_fields = {field.name: field for field in fields(ToolEnv)}
    state_fields = {field.name: field for field in fields(ToolTurnState)}
    context_fields = {field.name: field for field in fields(ToolContext)}

    env_required = {
        "tenant_id",
        "mode",
        "tool_entries",
        "knowledge_entries",
        "installed_tools",
        "installed_dataset_ids",
        "knowledge_available",
        "tools_available",
        "builder_input",
        "llm_client",
    }
    env_optional = {"hydrate_graph", "acceptance_runner", "live_run_authorized"}
    state_names = {
        "graph",
        "candidate_revision",
        "last_validation_revision",
        "last_error_signature",
        "last_mutation_changed",
        "attempts",
        "graph_hash",
    }
    assert set(env_fields) == env_required | env_optional
    assert set(state_fields) == state_names
    assert set(context_fields) == {"env", "state"}
    # Injected run inputs have no defaults: a tool must never silently read a
    # placeholder tenant or an empty catalogue because a caller forgot to pass one.
    for name in env_required:
        field = env_fields[name]
        assert field.default is MISSING, name
        assert field.default_factory is MISSING, name
    assert state_fields["graph"].default is MISSING
    assert state_fields["candidate_revision"].default == 0
    assert env_fields["hydrate_graph"].default is None
    assert state_fields["last_validation_revision"].default is None
    assert state_fields["last_error_signature"].default is None
    assert state_fields["last_mutation_changed"].default is False
    assert env_fields["acceptance_runner"].default is None
    assert env_fields["live_run_authorized"].default is False
    assert state_fields["graph_hash"].default is None


def test_tool_context_graph_is_rebindable(tool_context: ToolContext):
    tool_context.state.graph = upsert_node(
        tool_context.state.graph, node_id="start", node_type="start", title="开始", desc="", config={"variables": []}
    )

    assert [node["id"] for node in tool_context.state.graph["nodes"]] == ["start"]


def test_tool_context_treats_none_as_the_catalogue_unavailable_sentinel(tool_context: ToolContext):
    assert tool_context.env.knowledge_available is False
    assert tool_context.env.tools_available is False
    assert tool_context.env.installed_tools is None
    assert tool_context.env.installed_dataset_ids is None

    tool_context.env = replace(
        tool_context.env,
        knowledge_available=True,
        tools_available=True,
        installed_tools={("langgenius/google", "google_search")},
        installed_dataset_ids={"dataset-1"},
    )

    assert tool_context.env.installed_tools == {("langgenius/google", "google_search")}
    assert tool_context.env.installed_dataset_ids == {"dataset-1"}
