import pytest
from pydantic import ValidationError

from core.workflow.generator.compiler.intents.node_intent import (
    ConstantToolArgument,
    NodeBuildIntent,
    TemplateToolArgument,
    ToolBinding,
    VariableToolArgument,
    parse_node_build_intent,
    render_node_builder_spec,
)


def _base_intent(**changes: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "objective": "Summarize the input",
        "inputs": [{"source": ["start", "query"], "role": "question"}],
        "outputs": [{"name": "text", "type": "string"}],
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
        parse_node_build_intent(
            node_type="tool",
            raw=_base_intent(
                tool={
                    "binding": {"provider_name": "image", "tool_name": "generate"},
                    "arguments": {"prompt": argument},
                }
            ),
        )


def test_objective_is_trimmed_and_cannot_be_empty() -> None:
    intent = parse_node_build_intent(node_type="llm", raw=_base_intent(objective="  summarize  "))
    assert intent.objective == "summarize"

    with pytest.raises(ValidationError):
        parse_node_build_intent(node_type="llm", raw=_base_intent(objective="   "))


@pytest.mark.parametrize("node_type", ["llm", "code", "agent"])
def test_only_tool_nodes_accept_tool_invocation(node_type: str) -> None:
    raw = _base_intent(tool={"binding": {"provider_name": "image", "tool_name": "generate"}, "arguments": {}})
    with pytest.raises(ValueError, match="only for tool nodes"):
        parse_node_build_intent(node_type=node_type, raw=raw)


@pytest.mark.parametrize("mode", ["create", "update", "replace"])
def test_tool_nodes_always_require_a_complete_binding(mode: str) -> None:
    del mode
    with pytest.raises(ValueError, match="requires intent.tool"):
        parse_node_build_intent(node_type="tool", raw=_base_intent())

    with pytest.raises(ValidationError):
        parse_node_build_intent(
            node_type="tool",
            raw=_base_intent(tool={"binding": {"provider_name": "image"}, "arguments": {}}),
        )


def test_only_agent_nodes_accept_unique_tool_bindings() -> None:
    bindings = [{"provider_name": "search", "tool_name": "web"}]
    intent = parse_node_build_intent(node_type="agent", raw=_base_intent(tool_bindings=bindings))
    assert [(item.provider_name, item.tool_name) for item in intent.tool_bindings] == [("search", "web")]

    with pytest.raises(ValueError, match="only for agent nodes"):
        parse_node_build_intent(node_type="llm", raw=_base_intent(tool_bindings=bindings))
    with pytest.raises(ValidationError, match="duplicate"):
        parse_node_build_intent(node_type="agent", raw=_base_intent(tool_bindings=bindings * 2))


def test_agent_knowledge_replace_requires_complete_sets() -> None:
    intent = parse_node_build_intent(
        node_type="agent",
        raw=_base_intent(
            agent_knowledge={
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
        ),
    )

    assert intent.agent_knowledge is not None
    assert intent.agent_knowledge.operation == "replace"
    assert intent.agent_knowledge.sets[0].name == "Product docs"
    assert intent.agent_knowledge.sets[0].dataset_ids == ["ds-1"]


@pytest.mark.parametrize("node_type", ["llm", "tool", "knowledge-retrieval"])
def test_agent_knowledge_is_agent_only(node_type: str) -> None:
    raw = _base_intent(agent_knowledge={"operation": "clear"})
    if node_type == "tool":
        raw["tool"] = {"binding": {"provider_name": "image", "tool_name": "generate"}, "arguments": {}}

    with pytest.raises(ValueError, match="only for agent nodes"):
        parse_node_build_intent(node_type=node_type, raw=raw)


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
        parse_node_build_intent(node_type="agent", raw=_base_intent(agent_knowledge=agent_knowledge))


def test_agent_knowledge_clear_canonicalizes_supplied_sets_to_empty() -> None:
    intent = parse_node_build_intent(
        node_type="agent",
        raw=_base_intent(
            agent_knowledge={
                "operation": "clear",
                "sets": [{"name": "ignored", "dataset_ids": ["ds-1"]}],
            }
        ),
    )

    assert intent.agent_knowledge is not None
    assert intent.agent_knowledge.sets == []


def test_render_node_builder_spec_has_stable_headings_and_exact_bindings() -> None:
    intent = parse_node_build_intent(
        node_type="agent",
        raw=_base_intent(
            behavior="Use only cited facts",
            requirements=["Keep the answer concise"],
            tool_bindings=[{"provider_name": "search", "tool_name": "web"}],
        ),
    )

    rendered = render_node_builder_spec(intent)

    headings = [
        "Objective:",
        "Inputs:",
        "Outputs:",
        "Behavior:",
        "Variable references:",
        "Resource bindings:",
        "Configuration constraints:",
        "Fields to preserve:",
    ]
    assert [rendered.index(heading) for heading in headings] == sorted(rendered.index(heading) for heading in headings)
    assert "{{#start.query#}}" in rendered
    assert "search/web" in rendered
    assert "Keep the answer concise" in rendered


def test_template_transform_builder_spec_includes_variable_contract() -> None:
    intent = parse_node_build_intent(node_type="template-transform", raw=_base_intent())
    rendered = render_node_builder_spec(intent, node_type="template-transform")

    assert "template must be non-empty" in rendered
    assert "^[A-Za-z_][A-Za-z0-9_]*$" in rendered
    assert "30" in rendered
    assert "unique" in rendered
    assert "value_selector" in rendered
    assert "at least two non-empty strings" in rendered


def test_tool_intent_cannot_be_rendered_for_node_builder() -> None:
    intent = parse_node_build_intent(
        node_type="tool",
        raw=_base_intent(tool={"binding": {"provider_name": "image", "tool_name": "generate"}, "arguments": {}}),
    )

    with pytest.raises(ValueError, match="Tool intent"):
        render_node_builder_spec(intent)


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
