"""Shared condition-operator and constant-value rules.

Typed intent compilation and runtime completeness validation import this
module so If/Else, Loop, and List Operator cannot drift onto separate
operator whitelists.
"""

from __future__ import annotations

import math
from typing import Any

from core.workflow.generator.variables.variable_types import canonical_value_type

UNARY_CONDITION_OPERATORS = frozenset(
    {"empty", "not empty", "is null", "is not null", "null", "not null", "exists", "not exists"}
)

CONDITION_OPERATORS_BY_TYPE: dict[str, frozenset[str]] = {
    "string": frozenset(
        {"contains", "not contains", "start with", "end with", "is", "is not", "empty", "not empty"}
    ),
    "number": frozenset({"=", "≠", ">", "<", "≥", "≤", "empty", "not empty"}),
    "boolean": frozenset({"is", "is not", "empty", "not empty"}),
    "object": frozenset({"empty", "not empty"}),
    "array": frozenset({"empty", "not empty"}),
    "array[object]": frozenset({"empty", "not empty"}),
    "array[string]": frozenset({"contains", "not contains", "empty", "not empty"}),
    "array[number]": frozenset({"contains", "not contains", "empty", "not empty"}),
    "array[boolean]": frozenset({"contains", "not contains", "empty", "not empty"}),
    "file": frozenset({"exists", "not exists"}),
    "array[file]": frozenset({"empty", "not empty"}),
}

CONDITION_TYPES = frozenset(CONDITION_OPERATORS_BY_TYPE)


def validate_condition_value(*, value_type: str, operator: str, value: Any) -> Any:
    """Validate and normalize one condition constant.

    Numeric constants are persisted as finite numeric strings, matching the
    runtime condition contract. Boolean constants remain JSON booleans.
    Unary operators never accept a redundant value.
    """

    canonical_type = canonical_value_type(value_type)
    allowed = CONDITION_OPERATORS_BY_TYPE.get(canonical_type)
    if allowed is None:
        raise ValueError(f"conditions do not support value type {canonical_type!r}")
    if operator not in allowed:
        raise ValueError(f"operator {operator!r} is not valid for {canonical_type!r}")
    if operator in UNARY_CONDITION_OPERATORS:
        if value is not None:
            raise ValueError(f"unary operator {operator!r} must not include a value")
        return None
    if value is None:
        raise ValueError(f"operator {operator!r} requires a value")

    comparison_type = canonical_type
    if canonical_type.startswith("array["):
        comparison_type = canonical_type[6:-1]

    if comparison_type == "number":
        if isinstance(value, bool) or not isinstance(value, str | int | float):
            raise ValueError("numeric conditions require a finite numeric value")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("numeric conditions require a finite numeric value") from exc
        if not math.isfinite(numeric):
            raise ValueError("numeric conditions require a finite numeric value")
        return str(value)
    if comparison_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("boolean conditions require a JSON boolean value")
        return value
    if comparison_type == "string":
        if not isinstance(value, str):
            raise ValueError("string conditions require a string value")
        return value
    raise ValueError(f"operator {operator!r} cannot compare a constant for {canonical_type!r}")


__all__ = [
    "CONDITION_OPERATORS_BY_TYPE",
    "CONDITION_TYPES",
    "UNARY_CONDITION_OPERATORS",
    "validate_condition_value",
]
