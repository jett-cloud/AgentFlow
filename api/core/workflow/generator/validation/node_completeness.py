"""node completeness."""

from __future__ import annotations

from collections.abc import Mapping

from core.workflow.generator.types import WorkflowGenerateErrorDict
from core.workflow.generator.validation.node_validation_values import (
    _ALLOWED_CODE_OUTPUT_TYPES,
    _ASSIGNER_NO_VALUE_OPERATIONS,
    _CODE_OUTPUT_NAME_RE,
    _HUMAN_INPUT_RESERVED_OUTPUTS,
    _LOOP_CONDITION_TYPES,
    _LOOP_OPERATORS_BY_TYPE,
    _LOOP_VALUE_TYPES,
    _TEMPLATE_VARIABLE_NAME_MAX_LENGTH,
    _UNARY_CONDITION_OPERATORS,
    _bounded_int,
    _completeness_error,
    _loop_constant_matches,
    _model_completeness_errors,
    _non_empty_list,
    _non_empty_string,
    _optional_unit_score,
    _prompt_message_has_effective_text,
    _required_text_errors,
    _selector_completeness_errors,
    _unit_weight,
    _valid_selector,
)


def _llm_completeness_errors(node_id: str, data: Mapping[str, object]) -> list[WorkflowGenerateErrorDict]:
    errors: list[WorkflowGenerateErrorDict] = []
    if not data.get("memory"):
        prompt_template = data.get("prompt_template")
        messages = prompt_template if isinstance(prompt_template, list | tuple) else [prompt_template]
        if not any(_prompt_message_has_effective_text(message) for message in messages):
            errors.append(_completeness_error(node_id, "prompt_template", "requires at least one non-empty message"))
    errors.extend(_model_completeness_errors(node_id, data))
    return errors


def _if_else_completeness_errors(node_id: str, data: Mapping[str, object]) -> list[WorkflowGenerateErrorDict]:
    cases = data.get("cases")
    if not _non_empty_list(cases):
        return [_completeness_error(node_id, "cases", "requires at least one case")]
    errors: list[WorkflowGenerateErrorDict] = []
    seen_case_ids: set[str] = set()
    for case_index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            continue
        case_id = case.get("case_id")
        if not _non_empty_string(case_id):
            errors.append(_completeness_error(node_id, f"cases[{case_index}].case_id", "must be non-empty"))
        elif case_id == "false":
            errors.append(
                _completeness_error(
                    node_id,
                    f"cases[{case_index}].case_id",
                    "must not use the reserved ELSE id 'false'",
                )
            )
        elif case_id in seen_case_ids:
            errors.append(_completeness_error(node_id, f"cases[{case_index}].case_id", "must be unique"))
        else:
            seen_case_ids.add(case_id)
        conditions = case.get("conditions")
        if not _non_empty_list(conditions):
            errors.append(
                _completeness_error(
                    node_id,
                    f"cases[{case_index}].conditions",
                    "requires at least one condition",
                )
            )
            continue
        for condition_index, condition in enumerate(conditions):
            if not isinstance(condition, Mapping):
                continue
            prefix = f"cases[{case_index}].conditions[{condition_index}]"
            if not _valid_selector(condition.get("variable_selector")):
                errors.append(_completeness_error(node_id, f"{prefix}.variable_selector", "is invalid"))
            operator = condition.get("comparison_operator")
            if not _non_empty_string(operator):
                errors.append(_completeness_error(node_id, f"{prefix}.comparison_operator", "must be non-empty"))
            elif operator not in _UNARY_CONDITION_OPERATORS and condition.get("value") is None:
                errors.append(_completeness_error(node_id, f"{prefix}.value", "is required for this operator"))
    return errors


def _question_classifier_completeness_errors(
    node_id: str,
    data: Mapping[str, object],
) -> list[WorkflowGenerateErrorDict]:
    errors = _model_completeness_errors(node_id, data)
    if not _valid_selector(data.get("query_variable_selector")):
        errors.append(_completeness_error(node_id, "query_variable_selector", "is invalid"))
    classes = data.get("classes")
    if not isinstance(classes, list) or len(classes) < 2:
        errors.append(_completeness_error(node_id, "classes", "requires at least two classes"))
        return errors
    seen_ids: set[str] = set()
    for index, class_config in enumerate(classes):
        if not isinstance(class_config, Mapping):
            continue
        class_id = class_config.get("id")
        if not _non_empty_string(class_id):
            errors.append(_completeness_error(node_id, f"classes[{index}].id", "must be non-empty"))
        elif class_id in seen_ids:
            errors.append(_completeness_error(node_id, f"classes[{index}].id", "must be unique"))
        else:
            seen_ids.add(class_id)
        if not _non_empty_string(class_config.get("name")):
            errors.append(_completeness_error(node_id, f"classes[{index}].name", "must be non-empty"))
    return errors


