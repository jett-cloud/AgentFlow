from collections.abc import Callable

import pytest
from pydantic import ValidationError

from core.workflow.generator.compiler.intents.node_intent import parse_node_build_intent
from core.workflow.generator.compiler.node_compile_context import NodeCompileContext
from core.workflow.generator.compiler.node_intent_compiler import NodeIntentCompileError, compile_node_intent
from core.workflow.generator.validation.condition_operators import validate_condition_value
from core.workflow.generator.variables.type_unification import unify_branch_types
from core.workflow.graph.adapters.node_config_schema import validate_workflow_node_data


def _context(types: dict[tuple[str, ...], str]) -> NodeCompileContext:
    resolver: Callable[[tuple[str, ...]], str | None] = types.get
    return NodeCompileContext(
        node_id="target",
        surface="top_level",
        mode="create",
        source_type_resolver=resolver,
        model_entries=({"provider": "openai", "name": "gpt-4o", "model_type": "llm", "features": ()},),
        installed_dataset_ids=frozenset({"dataset-1"}),
        http_credential_reference_ids=frozenset(),
        human_input_delivery_capabilities=frozenset({"webapp", "email"}),
        human_input_member_reference_ids=frozenset({"member-1"}),
    )


def _compile(node_type: str, structure: dict[str, object], types: dict[tuple[str, ...], str]) -> dict:
    intent = parse_node_build_intent(
        node_type=node_type,
        raw={"objective": "Build the node", "structure": structure},
    )
    config = compile_node_intent(intent=intent, context=_context(types), base_config={})
    validate_workflow_node_data({"id": "target", "data": {"type": node_type, **config}})
    return config


def test_if_else_derives_var_type_and_deterministic_condition_id() -> None:
    structure = {
        "kind": "if-else",
        "cases": [
            {
                "id": "positive",
                "conditions": [{"source": ["start", "score"], "operator": ">", "value": "10"}],
            }
        ],
    }

    first = _compile("if-else", structure, {("start", "score"): "number"})
    second = _compile("if-else", structure, {("start", "score"): "number"})

    condition = first["cases"][0]["conditions"][0]
    assert condition["varType"] == "number"
    assert condition["value"] == "10"
    assert condition["id"] == second["cases"][0]["conditions"][0]["id"]
    assert "_targetBranches" not in first

    intent = parse_node_build_intent(node_type="if-else", raw={"objective": "Update", "structure": structure})
    updated = compile_node_intent(
        intent=intent,
        context=_context({("start", "score"): "number"}),
        base_config={"conditions": [{"stale": True}], "logical_operator": "or", "_targetBranches": []},
    )
    assert "conditions" not in updated
    assert "logical_operator" not in updated
    assert "_targetBranches" not in updated


def test_if_else_rejects_operator_for_confirmed_source_type() -> None:
    with pytest.raises(NodeIntentCompileError) as exc_info:
        _compile(
            "if-else",
            {
                "kind": "if-else",
                "cases": [
                    {
                        "id": "bad",
                        "conditions": [{"source": ["start", "score"], "operator": "contains", "value": "1"}],
                    }
                ],
            },
            {("start", "score"): "number"},
        )

    assert exc_info.value.code == "INVALID_CONDITION"
    assert exc_info.value.path == "structure.cases[0].conditions[0].operator"


def test_if_else_intent_rejects_agent_supplied_var_type() -> None:
    with pytest.raises(ValidationError):
        parse_node_build_intent(
            node_type="if-else",
            raw={
                "objective": "Branch",
                "structure": {
                    "kind": "if-else",
                    "cases": [
                        {
                            "id": "yes",
                            "conditions": [
                                {
                                    "source": ["start", "query"],
                                    "type": "string",
                                    "operator": "contains",
                                    "value": "yes",
                                }
                            ],
                        }
                    ],
                },
            },
        )


@pytest.mark.parametrize(
    ("value_type", "operator", "value", "expected"),
    [
        ("string", "contains", "x", "x"),
        ("number", ">", "2.5", "2.5"),
        ("number", "=", 0, "0"),
        ("boolean", "is", True, True),
        ("object", "empty", None, None),
        ("array[string]", "contains", "x", "x"),
        ("array[number]", "contains", "2", "2"),
        ("array[boolean]", "contains", False, False),
        ("array[object]", "not empty", None, None),
        ("file", "exists", None, None),
        ("array[file]", "not empty", None, None),
    ],
)
def test_condition_rules_cover_canonical_types(value_type: str, operator: str, value: object, expected: object) -> None:
    assert validate_condition_value(value_type=value_type, operator=operator, value=value) == expected


