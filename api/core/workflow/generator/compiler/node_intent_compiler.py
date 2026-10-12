"""Deterministically compile typed ordinary-node intent into runtime config."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from core.workflow.generator.compiler.intents.common import ConstantValueIntent, VariableRefIntent
from core.workflow.generator.compiler.intents.node_intent import (
    AnswerStructureIntent,
    AssignerStructureIntent,
    CodeStructureIntent,
    DocumentExtractorStructureIntent,
    EndStructureIntent,
    HttpBinaryBodyIntent,
    HttpCredentialAuthIntent,
    HttpFileFieldIntent,
    HttpFormBodyIntent,
    HttpRequestStructureIntent,
    HttpTextBodyIntent,
    HumanConstantOptionsIntent,
    HumanConstantStringIntent,
    HumanEmailDeliveryIntent,
    HumanFileInputIntent,
    HumanInputStructureIntent,
    HumanParagraphInputIntent,
    HumanSelectInputIntent,
    HumanVariableOptionsIntent,
    HumanVariableStringIntent,
    IfElseStructureIntent,
    KnowledgeRetrievalStructureIntent,
    ListOperatorStructureIntent,
    LLMStructureIntent,
    NodeBuildIntent,
    ParameterExtractorStructureIntent,
    QuestionClassifierStructureIntent,
    StartStructureIntent,
    StartVariableIntent,
    TemplateStructureIntent,
    VariableAggregatorStructureIntent,
)
from core.workflow.generator.compiler.node_compile_context import NodeCompileContext
from core.workflow.generator.resources.model_catalogue import resolve_agent_model
from core.workflow.generator.validation.condition_operators import (
    CONDITION_OPERATORS_BY_TYPE,
    validate_condition_value,
)
from core.workflow.generator.variables.syntax import collect_exact_references
from core.workflow.generator.variables.type_unification import unify_branch_types
from core.workflow.generator.variables.variable_registry import VariableResolutionError, canonical_registry_type
from core.workflow.generator.variables.variable_types import array_item_type, is_array_type


class NodeIntentCompileError(ValueError):
    """Stable semantic error produced before runtime graph validation."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        path: str,
        cause: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.path = path
        self.cause = dict(cause) if cause is not None else {"error_code": code, "error": detail}


