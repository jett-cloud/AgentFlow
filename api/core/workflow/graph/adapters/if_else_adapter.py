"""Translate persisted Dify if-else conditions for the Graphon runtime.

Persisted workflow graphs retain Dify's public condition vocabulary. Graphon
uses different names for the two null operators, so this module adapts a copy
at the graph boundary without changing stored DSL.
"""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from graphon.enums import BuiltinNodeTypes

_GRAPHON_OPERATOR_BY_DIFY_OPERATOR = {
    "is null": "null",
    "is not null": "not null",
}


def _adapt_condition(condition: object) -> object:
    if not isinstance(condition, Mapping):
        return deepcopy(condition)

    normalized: dict[str, Any] = deepcopy(dict(condition))
    operator = normalized.get("comparison_operator")
    if isinstance(operator, str):
        normalized["comparison_operator"] = _GRAPHON_OPERATOR_BY_DIFY_OPERATOR.get(operator, operator)

    sub_variable_condition = normalized.get("sub_variable_condition")
    if isinstance(sub_variable_condition, Mapping):
        normalized_sub_condition: dict[str, Any] = deepcopy(dict(sub_variable_condition))
        conditions = normalized_sub_condition.get("conditions")
        if isinstance(conditions, list):
            normalized_sub_condition["conditions"] = [_adapt_condition(item) for item in conditions]
        normalized["sub_variable_condition"] = normalized_sub_condition
    return normalized


def adapt_if_else_node_data_for_graph(node_data: Mapping[str, object]) -> dict[str, Any]:
    """Return a Graphon-compatible copy of one persisted node data mapping."""

    normalized: dict[str, Any] = deepcopy(dict(node_data))
    if normalized.get("type") != BuiltinNodeTypes.IF_ELSE:
        return normalized

    cases = normalized.get("cases")
    if not isinstance(cases, list):
        return normalized

    normalized_cases: list[object] = []
    for case in cases:
        if not isinstance(case, Mapping):
            normalized_cases.append(deepcopy(case))
            continue
        normalized_case: dict[str, Any] = deepcopy(dict(case))
        conditions = normalized_case.get("conditions")
        if isinstance(conditions, list):
            normalized_case["conditions"] = [_adapt_condition(item) for item in conditions]
        normalized_cases.append(normalized_case)
    normalized["cases"] = normalized_cases
    return normalized


__all__ = ["adapt_if_else_node_data_for_graph"]
