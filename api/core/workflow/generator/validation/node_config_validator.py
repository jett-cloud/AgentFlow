"""Validate runtime shape and generated completeness without modifying the candidate."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from core.workflow.generator.types import WorkflowGenerateErrorCode, WorkflowGenerateErrorDict
from core.workflow.generator.validation.agent_config import _agent_node_errors
from core.workflow.generator.validation.node_completeness import (
    _assigner_completeness_errors,
    _code_completeness_errors,
    _end_completeness_errors,
    _human_input_completeness_errors,
    _if_else_completeness_errors,
    _iteration_completeness_errors,
    _knowledge_retrieval_completeness_errors,
    _llm_completeness_errors,
    _loop_completeness_errors,
    _parameter_extractor_completeness_errors,
    _question_classifier_completeness_errors,
    _template_transform_completeness_errors,
    _variable_aggregator_completeness_errors,
)
from core.workflow.generator.validation.node_validation_values import (
    _CompletenessChecker,
    _err,
    _required_text_errors,
    _selector_completeness_errors,
)
from core.workflow.generator.validation.output_config import _code_output_errors, _end_output_errors
from core.workflow.graph.adapters.if_else_adapter import adapt_if_else_node_data_for_graph
from core.workflow.graph.adapters.node_config_schema import validate_workflow_node_data
from graphon.enums import BuiltinNodeTypes


def _node_for_runtime_validation(node: Mapping[str, object]) -> dict[str, Any]:
    """Build a runtime-facing validation copy without changing persisted DSL."""

    normalized = dict(node)
    data = node.get("data")
    if isinstance(data, Mapping):
        normalized["data"] = adapt_if_else_node_data_for_graph(data)
    return normalized


def collect_generated_node_completeness_errors(
    nodes: list[dict[str, object]],
) -> list[WorkflowGenerateErrorDict]:
    """Reject generator configs whose runtime-required semantic inputs are empty."""
    errors: list[WorkflowGenerateErrorDict] = []
    for node in nodes:
        data = node.get("data")
        if not isinstance(data, dict):
            continue
        runtime_valid = True
        try:
            validate_workflow_node_data(_node_for_runtime_validation(node))
        except (ValidationError, ValueError, TypeError):
            # Runtime-shape errors are owned by collect_node_config_errors.
            runtime_valid = False
        node_type = data.get("type")
        if not isinstance(node_type, str):
            continue
        if not runtime_valid and node_type != BuiltinNodeTypes.LOOP:
            continue
        checker = _COMPLETENESS_CHECKERS.get(node_type)
        if checker is None:
            continue
        errors.extend(checker(str(node.get("id") or ""), data))
    return errors


_COMPLETENESS_CHECKERS: dict[str, _CompletenessChecker] = {
    BuiltinNodeTypes.LLM: _llm_completeness_errors,
    BuiltinNodeTypes.ANSWER: lambda node_id, data: _required_text_errors(node_id, data, "answer"),
    BuiltinNodeTypes.TEMPLATE_TRANSFORM: _template_transform_completeness_errors,
    BuiltinNodeTypes.HTTP_REQUEST: lambda node_id, data: _required_text_errors(node_id, data, "url"),
    BuiltinNodeTypes.IF_ELSE: _if_else_completeness_errors,
    BuiltinNodeTypes.QUESTION_CLASSIFIER: _question_classifier_completeness_errors,
    BuiltinNodeTypes.PARAMETER_EXTRACTOR: _parameter_extractor_completeness_errors,
    BuiltinNodeTypes.DOCUMENT_EXTRACTOR: lambda node_id, data: _selector_completeness_errors(
        node_id, data, "variable_selector"
    ),
    BuiltinNodeTypes.VARIABLE_AGGREGATOR: _variable_aggregator_completeness_errors,
    BuiltinNodeTypes.LIST_OPERATOR: lambda node_id, data: _selector_completeness_errors(node_id, data, "variable"),
    BuiltinNodeTypes.VARIABLE_ASSIGNER: _assigner_completeness_errors,
    BuiltinNodeTypes.HUMAN_INPUT: _human_input_completeness_errors,
    BuiltinNodeTypes.ITERATION: _iteration_completeness_errors,
    BuiltinNodeTypes.LOOP: _loop_completeness_errors,
    BuiltinNodeTypes.CODE: _code_completeness_errors,
    BuiltinNodeTypes.END: _end_completeness_errors,
    BuiltinNodeTypes.KNOWLEDGE_RETRIEVAL: _knowledge_retrieval_completeness_errors,
}


def collect_node_config_errors(nodes: list[dict[str, Any]]) -> list[WorkflowGenerateErrorDict]:
    """Validate runtime schemas, preserving detailed Code/End/Agent errors."""
    errors: list[WorkflowGenerateErrorDict] = []
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("data"), dict):
            errors.append(_err("Node data must be an object", "", WorkflowGenerateErrorCode.INVALID_SCHEMA))
            continue
        data = node["data"]
        node_type = data.get("type")
        node_id = str(node.get("id") or "")
        before = len(errors)
        if node_type == BuiltinNodeTypes.CODE:
            errors.extend(_code_output_errors(node_id=node_id, data=data))
        elif node_type == BuiltinNodeTypes.END:
            errors.extend(_end_output_errors(node_id=node_id, data=data))
        elif node_type == BuiltinNodeTypes.AGENT:
            errors.extend(_agent_node_errors(node_id=node_id, data=data))
        if len(errors) == before:
            try:
                validate_workflow_node_data(_node_for_runtime_validation(node))
            except ValidationError as exc:
                for item in exc.errors(include_url=False, include_input=False):
                    path = ".".join(str(part) for part in item["loc"])
                    errors.append(_err(f"Node {node_id!r} {path}: {item['msg']}", node_id, "INVALID_NODE_CONFIG"))
            except (ValueError, TypeError) as exc:
                errors.append(_err(f"Node {node_id!r}: {exc}", node_id, "INVALID_NODE_CONFIG"))
    return errors