def _parameter_extractor_completeness_errors(
    node_id: str,
    data: Mapping[str, object],
) -> list[WorkflowGenerateErrorDict]:
    errors = _model_completeness_errors(node_id, data)
    if not _valid_selector(data.get("query")):
        errors.append(_completeness_error(node_id, "query", "is invalid"))
    parameters = data.get("parameters")
    if not _non_empty_list(parameters):
        errors.append(_completeness_error(node_id, "parameters", "requires at least one parameter"))
        return errors
    seen_names: set[str] = set()
    for index, parameter in enumerate(parameters):
        if not isinstance(parameter, Mapping):
            continue
        name = parameter.get("name")
        if isinstance(name, str) and name in seen_names:
            errors.append(_completeness_error(node_id, f"parameters[{index}].name", "must be unique"))
        elif isinstance(name, str):
            seen_names.add(name)
    return errors


def _variable_aggregator_completeness_errors(
    node_id: str,
    data: Mapping[str, object],
) -> list[WorkflowGenerateErrorDict]:
    variables = data.get("variables")
    if not _non_empty_list(variables):
        return [_completeness_error(node_id, "variables", "requires at least one selector")]
    return [
        _completeness_error(node_id, f"variables[{index}]", "is an invalid selector")
        for index, selector in enumerate(variables)
        if not _valid_selector(selector)
    ]


def _assigner_completeness_errors(node_id: str, data: Mapping[str, object]) -> list[WorkflowGenerateErrorDict]:
    items = data.get("items")
    if not _non_empty_list(items):
        return [_completeness_error(node_id, "items", "requires at least one assignment")]
    errors: list[WorkflowGenerateErrorDict] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            continue
        prefix = f"items[{index}]"
        if not _valid_selector(item.get("variable_selector")):
            errors.append(_completeness_error(node_id, f"{prefix}.variable_selector", "is invalid"))
        if (
            item.get("input_type") == "variable"
            and item.get("operation") not in _ASSIGNER_NO_VALUE_OPERATIONS
            and not _valid_selector(item.get("value"))
        ):
            errors.append(_completeness_error(node_id, f"{prefix}.value", "must be a variable selector"))
    return errors


def _human_input_completeness_errors(
    node_id: str,
    data: Mapping[str, object],
) -> list[WorkflowGenerateErrorDict]:
    errors = _required_text_errors(node_id, data, "form_content")
    delivery_methods = data.get("delivery_methods")
    if not isinstance(delivery_methods, list) or not any(
        isinstance(method, Mapping) and method.get("enabled") is True for method in delivery_methods
    ):
        errors.append(_completeness_error(node_id, "delivery_methods", "requires at least one enabled method"))
    for index, method in enumerate(delivery_methods if isinstance(delivery_methods, list) else []):
        if not isinstance(method, Mapping) or method.get("enabled") is not True:
            continue
        method_type = method.get("type")
        prefix = f"delivery_methods[{index}]"
        if method_type not in {"webapp", "email"}:
            errors.append(_completeness_error(node_id, prefix, "only webapp and email are supported"))
            continue
        if method_type != "email":
            continue
        config = method.get("config") if isinstance(method.get("config"), Mapping) else {}
        recipients = config.get("recipients") if isinstance(config.get("recipients"), Mapping) else {}
        subject = str(config.get("subject") or "")
        body = str(config.get("body") or "")
        items = recipients.get("items") if isinstance(recipients.get("items"), list) else []
        if not subject.strip():
            errors.append(_completeness_error(node_id, f"{prefix}.config.subject", "requires a subject"))
        if "{{#url#}}" not in body:
            errors.append(_completeness_error(node_id, f"{prefix}.config.body", "must include {{#url#}}"))
        if recipients.get("include_bound_group") is not True and not items:
            errors.append(
                _completeness_error(
                    node_id,
                    f"{prefix}.config.recipients",
                    "requires include_bound_group or at least one recipient",
                )
            )
    if not _non_empty_list(data.get("user_actions")):
        errors.append(_completeness_error(node_id, "user_actions", "requires at least one action"))
    else:
        for index, action in enumerate(data.get("user_actions") or []):
            if not isinstance(action, Mapping):
                continue
            if not _non_empty_string(action.get("title")):
                errors.append(
                    _completeness_error(node_id, f"user_actions[{index}].title", "requires a non-empty title")
                )
    timeout = data.get("timeout")
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0):
        errors.append(_completeness_error(node_id, "timeout", "must be a positive integer"))
    inputs = data.get("inputs")
    if isinstance(inputs, list):
        for index, item in enumerate(inputs):
            if not isinstance(item, Mapping):
                continue
            name = item.get("output_variable_name")
            prefix = f"inputs[{index}].output_variable_name"
            if not _non_empty_string(name):
                errors.append(_completeness_error(node_id, prefix, "requires a non-empty name"))
            elif name in _HUMAN_INPUT_RESERVED_OUTPUTS:
                errors.append(_completeness_error(node_id, prefix, "must not use a reserved output name"))
            elif not _CODE_OUTPUT_NAME_RE.fullmatch(str(name)):
                errors.append(_completeness_error(node_id, prefix, "is not a valid identifier"))
    return errors