def compile_node_intent(
    *,
    intent: NodeBuildIntent,
    context: NodeCompileContext,
    base_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one runtime config with typed semantic fields compiled by code."""
    config = deepcopy(dict(base_config))
    structure = intent.structure
    if structure is None:
        return config
    if isinstance(structure, StartStructureIntent):
        config["variables"] = [_start_variable(item) for item in structure.variables]
    elif isinstance(structure, EndStructureIntent):
        config["outputs"] = [
            {
                "variable": item.name,
                "value_selector": list(item.source),
                "value_type": _end_output_type(
                    context,
                    selector=item.source,
                    declared_type=item.type,
                    path=f"structure.outputs[{index}].source",
                ),
            }
            for index, item in enumerate(structure.outputs)
        ]
    elif isinstance(structure, AnswerStructureIntent):
        config["variables"] = []
        config["answer"] = structure.content
    elif isinstance(structure, TemplateStructureIntent):
        _resolve_bindings(context, structure.bindings, path="structure.bindings")
        config["template"] = structure.template
        config["variables"] = [
            {"variable": item.name, "value_selector": list(item.source)} for item in structure.bindings
        ]
    elif isinstance(structure, DocumentExtractorStructureIntent):
        actual_type = _resolve_source_type(
            context,
            structure.source,
            path="structure.source",
            required=True,
        )
        if actual_type not in {"file", "array[file]"}:
            raise NodeIntentCompileError(
                "VARIABLE_TYPE_MISMATCH",
                f"Document extractor source must be file or array[file], got {actual_type!r}",
                path="structure.source",
                cause={
                    "error_code": "VARIABLE_TYPE_MISMATCH",
                    "selector": list(structure.source),
                    "expected": ["file", "array[file]"],
                    "actual": actual_type,
                },
            )
        config["variable_selector"] = list(structure.source)
        config.pop("is_array_file", None)
    elif isinstance(structure, LLMStructureIntent):
        _validate_model(context, structure.model, path="structure.model")
        _validate_prompt_references(context, structure)
        config["model"] = structure.model.model_dump(mode="python")
        config["prompt_template"] = [item.model_dump(mode="python") for item in structure.prompt]
        config.setdefault("context", {"enabled": False, "variable_selector": []})
        config.setdefault("vision", {"enabled": False})
    elif isinstance(structure, CodeStructureIntent):
        _resolve_bindings(context, structure.bindings, path="structure.bindings")
        config["code_language"] = structure.language
        config["code"] = structure.code
        config["variables"] = [
            {"variable": item.name, "value_selector": list(item.source)} for item in structure.bindings
        ]
        config["outputs"] = {
            item.name: {"type": item.type, "children": _compile_output_children(item.children)}
            for item in intent.outputs
            if item.type is not None
        }
    elif isinstance(structure, IfElseStructureIntent):
        config["cases"] = _compile_if_else(context, structure)
        config.pop("conditions", None)
        config.pop("logical_operator", None)
        config.pop("_targetBranches", None)
    elif isinstance(structure, QuestionClassifierStructureIntent):
        _validate_model(context, structure.model, path="structure.model")
        _require_source_type(context, structure.query, expected="string", path="structure.query")
        config["query_variable_selector"] = list(structure.query)
        config["model"] = structure.model.model_dump(mode="python")
        config["classes"] = [item.model_dump(mode="python") for item in structure.classes]
        config["_targetBranches"] = [{"id": item.id, "name": ""} for item in structure.classes]
        config["vision"] = {"enabled": False}
        config["instruction"] = structure.instruction
    elif isinstance(structure, ParameterExtractorStructureIntent):
        _validate_model(context, structure.model, path="structure.model")
        _require_source_type(context, structure.query, expected="string", path="structure.query")
        config["query"] = list(structure.query)
        config["model"] = structure.model.model_dump(mode="python")
        config["parameters"] = [item.model_dump(mode="python", exclude_none=True) for item in structure.parameters]
        config["reasoning_mode"] = structure.reasoning_mode
        config["vision"] = {"enabled": False}
        config["instruction"] = structure.instruction
    elif isinstance(structure, VariableAggregatorStructureIntent):
        source_types = [
            _resolve_source_type(
                context,
                selector,
                path=f"structure.sources[{index}]",
                required=True,
            )
            for index, selector in enumerate(structure.sources)
        ]
        try:
            output_type = unify_branch_types(item for item in source_types if item is not None)
        except ValueError as exc:
            raise NodeIntentCompileError(
                "INCOMPATIBLE_BRANCH_TYPES",
                str(exc),
                path="structure.sources",
                cause={
                    "error_code": "INCOMPATIBLE_BRANCH_TYPES",
                    "selectors": [list(item) for item in structure.sources],
                    "actual_types": source_types,
                },
            ) from exc
        config["variables"] = [list(item) for item in structure.sources]
        config["output_type"] = output_type
        config.pop("advanced_settings", None)
    elif isinstance(structure, ListOperatorStructureIntent):
        _compile_list_operator(config=config, context=context, structure=structure)
    elif isinstance(structure, KnowledgeRetrievalStructureIntent):
        _compile_knowledge_retrieval(config=config, context=context, structure=structure)
    elif isinstance(structure, HttpRequestStructureIntent):
        _compile_http_request(config=config, context=context, structure=structure)
    elif isinstance(structure, HumanInputStructureIntent):
        _compile_human_input(config=config, context=context, structure=structure)
    elif isinstance(structure, AssignerStructureIntent):
        _compile_assigner(config=config, context=context, structure=structure)
    return config


def _compile_assigner(
    *,
    config: dict[str, Any],
    context: NodeCompileContext,
    structure: AssignerStructureIntent,
) -> None:
    """Compile explicit writes against the same registry on every surface."""
    registry = context.variable_registry
    if registry is None:
        raise NodeIntentCompileError(
            "CAPABILITY_UNAVAILABLE",
            "A typed variable registry is required to compile an assigner",
            path="structure.assignments",
            cause={
                "error_code": "CAPABILITY_UNAVAILABLE",
                "capability": "variable_registry",
                "hint": "Retry after the variable snapshot is available",
            },
        )

    items: list[dict[str, Any]] = []
    for index, assignment in enumerate(structure.assignments):
        target_path = f"structure.assignments[{index}].target"
        try:
            target = registry.resolve_writable(assignment.target, referrer_id=context.node_id)
        except VariableResolutionError as exc:
            cause: dict[str, object] = {
                "error_code": exc.code,
                "error": exc.detail,
                "selector": list(exc.selector),
                "writable_selectors": [list(item) for item in registry.writable_selectors()[:50]],
                "hint": "Choose one of the declared writable variables",
            }
            raise NodeIntentCompileError(exc.code, exc.detail, path=target_path, cause=cause) from exc

        item: dict[str, Any] = {
            "variable_selector": list(assignment.target),
            "operation": assignment.operation,
        }
        if assignment.operation == "clear":
            item.update({"input_type": "constant", "value": None})
            items.append(item)
            continue

        value = assignment.value
        value_path = f"structure.assignments[{index}].value"
        if isinstance(value, VariableRefIntent):
            try:
                registry.resolve(
                    value.selector,
                    referrer_id=context.node_id,
                    expected_type=target.value_type,
                )
            except VariableResolutionError as exc:
                cause = {
                    "error_code": exc.code,
                    "error": exc.detail,
                    "selector": list(exc.selector),
                    "hint": f"Provide a value compatible with {canonical_registry_type(target.value_type)!r}",
                }
                if exc.code in {"UNKNOWN_OUTPUT", "UNKNOWN_TOOL_OUTPUT"} and exc.selector:
                    cause["available_outputs"] = list(registry.outputs_for(exc.selector[0]))
                raise NodeIntentCompileError(
                    exc.code,
                    exc.detail,
                    path=f"{value_path}.selector",
                    cause=cause,
                ) from exc
            item.update({"input_type": "variable", "value": list(value.selector)})
        elif isinstance(value, ConstantValueIntent):
            if not _constant_matches_type(value.value, target.value_type):
                expected = canonical_registry_type(target.value_type)
                raise NodeIntentCompileError(
                    "VARIABLE_TYPE_MISMATCH",
                    f"constant value is incompatible with target type {expected!r}",
                    path=f"{value_path}.value",
                    cause={
                        "error_code": "VARIABLE_TYPE_MISMATCH",
                        "expected": expected,
                        "actual": type(value.value).__name__,
                        "target": list(assignment.target),
                        "hint": f"Use a constant compatible with {expected!r}",
                    },
                )
            item.update({"input_type": "constant", "value": value.value})
        else:  # Pydantic guards this; keep the compiler fail-closed.
            raise NodeIntentCompileError(
                "INVALID_ARGUMENT",
                "over-write requires a variable or constant value",
                path=value_path,
                cause={
                    "error_code": "INVALID_ARGUMENT",
                    "hint": "Set value.kind to 'variable' or 'constant'",
                },
            )
        items.append(item)

    config.clear()
    config.update({"version": "2", "items": items})


def _constant_matches_type(value: object, value_type: str) -> bool:
    canonical = canonical_registry_type(value_type)
    if canonical == "string":
        return isinstance(value, str)
    if canonical == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if canonical == "boolean":
        return isinstance(value, bool)
    if canonical == "object":
        return isinstance(value, dict)
    if canonical == "array":
        return isinstance(value, list)
    if canonical.startswith("array[") and canonical.endswith("]"):
        if not isinstance(value, list):
            return False
        item_type = canonical[6:-1]
        return all(_constant_matches_type(item, item_type) for item in value)
    return False


def _validate_model(context: NodeCompileContext, model: Any, *, path: str) -> None:
    if context.model_entries is None:
        raise NodeIntentCompileError(
            "CAPABILITY_UNAVAILABLE",
            "Model catalogue is unavailable for typed node compilation",
            path=path,
            cause={"error_code": "CAPABILITY_UNAVAILABLE", "capability": "model_catalogue"},
        )
    entry = resolve_agent_model(
        context.model_entries,
        provider=model.provider,
        name=model.name,
    )
    if entry is None:
        raise NodeIntentCompileError(
            "UNKNOWN_MODEL",
            f"Model {model.provider}/{model.name} is not in this run's model snapshot",
            path=path,
            cause={
                "error_code": "UNKNOWN_MODEL",
                "provider": model.provider,
                "name": model.name,
                "available_models": [
                    {"provider": item["provider"], "name": item["name"]} for item in context.model_entries
                ],
            },
        )


def _validate_prompt_references(context: NodeCompileContext, structure: LLMStructureIntent) -> None:
    for index, message in enumerate(structure.prompt):
        references = collect_exact_references({"text": message.text})
        for selector in references:
            _resolve_source_type(
                context,
                selector,
                path=f"structure.prompt[{index}].text",
                required=False,
            )


def _compile_if_else(context: NodeCompileContext, structure: IfElseStructureIntent) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for case_index, case in enumerate(structure.cases):
        conditions: list[dict[str, Any]] = []
        for condition_index, condition in enumerate(case.conditions):
            path = f"structure.cases[{case_index}].conditions[{condition_index}]"
            actual_type = _resolve_source_type(context, condition.source, path=f"{path}.source", required=True)
            assert actual_type is not None
            try:
                value = validate_condition_value(
                    value_type=actual_type,
                    operator=condition.operator,
                    value=condition.value,
                )
            except ValueError as exc:
                raise NodeIntentCompileError(
                    "INVALID_CONDITION",
                    str(exc),
                    path=f"{path}.operator" if "operator" in str(exc) else f"{path}.value",
                    cause={
                        "error_code": "INVALID_CONDITION",
                        "selector": list(condition.source),
                        "actual_type": actual_type,
                        "operator": condition.operator,
                    },
                ) from exc
            conditions.append(
                {
                    "id": str(
                        uuid5(NAMESPACE_URL, f"workflow-assist:{context.node_id}:{case_index}:{condition_index}")
                    ),
                    "variable_selector": list(condition.source),
                    "comparison_operator": condition.operator,
                    "value": value,
                    "varType": actual_type,
                }
            )
        cases.append(
            {
                "case_id": case.id,
                "logical_operator": case.logical_operator,
                "conditions": conditions,
            }
        )
    return cases


def _compile_list_operator(
    *,
    config: dict[str, Any],
    context: NodeCompileContext,
    structure: ListOperatorStructureIntent,
) -> None:
    source_type = _resolve_source_type(context, structure.source, path="structure.source", required=True)
    assert source_type is not None
    if not is_array_type(source_type):
        raise NodeIntentCompileError(
            "VARIABLE_TYPE_MISMATCH",
            f"List operator source must be an array, got {source_type!r}",
            path="structure.source",
            cause={
                "error_code": "VARIABLE_TYPE_MISMATCH",
                "selector": list(structure.source),
                "expected": "array",
                "actual": source_type,
            },
        )
    item_type = array_item_type(source_type)
    compiled_filters: list[dict[str, Any]] = []
    for index, item in enumerate(structure.filters):
        path = f"structure.filters[{index}]"
        if item_type == "object":
            if not item.key:
                raise NodeIntentCompileError(
                    "INVALID_LIST_OPERATION",
                    "Object-array filters require a field key",
                    path=f"{path}.key",
                )
            comparison_type = _list_object_comparison_type(item.operator, item.value, path=path)
        else:
            if item.key:
                raise NodeIntentCompileError(
                    "INVALID_LIST_OPERATION",
                    "Scalar-array filters must not include a field key",
                    path=f"{path}.key",
                )
            comparison_type = item_type
        try:
            value = validate_condition_value(
                value_type=comparison_type,
                operator=item.operator,
                value=item.value,
            )
        except ValueError as exc:
            raise NodeIntentCompileError(
                "INVALID_LIST_OPERATION",
                str(exc),
                path=f"{path}.operator" if "operator" in str(exc) else f"{path}.value",
            ) from exc
        compiled_filters.append({"key": item.key, "comparison_operator": item.operator, "value": value})

    if structure.sort is not None and item_type != "object":
        raise NodeIntentCompileError(
            "INVALID_LIST_OPERATION",
            "Sort keys are supported only for object-array elements",
            path="structure.sort.key",
            cause={"error_code": "INVALID_LIST_OPERATION", "element_type": item_type},
        )
    config["variable"] = list(structure.source)
    config["filter_by"] = {"enabled": bool(compiled_filters), "conditions": compiled_filters}
    config["order_by"] = {
        "enabled": structure.sort is not None,
        "key": structure.sort.key if structure.sort is not None else "",
        "value": structure.sort.direction if structure.sort is not None else "asc",
    }
    config["limit"] = {
        "enabled": structure.limit is not None,
        "size": structure.limit if structure.limit is not None else 10,
    }
    config["extract_by"] = {
        "enabled": structure.extract_serial is not None,
        "serial": str(structure.extract_serial or 1),
    }


def _list_object_comparison_type(operator: str, value: Any, *, path: str) -> str:
    if operator in CONDITION_OPERATORS_BY_TYPE["number"] - {"empty", "not empty"}:
        return "number"
    if operator in {"empty", "not empty"}:
        return "string"
    if operator in {"is", "is not"} and isinstance(value, bool):
        return "boolean"
    if operator in CONDITION_OPERATORS_BY_TYPE["string"]:
        return "string"
    raise NodeIntentCompileError(
        "INVALID_LIST_OPERATION",
        f"operator {operator!r} is not supported for object fields",
        path=f"{path}.operator",
    )


def _compile_knowledge_retrieval(
    *,
    config: dict[str, Any],
    context: NodeCompileContext,
    structure: KnowledgeRetrievalStructureIntent,
) -> None:
    if context.installed_dataset_ids is None:
        raise NodeIntentCompileError(
            "CAPABILITY_UNAVAILABLE",
            "Knowledge catalogue is unavailable for typed node compilation",
            path="structure.dataset_ids",
            cause={"error_code": "CAPABILITY_UNAVAILABLE", "capability": "knowledge_catalogue"},
        )
    for index, dataset_id in enumerate(structure.dataset_ids):
        if dataset_id not in context.installed_dataset_ids:
            raise NodeIntentCompileError(
                "UNKNOWN_DATASET",
                f"Dataset {dataset_id!r} is not in this run's knowledge snapshot",
                path=f"structure.dataset_ids[{index}]",
                cause={
                    "error_code": "UNKNOWN_DATASET",
                    "dataset_id": dataset_id,
                    "available_dataset_ids": sorted(context.installed_dataset_ids),
                },
            )
    if structure.query is not None:
        _require_source_type(context, structure.query, expected="string", path="structure.query")
    if structure.attachment is not None:
        actual = _resolve_source_type(context, structure.attachment, path="structure.attachment", required=True)
        if actual not in {"file", "array[file]"}:
            raise NodeIntentCompileError(
                "VARIABLE_TYPE_MISMATCH",
                f"Knowledge attachment must be file or array[file], got {actual!r}",
                path="structure.attachment",
                cause={
                    "error_code": "VARIABLE_TYPE_MISMATCH",
                    "selector": list(structure.attachment),
                    "expected": ["file", "array[file]"],
                    "actual": actual,
                },
            )
    config.update(
        {
            "query_variable_selector": list(structure.query) if structure.query is not None else [],
            "query_attachment_selector": list(structure.attachment) if structure.attachment is not None else [],
            "dataset_ids": list(structure.dataset_ids),
            "retrieval_mode": "multiple",
            "multiple_retrieval_config": {
                "top_k": structure.top_k,
                "score_threshold": structure.score_threshold,
                "reranking_mode": "reranking_model",
                "reranking_enable": False,
                "reranking_model": None,
                "weights": None,
            },
            "single_retrieval_config": None,
            "metadata_filtering_mode": "disabled",
            "metadata_model_config": None,
            "metadata_filtering_conditions": None,
            "vision": {"enabled": False},
        }
    )


def _resolve_template_references(context: NodeCompileContext, text: str, *, path: str) -> None:
    for selector in collect_exact_references({"text": text}):
        _resolve_source_type(context, selector, path=path, required=False)


def _compile_http_request(
    *,
    config: dict[str, Any],
    context: NodeCompileContext,
    structure: HttpRequestStructureIntent,
) -> None:
    _resolve_template_references(context, structure.url, path="structure.url")
    for collection_name, items in (("headers", structure.headers), ("params", structure.params)):
        for index, item in enumerate(items):
            _resolve_template_references(
                context,
                item.value,
                path=f"structure.{collection_name}[{index}].value",
            )
    if isinstance(structure.authorization, HttpCredentialAuthIntent):
        reference_id = structure.authorization.reference_id
        references = context.http_credential_reference_ids
        if references is None:
            raise NodeIntentCompileError(
                "CAPABILITY_UNAVAILABLE",
                "HTTP credential references are unavailable for this run",
                path="structure.authorization.reference_id",
                cause={"error_code": "CAPABILITY_UNAVAILABLE", "capability": "http_credentials"},
            )
        if reference_id not in references:
            raise NodeIntentCompileError(
                "UNKNOWN_CREDENTIAL",
                f"HTTP credential reference {reference_id!r} is not in this run's snapshot",
                path="structure.authorization.reference_id",
                cause={
                    "error_code": "UNKNOWN_CREDENTIAL",
                    "reference_id": reference_id,
                    "available_reference_ids": sorted(references),
                },
            )
        raise NodeIntentCompileError(
            "CAPABILITY_UNAVAILABLE",
            "HTTP credential reference hydration is not installed; plaintext credentials are forbidden",
            path="structure.authorization.reference_id",
            cause={"error_code": "CAPABILITY_UNAVAILABLE", "capability": "http_credential_hydration"},
        )

    body: dict[str, Any]
    if isinstance(structure.body, HttpTextBodyIntent):
        _resolve_template_references(context, structure.body.content, path="structure.body.content")
        body = {
            "type": structure.body.kind,
            "data": [{"key": "", "type": "text", "value": structure.body.content, "file": []}],
        }
    elif isinstance(structure.body, HttpFormBodyIntent):
        fields: list[dict[str, Any]] = []
        for index, item in enumerate(structure.body.fields):
            if isinstance(item, HttpFileFieldIntent):
                _require_file_source(context, item.source, path=f"structure.body.fields[{index}].source")
                fields.append({"key": item.name, "type": "file", "value": "", "file": list(item.source)})
            else:
                _resolve_template_references(
                    context,
                    item.value,
                    path=f"structure.body.fields[{index}].value",
                )
                fields.append({"key": item.name, "type": "text", "value": item.value, "file": []})
        body = {"type": structure.body.kind, "data": fields}
    elif isinstance(structure.body, HttpBinaryBodyIntent):
        _require_file_source(context, structure.body.source, path="structure.body.source")
        body = {
            "type": "binary",
            "data": [{"key": "", "type": "file", "value": "", "file": list(structure.body.source)}],
        }
    else:
        body = {"type": "none", "data": []}

    config.update(
        {
            "method": structure.method,
            "url": structure.url,
            "authorization": {"type": "no-auth", "config": None},
            "headers": "\n".join(f"{item.name}:{item.value}" for item in structure.headers),
            "params": "\n".join(f"{item.name}:{item.value}" for item in structure.params),
            "body": body,
            "timeout": {"connect": 0, "read": 0, "write": 0},
            "ssl_verify": structure.ssl_verify,
        }
    )


def _require_file_source(context: NodeCompileContext, selector: tuple[str, ...], *, path: str) -> None:
    actual = _resolve_source_type(context, selector, path=path, required=True)
    if actual not in {"file", "array[file]"}:
        raise NodeIntentCompileError(
            "VARIABLE_TYPE_MISMATCH",
            f"HTTP file source must be file or array[file], got {actual!r}",
            path=path,
            cause={
                "error_code": "VARIABLE_TYPE_MISMATCH",
                "selector": list(selector),
                "expected": ["file", "array[file]"],
                "actual": actual,
            },
        )


def _compile_human_input(
    *,
    config: dict[str, Any],
    context: NodeCompileContext,
    structure: HumanInputStructureIntent,
) -> None:
    capabilities = context.human_input_delivery_capabilities
    if capabilities is None:
        raise NodeIntentCompileError(
            "CAPABILITY_UNAVAILABLE",
            "Human Input delivery capabilities are unavailable for this run",
            path="structure.delivery",
            cause={"error_code": "CAPABILITY_UNAVAILABLE", "capability": "human_input_delivery"},
        )
    _resolve_template_references(context, structure.form_content, path="structure.form_content")
    delivery_methods: list[dict[str, Any]] = []
    for index, delivery in enumerate(structure.delivery):
        if delivery.kind not in capabilities:
            raise NodeIntentCompileError(
                "CAPABILITY_UNAVAILABLE",
                f"Human Input delivery method {delivery.kind!r} is unavailable",
                path=f"structure.delivery[{index}].kind",
                cause={
                    "error_code": "CAPABILITY_UNAVAILABLE",
                    "capability": f"human_input_delivery:{delivery.kind}",
                    "available_delivery_methods": sorted(capabilities),
                },
            )
        method_id = str(uuid5(NAMESPACE_URL, f"workflow-assist:{context.node_id}:delivery:{index}:{delivery.kind}"))
        if isinstance(delivery, HumanEmailDeliveryIntent):
            member_ids = context.human_input_member_reference_ids
            if member_ids is None:
                raise NodeIntentCompileError(
                    "CAPABILITY_UNAVAILABLE",
                    "Workspace member references are unavailable for this run",
                    path=f"structure.delivery[{index}].member_reference_ids",
                    cause={"error_code": "CAPABILITY_UNAVAILABLE", "capability": "workspace_members"},
                )
            for member_index, reference_id in enumerate(delivery.member_reference_ids):
                if reference_id not in member_ids:
                    raise NodeIntentCompileError(
                        "UNKNOWN_MEMBER",
                        f"Workspace member reference {reference_id!r} is not in this run's snapshot",
                        path=f"structure.delivery[{index}].member_reference_ids[{member_index}]",
                        cause={
                            "error_code": "UNKNOWN_MEMBER",
                            "reference_id": reference_id,
                            "available_reference_ids": sorted(member_ids),
                        },
                    )
            _resolve_template_references(
                context,
                delivery.body,
                path=f"structure.delivery[{index}].body",
            )
            delivery_methods.append(
                {
                    "id": method_id,
                    "type": "email",
                    "enabled": True,
                    "config": {
                        "recipients": {
                            "include_bound_group": False,
                            "items": [
                                {"type": "member", "reference_id": reference_id}
                                for reference_id in delivery.member_reference_ids
                            ],
                        },
                        "subject": delivery.subject,
                        "body": delivery.body,
                        "debug_mode": False,
                    },
                }
            )
        else:
            delivery_methods.append({"id": method_id, "type": "webapp", "enabled": True, "config": {}})

    inputs = [_compile_human_input_field(context, item, index=index) for index, item in enumerate(structure.inputs)]
    config.update(
        {
            "form_content": structure.form_content,
            "inputs": inputs,
            "delivery_methods": delivery_methods,
            "user_actions": [item.model_dump(mode="python") for item in structure.actions],
        }
    )
    if structure.timeout is not None:
        config["timeout"] = structure.timeout
    elif context.mode != "update" or "timeout" not in config:
        config["timeout"] = 3
    if structure.timeout_unit is not None:
        config["timeout_unit"] = structure.timeout_unit
    elif context.mode != "update" or "timeout_unit" not in config:
        config["timeout_unit"] = "day"
    config.pop("_targetBranches", None)


def _compile_human_input_field(context: NodeCompileContext, item: Any, *, index: int) -> dict[str, Any]:
    if isinstance(item, HumanParagraphInputIntent):
        result: dict[str, Any] = {"type": "paragraph", "output_variable_name": item.output_variable_name}
        if isinstance(item.default, HumanConstantStringIntent):
            result["default"] = {"type": "constant", "selector": [], "value": item.default.value}
        elif isinstance(item.default, HumanVariableStringIntent):
            _require_source_type(
                context,
                item.default.source,
                expected="string",
                path=f"structure.inputs[{index}].default.source",
            )
            result["default"] = {"type": "variable", "selector": list(item.default.source), "value": ""}
        return result
    if isinstance(item, HumanSelectInputIntent):
        options = item.options
        if isinstance(options, HumanConstantOptionsIntent):
            option_source = {"type": "constant", "selector": [], "value": list(options.values)}
        elif isinstance(options, HumanVariableOptionsIntent):
            _require_source_type(
                context,
                options.source,
                expected="array[string]",
                path=f"structure.inputs[{index}].options.source",
            )
            option_source = {"type": "variable", "selector": list(options.source), "value": []}
        else:  # pragma: no cover - discriminated union is exhaustive
            raise AssertionError("unexpected Human Input options source")
        return {
            "type": "select",
            "output_variable_name": item.output_variable_name,
            "option_source": option_source,
        }
    if isinstance(item, HumanFileInputIntent):
        result = {
            "type": item.type,
            "output_variable_name": item.output_variable_name,
            "allowed_file_types": list(item.allowed_file_types),
            "allowed_file_upload_methods": list(item.allowed_file_upload_methods),
            "allowed_file_extensions": list(item.allowed_file_extensions),
        }
        if item.type == "file-list":
            result["number_limits"] = item.number_limits or 5
        return result
    raise AssertionError("unexpected Human Input field")


def _require_source_type(
    context: NodeCompileContext,
    selector: tuple[str, ...],
    *,
    expected: str,
    path: str,
) -> None:
    actual = _resolve_source_type(context, selector, path=path, required=True)
    if actual != expected:
        raise NodeIntentCompileError(
            "VARIABLE_TYPE_MISMATCH",
            f"Input {'.'.join(selector)!r} must be {expected}, got {actual!r}",
            path=path,
            cause={
                "error_code": "VARIABLE_TYPE_MISMATCH",
                "selector": list(selector),
                "expected": expected,
                "actual": actual,
            },
        )


def _end_output_type(
    context: NodeCompileContext,
    *,
    selector: tuple[str, ...],
    declared_type: str | None,
    path: str,
) -> str:
    if not context.can_resolve_source_types:
        if declared_type is not None:
            return declared_type
        raise NodeIntentCompileError(
            "OUTPUT_TYPE_UNAVAILABLE",
            f"Cannot derive the type of {'.'.join(selector)!r} without a variable snapshot",
            path=path,
            cause={"error_code": "OUTPUT_TYPE_UNAVAILABLE", "selector": list(selector)},
        )
    actual_type = _resolve_source_type(context, selector, path=path, required=True)
    assert actual_type is not None
    if declared_type is not None and actual_type != declared_type:
        raise NodeIntentCompileError(
            "VARIABLE_TYPE_MISMATCH",
            f"End output source {'.'.join(selector)!r} is {actual_type}, not {declared_type}",
            path=path,
            cause={
                "error_code": "VARIABLE_TYPE_MISMATCH",
                "selector": list(selector),
                "expected": declared_type,
                "actual": actual_type,
            },
        )
    return actual_type


def _resolve_bindings(context: NodeCompileContext, bindings: list[Any], *, path: str) -> None:
    if not context.can_resolve_source_types:
        return
    for index, binding in enumerate(bindings):
        _resolve_source_type(context, binding.source, path=f"{path}[{index}].source", required=False)


def _resolve_source_type(
    context: NodeCompileContext,
    selector: tuple[str, ...],
    *,
    path: str,
    required: bool,
) -> str | None:
    try:
        actual_type = context.resolve_source_type(selector)
    except VariableResolutionError as exc:
        cause: dict[str, object] = {
            "error_code": exc.code,
            "error": exc.detail,
            "selector": list(exc.selector),
        }
        if context.variable_registry is not None and exc.code == "UNKNOWN_OUTPUT" and exc.selector:
            cause["available_outputs"] = list(context.variable_registry.outputs_for(exc.selector[0]))
        raise NodeIntentCompileError(exc.code, exc.detail, path=path, cause=cause) from exc
    if actual_type is None and required:
        raise NodeIntentCompileError(
            "OUTPUT_TYPE_UNAVAILABLE",
            f"Cannot derive the type of {'.'.join(selector)!r}",
            path=path,
            cause={"error_code": "OUTPUT_TYPE_UNAVAILABLE", "selector": list(selector)},
        )
    return actual_type


def _compile_output_children(children: dict[str, Any] | None) -> dict[str, Any] | None:
    if not children:
        return None
    return {
        name: {"type": child.type, "children": _compile_output_children(child.children)}
        for name, child in children.items()
    }


def _start_variable(intent: StartVariableIntent) -> dict[str, Any]:
    variable: dict[str, Any] = {
        "variable": intent.name,
        "label": intent.label,
        "type": intent.type,
        "required": intent.required,
    }
    if intent.type in {"text-input", "paragraph"}:
        variable["max_length"] = intent.max_length or (256 if intent.type == "text-input" else 4096)
        variable["options"] = []
    elif intent.type == "select":
        variable["options"] = list(intent.options)
    elif intent.type in {"file", "file-list"}:
        variable["allowed_file_types"] = list(intent.allowed_file_types)
        variable["allowed_file_upload_methods"] = list(intent.allowed_file_upload_methods)
        variable["allowed_file_extensions"] = list(intent.allowed_file_extensions)
    elif intent.type == "checkbox":
        variable["default"] = bool(intent.default) if intent.default is not None else False
    elif intent.type == "json_object":
        variable["json_schema"] = deepcopy(intent.json_schema)
    if intent.default is not None and intent.type != "checkbox":
        variable["default"] = deepcopy(intent.default)
    return variable


__all__ = ["NodeIntentCompileError", "compile_node_intent"]