@pytest.mark.parametrize(
    ("value_type", "operator", "value"),
    [
        ("number", "contains", "2"),
        ("boolean", "is", "true"),
        ("string", "empty", "redundant"),
        ("array[number]", "contains", "NaN"),
    ],
)
def test_condition_rules_reject_wrong_operator_or_value(value_type: str, operator: str, value: object) -> None:
    with pytest.raises(ValueError):
        validate_condition_value(value_type=value_type, operator=operator, value=value)


def test_question_classifier_compiles_model_branches_and_query() -> None:
    config = _compile(
        "question-classifier",
        {
            "kind": "question-classifier",
            "query": ["start", "query"],
            "model": {"provider": "openai", "name": "gpt-4o"},
            "classes": [
                {"id": "sales", "name": "Sales"},
                {"id": "support", "name": "Support", "label": "Help"},
            ],
        },
        {("start", "query"): "string"},
    )

    assert config["query_variable_selector"] == ["start", "query"]
    assert config["_targetBranches"] == [
        {"id": "sales", "name": ""},
        {"id": "support", "name": ""},
    ]
    assert config["vision"] == {"enabled": False}


def test_question_classifier_rejects_unknown_model_and_non_string_query() -> None:
    structure = {
        "kind": "question-classifier",
        "query": ["start", "query"],
        "model": {"provider": "invented", "name": "missing"},
        "classes": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
    }
    with pytest.raises(NodeIntentCompileError) as exc_info:
        _compile("question-classifier", structure, {("start", "query"): "string"})
    assert exc_info.value.code == "UNKNOWN_MODEL"
    assert exc_info.value.path == "structure.model"

    structure["model"] = {"provider": "openai", "name": "gpt-4o"}
    with pytest.raises(NodeIntentCompileError) as exc_info:
        _compile("question-classifier", structure, {("start", "query"): "number"})
    assert exc_info.value.code == "VARIABLE_TYPE_MISMATCH"
    assert exc_info.value.path == "structure.query"


@pytest.mark.parametrize(
    "classes",
    [
        [{"id": "only", "name": "Only"}],
        [{"id": "same", "name": "A"}, {"id": "same", "name": "B"}],
        [{"id": "a", "name": "Same"}, {"id": "b", "name": "Same"}],
    ],
)
def test_question_classifier_requires_two_unique_classes(classes: list[dict[str, str]]) -> None:
    with pytest.raises(ValidationError):
        parse_node_build_intent(
            node_type="question-classifier",
            raw={
                "objective": "Route",
                "structure": {
                    "kind": "question-classifier",
                    "query": ["start", "query"],
                    "model": {"provider": "openai", "name": "gpt-4o"},
                    "classes": classes,
                },
            },
        )


def test_parameter_extractor_derives_runtime_outputs_from_parameters() -> None:
    config = _compile(
        "parameter-extractor",
        {
            "kind": "parameter-extractor",
            "query": ["start", "query"],
            "model": {"provider": "openai", "name": "gpt-4o"},
            "parameters": [{"name": "count", "type": "number", "description": "Requested count", "required": True}],
        },
        {("start", "query"): "string"},
    )

    assert config["parameters"] == [
        {"name": "count", "type": "number", "description": "Requested count", "required": True}
    ]
    assert config["reasoning_mode"] == "function_call"


def test_parameter_extractor_rejects_duplicate_outputs_and_agent_declared_outputs() -> None:
    structure = {
        "kind": "parameter-extractor",
        "query": ["start", "query"],
        "model": {"provider": "openai", "name": "gpt-4o"},
        "parameters": [
            {"name": "topic", "type": "string", "description": "Topic"},
            {"name": "topic", "type": "string", "description": "Again"},
        ],
    }
    with pytest.raises(ValidationError, match="unique"):
        parse_node_build_intent(node_type="parameter-extractor", raw={"objective": "Extract", "structure": structure})

    structure["parameters"] = [{"name": "topic", "type": "string", "description": "Topic"}]
    with pytest.raises(ValueError, match="derived"):
        parse_node_build_intent(
            node_type="parameter-extractor",
            raw={
                "objective": "Extract",
                "outputs": [{"name": "topic", "type": "string"}],
                "structure": structure,
            },
        )


def test_variable_aggregator_unifies_aliases_and_rejects_incompatible_types() -> None:
    config = _compile(
        "variable-aggregator",
        {
            "kind": "variable-aggregator",
            "sources": [["left", "value"], ["right", "value"]],
        },
        {("left", "value"): "integer", ("right", "value"): "number"},
    )
    assert config["output_type"] == "number"
    assert config["variables"] == [["left", "value"], ["right", "value"]]

    with pytest.raises(NodeIntentCompileError) as exc_info:
        _compile(
            "variable-aggregator",
            {
                "kind": "variable-aggregator",
                "sources": [["left", "value"], ["right", "value"]],
            },
            {("left", "value"): "string", ("right", "value"): "number"},
        )
    assert exc_info.value.code == "INCOMPATIBLE_BRANCH_TYPES"
    assert exc_info.value.path == "structure.sources"