def _loop_completeness_errors(
    node_id: str,
    data: Mapping[str, object],
) -> list[WorkflowGenerateErrorDict]:
    errors: list[WorkflowGenerateErrorDict] = []
    loop_count = data.get("loop_count")
    if isinstance(loop_count, bool) or not isinstance(loop_count, int) or loop_count < 1 or loop_count > 100:
        errors.append(_completeness_error(node_id, "loop_count", "must be an integer from 1 to 100"))

    variables = data.get("loop_variables")
    if not isinstance(variables, list):
        errors.append(_completeness_error(node_id, "loop_variables", "must be a list"))
        return errors

    seen_labels: set[str] = set()
    for index, item in enumerate(variables):
        if not isinstance(item, Mapping):
            continue
        prefix = f"loop_variables[{index}]"
        if not _non_empty_string(item.get("id")):
            errors.append(_completeness_error(node_id, f"{prefix}.id", "requires a non-empty id"))
        label = item.get("label")
        if not _non_empty_string(label):
            errors.append(_completeness_error(node_id, f"{prefix}.label", "requires a non-empty name"))
        elif not _CODE_OUTPUT_NAME_RE.fullmatch(str(label)):
            errors.append(_completeness_error(node_id, f"{prefix}.label", "is not a valid identifier"))
        elif str(label) in seen_labels:
            errors.append(_completeness_error(node_id, f"{prefix}.label", "must be unique"))
        else:
            seen_labels.add(str(label))
        if item.get("var_type") not in _ALLOWED_CODE_OUTPUT_TYPES:
            errors.append(_completeness_error(node_id, f"{prefix}.var_type", "is not a supported loop variable type"))
        value_type = item.get("value_type")
        if value_type not in _LOOP_VALUE_TYPES:
            errors.append(_completeness_error(node_id, f"{prefix}.value_type", "must be constant or variable"))
        if value_type == "variable" and not _valid_selector(item.get("value")):
            errors.append(_completeness_error(node_id, f"{prefix}.value", "requires a bound node and variable"))
        elif value_type == "constant" and "value" not in item:
            errors.append(_completeness_error(node_id, f"{prefix}.value", "requires a value"))
        elif value_type == "constant" and not _loop_constant_matches(item.get("var_type"), item.get("value")):
            errors.append(_completeness_error(node_id, f"{prefix}.value", "cannot be parsed as type of var_type"))

    conditions = data.get("break_conditions")
    if isinstance(conditions, list):
        for index, condition in enumerate(conditions):
            if not isinstance(condition, Mapping):
                continue
            prefix = f"break_conditions[{index}]"
            if not _non_empty_string(condition.get("id")):
                errors.append(_completeness_error(node_id, f"{prefix}.id", "requires a non-empty id"))
            if not _valid_selector(condition.get("variable_selector")):
                errors.append(_completeness_error(node_id, f"{prefix}.variable_selector", "is invalid"))
            if not _non_empty_string(condition.get("varType")):
                errors.append(_completeness_error(node_id, f"{prefix}.varType", "must be non-empty"))
            elif condition.get("varType") not in _LOOP_CONDITION_TYPES:
                errors.append(_completeness_error(node_id, f"{prefix}.varType", "is not a supported condition type"))
            operator = condition.get("comparison_operator")
            if not _non_empty_string(operator):
                errors.append(_completeness_error(node_id, f"{prefix}.comparison_operator", "must be non-empty"))
            else:
                allowed_operators = _LOOP_OPERATORS_BY_TYPE.get(str(condition.get("varType") or ""), frozenset())
                if str(condition.get("varType") or "") in _LOOP_CONDITION_TYPES and operator not in allowed_operators:
                    errors.append(
                        _completeness_error(
                            node_id,
                            f"{prefix}.comparison_operator",
                            "is not valid for varType",
                        )
                    )
                elif operator not in _UNARY_CONDITION_OPERATORS and condition.get("value") is None:
                    errors.append(_completeness_error(node_id, f"{prefix}.value", "is required for this operator"))
    return errors


