import pytest
from pydantic import ValidationError

from core.workflow.generator.compiler.intents.node_intent import (
    AgentKnowledgeIntent,
    AssignerStructureIntent,
    AssignmentIntent,
    ConstantToolArgument,
    NodeBuildIntent,
    TemplateToolArgument,
    ToolBinding,
    ToolNodeBuildIntent,
    VariableToolArgument,
    parse_node_build_intent,
)


def _base_intent(**changes: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "objective": "Summarize the input",
        "outputs": [{"name": "text", "type": "string"}],
        "structure": {
            "kind": "llm",
            "model": {"provider": "openai", "name": "gpt-4o"},
            "prompt": [{"role": "user", "text": "{{#start.query#}}"}],
        },
    }
    raw.update(changes)
    return raw


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (ToolBinding, {"provider_name": "p", "tool_name": "t", "extra": True}),
        (VariableToolArgument, {"kind": "variable", "selector": ["n", "v"], "extra": True}),
        (TemplateToolArgument, {"kind": "template", "text": "x", "extra": True}),
        (ConstantToolArgument, {"kind": "constant", "value": 1, "extra": True}),
        (NodeBuildIntent, {**_base_intent(), "extra": True}),
    ],
)
def test_intent_models_forbid_extra_fields(model: type, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("selector", [[], ["node"], ["", "var"], ["node", ""], ["node", "var", ""]])
def test_variable_selector_requires_at_least_two_non_empty_parts(selector: list[str]) -> None:
    with pytest.raises(ValidationError):
        VariableToolArgument.model_validate({"kind": "variable", "selector": selector})


def test_variable_selector_accepts_nested_output_paths() -> None:
    argument = VariableToolArgument.model_validate(
        {"kind": "variable", "selector": ["iteration", "item", "source_image"]}
    )

    assert argument.selector == ("iteration", "item", "source_image")


@pytest.mark.parametrize(
    "argument",
    [
        {"kind": "variable", "selector": ["node", "var"], "text": "wrong"},
        {"kind": "template", "text": "x", "selector": ["node", "var"]},
        {"kind": "unknown", "value": "x"},
    ],
)
def test_tool_argument_discriminator_rejects_fields_from_other_kinds(argument: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ToolNodeBuildIntent.model_validate(
            {
                "binding": {"provider_name": "image", "tool_name": "generate"},
                "arguments": {"prompt": argument},
            }
        )


def test_objective_is_trimmed_and_cannot_be_empty() -> None:
    intent = parse_node_build_intent(node_type="llm", raw=_base_intent(objective="  summarize  "))
    assert intent.objective == "summarize"

    with pytest.raises(ValidationError):
        parse_node_build_intent(node_type="llm", raw=_base_intent(objective="   "))


@pytest.mark.parametrize(
    "legacy_field",
    ["behavior", "inputs", "requirements", "tool", "tool_bindings", "agent_knowledge"],
)
def test_ordinary_intent_rejects_retired_or_specialized_fields(legacy_field: str) -> None:
    value: object = "legacy"
    if legacy_field in {"inputs", "requirements", "tool_bindings"}:
        value = []
    elif legacy_field == "tool":
        value = {"binding": {"provider_name": "image", "tool_name": "generate"}, "arguments": {}}
    elif legacy_field == "agent_knowledge":
        value = {"operation": "clear"}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        parse_node_build_intent(node_type="llm", raw=_base_intent(**{legacy_field: value}))


def test_agent_knowledge_replace_requires_complete_sets() -> None:
    intent = AgentKnowledgeIntent.model_validate(
        {
            "operation": "replace",
            "sets": [
                {
                    "name": " Product docs ",
                    "dataset_ids": [" ds-1 "],
                    "query_mode": "generated_query",
                    "retrieval_mode": "multiple",
                }
            ],
        }
    )

    assert intent.operation == "replace"
    assert intent.sets[0].name == "Product docs"
    assert intent.sets[0].dataset_ids == ["ds-1"]


@pytest.mark.parametrize(
    "agent_knowledge",
    [
        {"operation": "replace", "sets": []},
        {"operation": "replace", "sets": [{"name": "Docs", "dataset_ids": []}]},
        {"operation": "replace", "sets": [{"name": "Docs", "dataset_ids": [" "]}]},
        {
            "operation": "replace",
            "sets": [
                {"name": "Docs", "dataset_ids": ["ds-1"]},
                {"name": " docs ", "dataset_ids": ["ds-2"]},
            ],
        },
        {
            "operation": "replace",
            "sets": [
                {
                    "name": "Docs",
                    "dataset_ids": ["ds-1"],
                    "query_mode": "user_query",
                    "query_value": " ",
                }
            ],
        },
        {
            "operation": "replace",
            "sets": [{"name": "Docs", "dataset_ids": ["ds-1"], "retrieval_mode": "single"}],
        },
    ],
)
def test_agent_knowledge_rejects_ambiguous_or_incomplete_replace(agent_knowledge: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AgentKnowledgeIntent.model_validate(agent_knowledge)


def test_agent_knowledge_clear_canonicalizes_supplied_sets_to_empty() -> None:
    intent = AgentKnowledgeIntent.model_validate(
        {
            "operation": "clear",
            "sets": [{"name": "ignored", "dataset_ids": ["ds-1"]}],
        }
    )

    assert intent.sets == []


def test_structure_kind_must_match_outer_node_type() -> None:
    with pytest.raises(ValueError, match="does not match node type"):
        parse_node_build_intent(
            node_type="answer",
            raw={"objective": "Answer", "structure": {"kind": "template-transform", "template": "Hello"}},
        )


@pytest.mark.parametrize("output_type", ["file", "array", "array[file]"])
def test_code_structure_rejects_runtime_unsupported_output_types(output_type: str) -> None:
    with pytest.raises(ValueError, match="unsupported Code output type"):
        parse_node_build_intent(
            node_type="code",
            raw={
                "objective": "Calculate",
                "outputs": [{"name": "result", "type": output_type}],
                "structure": {"kind": "code", "code": "def main():\n    return {}"},
            },
        )


@pytest.mark.parametrize(
    "structure",
    [
        {
            "kind": "start",
            "variables": [
                {"name": "query", "label": "Query", "type": "paragraph"},
                {"name": "query", "label": "Again", "type": "paragraph"},
            ],
        },
        {
            "kind": "end",
            "outputs": [
                {"name": "result", "source": ["a", "text"], "type": "string"},
                {"name": "result", "source": ["b", "text"], "type": "string"},
            ],
        },
    ],
)
def test_structured_variable_names_must_be_unique(structure: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="unique"):
        NodeBuildIntent.model_validate({"objective": "Build", "structure": structure})


def test_assigner_structure_requires_explicit_target_and_value_kind() -> None:
    intent = parse_node_build_intent(
        node_type="assigner",
        raw={
            "objective": "Store the revised document",
            "structure": {
                "kind": "assigner",
                "assignments": [
                    {
                        "target": ["revision_loop", "optimized_doc"],
                        "operation": "over-write",
                        "value": {"kind": "variable", "selector": ["optimize", "text"]},
                    }
                ],
            },
        },
    )

    assert isinstance(intent.structure, AssignerStructureIntent)
    assert intent.structure.assignments[0].target == ("revision_loop", "optimized_doc")


def test_assigner_clear_rejects_a_value() -> None:
    with pytest.raises(ValidationError, match="clear must not include value"):
        AssignmentIntent.model_validate(
            {
                "target": ["loop1", "acc"],
                "operation": "clear",
                "value": {"kind": "constant", "value": "unexpected"},
            }
        )


def test_end_structure_allows_compiler_derived_output_type() -> None:
    intent = parse_node_build_intent(
        node_type="end",
        raw={
            "objective": "Return the result",
            "structure": {
                "kind": "end",
                "outputs": [{"name": "result", "source": ["worker", "result"]}],
            },
        },
    )

    assert intent.structure is not None
    assert intent.structure.kind == "end"
    assert intent.structure.outputs[0].type is None


def test_document_extractor_structure_rejects_runtime_fields() -> None:
    with pytest.raises(ValidationError):
        parse_node_build_intent(
            node_type="document-extractor",
            raw={
                "objective": "Extract text",
                "structure": {
                    "kind": "document-extractor",
                    "source": ["start", "document"],
                    "is_array_file": False,
                },
            },
        )


def test_assigner_phase_one_rejects_unimplemented_operations() -> None:
    with pytest.raises(ValidationError):
        AssignmentIntent.model_validate(
            {
                "target": ["loop1", "acc"],
                "operation": "append",
                "value": {"kind": "constant", "value": "item"},
            }
        )