@pytest.mark.parametrize("value_types", [("any", "any"), ("string", "number")])
def test_type_unification_never_falls_back_to_any(value_types: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        unify_branch_types(value_types)


def test_list_operator_distinguishes_scalar_and_object_arrays() -> None:
    scalar = _compile(
        "list-operator",
        {
            "kind": "list-operator",
            "source": ["start", "scores"],
            "filters": [{"operator": ">", "value": "5"}],
            "limit": 10,
        },
        {("start", "scores"): "array[number]"},
    )
    assert scalar["filter_by"]["conditions"][0]["comparison_operator"] == ">"
    assert scalar["limit"] == {"enabled": True, "size": 10}

    objects = _compile(
        "list-operator",
        {
            "kind": "list-operator",
            "source": ["start", "rows"],
            "filters": [{"key": "name", "operator": "contains", "value": "A"}],
            "sort": {"key": "name", "direction": "desc"},
            "extract_serial": 2,
        },
        {("start", "rows"): "array[object]"},
    )
    assert objects["order_by"] == {"enabled": True, "key": "name", "value": "desc"}
    assert objects["extract_by"] == {"enabled": True, "serial": "2"}


def test_list_operator_rejects_non_array_and_wrong_key_shape() -> None:
    with pytest.raises(NodeIntentCompileError) as exc_info:
        _compile(
            "list-operator",
            {"kind": "list-operator", "source": ["start", "query"]},
            {("start", "query"): "string"},
        )
    assert exc_info.value.code == "VARIABLE_TYPE_MISMATCH"

    with pytest.raises(NodeIntentCompileError) as exc_info:
        _compile(
            "list-operator",
            {
                "kind": "list-operator",
                "source": ["start", "scores"],
                "sort": {"key": "score"},
            },
            {("start", "scores"): "array[number]"},
        )
    assert exc_info.value.path == "structure.sort.key"


@pytest.mark.parametrize(("field", "value"), [("limit", 0), ("limit", 1001), ("extract_serial", 0)])
def test_list_operator_ranges_are_validated_in_intent(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        parse_node_build_intent(
            node_type="list-operator",
            raw={
                "objective": "Process list",
                "structure": {"kind": "list-operator", "source": ["start", "items"], field: value},
            },
        )


def test_knowledge_retrieval_compiles_snapshot_backed_multiple_retrieval() -> None:
    config = _compile(
        "knowledge-retrieval",
        {
            "kind": "knowledge-retrieval",
            "dataset_ids": ["dataset-1"],
            "query": ["start", "query"],
            "top_k": 6,
            "score_threshold": 0.4,
        },
        {("start", "query"): "string"},
    )

    assert config["dataset_ids"] == ["dataset-1"]
    assert config["query_variable_selector"] == ["start", "query"]
    assert config["multiple_retrieval_config"]["top_k"] == 6
    assert config["multiple_retrieval_config"]["reranking_enable"] is False


def test_knowledge_retrieval_distinguishes_unavailable_and_unknown_dataset() -> None:
    intent = parse_node_build_intent(
        node_type="knowledge-retrieval",
        raw={
            "objective": "Retrieve",
            "structure": {
                "kind": "knowledge-retrieval",
                "dataset_ids": ["missing"],
                "query": ["start", "query"],
            },
        },
    )
    with pytest.raises(NodeIntentCompileError) as exc_info:
        compile_node_intent(
            intent=intent,
            context=_context({("start", "query"): "string"}),
            base_config={},
        )
    assert exc_info.value.code == "UNKNOWN_DATASET"
    assert exc_info.value.path == "structure.dataset_ids[0]"

    unavailable = _context({("start", "query"): "string"})
    unavailable = NodeCompileContext(
        node_id=unavailable.node_id,
        surface=unavailable.surface,
        mode=unavailable.mode,
        source_type_resolver=unavailable.source_type_resolver,
        model_entries=unavailable.model_entries,
    )
    with pytest.raises(NodeIntentCompileError) as exc_info:
        compile_node_intent(intent=intent, context=unavailable, base_config={})
    assert exc_info.value.code == "CAPABILITY_UNAVAILABLE"


def test_http_request_compiles_semantic_fields_and_file_source() -> None:
    config = _compile(
        "http-request",
        {
            "kind": "http-request",
            "method": "post",
            "url": "https://example.com/items?q={{#start.query#}}",
            "headers": [{"name": "Content-Type", "value": "application/octet-stream"}],
            "body": {"kind": "binary", "source": ["start", "document"]},
        },
        {("start", "query"): "string", ("start", "document"): "file"},
    )

    assert config["authorization"] == {"type": "no-auth", "config": None}
    assert config["headers"] == "Content-Type:application/octet-stream"
    assert config["body"]["data"][0]["file"] == ["start", "document"]


@pytest.mark.parametrize(
    "structure",
    [
        {
            "kind": "http-request",
            "url": "https://example.com?api_key=plaintext",
        },
        {
            "kind": "http-request",
            "url": "https://example.com",
            "headers": [{"name": "Authorization", "value": "Bearer plaintext"}],
        },
        {
            "kind": "http-request",
            "url": "https://example.com",
            "authorization": {"kind": "api-key", "value": "plaintext"},
        },
    ],
)
def test_http_request_intent_rejects_plaintext_credentials(structure: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        parse_node_build_intent(
            node_type="http-request",
            raw={"objective": "Call API", "structure": structure},
        )


def test_http_request_credential_reference_fails_closed_without_snapshot_binding() -> None:
    intent = parse_node_build_intent(
        node_type="http-request",
        raw={
            "objective": "Call API",
            "structure": {
                "kind": "http-request",
                "url": "https://example.com",
                "authorization": {"kind": "reference", "reference_id": "credential-1"},
            },
        },
    )
    with pytest.raises(NodeIntentCompileError) as exc_info:
        compile_node_intent(intent=intent, context=_context({}), base_config={})
    assert exc_info.value.code == "UNKNOWN_CREDENTIAL"
    assert exc_info.value.path == "structure.authorization.reference_id"


def test_human_input_compiles_capabilities_members_defaults_and_preserves_update_timeout() -> None:
    structure = {
        "kind": "human-input",
        "form_content": "Review {{#start.query#}}",
        "inputs": [
            {"type": "paragraph", "output_variable_name": "comment"},
            {
                "type": "select",
                "output_variable_name": "priority",
                "options": {"kind": "constant", "values": ["high", "low"]},
            },
        ],
        "delivery": [
            {"kind": "webapp"},
            {
                "kind": "email",
                "member_reference_ids": ["member-1"],
                "subject": "Review requested",
                "body": "Open {{#url#}} for {{#start.query#}}",
            },
        ],
        "actions": [{"id": "approve", "title": "Approve", "button_style": "primary"}],
    }
    config = _compile("human-input", structure, {("start", "query"): "string"})

    assert config["timeout"] == 3
    assert config["timeout_unit"] == "day"
    assert [item["type"] for item in config["delivery_methods"]] == ["webapp", "email"]
    assert config["delivery_methods"][1]["config"]["recipients"]["items"] == [
        {"type": "member", "reference_id": "member-1"}
    ]
    assert "_targetBranches" not in config

    intent = parse_node_build_intent(node_type="human-input", raw={"objective": "Update", "structure": structure})
    updated = compile_node_intent(
        intent=intent,
        context=NodeCompileContext(
            **{
                **_context({("start", "query"): "string"}).__dict__,
                "mode": "update",
                "old_config": {"timeout": 12, "timeout_unit": "hour"},
            }
        ),
        base_config={"timeout": 12, "timeout_unit": "hour", "_targetBranches": [{"id": "stale"}]},
    )
    assert updated["timeout"] == 12
    assert updated["timeout_unit"] == "hour"
    assert "_targetBranches" not in updated


def test_human_input_rejects_unavailable_delivery_and_unknown_member() -> None:
    intent = parse_node_build_intent(
        node_type="human-input",
        raw={
            "objective": "Ask",
            "structure": {
                "kind": "human-input",
                "form_content": "Review",
                "delivery": [
                    {
                        "kind": "email",
                        "member_reference_ids": ["missing"],
                        "subject": "Review",
                        "body": "Open {{#url#}}",
                    }
                ],
                "actions": [{"id": "approve", "title": "Approve"}],
            },
        },
    )
    context = _context({})
    with pytest.raises(NodeIntentCompileError) as exc_info:
        compile_node_intent(intent=intent, context=context, base_config={})
    assert exc_info.value.code == "UNKNOWN_MEMBER"

    unavailable = NodeCompileContext(
        node_id="target",
        surface="top_level",
        mode="create",
        source_type_resolver={}.get,
        human_input_delivery_capabilities=frozenset({"webapp"}),
        human_input_member_reference_ids=frozenset(),
    )
    with pytest.raises(NodeIntentCompileError) as exc_info:
        compile_node_intent(intent=intent, context=unavailable, base_config={})
    assert exc_info.value.code == "CAPABILITY_UNAVAILABLE"
    assert exc_info.value.path == "structure.delivery[0].kind"
