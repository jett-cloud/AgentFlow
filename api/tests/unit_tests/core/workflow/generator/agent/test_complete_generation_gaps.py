"""Executable gap cases for Workflow Assist complete-generation contracts."""

from copy import deepcopy
from dataclasses import replace

import pytest

from core.workflow.generator.agent.tools.tools import ToolContext, dispatch
from core.workflow.generator.agent.types import ToolCall
from core.workflow.generator.compiler.intents.node_intent import (
    NodeBuildIntent,
    parse_node_build_intent,
)
from core.workflow.generator.graph.graph_ops import empty_graph, find_node, upsert_node
from tests.unit_tests.core.workflow.generator.node_fixtures import builder_config


class _FakeBuilder:
    """Model-boundary fake returning one chosen runtime config."""

    def __init__(self, config: dict[str, object]) -> None:
        self._config = config

    def iter_json(self, *, messages: list[object], stage: str):
        del stage
        yield from ()
        return {"config": builder_config(messages, self._config)}


class _SequenceBuilder:
    def __init__(self, configs: list[dict[str, object]]) -> None:
        self._configs = iter(configs)
        self.calls = 0

    def iter_json(self, *, messages: list[object], stage: str):
        del stage
        self.calls += 1
        yield from ()
        return {"config": builder_config(messages, next(self._configs))}


class _UnexpectedBuilder:
    def iter_json(self, *, messages: list[object], stage: str):
        del messages, stage
        raise AssertionError("fully structured nodes must not call Builder")
        yield  # pragma: no cover


def _call(*, node_id: str, node_type: str, intent: dict[str, object]) -> ToolCall:
    return {
        "id": f"build-{node_id}",
        "name": "build_node",
        "arguments": {
            "mode": "create",
            "id": node_id,
            "type": node_type,
            "title": node_id,
            "intent": intent,
        },
    }


def _update_call(*, node_id: str, intent: dict[str, object]) -> ToolCall:
    return {
        "id": f"update-{node_id}",
        "name": "build_node",
        "arguments": {"mode": "update", "id": node_id, "intent": intent},
    }


def _start_graph() -> dict:
    return upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="Start",
        desc="",
        config={
            "variables": [
                {
                    "variable": "query",
                    "label": "Query",
                    "type": "paragraph",
                    "required": True,
                    "max_length": 1024,
                    "options": [],
                }
            ]
        },
    )