def _iteration_completeness_errors(
    node_id: str,
    data: Mapping[str, object],
) -> list[WorkflowGenerateErrorDict]:
    errors = _selector_completeness_errors(node_id, data, "iterator_selector")
    errors.extend(_selector_completeness_errors(node_id, data, "output_selector"))
    return errors


def _code_completeness_errors(node_id: str, data: Mapping[str, object]) -> list[WorkflowGenerateErrorDict]:
    errors: list[WorkflowGenerateErrorDict] = []
    code = data.get("code")
    if not isinstance(code, str) or not code.strip():
        errors.append(_completeness_error(node_id, "code", "requires non-empty source code"))

    variables = data.get("variables")
    if not isinstance(variables, list):
        return errors

    seen: set[str] = set()
    for index, variable in enumerate(variables):
        if not isinstance(variable, Mapping):
            continue
        name = variable.get("variable")
        if not isinstance(name, str) or not _CODE_OUTPUT_NAME_RE.fullmatch(name):
            errors.append(_completeness_error(node_id, f"variables[{index}].variable", "requires a valid identifier"))
        elif name in seen:
            errors.append(_completeness_error(node_id, f"variables[{index}].variable", "must be unique"))
        else:
            seen.add(name)

        if not _valid_selector(variable.get("value_selector")):
            errors.append(
                _completeness_error(
                    node_id,
                    f"variables[{index}].value_selector",
                    "requires a bound node and variable",
                )
            )
    return errors


def _template_transform_completeness_errors(
    node_id: str,
    data: Mapping[str, object],
) -> list[WorkflowGenerateErrorDict]:
    errors = _required_text_errors(node_id, data, "template")
    variables = data.get("variables")
    if not isinstance(variables, list):
        return errors

    seen: set[str] = set()
    for index, variable in enumerate(variables):
        if not isinstance(variable, Mapping):
            continue
        name = variable.get("variable")
        field = f"variables[{index}].variable"
        if (
            not isinstance(name, str)
            or len(name) > _TEMPLATE_VARIABLE_NAME_MAX_LENGTH
            or not _CODE_OUTPUT_NAME_RE.fullmatch(name)
        ):
            errors.append(_completeness_error(node_id, field, "requires a valid identifier of at most 30 characters"))
        elif name in seen:
            errors.append(_completeness_error(node_id, field, "must be unique"))
        else:
            seen.add(name)

        if not _valid_selector(variable.get("value_selector")):
            errors.append(
                _completeness_error(
                    node_id,
                    f"variables[{index}].value_selector",
                    "requires a bound node and variable",
                )
            )
    return errors


def _end_completeness_errors(
    node_id: str,
    data: Mapping[str, object],
) -> list[WorkflowGenerateErrorDict]:
    if not _non_empty_list(data.get("outputs")):
        return [_completeness_error(node_id, "outputs", "requires at least one output")]
    return []


