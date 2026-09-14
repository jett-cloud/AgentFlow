"""Runtime-shape and generated-node completeness validation."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from core.workflow.generator.graph.graph_postprocessor import postprocess_graph
from core.workflow.generator.types import GraphDict, WorkflowGenerateErrorCode
from core.workflow.generator.validation.node_completeness import _knowledge_retrieval_completeness_errors
from core.workflow.generator.validation.node_config_validator import (
    collect_generated_node_completeness_errors,
    collect_node_config_errors,
)
from core.workflow.generator.validation.output_config import fill_end_output_value_types
from core.workflow.graph.adapters.node_config_schema import validate_workflow_node_data


def _model_config() -> dict[str, object]:
    return {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {}}


def _minimal_generated_node_data(node_type: str) -> dict[str, object]:
    configs: dict[str, dict[str, object]] = {
        "llm": {
            "type": "llm",
            "model": _model_config(),
            "prompt_template": [{"role": "user", "text": "Process the input."}],
            "context": {"enabled": False, "variable_selector": []},
        },
        "answer": {"type": "answer", "answer": "Done."},
        "template-transform": {
            "type": "template-transform",
            "template": "Hello {{ name }}",
            "variables": [
                {"variable": "name", "value_selector": ["start", "name"]},
            ],
        },
        "http-request": {
            "type": "http-request",
            "method": "get",
            "url": "https://example.com",
            "authorization": {"type": "no-auth", "config": None},
            "headers": "",
            "params": "",
            "body": {"type": "none", "data": []},
        },
        "if-else": {
            "type": "if-else",
            "cases": [
                {
                    "case_id": "true",
                    "logical_operator": "and",
                    "conditions": [
                        {
                            "variable_selector": ["start", "query"],
                            "comparison_operator": "empty",
                            "value": None,
                        }
                    ],
                }
            ],
        },
        "question-classifier": {
            "type": "question-classifier",
            "query_variable_selector": ["start", "query"],
            "model": _model_config(),
            "classes": [{"id": "1", "name": "First"}, {"id": "2", "name": "Second"}],
            "instruction": "",
        },
        "parameter-extractor": {
            "type": "parameter-extractor",
            "query": ["start", "query"],
            "model": _model_config(),
            "parameters": [{"name": "topic", "type": "string", "description": "Extract the topic", "required": True}],
            "reasoning_mode": "prompt",
            "instruction": "",
        },
        "document-extractor": {
            "type": "document-extractor",
            "variable_selector": ["start", "document"],
            "is_array_file": False,
        },
        "variable-aggregator": {
            "type": "variable-aggregator",
            "output_type": "string",
            "variables": [["branch", "text"]],
        },
        "list-operator": {
            "type": "list-operator",
            "variable": ["start", "items"],
            "filter_by": {"enabled": False, "conditions": []},
            "order_by": {"enabled": False, "key": "", "value": "asc"},
            "limit": {"enabled": False, "size": 10},
            "extract_by": {"enabled": False, "serial": "1"},
        },
        "assigner": {
            "type": "assigner",
            "version": "2",
            "items": [
                {
                    "variable_selector": ["conversation", "result"],
                    "input_type": "constant",
                    "operation": "over-write",
                    "value": "done",
                }
            ],
        },
        "human-input": {
            "type": "human-input",
            "delivery_methods": [{"type": "webapp", "enabled": True}],
            "form_content": "Approve this result?",
            "inputs": [],
            "user_actions": [{"id": "approve", "title": "Approve", "button_style": "primary"}],
        },
        "iteration": {
            "type": "iteration",
            "start_node_id": "node_iterationstart",
            "iterator_selector": ["start", "items"],
            "output_selector": ["child", "result"],
        },
        "code": {
            "type": "code",
            "code_language": "python3",
            "code": "def main(query: str):\n    return {'result': query}",
            "variables": [{"variable": "query", "value_selector": ["start", "query"]}],
            "outputs": {"result": {"type": "string", "children": None}},
        },
    }
    return deepcopy(configs[node_type])


def _semantically_empty_generated_node_data(node_type: str) -> tuple[dict[str, object], str]:
    data = _minimal_generated_node_data(node_type)
    expected_field = {
        "llm": "prompt_template",
        "answer": "answer",
        "template-transform": "template",
        "http-request": "url",
        "if-else": "cases",
        "question-classifier": "query_variable_selector",
        "parameter-extractor": "query",
        "document-extractor": "variable_selector",
        "variable-aggregator": "variables",
        "list-operator": "variable",
        "assigner": "items",
        "human-input": "form_content",
        "iteration": "iterator_selector",
        "code": "code",
    }[node_type]
    if node_type == "llm":
        data[expected_field] = [{"role": "user", "text": "  "}]
    else:
        data[expected_field] = (
            []
            if expected_field
            in {
                "cases",
                "query_variable_selector",
                "query",
                "variable_selector",
                "variables",
                "variable",
                "items",
                "iterator_selector",
            }
            else "  "
        )
    return data, expected_field


_GENERATED_COMPLETENESS_NODE_TYPES = (
    "llm",
    "answer",
    "template-transform",
    "http-request",
    "if-else",
    "question-classifier",
    "parameter-extractor",
    "document-extractor",
    "variable-aggregator",
    "list-operator",
    "assigner",
    "human-input",
    "iteration",
    "code",
)


@pytest.mark.parametrize("node_type", _GENERATED_COMPLETENESS_NODE_TYPES)
def test_runtime_schema_accepts_semantically_empty_generated_node_config(node_type: str):
    data, _ = _semantically_empty_generated_node_data(node_type)

    validate_workflow_node_data({"id": f"node_{node_type}", "data": data})


@pytest.mark.parametrize("node_type", _GENERATED_COMPLETENESS_NODE_TYPES)
def test_generated_completeness_rejects_semantically_empty_node_config(node_type: str):
    from core.workflow.generator.validation.node_config_validator import collect_generated_node_completeness_errors

    data, expected_field = _semantically_empty_generated_node_data(node_type)
    node_id = f"node_{node_type}"

    errors = collect_generated_node_completeness_errors([{"id": node_id, "data": data}])

    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_NODE_CONFIG
    assert errors[0]["node_id"] == node_id
    assert node_id in errors[0]["detail"]
    assert expected_field in errors[0]["detail"]


@pytest.mark.parametrize("node_type", _GENERATED_COMPLETENESS_NODE_TYPES)
def test_generated_completeness_accepts_minimal_node_config(node_type: str):
    from core.workflow.generator.validation.node_config_validator import collect_generated_node_completeness_errors

    node_id = f"node_{node_type}"
    data = _minimal_generated_node_data(node_type)

    validate_workflow_node_data({"id": node_id, "data": data})
    assert collect_generated_node_completeness_errors([{"id": node_id, "data": data}]) == []


def test_template_transform_generated_completeness_accepts_empty_variables():
    from core.workflow.generator.validation.node_config_validator import collect_generated_node_completeness_errors

    data = {
        "type": "template-transform",
        "template": "Static output",
        "variables": [],
    }

    validate_workflow_node_data({"id": "node_template-transform", "data": data})
    assert collect_generated_node_completeness_errors([{"id": "node_template-transform", "data": data}]) == []


@pytest.mark.parametrize(
    ("variables", "expected_field"),
    [
        pytest.param(
            [{"variable": "name", "value_selector": []}],
            "variables[0].value_selector",
            id="template-transform-empty-selector",
        ),
        pytest.param(
            [{"variable": "name", "value_selector": ["start"]}],
            "variables[0].value_selector",
            id="template-transform-single-part-selector",
        ),
        pytest.param(
            [{"variable": "name", "value_selector": ["start", ""]}],
            "variables[0].value_selector",
            id="template-transform-empty-selector-part",
        ),
        pytest.param(
            [{"variable": "1name", "value_selector": ["start", "name"]}],
            "variables[0].variable",
            id="template-transform-invalid-name",
        ),
        pytest.param(
            [{"variable": "x" * 31, "value_selector": ["start", "name"]}],
            "variables[0].variable",
            id="template-transform-name-too-long",
        ),
        pytest.param(
            [
                {"variable": "name", "value_selector": ["start", "name"]},
                {"variable": "name", "value_selector": ["start", "other"]},
            ],
            "variables[1].variable",
            id="template-transform-duplicate-name",
        ),
    ],
)
def test_template_transform_generated_completeness_rejects_invalid_variables(
    variables: list[dict[str, object]],
    expected_field: str,
):
    from core.workflow.generator.validation.node_config_validator import collect_generated_node_completeness_errors

    data = _minimal_generated_node_data("template-transform")
    data["variables"] = variables
    node_id = "node_template-transform"

    errors = collect_generated_node_completeness_errors([{"id": node_id, "data": data}])

    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_NODE_CONFIG
    assert errors[0]["node_id"] == node_id
    assert expected_field in errors[0]["detail"]


def test_if_else_schema_validation_adapts_official_null_operator_without_mutating_input():
    data = _minimal_generated_node_data("if-else")
    condition = data["cases"][0]["conditions"][0]
    condition.update(
        {
            "id": "condition-1",
            "varType": "string",
            "comparison_operator": "is null",
            "value": "",
        }
    )
    node = {"id": "branch", "data": data}
    before = deepcopy(node)

    assert collect_node_config_errors([node]) == []
    assert node == before


@pytest.mark.parametrize(
    ("case_ids", "expected_field"),
    [
        ([""], "cases[0].case_id"),
        (["same", "same"], "cases[1].case_id"),
        (["false"], "cases[0].case_id"),
    ],
)
def test_if_else_completeness_rejects_invalid_case_ids(case_ids: list[str], expected_field: str):
    from core.workflow.generator.validation.node_config_validator import collect_generated_node_completeness_errors

    data = _minimal_generated_node_data("if-else")
    template_case = deepcopy(data["cases"][0])
    data["cases"] = [{**deepcopy(template_case), "case_id": case_id} for case_id in case_ids]

    errors = collect_generated_node_completeness_errors([{"id": "branch", "data": data}])

    assert any(expected_field in error["detail"] for error in errors)


def test_if_else_completeness_accepts_reordered_first_uuid_and_official_null_operator():
    from core.workflow.generator.validation.node_config_validator import collect_generated_node_completeness_errors

    data = _minimal_generated_node_data("if-else")
    data["cases"][0]["case_id"] = "b61c92c8-2398-44e9-871a-278428a14c75"
    data["cases"][0]["conditions"][0].update(
        {
            "id": "condition-1",
            "varType": "string",
            "comparison_operator": "is not null",
            "value": "",
        }
    )

    assert collect_generated_node_completeness_errors([{"id": "branch", "data": data}]) == []


@pytest.mark.parametrize(
    ("data", "expected_field"),
    [
        (
            {
                "type": "loop",
                "start_node_id": "loopstart",
                "loop_count": 0,
                "break_conditions": [],
                "logical_operator": "and",
                "loop_variables": [],
            },
            "loop_count",
        ),
        (
            {
                "type": "loop",
                "start_node_id": "loopstart",
                "loop_count": -1,
                "break_conditions": [],
                "logical_operator": "and",
                "loop_variables": [],
            },
            "loop_count",
        ),
        (
            {
                "type": "loop",
                "start_node_id": "loopstart",
                "loop_count": 1,
                "break_conditions": [],
                "logical_operator": "and",
                "loop_variables": None,
            },
            "loop_variables",
        ),
        (
            {
                "type": "loop",
                "start_node_id": "loopstart",
                "loop_count": 1,
                "break_conditions": [],
                "logical_operator": "and",
                "loop_variables": [{"label": "count", "var_type": "number", "value_type": "constant"}],
            },
            "value",
        ),
        (
            {
                "type": "iteration",
                "start_node_id": "iterationstart",
                "iterator_selector": ["start", "items"],
                "output_selector": ["child", "result"],
                "parallel_nums": 0,
            },
            "parallel_nums",
        ),
        (
            {
                "type": "iteration",
                "start_node_id": "iterationstart",
                "iterator_selector": ["start", "items"],
                "output_selector": ["child", "result"],
                "parallel_nums": -1,
            },
            "parallel_nums",
        ),
    ],
)
def test_runtime_schema_rejects_invalid_container_boundaries(data: dict[str, object], expected_field: str):
    with pytest.raises(ValidationError) as exc_info:
        validate_workflow_node_data({"id": "container", "data": data})

    assert expected_field in str(exc_info.value)


@pytest.mark.parametrize(
    "data",
    [
        {
            "type": "iteration",
            "iterator_selector": ["start", "items"],
            "output_selector": ["child", "result"],
        },
        {
            "type": "loop",
            "loop_count": 1,
            "break_conditions": [],
            "logical_operator": "and",
            "loop_variables": [],
        },
    ],
)
def test_runtime_schema_requires_container_start_node_id(data: dict[str, object]):
    with pytest.raises(ValidationError) as exc_info:
        validate_workflow_node_data({"id": "container", "data": data})

    assert "start_node_id" in str(exc_info.value)


def test_runtime_schema_rejects_invalid_human_input_action_id():
    data = _minimal_generated_node_data("human-input")
    data["user_actions"] = [{"id": "approve-now", "title": "Approve", "button_style": "primary"}]

    with pytest.raises(ValidationError) as exc_info:
        validate_workflow_node_data({"id": "review", "data": data})

    assert "user_actions.0.id" in str(exc_info.value)


@pytest.mark.parametrize(
    "prompt_template",
    [
        [{"role": "user", "text": "", "edition_type": "jinja2", "jinja2_text": "Hello {{ name }}"}],
        {"text": "", "edition_type": "jinja2", "jinja2_text": "Hello {{ name }}"},
    ],
)
def test_generated_completeness_accepts_effective_jinja2_llm_prompt(prompt_template: object):
    from core.workflow.generator.validation.node_config_validator import collect_generated_node_completeness_errors

    data = _minimal_generated_node_data("llm")
    data["prompt_template"] = prompt_template
    validate_workflow_node_data({"id": "llm", "data": data})

    assert collect_generated_node_completeness_errors([{"id": "llm", "data": data}]) == []


def test_generated_completeness_rejects_basic_llm_prompt_with_only_stale_jinja2_text():
    from core.workflow.generator.validation.node_config_validator import collect_generated_node_completeness_errors

    data = _minimal_generated_node_data("llm")
    data["prompt_template"] = [{"role": "user", "text": "", "edition_type": "basic", "jinja2_text": "Ignored content"}]
    validate_workflow_node_data({"id": "llm", "data": data})

    errors = collect_generated_node_completeness_errors([{"id": "llm", "data": data}])

    assert len(errors) == 1
    assert "prompt_template" in errors[0]["detail"]


def test_generated_completeness_accepts_empty_llm_prompt_when_memory_enabled():
    data = _minimal_generated_node_data("llm")
    data["prompt_template"] = [{"role": "user", "text": ""}]
    data["memory"] = {"window": {"enabled": True, "size": 10}}
    validate_workflow_node_data({"id": "llm", "data": data})

    assert collect_generated_node_completeness_errors([{"id": "llm", "data": data}]) == []


def test_generated_completeness_rejects_jinja_llm_prompt_with_only_stale_basic_text():
    data = _minimal_generated_node_data("llm")
    data["prompt_template"] = [
        {"role": "user", "text": "Stale basic text", "edition_type": "jinja2", "jinja2_text": "  "}
    ]
    validate_workflow_node_data({"id": "llm", "data": data})

    errors = collect_generated_node_completeness_errors([{"id": "llm", "data": data}])

    assert len(errors) == 1
    assert "prompt_template" in errors[0]["detail"]


def test_generated_completeness_still_rejects_empty_model_when_memory_enabled():
    data = _minimal_generated_node_data("llm")
    data["prompt_template"] = [{"role": "user", "text": ""}]
    data["memory"] = {"window": {"enabled": True, "size": 10}}
    data["model"] = {"provider": "", "name": "gpt-4o", "mode": "chat"}

    errors = collect_generated_node_completeness_errors([{"id": "llm", "data": data}])

    assert any("model.provider" in error["detail"] for error in errors)


_ADDITIONAL_INCOMPLETE_CONFIGS: tuple[tuple[str, dict[str, object], str], ...] = (
    ("llm", {"model": {"provider": "", "name": "gpt-4o", "mode": "chat"}}, "model.provider"),
    ("llm", {"model": {"provider": "openai", "name": " ", "mode": "chat"}}, "model.name"),
    (
        "question-classifier",
        {"model": {"provider": "", "name": "gpt-4o", "mode": "chat"}},
        "model.provider",
    ),
    (
        "question-classifier",
        {"model": {"provider": "openai", "name": " ", "mode": "chat"}},
        "model.name",
    ),
    (
        "parameter-extractor",
        {"model": {"provider": "", "name": "gpt-4o", "mode": "chat"}},
        "model.provider",
    ),
    (
        "parameter-extractor",
        {"model": {"provider": "openai", "name": " ", "mode": "chat"}},
        "model.name",
    ),
    (
        "if-else",
        {"cases": [{"case_id": "true", "logical_operator": "and", "conditions": []}]},
        "cases[0].conditions",
    ),
    (
        "if-else",
        {
            "cases": [
                {
                    "case_id": "true",
                    "logical_operator": "and",
                    "conditions": [{"variable_selector": [], "comparison_operator": "empty", "value": None}],
                }
            ]
        },
        "cases[0].conditions[0].variable_selector",
    ),
    (
        "if-else",
        {
            "cases": [
                {
                    "case_id": "true",
                    "logical_operator": "and",
                    "conditions": [
                        {
                            "variable_selector": ["start", "query"],
                            "comparison_operator": "is",
                            "value": None,
                        }
                    ],
                }
            ]
        },
        "cases[0].conditions[0].value",
    ),
    ("question-classifier", {"classes": [{"id": "1", "name": "Only"}]}, "classes"),
    (
        "question-classifier",
        {"classes": [{"id": "", "name": "First"}, {"id": "2", "name": "Second"}]},
        "classes[0].id",
    ),
    (
        "question-classifier",
        {"classes": [{"id": "1", "name": " "}, {"id": "2", "name": "Second"}]},
        "classes[0].name",
    ),
    (
        "question-classifier",
        {"classes": [{"id": "1", "name": "First"}, {"id": "1", "name": "Second"}]},
        "classes[1].id",
    ),
    ("parameter-extractor", {"parameters": []}, "parameters"),
    (
        "parameter-extractor",
        {
            "parameters": [
                {"name": "topic", "type": "string", "description": "First", "required": True},
                {"name": "topic", "type": "number", "description": "Second", "required": False},
            ]
        },
        "parameters[1].name",
    ),
    ("variable-aggregator", {"variables": [["start", "items"], [""]]}, "variables[1]"),
    (
        "assigner",
        {
            "items": [
                {
                    "variable_selector": [],
                    "input_type": "constant",
                    "operation": "over-write",
                    "value": "done",
                }
            ]
        },
        "items[0].variable_selector",
    ),
    (
        "assigner",
        {
            "items": [
                {
                    "variable_selector": ["conversation", "result"],
                    "input_type": "variable",
                    "operation": "over-write",
                    "value": [],
                }
            ]
        },
        "items[0].value",
    ),
    ("human-input", {"delivery_methods": []}, "delivery_methods"),
    (
        "human-input",
        {"delivery_methods": [{"type": "webapp", "enabled": False}]},
        "delivery_methods",
    ),
    ("human-input", {"user_actions": []}, "user_actions"),
    ("iteration", {"output_selector": []}, "output_selector"),
    (
        "code",
        {"variables": [{"variable": "query", "value_selector": []}]},
        "variables[0].value_selector",
    ),
    (
        "code",
        {"variables": [{"variable": "1query", "value_selector": ["start", "query"]}]},
        "variables[0].variable",
    ),
    (
        "code",
        {
            "variables": [
                {"variable": "query", "value_selector": ["start", "query"]},
                {"variable": "query", "value_selector": ["start", "other"]},
            ]
        },
        "variables[1].variable",
    ),
)


@pytest.mark.parametrize(("node_type", "overrides", "expected_field"), _ADDITIONAL_INCOMPLETE_CONFIGS)
def test_generated_completeness_rejects_each_invalid_semantic_field(
    node_type: str,
    overrides: dict[str, object],
    expected_field: str,
):
    from core.workflow.generator.validation.node_config_validator import collect_generated_node_completeness_errors

    data = _minimal_generated_node_data(node_type)
    data.update(deepcopy(overrides))
    node_id = f"node_{node_type}"
    validate_workflow_node_data({"id": node_id, "data": data})

    errors = collect_generated_node_completeness_errors([{"id": node_id, "data": data}])

    assert len(errors) == 1
    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_NODE_CONFIG
    assert expected_field in errors[0]["detail"]


@pytest.mark.parametrize(
    ("node_type", "overrides"),
    [
        (
            "if-else",
            {
                "cases": [
                    {
                        "case_id": "true",
                        "logical_operator": "and",
                        "conditions": [
                            {
                                "variable_selector": ["start", "query"],
                                "comparison_operator": "",
                                "value": None,
                            }
                        ],
                    }
                ]
            },
        ),
        (
            "parameter-extractor",
            {"parameters": [{"name": "", "type": "string", "description": "", "required": True}]},
        ),
        (
            "parameter-extractor",
            {"parameters": [{"name": "topic", "type": "", "description": "", "required": True}]},
        ),
        (
            "assigner",
            {
                "items": [
                    {
                        "variable_selector": ["conversation", "result"],
                        "input_type": "unknown",
                        "operation": "over-write",
                    }
                ]
            },
        ),
        (
            "assigner",
            {
                "items": [
                    {
                        "variable_selector": ["conversation", "result"],
                        "input_type": "constant",
                        "operation": "unknown",
                    }
                ]
            },
        ),
    ],
)
def test_runtime_schema_rejects_invalid_semantic_enum_or_required_value(
    node_type: str,
    overrides: dict[str, object],
):
    data = _minimal_generated_node_data(node_type)
    data.update(overrides)

    with pytest.raises(ValidationError):
        validate_workflow_node_data({"id": f"node_{node_type}", "data": data})


@pytest.mark.parametrize("value", [False, 0, ""])
def test_assigner_constant_json_scalars_are_complete(value: object):
    from core.workflow.generator.validation.node_config_validator import collect_generated_node_completeness_errors

    data = _minimal_generated_node_data("assigner")
    data["items"] = [
        {
            "variable_selector": ["conversation", "result"],
            "input_type": "constant",
            "operation": "over-write",
            "value": value,
        }
    ]

    assert collect_generated_node_completeness_errors([{"id": "assign", "data": data}]) == []


@pytest.mark.parametrize("operation", ["clear", "remove-first", "remove-last"])
def test_assigner_no_value_operations_are_complete(operation: str):
    from core.workflow.generator.validation.node_config_validator import collect_generated_node_completeness_errors

    data = _minimal_generated_node_data("assigner")
    data["items"] = [
        {
            "variable_selector": ["conversation", "result"],
            "input_type": "constant",
            "operation": operation,
        }
    ]

    assert collect_generated_node_completeness_errors([{"id": "assign", "data": data}]) == []


def test_code_node_accepts_empty_outputs():
    node = {
        "id": "node_code",
        "data": {
            "type": "code",
            "variables": [],
            "code_language": "python3",
            "code": "def main():\n    return {}",
            "outputs": {},
        },
    }

    assert collect_node_config_errors([node]) == []


@pytest.mark.parametrize("outputs", [None, [], "result"])
def test_code_node_rejects_non_mapping_outputs(outputs: object):
    node = {
        "id": "node_code",
        "data": {
            "type": "code",
            "variables": [],
            "code_language": "python3",
            "code": "def main():\n    return {}",
            "outputs": outputs,
        },
    }

    errors = collect_node_config_errors([node])

    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_CODE_OUTPUT
    assert errors[0]["node_id"] == "node_code"


def test_code_node_rejects_bare_array_output_type():
    nodes = [
        {
            "id": "node_parse",
            "data": {
                "type": "code",
                "outputs": {"questions": {"type": "array", "children": None}},
            },
        }
    ]

    errors = collect_node_config_errors(nodes)

    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_CODE_OUTPUT
    assert errors[0]["node_id"] == "node_parse"
    assert "questions" in errors[0]["detail"]
    assert "'array'" in errors[0]["detail"]
    assert "array[object]" in errors[0]["detail"]


def test_code_node_accepts_whitelist_output_type():
    nodes = [
        {
            "id": "node_parse",
            "data": {
                "type": "code",
                "variables": [],
                "code_language": "python3",
                "code": "def main():\n    return {'questions': []}",
                "outputs": {"questions": {"type": "array[object]", "children": None}},
            },
        }
    ]

    assert collect_node_config_errors(nodes) == []


def test_end_node_reports_missing_value_type():
    nodes = [
        {
            "id": "node_end",
            "data": {
                "type": "end",
                "outputs": [{"variable": "accuracy", "value_selector": ["node_code", "accuracy"]}],
            },
        }
    ]

    errors = collect_node_config_errors(nodes)

    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_END_OUTPUT
    assert "accuracy" in errors[0]["detail"]
    assert "value_type" in errors[0]["detail"]


def test_end_node_accepts_empty_outputs_list():
    nodes = [{"id": "node_end", "data": {"type": "end", "outputs": []}}]
    assert collect_node_config_errors(nodes) == []


def test_generated_end_requires_at_least_one_output():
    nodes = [{"id": "node_end", "data": {"type": "end", "outputs": []}}]

    errors = collect_generated_node_completeness_errors(nodes)

    assert len(errors) == 1
    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_NODE_CONFIG
    assert errors[0]["node_id"] == "node_end"
    assert "outputs" in errors[0]["detail"]
    assert "at least one" in errors[0]["detail"]


def test_generated_end_accepts_one_complete_output():
    nodes = [
        {
            "id": "node_end",
            "data": {
                "type": "end",
                "outputs": [
                    {
                        "variable": "result",
                        "value_selector": ["node_llm", "text"],
                        "value_type": "string",
                    }
                ],
            },
        }
    ]

    assert collect_generated_node_completeness_errors(nodes) == []


def _complete_end_output(variable: str = "result") -> dict[str, object]:
    return {
        "variable": variable,
        "value_selector": ["start", "query"],
        "value_type": "string",
    }


def test_end_node_rejects_duplicate_output_names():
    nodes = [
        {
            "id": "node_end",
            "data": {
                "type": "end",
                "outputs": [_complete_end_output("result"), _complete_end_output("result")],
            },
        }
    ]

    errors = collect_node_config_errors(nodes)

    assert len(errors) == 1
    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_END_OUTPUT
    assert errors[0]["node_id"] == "node_end"
    assert "result" in errors[0]["detail"]
    assert "duplicate" in errors[0]["detail"]


def test_end_node_rejects_invalid_output_name():
    nodes = [
        {
            "id": "node_end",
            "data": {
                "type": "end",
                "outputs": [_complete_end_output("1 invalid")],
            },
        }
    ]

    errors = collect_node_config_errors(nodes)

    assert len(errors) == 1
    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_END_OUTPUT
    assert errors[0]["node_id"] == "node_end"
    assert "1 invalid" in errors[0]["detail"]
    assert "invalid name" in errors[0]["detail"]


def test_fill_end_output_value_types_infers_code_output_then_defaults_to_any():
    nodes = [
        {
            "id": "node_code",
            "data": {
                "type": "code",
                "variables": [],
                "code_language": "python3",
                "code": "def main():\n    return {'accuracy': 0}",
                "outputs": {"accuracy": {"type": "number", "children": None}},
            },
        },
        {
            "id": "node_end",
            "data": {
                "type": "end",
                "outputs": [
                    {"variable": "accuracy", "value_selector": ["node_code", "accuracy"]},
                    {"variable": "notes", "value_selector": ["missing", "x"]},
                ],
            },
        },
    ]

    fill_end_output_value_types(nodes)

    outputs = nodes[1]["data"]["outputs"]
    assert outputs[0]["value_type"] == "number"
    assert outputs[1]["value_type"] == "any"
    assert collect_node_config_errors(nodes) == []


def test_postprocess_fills_end_value_type():
    graph: GraphDict = {
        "nodes": [
            {"id": "start", "data": {"type": "start", "variables": []}},
            {
                "id": "end",
                "data": {
                    "type": "end",
                    "outputs": [{"variable": "result", "value_selector": ["start", "query"]}],
                },
            },
        ],
        "edges": [{"source": "start", "target": "end"}],
        "viewport": {"x": 0, "y": 0, "zoom": 0.7},
    }

    result = postprocess_graph(graph=graph, mode="workflow")
    end = next(node for node in result["nodes"] if node["id"] == "end")
    assert end["data"]["outputs"][0]["value_type"] == "any"


def _agent_data(**overrides: object) -> dict:
    data: dict = {
        "type": "agent",
        "version": "2",
        "agent_node_kind": "dify_agent",
        "agent_task": "research the question",
        "agent_binding": {"binding_type": "inline_agent"},
        "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
    }
    data.update(overrides)
    return data


def test_agent_node_accepts_inline_binding_without_ids():
    nodes = [{"id": "agent_1", "data": _agent_data()}]
    assert collect_node_config_errors(nodes) == []


def test_agent_rejects_settings_that_hydrate_cannot_parse():
    data = _agent_data(model={"provider": "openai", "name": "gpt-4o", "completion_params": {"temperature": []}})
    errors = collect_node_config_errors([{"id": "agent", "data": data}])
    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_AGENT_NODE
    assert "completion_params.temperature" in errors[0]["detail"]


def test_agent_node_rejects_missing_version():
    nodes = [{"id": "agent_1", "data": _agent_data(version="1")}]
    errors = collect_node_config_errors(nodes)
    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_AGENT_NODE
    assert "version='2'" in errors[0]["detail"]


def test_agent_node_rejects_empty_task():
    nodes = [{"id": "agent_1", "data": _agent_data(agent_task="  ")}]
    errors = collect_node_config_errors(nodes)
    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_AGENT_NODE
    assert "agent_task" in errors[0]["detail"]


def test_agent_node_rejects_invalid_model():
    nodes = [{"id": "agent_1", "data": _agent_data(model={"provider": "", "name": "gpt-4o"})}]
    errors = collect_node_config_errors(nodes)
    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_AGENT_NODE
    assert "provider" in errors[0]["detail"]


def test_agent_node_rejects_illegal_declared_output_type():
    nodes = [
        {
            "id": "agent_1",
            "data": _agent_data(agent_declared_outputs=[{"name": "questions", "type": "array[object]"}]),
        }
    ]
    errors = collect_node_config_errors(nodes)
    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_AGENT_NODE
    assert "agent_declared_outputs[0]" in errors[0]["detail"]


def test_agent_node_rejects_declared_output_name_format():
    nodes = [{"id": "agent_1", "data": _agent_data(agent_declared_outputs=[{"name": "bad-name", "type": "string"}])}]
    errors = collect_node_config_errors(nodes)
    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_AGENT_NODE
    assert "bad-name" in errors[0]["detail"]


def test_agent_node_rejects_duplicate_declared_output_names():
    nodes = [
        {
            "id": "agent_1",
            "data": _agent_data(
                agent_declared_outputs=[
                    {"name": "result", "type": "string"},
                    {"name": "result", "type": "number"},
                ]
            ),
        }
    ]
    errors = collect_node_config_errors(nodes)
    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_AGENT_NODE
    assert "duplicate name 'result'" in errors[0]["detail"]


def test_agent_node_rejects_non_object_dify_tools_entry():
    nodes = [{"id": "agent_1", "data": _agent_data(dify_tools=[42])}]
    errors = collect_node_config_errors(nodes)
    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_AGENT_NODE
    assert "dify_tools[0]" in errors[0]["detail"]


def test_agent_node_rejects_invalid_knowledge_projection():
    nodes = [
        {
            "id": "agent_1",
            "data": _agent_data(
                knowledge={
                    "sets": [
                        {
                            "id": "ks-1",
                            "name": "Docs",
                            "datasets": [],
                            "query": {"mode": "generated_query"},
                            "retrieval": {"mode": "multiple", "top_k": 4},
                        }
                    ]
                }
            ),
        }
    ]

    errors = collect_node_config_errors(nodes)

    assert errors[0]["code"] == WorkflowGenerateErrorCode.INVALID_AGENT_NODE
    assert "knowledge.sets.0" in errors[0]["detail"]


def test_unhydrated_inline_agent_is_not_a_config_error():
    from core.workflow.generator.validation.agent_config import collect_unhydrated_inline_agent_errors

    nodes = [{"id": "agent_1", "data": _agent_data()}]
    assert collect_node_config_errors(nodes) == []
    errors = collect_unhydrated_inline_agent_errors(nodes)
    assert errors[0]["code"] == WorkflowGenerateErrorCode.AGENT_BINDING_MISSING
    assert errors[0]["node_id"] == "agent_1"


def test_human_input_completeness_rejects_incomplete_email_and_ignores_target_branches():
    from core.workflow.generator.validation.node_config_validator import collect_generated_node_completeness_errors

    incomplete = _minimal_generated_node_data("human-input")
    incomplete["delivery_methods"] = [
        {
            "type": "email",
            "enabled": True,
            "config": {
                "recipients": {"include_bound_group": False, "items": []},
                "subject": "",
                "body": "missing url",
            },
        }
    ]
    incomplete["_targetBranches"] = [{"id": "stale"}]
    errors = collect_generated_node_completeness_errors([{"id": "review", "data": incomplete}])
    assert errors
    assert any(
        "subject" in item["detail"] or "url" in item["detail"] or "recipients" in item["detail"] for item in errors
    )

    valid = _minimal_generated_node_data("human-input")
    valid["_targetBranches"] = [{"id": "stale"}]
    assert collect_generated_node_completeness_errors([{"id": "review", "data": valid}]) == []

    slack = _minimal_generated_node_data("human-input")
    slack["delivery_methods"] = [{"type": "slack", "enabled": True}]
    slack_errors = collect_generated_node_completeness_errors([{"id": "review", "data": slack}])
    assert any("webapp and email" in item["detail"] for item in slack_errors)


def test_human_input_completeness_rejects_empty_titles_reserved_names_and_zero_timeout():
    from core.workflow.generator.validation.node_config_validator import collect_generated_node_completeness_errors

    empty_title = _minimal_generated_node_data("human-input")
    empty_title["user_actions"] = [{"id": "approve", "title": "  ", "button_style": "primary"}]
    title_errors = collect_generated_node_completeness_errors([{"id": "review", "data": empty_title}])
    assert any("user_actions[0].title" in item["detail"] for item in title_errors)

    reserved = _minimal_generated_node_data("human-input")
    reserved["inputs"] = [{"type": "paragraph", "output_variable_name": "__action_id"}]
    reserved_errors = collect_generated_node_completeness_errors([{"id": "review", "data": reserved}])
    assert any("reserved" in item["detail"] for item in reserved_errors)

    empty_name = _minimal_generated_node_data("human-input")
    empty_name["inputs"] = [{"type": "paragraph", "output_variable_name": ""}]
    name_errors = collect_generated_node_completeness_errors([{"id": "review", "data": empty_name}])
    assert any("output_variable_name" in item["detail"] for item in name_errors)

    zero_timeout = _minimal_generated_node_data("human-input")
    zero_timeout["timeout"] = 0
    timeout_errors = collect_generated_node_completeness_errors([{"id": "review", "data": zero_timeout}])
    assert any("timeout" in item["detail"] for item in timeout_errors)


def _knowledge_retrieval_base(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "type": "knowledge-retrieval",
        "title": "Search",
        "query_variable_selector": ["start", "query"],
        "query_attachment_selector": [],
        "dataset_ids": ["ds-1"],
        "retrieval_mode": "multiple",
        "multiple_retrieval_config": {
            "top_k": 4,
            "score_threshold": None,
            "reranking_enable": False,
        },
    }
    data.update(overrides)
    return data


def test_knowledge_retrieval_requires_query_or_attachment() -> None:
    node = {
        "id": "kr",
        "data": _knowledge_retrieval_base(
            query_variable_selector=[],
            query_attachment_selector=[],
        ),
    }

    errors = collect_generated_node_completeness_errors([node])

    assert any(error["node_id"] == "kr" and "query" in error["detail"] for error in errors)


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({"retrieval_mode": "single", "multiple_retrieval_config": None}, "single_retrieval_config.model"),
        ({"retrieval_mode": "multiple", "multiple_retrieval_config": None}, "multiple_retrieval_config"),
    ],
)
def test_knowledge_retrieval_requires_active_mode_config(data: dict[str, object], field: str) -> None:
    node_data = _knowledge_retrieval_base(**data)
    errors = collect_generated_node_completeness_errors([{"id": "kr", "data": node_data}])

    assert any(field in error["detail"] for error in errors)


def test_knowledge_retrieval_reranking_model_requires_provider_and_model() -> None:
    node_data = _knowledge_retrieval_base(
        multiple_retrieval_config={
            "top_k": 4,
            "score_threshold": None,
            "reranking_enable": True,
            "reranking_mode": "reranking_model",
        }
    )
    errors = collect_generated_node_completeness_errors([{"id": "kr", "data": node_data}])

    assert any("reranking_model" in error["detail"] for error in errors)


def test_knowledge_retrieval_weighted_score_requires_weights() -> None:
    node_data = _knowledge_retrieval_base(
        multiple_retrieval_config={
            "top_k": 4,
            "score_threshold": None,
            "reranking_mode": "weighted_score",
        }
    )
    errors = collect_generated_node_completeness_errors([{"id": "kr", "data": node_data}])

    assert any("weights" in error["detail"] for error in errors)


def test_knowledge_retrieval_weighted_score_accepts_valid_weights() -> None:
    node_data = _knowledge_retrieval_base(
        multiple_retrieval_config={
            "top_k": 4,
            "score_threshold": None,
            "reranking_mode": "weighted_score",
            "weights": {
                "vector_setting": {
                    "vector_weight": 0.7,
                    "embedding_provider_name": "openai",
                    "embedding_model_name": "text-embedding-3-small",
                },
                "keyword_setting": {"keyword_weight": 0.3},
            },
        }
    )

    assert collect_generated_node_completeness_errors([{"id": "kr", "data": node_data}]) == []


@pytest.mark.parametrize(
    ("top_k", "score_threshold", "field"),
    [
        (0, None, "top_k"),
        (11, None, "top_k"),
        (True, None, "top_k"),
        (4, -0.1, "score_threshold"),
        (4, 1.1, "score_threshold"),
        (4, True, "score_threshold"),
        (4, float("nan"), "score_threshold"),
        (4, float("inf"), "score_threshold"),
    ],
)
def test_knowledge_retrieval_rejects_illegal_top_k_and_score_threshold(
    top_k: object,
    score_threshold: object,
    field: str,
) -> None:
    node_data = _knowledge_retrieval_base(
        multiple_retrieval_config={
            "top_k": top_k,
            "score_threshold": score_threshold,
            "reranking_enable": False,
        }
    )
    errors = _knowledge_retrieval_completeness_errors("kr", node_data)

    assert any(field in error["detail"] for error in errors)


def test_knowledge_retrieval_generated_graph_rejects_out_of_range_retrieval_numbers() -> None:
    cases = (
        (0, None, "top_k"),
        (11, None, "top_k"),
        (4, -0.1, "score_threshold"),
        (4, 1.1, "score_threshold"),
    )
    for top_k, score_threshold, field in cases:
        node_data = _knowledge_retrieval_base(
            multiple_retrieval_config={
                "top_k": top_k,
                "score_threshold": score_threshold,
                "reranking_enable": False,
            }
        )
        errors = collect_generated_node_completeness_errors([{"id": "kr", "data": node_data}])
        assert any(field in error["detail"] for error in errors)


def test_loop_completeness_rejects_duplicate_variable_labels() -> None:
    errors = collect_generated_node_completeness_errors(
        [
            {
                "id": "loop",
                "data": {
                    "type": "loop",
                    "start_node_id": "loopstart",
                    "loop_count": 2,
                    "logical_operator": "and",
                    "break_conditions": [],
                    "loop_variables": [
                        {
                            "id": "a",
                            "label": "count",
                            "var_type": "number",
                            "value_type": "constant",
                            "value": 0,
                        },
                        {
                            "id": "b",
                            "label": "count",
                            "var_type": "number",
                            "value_type": "constant",
                            "value": 1,
                        },
                    ],
                },
            }
        ]
    )

    assert any("must be unique" in error["detail"] for error in errors)


def _loop_completeness_payload(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "type": "loop",
        "start_node_id": "loopstart",
        "loop_count": 2,
        "logical_operator": "and",
        "break_conditions": [],
        "loop_variables": [
            {
                "id": "a",
                "label": "count",
                "var_type": "number",
                "value_type": "constant",
                "value": 0,
            }
        ],
    }
    data.update(overrides)
    return data


def test_loop_completeness_rejects_illegal_value_type() -> None:
    errors = collect_generated_node_completeness_errors(
        [
            {
                "id": "loop",
                "data": _loop_completeness_payload(
                    loop_variables=[
                        {
                            "id": "a",
                            "label": "count",
                            "var_type": "number",
                            "value_type": "bogus",
                            "value": 0,
                        }
                    ]
                ),
            }
        ]
    )
    assert any("value_type" in error["detail"] for error in errors)


def test_loop_completeness_rejects_number_constant_string() -> None:
    errors = collect_generated_node_completeness_errors(
        [
            {
                "id": "loop",
                "data": _loop_completeness_payload(
                    loop_variables=[
                        {
                            "id": "a",
                            "label": "count",
                            "var_type": "number",
                            "value_type": "constant",
                            "value": "abc",
                        }
                    ]
                ),
            }
        ]
    )
    assert any("cannot be parsed as type" in error["detail"] for error in errors)


def test_loop_completeness_rejects_unsupported_break_operator() -> None:
    errors = collect_generated_node_completeness_errors(
        [
            {
                "id": "loop",
                "data": _loop_completeness_payload(
                    break_conditions=[
                        {
                            "id": "c1",
                            "variable_selector": ["loop", "count"],
                            "varType": "bogus",
                            "comparison_operator": ">",
                            "value": 1,
                        }
                    ]
                ),
            }
        ]
    )
    assert errors
    assert any("varType" in error["detail"] or "comparison_operator" in error["detail"] for error in errors)