def test_build_node_rejects_config_that_omits_required_intent_input(tool_context: ToolContext) -> None:
    tool_context.state.graph = _start_graph()
    tool_context.env = replace(
        tool_context.env,
        llm_client=_FakeBuilder(
            {
                "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {}},
                "prompt_template": [{"role": "user", "text": "总结用户提供的问题。"}],
                "context": {"enabled": False, "variable_selector": []},
            }
        ),
    )
    before = deepcopy(tool_context.state.graph)

    result = dispatch(
        _call(
            node_id="summarize",
            node_type="llm",
            intent={
                "objective": "Summarize the question",
                "outputs": [{"name": "text", "type": "string"}],
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "MISSING_NODE_STRUCTURE"
    assert result["changed"] is False
    assert tool_context.state.graph == before
    assert find_node(tool_context.state.graph, "summarize") is None


def test_build_node_rejects_intent_input_from_unknown_node(tool_context: ToolContext) -> None:
    tool_context.env = replace(
        tool_context.env,
        llm_client=_FakeBuilder(
            {
                "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {}},
                "prompt_template": [{"role": "user", "text": "{{#missing.query#}}"}],
                "context": {"enabled": False, "variable_selector": []},
            }
        ),
    )
    before = deepcopy(tool_context.state.graph)

    result = dispatch(
        _call(
            node_id="summarize",
            node_type="llm",
            intent={
                "objective": "Summarize the question",
                "outputs": [{"name": "text", "type": "string"}],
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "MISSING_NODE_STRUCTURE"
    assert result["changed"] is False
    assert tool_context.state.graph == before


def test_build_node_rejects_config_that_omits_declared_dynamic_output(tool_context: ToolContext) -> None:
    tool_context.env = replace(
        tool_context.env,
        llm_client=_FakeBuilder(
            {
                "variables": [],
                "code_language": "python3",
                "code": "def main():\n    return {'other': 'value'}",
                "outputs": {"other": {"type": "string", "children": None}},
            }
        ),
    )
    before = deepcopy(tool_context.state.graph)

    result = dispatch(
        _call(
            node_id="calculate",
            node_type="code",
            intent={
                "objective": "Return the calculated result",
                "outputs": [{"name": "result", "type": "string"}],
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "MISSING_NODE_STRUCTURE"
    assert result["changed"] is False
    assert tool_context.state.graph == before
    assert find_node(tool_context.state.graph, "calculate") is None


def test_build_node_rejects_dynamic_output_with_wrong_type(tool_context: ToolContext) -> None:
    tool_context.env = replace(
        tool_context.env,
        llm_client=_FakeBuilder(
            {
                "variables": [],
                "code_language": "python3",
                "code": "def main():\n    return {'result': 1}",
                "outputs": {"result": {"type": "number", "children": None}},
            }
        ),
    )
    before = deepcopy(tool_context.state.graph)

    result = dispatch(
        _call(
            node_id="calculate",
            node_type="code",
            intent={
                "objective": "Return a textual result",
                "outputs": [{"name": "result", "type": "string"}],
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "MISSING_NODE_STRUCTURE"
    assert result["changed"] is False
    assert tool_context.state.graph == before


def test_code_comment_reference_does_not_satisfy_intent_input(tool_context: ToolContext) -> None:
    tool_context.state.graph = _start_graph()
    tool_context.env = replace(
        tool_context.env,
        llm_client=_FakeBuilder(
            {
                "variables": [],
                "code_language": "python3",
                "code": "# Read {{#start.query#}} later\ndef main():\n    return {'result': 'ok'}",
                "outputs": {"result": {"type": "string", "children": None}},
            }
        ),
    )
    before = deepcopy(tool_context.state.graph)

    result = dispatch(
        _call(
            node_id="calculate",
            node_type="code",
            intent={
                "objective": "Process the question",
                "outputs": [{"name": "result", "type": "string"}],
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "MISSING_NODE_STRUCTURE"
    assert tool_context.state.graph == before


def test_ordinary_node_structure_accepts_nested_variable_selector() -> None:
    intent = NodeBuildIntent.model_validate(
        {
            "objective": "Read a field from the current iteration item",
            "structure": {
                "kind": "template-transform",
                "template": "{{ title }}",
                "bindings": [{"name": "title", "source": ["iteration", "item", "title"]}],
            },
        }
    )

    assert intent.structure is not None
    assert intent.structure.bindings[0].source == ("iteration", "item", "title")


def test_node_intent_rejects_unknown_output_type() -> None:
    with pytest.raises(ValueError, match="unsupported output type"):
        NodeBuildIntent.model_validate(
            {
                "objective": "Produce one result",
                "outputs": [{"name": "result", "type": "mystery"}],
            }
        )


def test_code_node_intent_requires_types_for_dynamic_outputs() -> None:
    with pytest.raises(ValueError, match="Code output 'result' requires an explicit type"):
        parse_node_build_intent(
            node_type="code",
            raw={
                "objective": "Produce one result",
                "outputs": [{"name": "result"}],
            },
        )


def test_end_structure_overrides_builder_output_mapping(tool_context: ToolContext) -> None:
    tool_context.state.graph = _start_graph()
    tool_context.env = replace(
        tool_context.env,
        llm_client=_FakeBuilder(
            {"outputs": [{"variable": "wrong", "value_selector": ["sys", "files"], "value_type": "array[file]"}]}
        ),
    )

    result = dispatch(
        _call(
            node_id="end",
            node_type="end",
            intent={
                "objective": "Return the question",
                "structure": {
                    "kind": "end",
                    "outputs": [{"name": "question", "source": ["start", "query"], "type": "string"}],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is True
    end = find_node(tool_context.state.graph, "end")
    assert end is not None
    assert end["data"]["outputs"] == [
        {"variable": "question", "value_selector": ["start", "query"], "value_type": "string"}
    ]


def test_fully_structured_end_does_not_call_builder(tool_context: ToolContext) -> None:
    tool_context.state.graph = _start_graph()
    tool_context.env = replace(tool_context.env, llm_client=_UnexpectedBuilder())

    result = dispatch(
        _call(
            node_id="end",
            node_type="end",
            intent={
                "objective": "Return the question",
                "structure": {
                    "kind": "end",
                    "outputs": [{"name": "question", "source": ["start", "query"], "type": "string"}],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is True


def test_code_structure_overrides_builder_bindings_code_and_outputs(tool_context: ToolContext) -> None:
    tool_context.state.graph = _start_graph()
    tool_context.env = replace(
        tool_context.env,
        llm_client=_FakeBuilder(
            {
                "variables": [],
                "code_language": "python3",
                "code": "def main():\n    return {'wrong': True}",
                "outputs": {"wrong": {"type": "boolean", "children": None}},
            }
        ),
    )

    result = dispatch(
        _call(
            node_id="code",
            node_type="code",
            intent={
                "objective": "Return the question",
                "outputs": [{"name": "result", "type": "string"}],
                "structure": {
                    "kind": "code",
                    "language": "python3",
                    "code": "def main(question: str):\n    return {'result': question}",
                    "bindings": [{"name": "question", "source": ["start", "query"]}],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is True
    code = find_node(tool_context.state.graph, "code")
    assert code is not None
    assert code["data"]["variables"] == [{"variable": "question", "value_selector": ["start", "query"]}]
    assert code["data"]["outputs"] == {"result": {"type": "string", "children": None}}
    assert "return {'result': question}" in code["data"]["code"]
    assert result["content"]["variables"] == [
        {
            "selector": ["code", "result"],
            "type": "string",
            "scope": "workflow",
            "confirmed": True,
        }
    ]


def test_start_structure_compiles_runtime_input_form(tool_context: ToolContext) -> None:
    tool_context.env = replace(tool_context.env, llm_client=_FakeBuilder({"variables": []}))

    result = dispatch(
        _call(
            node_id="start",
            node_type="start",
            intent={
                "objective": "Accept a required question",
                "structure": {
                    "kind": "start",
                    "variables": [{"name": "query", "label": "Question", "type": "paragraph", "required": True}],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is True
    start = find_node(tool_context.state.graph, "start")
    assert start is not None
    assert start["data"]["variables"] == [
        {
            "variable": "query",
            "label": "Question",
            "type": "paragraph",
            "required": True,
            "max_length": 4096,
            "options": [],
        }
    ]


def test_answer_and_template_structures_compile_content_and_bindings(tool_context: ToolContext) -> None:
    tool_context.state.graph = _start_graph()
    tool_context.env = replace(tool_context.env, llm_client=_FakeBuilder({"answer": "错误", "variables": []}))

    answer_result = dispatch(
        _call(
            node_id="answer",
            node_type="answer",
            intent={
                "objective": "Answer with the question",
                "structure": {"kind": "answer", "content": "Received: {{#start.query#}}"},
            },
        ),
        tool_context,
    )

    assert answer_result["ok"] is True
    assert find_node(tool_context.state.graph, "answer")["data"]["answer"] == "Received: {{#start.query#}}"

    tool_context.env = replace(
        tool_context.env,
        llm_client=_FakeBuilder({"template": "错误", "variables": []}),
    )
    template_result = dispatch(
        _call(
            node_id="template",
            node_type="template-transform",
            intent={
                "objective": "Format the question",
                "structure": {
                    "kind": "template-transform",
                    "template": "Question: {{ question }}",
                    "bindings": [{"name": "question", "source": ["start", "query"]}],
                },
            },
        ),
        tool_context,
    )

    assert template_result["ok"] is True
    template = find_node(tool_context.state.graph, "template")
    assert template["data"]["variables"] == [{"variable": "question", "value_selector": ["start", "query"]}]


def test_llm_and_if_else_structures_override_builder_identity_and_conditions(tool_context: ToolContext) -> None:
    tool_context.state.graph = _start_graph()
    tool_context.env = replace(
        tool_context.env,
        llm_client=_FakeBuilder(
            {
                "model": {"provider": "wrong", "name": "wrong", "mode": "chat", "completion_params": {}},
                "prompt_template": [{"role": "user", "text": "错误"}],
                "context": {"enabled": False, "variable_selector": []},
            }
        ),
    )

    llm_result = dispatch(
        _call(
            node_id="llm",
            node_type="llm",
            intent={
                "objective": "Summarize",
                "outputs": [{"name": "text", "type": "string"}],
                "structure": {
                    "kind": "llm",
                    "model": {"provider": "openai", "name": "gpt-4o"},
                    "prompt": [{"role": "user", "text": "Summarize {{#start.query#}}"}],
                },
            },
        ),
        tool_context,
    )

    assert llm_result["ok"] is True
    llm = find_node(tool_context.state.graph, "llm")
    assert llm["data"]["model"]["provider"] == "openai"
    assert llm["data"]["prompt_template"][0]["text"] == "Summarize {{#start.query#}}"

    tool_context.env = replace(
        tool_context.env,
        llm_client=_FakeBuilder(
            {
                "cases": [
                    {
                        "case_id": "wrong",
                        "logical_operator": "and",
                        "conditions": [
                            {
                                "variable_selector": ["start", "query"],
                                "comparison_operator": "empty",
                                "value": None,
                                "varType": "string",
                            }
                        ],
                    }
                ]
            }
        ),
    )
    branch_result = dispatch(
        _call(
            node_id="branch",
            node_type="if-else",
            intent={
                "objective": "Check confirmation",
                "structure": {
                    "kind": "if-else",
                    "cases": [
                        {
                            "id": "confirmed",
                            "conditions": [
                                {
                                    "source": ["start", "query"],
                                    "operator": "contains",
                                    "value": "yes",
                                }
                            ],
                        }
                    ],
                },
            },
        ),
        tool_context,
    )

    assert branch_result["ok"] is True
    branch = find_node(tool_context.state.graph, "branch")
    assert branch["data"]["cases"][0]["case_id"] == "confirmed"
    assert branch["data"]["cases"][0]["conditions"][0]["comparison_operator"] == "contains"


def test_typed_llm_rejects_model_outside_snapshot_without_builder(tool_context: ToolContext) -> None:
    tool_context.state.graph = _start_graph()
    original = deepcopy(tool_context.state.graph)
    tool_context.env = replace(tool_context.env, llm_client=_UnexpectedBuilder())

    result = dispatch(
        _call(
            node_id="llm",
            node_type="llm",
            intent={
                "objective": "Summarize",
                "structure": {
                    "kind": "llm",
                    "model": {"provider": "invented", "name": "not-installed"},
                    "prompt": [{"role": "user", "text": "Summarize {{#start.query#}}"}],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_MODEL"
    assert result["path"] == "structure.model"
    assert result["cause"]["available_models"] == [
        {"provider": "openai", "name": "gpt-4o"},
        {"provider": "openai", "name": "gpt-4.1"},
    ]
    assert tool_context.state.graph == original


def test_typed_classifier_and_parameter_extractor_compile_without_builder(tool_context: ToolContext) -> None:
    tool_context.state.graph = _start_graph()
    tool_context.env = replace(tool_context.env, llm_client=_UnexpectedBuilder())

    classifier_result = dispatch(
        _call(
            node_id="route",
            node_type="question-classifier",
            intent={
                "objective": "Route the request",
                "structure": {
                    "kind": "question-classifier",
                    "query": ["start", "query"],
                    "model": {"provider": "openai", "name": "gpt-4o"},
                    "classes": [
                        {"id": "sales", "name": "Sales"},
                        {"id": "support", "name": "Support"},
                    ],
                },
            },
        ),
        tool_context,
    )
    extractor_result = dispatch(
        _call(
            node_id="extract",
            node_type="parameter-extractor",
            intent={
                "objective": "Extract the topic",
                "structure": {
                    "kind": "parameter-extractor",
                    "query": ["start", "query"],
                    "model": {"provider": "openai", "name": "gpt-4o"},
                    "parameters": [
                        {"name": "topic", "type": "string", "description": "Request topic", "required": True}
                    ],
                },
            },
        ),
        tool_context,
    )

    assert classifier_result["ok"] is True
    assert extractor_result["ok"] is True
    classifier = find_node(tool_context.state.graph, "route")
    extractor = find_node(tool_context.state.graph, "extract")
    assert classifier["data"]["_targetBranches"] == [
        {"id": "sales", "name": ""},
        {"id": "support", "name": ""},
    ]
    assert [item["name"] for item in extractor["data"]["parameters"]] == ["topic"]


def test_typed_aggregator_type_failure_is_atomic(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="Start",
        desc="",
        config={
            "variables": [
                {"variable": "text", "label": "Text", "type": "paragraph", "required": True},
                {"variable": "score", "label": "Score", "type": "number", "required": True},
            ]
        },
    )
    original = deepcopy(tool_context.state.graph)
    tool_context.env = replace(tool_context.env, llm_client=_UnexpectedBuilder())

    result = dispatch(
        _call(
            node_id="merge",
            node_type="variable-aggregator",
            intent={
                "objective": "Merge branch results",
                "structure": {
                    "kind": "variable-aggregator",
                    "sources": [["start", "text"], ["start", "score"]],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "INCOMPATIBLE_BRANCH_TYPES"
    assert result["path"] == "structure.sources"
    assert result["changed"] is False
    assert tool_context.state.graph == original


def test_typed_llm_distinguishes_unavailable_model_catalogue(tool_context: ToolContext) -> None:
    tool_context.state.graph = _start_graph()
    tool_context.env = replace(
        tool_context.env,
        models_available=False,
        llm_client=_UnexpectedBuilder(),
    )

    result = dispatch(
        _call(
            node_id="llm",
            node_type="llm",
            intent={
                "objective": "Summarize",
                "structure": {
                    "kind": "llm",
                    "model": {"provider": "openai", "name": "gpt-4o"},
                    "prompt": [{"role": "user", "text": "Summarize {{#start.query#}}"}],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "CAPABILITY_UNAVAILABLE"
    assert result["path"] == "structure.model"
    assert result["cause"]["capability"] == "model_catalogue"


def test_typed_llm_treats_available_empty_model_catalogue_as_unknown_model(tool_context: ToolContext) -> None:
    tool_context.state.graph = _start_graph()
    tool_context.env = replace(
        tool_context.env,
        agent_model_entries=(),
        models_available=True,
        llm_client=_UnexpectedBuilder(),
    )

    result = dispatch(
        _call(
            node_id="llm",
            node_type="llm",
            intent={
                "objective": "Summarize",
                "structure": {
                    "kind": "llm",
                    "model": {"provider": "openai", "name": "gpt-4o"},
                    "prompt": [{"role": "user", "text": "Summarize {{#start.query#}}"}],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_MODEL"
    assert result["cause"]["available_models"] == []


def test_typed_llm_rejects_unknown_prompt_binding_before_commit(tool_context: ToolContext) -> None:
    original = deepcopy(tool_context.state.graph)
    tool_context.env = replace(tool_context.env, llm_client=_UnexpectedBuilder())

    result = dispatch(
        _call(
            node_id="llm",
            node_type="llm",
            intent={
                "objective": "Summarize",
                "structure": {
                    "kind": "llm",
                    "model": {"provider": "openai", "name": "gpt-4o"},
                    "prompt": [{"role": "user", "text": "Summarize {{#missing.text#}}"}],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_NODE_REFERENCE"
    assert result["path"] == "structure.prompt[0].text"
    assert tool_context.state.graph == original


def test_update_requires_structure_and_explicit_bindings_can_be_preserved_or_cleared(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(
        _start_graph(),
        node_id="template",
        node_type="template-transform",
        title="Template",
        desc="",
        config={
            "template": "Old {{ question }}",
            "variables": [{"variable": "question", "value_selector": ["start", "query"]}],
        },
    )
    missing = dispatch(
        _update_call(node_id="template", intent={"objective": "Update wording only"}),
        tool_context,
    )

    assert missing["ok"] is False
    assert missing["error_code"] == "MISSING_NODE_STRUCTURE"

    preserved = dispatch(
        _update_call(
            node_id="template",
            intent={
                "objective": "Update wording",
                "structure": {
                    "kind": "template-transform",
                    "template": "Updated {{ question }}",
                    "bindings": [{"name": "question", "source": ["start", "query"]}],
                },
            },
        ),
        tool_context,
    )
    assert preserved["ok"] is True
    assert find_node(tool_context.state.graph, "template")["data"]["variables"] == [
        {"variable": "question", "value_selector": ["start", "query"]}
    ]

    cleared = dispatch(
        _update_call(
            node_id="template",
            intent={
                "objective": "Make the template static",
                "structure": {"kind": "template-transform", "template": "Static", "bindings": []},
            },
        ),
        tool_context,
    )

    assert cleared["ok"] is True
    assert find_node(tool_context.state.graph, "template")["data"]["variables"] == []


def test_unknown_node_in_structured_end_mapping_returns_detailed_issue(tool_context: ToolContext) -> None:
    tool_context.env = replace(tool_context.env, llm_client=_FakeBuilder({"outputs": []}))

    result = dispatch(
        _call(
            node_id="end",
            node_type="end",
            intent={
                "objective": "Return missing output",
                "structure": {
                    "kind": "end",
                    "outputs": [{"name": "result", "source": ["missing", "text"], "type": "string"}],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_NODE_REFERENCE"
    assert result["path"] == "structure.outputs[0].source"
    assert result["cause"]["contract_revision"] == 1
    assert result["cause"]["expected"] == "existing or pending producer node"


def test_unknown_output_in_structured_end_mapping_returns_confirmed_candidates(tool_context: ToolContext) -> None:
    tool_context.state.graph = _start_graph()
    original = deepcopy(tool_context.state.graph)
    tool_context.env = replace(tool_context.env, llm_client=_UnexpectedBuilder())

    result = dispatch(
        _call(
            node_id="end",
            node_type="end",
            intent={
                "objective": "Return a missing Start output",
                "structure": {
                    "kind": "end",
                    "outputs": [{"name": "result", "source": ["start", "missing"], "type": "string"}],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_OUTPUT"
    assert result["path"] == "structure.outputs[0].source"
    assert result["cause"]["actual"] == "start.missing"
    assert "start.query" in result["cause"]["available_variables"]
    assert tool_context.state.graph == original


def test_structured_end_rejects_confirmed_source_type_mismatch(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="Start",
        desc="",
        config={
            "variables": [
                {
                    "variable": "score",
                    "label": "Score",
                    "type": "number",
                    "required": True,
                }
            ]
        },
    )
    original = deepcopy(tool_context.state.graph)

    result = dispatch(
        _call(
            node_id="end",
            node_type="end",
            intent={
                "objective": "Return score as text",
                "structure": {
                    "kind": "end",
                    "outputs": [{"name": "result", "source": ["start", "score"], "type": "string"}],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "VARIABLE_TYPE_MISMATCH"
    assert result["path"] == "structure.outputs[0].source"
    assert result["cause"]["expected"] == "string"
    assert result["cause"]["actual"] == "number"
    assert tool_context.state.graph == original


def test_structured_end_derives_confirmed_source_type(tool_context: ToolContext) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="Start",
        desc="",
        config={
            "variables": [
                {"variable": "score", "label": "Score", "type": "number", "required": True}
            ]
        },
    )
    tool_context.env = replace(tool_context.env, llm_client=_UnexpectedBuilder())

    result = dispatch(
        _call(
            node_id="end",
            node_type="end",
            intent={
                "objective": "Return the score",
                "structure": {
                    "kind": "end",
                    "outputs": [{"name": "score", "source": ["start", "score"]}],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is True
    assert find_node(tool_context.state.graph, "end")["data"]["outputs"] == [
        {"variable": "score", "value_selector": ["start", "score"], "value_type": "number"}
    ]


@pytest.mark.parametrize("input_type", ["file", "file-list"])
def test_document_extractor_structure_compiles_without_builder(
    tool_context: ToolContext,
    input_type: str,
) -> None:
    tool_context.state.graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="Start",
        desc="",
        config={
            "variables": [
                {
                    "variable": "document",
                    "label": "Document",
                    "type": input_type,
                    "required": True,
                    "allowed_file_types": ["document"],
                    "allowed_file_upload_methods": ["local_file"],
                    "allowed_file_extensions": [],
                }
            ]
        },
    )
    tool_context.env = replace(tool_context.env, llm_client=_UnexpectedBuilder())

    result = dispatch(
        _call(
            node_id="extract",
            node_type="document-extractor",
            intent={
                "objective": "Extract text from the uploaded document",
                "structure": {
                    "kind": "document-extractor",
                    "source": ["start", "document"],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is True
    extractor = find_node(tool_context.state.graph, "extract")
    assert extractor["data"]["variable_selector"] == ["start", "document"]
    assert "is_array_file" not in extractor["data"]


def test_document_extractor_rejects_non_file_source_before_commit(tool_context: ToolContext) -> None:
    tool_context.state.graph = _start_graph()
    original = deepcopy(tool_context.state.graph)
    tool_context.env = replace(tool_context.env, llm_client=_UnexpectedBuilder())

    result = dispatch(
        _call(
            node_id="extract",
            node_type="document-extractor",
            intent={
                "objective": "Extract text",
                "structure": {
                    "kind": "document-extractor",
                    "source": ["start", "query"],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "VARIABLE_TYPE_MISMATCH"
    assert result["path"] == "structure.source"
    assert result["cause"]["expected"] == ["file", "array[file]"]
    assert result["cause"]["actual"] == "string"
    assert tool_context.state.graph == original


def test_document_extractor_accepts_advanced_chat_system_files(tool_context: ToolContext) -> None:
    tool_context.env = replace(
        tool_context.env,
        mode="advanced-chat",
        llm_client=_UnexpectedBuilder(),
    )

    result = dispatch(
        _call(
            node_id="extract",
            node_type="document-extractor",
            intent={
                "objective": "Extract uploaded chat files",
                "structure": {
                    "kind": "document-extractor",
                    "source": ["sys", "files"],
                },
            },
        ),
        tool_context,
    )

    assert result["ok"] is True
    assert find_node(tool_context.state.graph, "extract")["data"]["variable_selector"] == ["sys", "files"]


def test_ordinary_node_does_not_invoke_builder_for_missing_structure(tool_context: ToolContext) -> None:
    tool_context.state.graph = _start_graph()
    builder = _SequenceBuilder(
        [
            {
                "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {}},
                "prompt_template": [{"role": "user", "text": "Summarize the question."}],
                "context": {"enabled": False, "variable_selector": []},
            },
            {
                "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {}},
                "prompt_template": [{"role": "user", "text": "Summarize: {{#start.query#}}"}],
                "context": {"enabled": False, "variable_selector": []},
            },
        ]
    )
    tool_context.env = replace(tool_context.env, llm_client=builder)

    result = dispatch(
        _call(
            node_id="summary",
            node_type="llm",
            intent={
                "objective": "Summarize",
                "outputs": [{"name": "text", "type": "string"}],
            },
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "MISSING_NODE_STRUCTURE"
    assert builder.calls == 0
    assert find_node(tool_context.state.graph, "summary") is None


def test_ordinary_node_never_repairs_model_authored_runtime_config(tool_context: ToolContext) -> None:
    builder = _SequenceBuilder(
        [
            {
                "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {}},
                "prompt_template": [],
                "context": {"enabled": False, "variable_selector": []},
            },
            {
                "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {}},
                "prompt_template": [{"role": "user", "text": "Write a short summary."}],
                "context": {"enabled": False, "variable_selector": []},
            },
        ]
    )
    tool_context.env = replace(tool_context.env, llm_client=builder)

    result = dispatch(
        _call(
            node_id="summary",
            node_type="llm",
            intent={"objective": "Write a summary", "outputs": [{"name": "text", "type": "string"}]},
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "MISSING_NODE_STRUCTURE"
    assert builder.calls == 0
