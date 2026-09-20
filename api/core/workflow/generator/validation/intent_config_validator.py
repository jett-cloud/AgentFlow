"""Check that a compiled ordinary-node config fulfils its structured intent.

Runtime schema validation answers whether a node can execute. This module
answers the separate question whether the Builder preserved every required
input and declared output requested through ``build_node``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.workflow.generator.agent.tools.tool_context import PendingPlanNode
from core.workflow.generator.compiler.intents.node_intent import (
    CodeStructureIntent,
    EndStructureIntent,
    IfElseStructureIntent,
    NodeBuildIntent,
    TemplateStructureIntent,
)
from core.workflow.generator.graph.types import MinimalGraphDict
from core.workflow.generator.variables.declarations import declared_output_type, declared_outputs, declares_variable
from core.workflow.generator.variables.syntax import collect_exact_references
from core.workflow.generator.variables.variable_registry import canonical_registry_type
from core.workflow.generator.variables.variable_types import canonical_value_type


@dataclass(frozen=True)
class IntentConfigIssue:
    code: str
    detail: str
    node_id: str | None = None
    field_path: str | None = None
    expected: object | None = None
    actual: object | None = None
    available_variables: tuple[str, ...] = ()
    contract_revision: int = 1

    def cause(self) -> dict[str, object]:
        result: dict[str, object] = {
            "error_code": self.code,
            "error": self.detail,
            "contract_revision": self.contract_revision,
        }
        for key, value in (
            ("node_id", self.node_id),
            ("field_path", self.field_path),
            ("expected", self.expected),
            ("actual", self.actual),
        ):
            if value is not None:
                result[key] = value
        if self.available_variables:
            result["available_variables"] = list(self.available_variables)
        return result


def _required_bindings(intent: NodeBuildIntent) -> list[tuple[tuple[str, ...], str, str, str | None]]:
    bindings: list[tuple[tuple[str, ...], str, str, str | None]] = [
        (item.source, item.role, f"inputs[{index}].source", None) for index, item in enumerate(intent.inputs)
    ]
    structure = intent.structure
    if isinstance(structure, EndStructureIntent):
        bindings.extend(
            (item.source, item.name, f"structure.outputs[{index}].source", item.type)
            for index, item in enumerate(structure.outputs)
        )
    elif isinstance(structure, TemplateStructureIntent | CodeStructureIntent):
        bindings.extend(
            (item.source, item.name, f"structure.bindings[{index}].source", None)
            for index, item in enumerate(structure.bindings)
        )
    elif isinstance(structure, IfElseStructureIntent):
        bindings.extend(
            (
                condition.source,
                case.id,
                f"structure.cases[{case_index}].conditions[{condition_index}].source",
                condition.type,
            )
            for case_index, case in enumerate(structure.cases)
            for condition_index, condition in enumerate(case.conditions)
        )
    return bindings


def validate_intent_reference_nodes(
    *,
    intent: NodeBuildIntent,
    graph: MinimalGraphDict,
    pending_nodes: tuple[PendingPlanNode, ...],
) -> list[IntentConfigIssue]:
    """Reject input producers absent from both the candidate and current build batch."""
    nodes_by_id = {
        str(node["id"]): node
        for node in graph.get("nodes", [])
        if isinstance(node, dict) and isinstance(node.get("id"), str) and node["id"]
    }
    known_node_ids = set(nodes_by_id)
    pending_by_id = {node.id: node for node in pending_nodes}
    known_node_ids.update(node.id for node in pending_nodes)
    available_variables = sorted(
        f"{node['id']}.{output}"
        for node in graph.get("nodes", [])
        if isinstance(node, dict) and isinstance(node.get("id"), str)
        for output in declared_outputs(node)
    )
    available_variables.extend(f"{node.id}.{output}" for node in pending_nodes for output in node.provisional_outputs)
    for source, _role, field_path, expected_type in _required_bindings(intent):
        if source[0] not in known_node_ids:
            return [
                IntentConfigIssue(
                    code="UNKNOWN_NODE_REFERENCE",
                    detail=f"Input {'.'.join(source)!r} references an unknown node",
                    node_id=source[0],
                    field_path=field_path,
                    expected="existing or pending producer node",
                    actual=source[0],
                    available_variables=tuple(available_variables[:50]),
                )
            ]
        graph_node = nodes_by_id.get(source[0])
        pending_node = pending_by_id.get(source[0])
        output_exists = graph_node is not None and declares_variable(dict(graph_node), ".".join(source[1:]))
        if pending_node is not None:
            output_exists = output_exists or source[1] in pending_node.provisional_outputs
        if not output_exists:
            return [
                IntentConfigIssue(
                    code="UNKNOWN_OUTPUT",
                    detail=f"Input {'.'.join(source)!r} references an output the producer does not declare",
                    node_id=source[0],
                    field_path=field_path,
                    expected="declared producer output",
                    actual=".".join(source),
                    available_variables=tuple(available_variables[:50]),
                )
            ]
        if graph_node is not None and expected_type is not None:
            actual_type = declared_output_type(dict(graph_node), ".".join(source[1:]))
            if actual_type is not None and canonical_registry_type(actual_type) != canonical_registry_type(
                expected_type
            ):
                return [
                    IntentConfigIssue(
                        code="VARIABLE_TYPE_MISMATCH",
                        detail=(f"Input {'.'.join(source)!r} expects {expected_type!r}, got confirmed {actual_type!r}"),
                        node_id=source[0],
                        field_path=field_path,
                        expected=canonical_registry_type(expected_type),
                        actual=canonical_registry_type(actual_type),
                        available_variables=tuple(available_variables[:50]),
                    )
                ]
    return []


def validate_node_config_against_intent(
    *,
    node_id: str,
    node_type: str,
    title: str,
    intent: NodeBuildIntent,
    config: dict[str, Any],
) -> list[IntentConfigIssue]:
    """Return required intent fields omitted or changed by the node Builder."""
    issues: list[IntentConfigIssue] = []
    reference_config = config
    if node_type == "code":
        # Code is executable payload, not a runtime variable binding. A
        # placeholder in a comment or string literal must not satisfy intent.
        reference_config = {key: value for key, value in config.items() if key != "code"}
    actual_references = collect_exact_references(reference_config)
    for source, role, field_path, _expected_type in _required_bindings(intent):
        expected = tuple(source)
        if expected not in actual_references:
            issues.append(
                IntentConfigIssue(
                    code="INTENT_INPUT_MISSING",
                    detail=(f"Node {node_id!r} config omitted required input {'.'.join(source)!r} ({role})"),
                    node_id=node_id,
                    field_path=field_path,
                    expected=".".join(source),
                    actual=sorted(".".join(item) for item in actual_references),
                )
            )

    node = {"id": node_id, "data": {**config, "type": node_type, "title": title}}
    actual_outputs = set(declared_outputs(node))
    output_intents = () if node_type in {"end", "answer"} else intent.outputs
    for output_intent in output_intents:
        if output_intent.name not in actual_outputs:
            issues.append(
                IntentConfigIssue(
                    code="INTENT_OUTPUT_MISSING",
                    detail=f"Node {node_id!r} config omitted declared output {output_intent.name!r}",
                    node_id=node_id,
                    field_path=f"outputs.{output_intent.name}",
                    expected=output_intent.name,
                    actual=sorted(actual_outputs),
                )
            )
            continue
        if output_intent.type is None:
            continue
        actual_type = declared_output_type(node, output_intent.name)
        if actual_type is None:
            continue
        if canonical_value_type(actual_type) != canonical_value_type(output_intent.type):
            issues.append(
                IntentConfigIssue(
                    code="INTENT_OUTPUT_TYPE_MISMATCH",
                    detail=(
                        f"Node {node_id!r} output {output_intent.name!r} expects "
                        f"{output_intent.type!r}, got {actual_type!r}"
                    ),
                    node_id=node_id,
                    field_path=f"outputs.{output_intent.name}.type",
                    expected=output_intent.type,
                    actual=actual_type,
                )
            )
    return issues
