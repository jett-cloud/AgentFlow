import json
from dataclasses import MISSING, fields, replace
from typing import Any

from jsonschema import Draft202012Validator

from core.workflow.generator.agent.tools.tools import (
    TERMINAL_TOOLS,
    TOOL_NAMES,
    TOOL_SCHEMAS,
    ToolContext,
    ToolEnv,
    ToolTurnState,
)
from core.workflow.generator.graph.graph_ops import upsert_node

_EXPECTED = {
    "submit_workflow_plan",
    "read_graph",
    "read_node",
    "build_node",
    "build_tool_node",
    "build_agent_node",
    "build_loop",
    "build_iteration",
    "delete_node",
    "connect",
    "disconnect",
    "inspect_node_schema",
    "activate_skills",
    "validate_graph",
    "search_datasets",
    "search_tools",
    "inspect_tool",
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
    assert len(TOOL_SCHEMAS) == 22


def test_workflow_plan_schema_exposes_structured_resources_but_not_verified_claims() -> None:
    serialized = json.dumps(_schema("submit_workflow_plan")["parameters"], sort_keys=True)

    assert '"dataset_id"' in serialized
    assert '"provider_name"' in serialized
    assert '"tool_name"' in serialized
    assert '"provider"' in serialized
    assert '"verified"' not in serialized


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
        if "oneOf" in node:
            for index, branch in enumerate(node["oneOf"]):
                assert_typed(branch, f"{path}.oneOf[{index}]")
            return
        assert node.get("type") in {"object", "array", "string", "number", "integer", "boolean", "null"}, path
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


def test_build_node_schema_has_structured_intent_and_update_forbids_type():
    parameters = _schema("build_node")["parameters"]
    properties = parameters["properties"]

    assert "config" not in properties
    assert "purpose" not in properties
    assert set(parameters["required"]) >= {"mode", "id", "intent"}
    assert properties["mode"]["enum"] == ["create", "update", "replace"]

    update_then: dict[str, Any] | None = None
    for clause in parameters.get("allOf", []):
        mode_schema = clause.get("if", {}).get("properties", {}).get("mode", {})
        if mode_schema.get("const") == "update":
            update_then = clause.get("then")
            break

    assert update_then is not None
    assert update_then.get("not") == {"required": ["type"]}
    intent = properties["intent"]
    assert intent["type"] == "object"
    assert set(intent["properties"]) >= {
        "objective",
        "behavior",
        "inputs",
        "outputs",
        "requirements",
        "tool",
        "tool_bindings",
        "agent_knowledge",
        "structure",
    }
    arguments = intent["properties"]["tool"]["properties"]["arguments"]["additionalProperties"]
    assert {branch["properties"]["kind"]["const"] for branch in arguments["oneOf"]} == {
        "variable",
        "template",
        "constant",
    }

    agent_knowledge = intent["properties"]["agent_knowledge"]
    assert agent_knowledge["properties"]["operation"]["enum"] == ["replace", "clear"]
    knowledge_set = agent_knowledge["properties"]["sets"]["items"]
    assert knowledge_set["additionalProperties"] is False
    assert knowledge_set["properties"]["retrieval_mode"]["enum"] == ["multiple"]
    assert knowledge_set["properties"]["query_mode"]["enum"] == ["generated_query", "user_query"]
    structure = intent["properties"]["structure"]
    assert {branch["properties"]["kind"]["const"] for branch in structure["oneOf"]} == {
        "start",
        "end",
        "answer",
        "template-transform",
        "llm",
        "code",
        "if-else",
    }


def test_build_node_constant_argument_schema_accepts_arbitrary_json_array_items() -> None:
    intent = _schema("build_node")["parameters"]["properties"]["intent"]
    arguments = intent["properties"]["tool"]["properties"]["arguments"]["additionalProperties"]
    constant = next(branch for branch in arguments["oneOf"] if branch["properties"]["kind"]["const"] == "constant")
    value_schema = constant["properties"]["value"]

    assert Draft202012Validator(value_schema).is_valid(["text", 1, False, None, {"nested": ["value"]}])


def test_build_node_variable_argument_schema_accepts_nested_selectors() -> None:
    intent = _schema("build_node")["parameters"]["properties"]["intent"]
    arguments = intent["properties"]["tool"]["properties"]["arguments"]["additionalProperties"]
    variable = next(branch for branch in arguments["oneOf"] if branch["properties"]["kind"]["const"] == "variable")

    assert Draft202012Validator(variable).is_valid(
        {"kind": "variable", "selector": ["iteration", "item", "source_image"]}
    )


def test_build_node_input_schema_accepts_nested_selectors() -> None:
    intent = _schema("build_node")["parameters"]["properties"]["intent"]

    assert Draft202012Validator(intent).is_valid(
        {
            "objective": "Read the nested title",
            "inputs": [{"source": ["iteration", "item", "title"], "role": "title"}],
        }
    )


def test_build_loop_schema_exposes_typed_children_and_edges() -> None:
    parameters = _schema("build_loop")["parameters"]
    child_schema = parameters["properties"]["children"]["items"]
    edge_schema = parameters["properties"]["edges"]["items"]

    assert "oneOf" in child_schema
    assert set(edge_schema["properties"]) >= {"source", "target", "source_handle"}
    assert set(parameters["required"]) >= {
        "mode",
        "id",
        "loop_count",
        "loop_variables",
        "children",
        "edges",
        "break_conditions",
        "outputs",
        "logical_operator",
    }


def test_build_iteration_schema_requires_complete_submission() -> None:
    parameters = _schema("build_iteration")["parameters"]

    assert set(parameters["required"]) >= {
        "mode",
        "id",
        "iterator_selector",
        "iterator_input_type",
        "output_selector",
        "children",
        "edges",
        "outputs",
        "is_parallel",
        "parallel_nums",
        "error_handle_mode",
        "flatten_output",
    }


def test_specialized_builder_schemas_hide_system_owned_and_secret_fields() -> None:
    forbidden = {"credential", "credentials", "secret", "parentId", "start_node_id"}

    for name in ("build_tool_node", "build_agent_node", "build_loop", "build_iteration"):
        rendered = str(_schema(name)["parameters"])
        for field in forbidden:
            assert field not in rendered, f"{name} exposes {field}"


def test_activate_skills_schema_enumerates_registered_skills():
    from core.workflow.generator.prompts.loader import registered_skill_names

    parameters = _schema("activate_skills")["parameters"]
    names = parameters["properties"]["names"]
    assert parameters["required"] == ["names"]
    assert names["type"] == "array"
    assert names["maxItems"] == 4
    assert names["items"]["type"] == "string"
    assert names["items"]["enum"] == list(registered_skill_names())
    assert "create-from-scratch" in names["items"]["enum"]
    assert "bind-resources" in names["items"]["enum"]
    assert "build-container" in names["items"]["enum"]
    assert "verify-and-finish" in names["items"]["enum"]


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


def test_inspect_tool_requires_an_exact_binding():
    parameters = _schema("inspect_tool")["parameters"]

    assert parameters["required"] == ["provider_name", "tool_name"]
    assert parameters["properties"] == {
        "provider_name": {"type": "string"},
        "tool_name": {"type": "string"},
    }


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
        "agent_model_entries",
        "models_available",
    }
    env_optional = {
        "require_resource_context",
        "hydrate_graph",
        "acceptance_runner",
        "authorize_live_acceptance",
        "environment_variables",
        "conversation_variables",
        "run_id",
        "run_epoch",
        "contract_rollout_stage",
    }
    state_names = {
        "graph",
        "candidate_revision",
        "last_validation_revision",
        "last_error_signature",
        "last_mutation_changed",
        "attempts",
        "graph_hash",
        "pending_plan_nodes",
        "compile_cache",
        "model_call_budget",
        "contract_protocol_version",
        "workflow_contract",
        "contract_revision",
        "contract_hash",
        "candidate_base_hash",
        "user_turn_evidence",
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
    assert state_fields["graph_hash"].default is None
    assert state_fields["contract_protocol_version"].default is None
    assert state_fields["workflow_contract"].default is None
    assert state_fields["contract_revision"].default == 0
    assert state_fields["contract_hash"].default is None
    assert state_fields["candidate_base_hash"].default is None
    assert state_fields["pending_plan_nodes"].default == ()


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
