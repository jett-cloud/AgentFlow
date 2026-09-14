"""node validation values."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from typing import TypeGuard

from pydantic import ValidationError

from core.workflow.generator.types import WorkflowGenerateErrorCode, WorkflowGenerateErrorDict
from graphon.nodes.base.entities import OutputVariableType
from graphon.nodes.loop.loop_node import LoopNode
from graphon.variables.factory import TypeMismatchError
from graphon.variables.types import SegmentType

_CODE_OUTPUT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


_TEMPLATE_VARIABLE_NAME_MAX_LENGTH = 30


_HUMAN_INPUT_RESERVED_OUTPUTS = frozenset({"__action_id", "__action_value", "__rendered_content"})


_ALLOWED_CODE_OUTPUT_TYPES = frozenset(
    {
        "string",
        "number",
        "object",
        "boolean",
        "array[string]",
        "array[number]",
        "array[object]",
        "array[boolean]",
    }
)


_CODE_OUTPUT_TYPE_HINT = "use array[string], array[number], array[boolean], or array[object]"


_ALLOWED_END_VALUE_TYPES = frozenset(item.value for item in OutputVariableType)


def _err(detail: str, node_id: str, code: str) -> WorkflowGenerateErrorDict:
    out: WorkflowGenerateErrorDict = {"code": code, "detail": detail}
    if node_id:
        out["node_id"] = node_id
    return out


def _non_empty_string(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def _valid_selector(value: object) -> bool:
    return isinstance(value, list | tuple) and len(value) >= 2 and all(_non_empty_string(item) for item in value)


def _non_empty_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list) and bool(value)


def _completeness_error(node_id: str, field: str, requirement: str) -> WorkflowGenerateErrorDict:
    return _err(
        f"Node {node_id!r} field {field!r} {requirement}",
        node_id,
        WorkflowGenerateErrorCode.INVALID_NODE_CONFIG,
    )


type _CompletenessChecker = Callable[[str, Mapping[str, object]], list[WorkflowGenerateErrorDict]]


def _prompt_message_has_effective_text(message: object) -> bool:
    if not isinstance(message, Mapping):
        return False
    if message.get("edition_type") == "jinja2":
        return _non_empty_string(message.get("jinja2_text"))
    return _non_empty_string(message.get("text"))


def _model_completeness_errors(
    node_id: str,
    data: Mapping[str, object],
) -> list[WorkflowGenerateErrorDict]:
    errors: list[WorkflowGenerateErrorDict] = []
    model = data.get("model")
    if isinstance(model, Mapping):
        for field in ("provider", "name"):
            if not _non_empty_string(model.get(field)):
                errors.append(_completeness_error(node_id, f"model.{field}", "must be non-empty"))
    return errors


def _required_text_errors(
    node_id: str,
    data: Mapping[str, object],
    field: str,
) -> list[WorkflowGenerateErrorDict]:
    if _non_empty_string(data.get(field)):
        return []
    return [_completeness_error(node_id, field, "must be non-empty")]


_UNARY_CONDITION_OPERATORS = frozenset(
    {"empty", "not empty", "is null", "is not null", "null", "not null", "exists", "not exists"}
)


_LOOP_VALUE_TYPES = frozenset({"constant", "variable"})


_LOOP_CONDITION_TYPES = _ALLOWED_CODE_OUTPUT_TYPES | frozenset({"file", "array"})


_LOOP_OPERATORS_BY_TYPE: dict[str, frozenset[str]] = {
    "string": frozenset({"contains", "not contains", "start with", "end with", "is", "is not", "empty", "not empty"}),
    "number": frozenset({"=", "≠", ">", "<", "≥", "≤", "empty", "not empty"}),
    "boolean": frozenset({"is", "is not", "empty", "not empty"}),
    "object": frozenset({"empty", "not empty"}),
    "array": frozenset({"empty", "not empty"}),
    "array[object]": frozenset({"empty", "not empty"}),
    "array[string]": frozenset({"contains", "not contains", "empty", "not empty"}),
    "array[number]": frozenset({"contains", "not contains", "empty", "not empty"}),
    "file": frozenset({"exists", "not exists"}),
}


def _loop_constant_matches(var_type: object, value: object) -> bool:
    if not isinstance(var_type, str):
        return False
    try:
        segment_type = SegmentType(var_type)
    except ValueError:
        return False
    try:
        LoopNode._get_segment_for_constant(var_type=segment_type, original_value=value)
    except (TypeMismatchError, ValueError, TypeError, AssertionError):
        return False
    return True


def _selector_completeness_errors(
    node_id: str,
    data: Mapping[str, object],
    field: str,
) -> list[WorkflowGenerateErrorDict]:
    if _valid_selector(data.get(field)):
        return []
    return [_completeness_error(node_id, field, "is invalid")]


_ASSIGNER_NO_VALUE_OPERATIONS = frozenset({"clear", "remove-first", "remove-last"})


def _unit_weight(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    weight = float(value)
    if not math.isfinite(weight) or not 0 <= weight <= 1:
        return None
    return weight


def _bounded_int(value: object, *, minimum: int, maximum: int) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return minimum <= value <= maximum


def _optional_unit_score(value: object) -> bool:
    if value is None:
        return True
    return _unit_weight(value) is not None


def _pydantic_config_errors(
    *,
    node_id: str,
    prefix: str,
    exc: ValidationError,
) -> list[WorkflowGenerateErrorDict]:
    errors: list[WorkflowGenerateErrorDict] = []
    for item in exc.errors():
        loc = ".".join(str(part) for part in item.get("loc", ()))
        location = f"{prefix}.{loc}" if loc else prefix
        message = str(item.get("msg") or "invalid")
        errors.append(
            _err(
                f"Agent node {node_id!r} {location}: {message}",
                node_id,
                WorkflowGenerateErrorCode.INVALID_AGENT_NODE,
            )
        )
    return errors
