"""output config."""

from __future__ import annotations

from typing import Any

from core.workflow.generator.types import WorkflowGenerateErrorCode, WorkflowGenerateErrorDict
from core.workflow.generator.validation.node_validation_values import (
    _ALLOWED_CODE_OUTPUT_TYPES,
    _ALLOWED_END_VALUE_TYPES,
    _CODE_OUTPUT_NAME_RE,
    _CODE_OUTPUT_TYPE_HINT,
    _err,
    _non_empty_string,
)
from graphon.enums import BuiltinNodeTypes
from graphon.nodes.base.entities import OutputVariableType


def fill_end_output_value_types(nodes: list[dict[str, Any]]) -> None:
    """Set missing end ``value_type`` from the source output, defaulting to ``any``."""
    by_id = {node_id: node for node in nodes if isinstance(node_id := node.get("id"), str) and node_id}
    for node in nodes:
        data = node.get("data")
        if not isinstance(data, dict) or data.get("type") != BuiltinNodeTypes.END:
            continue
        outputs = data.get("outputs")
        if not isinstance(outputs, list):
            continue
        for item in outputs:
            if not isinstance(item, dict):
                continue
            current = item.get("value_type")
            if isinstance(current, str) and current.strip():
                continue
            item["value_type"] = _infer_end_value_type(by_id, item.get("value_selector"))


def _code_output_errors(*, node_id: str, data: dict[str, Any]) -> list[WorkflowGenerateErrorDict]:
    outputs = data.get("outputs")
    if not isinstance(outputs, dict):
        return [
            _err(
                f"Code node {node_id!r} outputs must be an object",
                node_id,
                WorkflowGenerateErrorCode.INVALID_CODE_OUTPUT,
            )
        ]
    errors: list[WorkflowGenerateErrorDict] = []
    for name, spec in outputs.items():
        if not isinstance(name, str) or not _CODE_OUTPUT_NAME_RE.fullmatch(name):
            errors.append(
                _err(
                    f"Code node {node_id!r} output {name!r} has invalid name",
                    node_id,
                    WorkflowGenerateErrorCode.INVALID_CODE_OUTPUT,
                )
            )
            continue
        raw_type = spec.get("type") if isinstance(spec, dict) else spec
        if not isinstance(raw_type, str) or raw_type not in _ALLOWED_CODE_OUTPUT_TYPES:
            errors.append(
                _err(
                    f"Code node {node_id!r} output {name!r} has unsupported type {raw_type!r}; "
                    f"{_CODE_OUTPUT_TYPE_HINT}.",
                    node_id,
                    WorkflowGenerateErrorCode.INVALID_CODE_OUTPUT,
                )
            )
    return errors


def _end_output_errors(*, node_id: str, data: dict[str, Any]) -> list[WorkflowGenerateErrorDict]:
    outputs = data.get("outputs")
    if outputs is None:
        # Generator stubs omit outputs; postprocess fills ``[]``. Empty is legal
        # for graphon EndNodeData. Non-empty entries still need value_type.
        return []
    if not isinstance(outputs, list):
        return [
            _err(
                f"End node {node_id!r} has invalid outputs",
                node_id,
                WorkflowGenerateErrorCode.INVALID_END_OUTPUT,
            )
        ]
    errors: list[WorkflowGenerateErrorDict] = []
    seen_variables: set[str] = set()
    for item in outputs:
        if not isinstance(item, dict):
            errors.append(
                _err(
                    f"End node {node_id!r} has invalid outputs",
                    node_id,
                    WorkflowGenerateErrorCode.INVALID_END_OUTPUT,
                )
            )
            continue
        variable = item.get("variable")
        selector = item.get("value_selector")
        if not isinstance(variable, str) or not variable.strip():
            errors.append(
                _err(
                    f"End node {node_id!r} output is missing a variable name",
                    node_id,
                    WorkflowGenerateErrorCode.INVALID_END_OUTPUT,
                )
            )
        elif not _CODE_OUTPUT_NAME_RE.fullmatch(variable):
            errors.append(
                _err(
                    f"End node {node_id!r} output {variable!r} has invalid name",
                    node_id,
                    WorkflowGenerateErrorCode.INVALID_END_OUTPUT,
                )
            )
        elif variable in seen_variables:
            errors.append(
                _err(
                    f"End node {node_id!r} output {variable!r} is duplicate",
                    node_id,
                    WorkflowGenerateErrorCode.INVALID_END_OUTPUT,
                )
            )
        else:
            seen_variables.add(variable)
        if not isinstance(selector, list) or len(selector) < 2 or not all(_non_empty_string(x) for x in selector):
            errors.append(
                _err(
                    f"End node {node_id!r} output {variable!r} is missing value_selector",
                    node_id,
                    WorkflowGenerateErrorCode.INVALID_END_OUTPUT,
                )
            )
        value_type = item.get("value_type")
        if value_type is None or (isinstance(value_type, str) and not value_type.strip()):
            errors.append(
                _err(
                    f"End node {node_id!r} output {variable!r} is missing value_type",
                    node_id,
                    WorkflowGenerateErrorCode.INVALID_END_OUTPUT,
                )
            )
        elif not isinstance(value_type, str) or value_type not in _ALLOWED_END_VALUE_TYPES:
            errors.append(
                _err(
                    f"End node {node_id!r} output {variable!r} has invalid value_type {value_type!r}",
                    node_id,
                    WorkflowGenerateErrorCode.INVALID_END_OUTPUT,
                )
            )
    return errors


def _infer_end_value_type(by_id: dict[str, Any], selector: object) -> str:
    if not isinstance(selector, list) or len(selector) < 2 or not all(isinstance(x, str) for x in selector):
        return OutputVariableType.ANY.value
    target = by_id.get(selector[0])
    if not isinstance(target, dict):
        return OutputVariableType.ANY.value
    data = target.get("data") or {}
    base = selector[1]
    node_type = data.get("type")
    if node_type == BuiltinNodeTypes.CODE:
        outputs = data.get("outputs")
        spec = outputs.get(base) if isinstance(outputs, dict) else None
        if isinstance(spec, dict) and isinstance(spec.get("type"), str) and spec["type"] in _ALLOWED_CODE_OUTPUT_TYPES:
            return str(spec["type"])
    if node_type == BuiltinNodeTypes.LLM and base == "text":
        return OutputVariableType.STRING.value
    if node_type == BuiltinNodeTypes.KNOWLEDGE_RETRIEVAL and base == "result":
        return OutputVariableType.ARRAY_OBJECT.value
    return OutputVariableType.ANY.value
