"""Evaluate observed acceptance outputs without trusting model claims."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, TypedDict

from core.workflow.generator.acceptance.evidence import AcceptanceAssertionResult, GraphExecutionTrace
from core.workflow.generator.graph.types import MinimalGraphDict
from core.workflow.generator.variables.declarations import declared_output_type, declared_outputs


class BusinessAssertion(TypedDict):
    path: list[str]
    operator: Literal["equals", "contains", "not_empty"]
    expected: object


def evaluate_runtime_contract(
    graph: MinimalGraphDict,
    trace: GraphExecutionTrace,
    business_assertions: Sequence[BusinessAssertion] = (),
) -> list[AcceptanceAssertionResult]:
    """Check declared node/terminal outputs, then optional case business assertions."""
    results: list[AcceptanceAssertionResult] = []
    for raw_node in graph.get("nodes") or []:
        if not isinstance(raw_node, dict):
            continue
        node_id = str(raw_node.get("id") or "")
        if not node_id or node_id not in trace.executed_node_ids:
            continue
        data = raw_node.get("data")
        node_type = str(data.get("type") or "") if isinstance(data, Mapping) else ""
        if node_type in {"code", "agent"}:
            observed = trace.node_outputs.get(node_id, {})
            for name in declared_outputs(raw_node):
                expected_type = declared_output_type(raw_node, name)
                if node_type == "agent" and not data.get("agent_declared_outputs"):
                    expected_type = {"text": "string", "files": "array[file]", "json": "object"}.get(name)
                results.extend(_output_results(f"{node_id}.{name}", observed, name, expected_type))
        elif node_type in {"end", "answer"} and isinstance(data, Mapping):
            terminal_outputs = data.get("outputs") or []
            if node_type == "answer":
                terminal_outputs = [{"variable": "answer", "value_type": "string"}]
            for output in terminal_outputs:
                if not isinstance(output, Mapping):
                    continue
                name = output.get("variable")
                if isinstance(name, str) and name:
                    expected_type = output.get("value_type")
                    results.extend(
                        _output_results(
                            f"outputs.{name}",
                            trace.graph_outputs,
                            name,
                            str(expected_type) if isinstance(expected_type, str) else None,
                        )
                    )
    for assertion in business_assertions:
        path = assertion.get("path") or []
        actual, present = _resolve_path(trace.graph_outputs, path)
        operator = assertion.get("operator")
        expected = assertion.get("expected")
        passed = present and _business_matches(actual, operator, expected)
        results.append(
            {
                "kind": "business",
                "path": ".".join(path),
                "passed": passed,
                "expected": {"operator": operator, "value_type": _runtime_type(expected)},
                "actual": _value_summary(actual) if present else {"present": False},
            }
        )
    return results


def _output_results(
    path: str,
    observed: Mapping[str, object],
    name: str,
    expected_type: str | None,
) -> list[AcceptanceAssertionResult]:
    if name not in observed:
        return [{"kind": "output_present", "path": path, "passed": False, "expected": True, "actual": None}]
    if expected_type in (None, "", "any"):
        return []
    actual = observed[name]
    return [
        {
            "kind": "output_type",
            "path": path,
            "passed": _matches_type(actual, expected_type),
            "expected": expected_type,
            "actual": _runtime_type(actual),
        }
    ]


def _runtime_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def _value_summary(value: object) -> dict[str, object]:
    summary: dict[str, object] = {"present": True, "type": _runtime_type(value)}
    if isinstance(value, (str, list, tuple, set, Mapping)):
        summary["length"] = len(value)
    return summary


def _matches_type(value: object, expected_type: str) -> bool:
    normalized = expected_type.casefold().replace("arrayfile", "array[file]")
    if normalized in {"integer", "int"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if normalized == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if normalized in {"boolean", "bool"}:
        return isinstance(value, bool)
    if normalized in {"string", "text"}:
        return isinstance(value, str)
    if normalized in {"object", "json"}:
        return isinstance(value, Mapping)
    if normalized.startswith("array"):
        if not isinstance(value, list):
            return False
        inner = normalized.removeprefix("array[").removesuffix("]") if "[" in normalized else ""
        return not inner or inner == "any" or all(_matches_type(item, inner) for item in value)
    if normalized == "file":
        return isinstance(value, Mapping)
    return True


def _resolve_path(value: object, path: Sequence[str]) -> tuple[object, bool]:
    current = value
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return None, False
        current = current[part]
    return current, True


def _business_matches(actual: object, operator: object, expected: object) -> bool:
    if operator == "equals":
        return actual == expected
    if operator == "contains":
        if isinstance(actual, str) and isinstance(expected, str):
            return expected in actual
        if isinstance(actual, (list, tuple, set)):
            return expected in actual
        return False
    if operator == "not_empty":
        return actual is not None and actual not in ("", [], {})
    return False