def _knowledge_retrieval_completeness_errors(
    node_id: str,
    data: Mapping[str, object],
) -> list[WorkflowGenerateErrorDict]:
    errors: list[WorkflowGenerateErrorDict] = []
    query_selector = data.get("query_variable_selector")
    attachment_selector = data.get("query_attachment_selector")
    if not _valid_selector(query_selector) and not _valid_selector(attachment_selector):
        errors.append(_completeness_error(node_id, "query", "requires a query or attachment selector"))

    retrieval_mode = data.get("retrieval_mode")
    if retrieval_mode == "single":
        single = data.get("single_retrieval_config")
        model = single.get("model") if isinstance(single, Mapping) else None
        if not isinstance(model, Mapping):
            errors.append(_completeness_error(node_id, "single_retrieval_config.model", "is required"))
        else:
            for field in ("provider", "name"):
                if not _non_empty_string(model.get(field)):
                    errors.append(
                        _completeness_error(
                            node_id,
                            f"single_retrieval_config.model.{field}",
                            "must be non-empty",
                        )
                    )
    elif retrieval_mode == "multiple":
        multiple = data.get("multiple_retrieval_config")
        if not isinstance(multiple, Mapping):
            errors.append(_completeness_error(node_id, "multiple_retrieval_config", "is required"))
        else:
            if not _bounded_int(multiple.get("top_k"), minimum=1, maximum=10):
                errors.append(
                    _completeness_error(
                        node_id,
                        "multiple_retrieval_config.top_k",
                        "must be an integer between 1 and 10",
                    )
                )
            if not _optional_unit_score(multiple.get("score_threshold")):
                errors.append(
                    _completeness_error(
                        node_id,
                        "multiple_retrieval_config.score_threshold",
                        "must be a finite number between 0 and 1",
                    )
                )
            reranking_mode = multiple.get("reranking_mode") or "reranking_model"
            if reranking_mode == "reranking_model" and multiple.get("reranking_enable"):
                model = multiple.get("reranking_model")
                if not isinstance(model, Mapping):
                    errors.append(
                        _completeness_error(node_id, "multiple_retrieval_config.reranking_model", "is required")
                    )
                else:
                    for field in ("provider", "model"):
                        if not _non_empty_string(model.get(field)):
                            errors.append(
                                _completeness_error(
                                    node_id,
                                    f"multiple_retrieval_config.reranking_model.{field}",
                                    "must be non-empty",
                                )
                            )
            elif reranking_mode == "weighted_score":
                weights = multiple.get("weights")
                vector = weights.get("vector_setting") if isinstance(weights, Mapping) else None
                keyword = weights.get("keyword_setting") if isinstance(weights, Mapping) else None
                vector_weight = vector.get("vector_weight") if isinstance(vector, Mapping) else None
                keyword_weight = keyword.get("keyword_weight") if isinstance(keyword, Mapping) else None
                normalized_vector_weight = _unit_weight(vector_weight)
                normalized_keyword_weight = _unit_weight(keyword_weight)
                weights_are_valid = (
                    isinstance(vector, Mapping)
                    and isinstance(keyword, Mapping)
                    and normalized_vector_weight is not None
                    and normalized_keyword_weight is not None
                    and abs(normalized_vector_weight + normalized_keyword_weight - 1) <= 1e-6
                    and _non_empty_string(vector.get("embedding_provider_name"))
                    and _non_empty_string(vector.get("embedding_model_name"))
                )
                if not weights_are_valid:
                    errors.append(
                        _completeness_error(
                            node_id,
                            "multiple_retrieval_config.weights",
                            "must define valid vector and keyword weights",
                        )
                    )
            elif reranking_mode != "reranking_model":
                errors.append(
                    _completeness_error(
                        node_id,
                        "multiple_retrieval_config.reranking_mode",
                        "must be 'reranking_model' or 'weighted_score'",
                    )
                )

    metadata_mode = data.get("metadata_filtering_mode") or "disabled"
    if metadata_mode == "automatic":
        model = data.get("metadata_model_config")
        if not isinstance(model, Mapping):
            errors.append(_completeness_error(node_id, "metadata_model_config", "is required"))
        else:
            for field in ("provider", "name"):
                if not _non_empty_string(model.get(field)):
                    errors.append(_completeness_error(node_id, f"metadata_model_config.{field}", "must be non-empty"))
    elif metadata_mode == "manual":
        conditions = data.get("metadata_filtering_conditions")
        items = conditions.get("conditions") if isinstance(conditions, Mapping) else None
        if not _non_empty_list(items):
            errors.append(
                _completeness_error(node_id, "metadata_filtering_conditions.conditions", "requires a condition")
            )
    return errors
