"""Check that a compiled ordinary-node config fulfils its typed structure.

Runtime schema validation answers whether a node can execute. This module
separately verifies that deterministic compilation preserved each typed
selector and declared output requested through ``build_node``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core.workflow.generator.agent.tools.tool_context import PendingPlanNode
from core.workflow.generator.compiler.intents.node_intent import (
    CodeStructureIntent,
    DocumentExtractorStructureIntent,
    EndStructureIntent,
    HttpBinaryBodyIntent,
    HttpFileFieldIntent,
    HttpFormBodyIntent,
    HttpRequestStructureIntent,
    HttpTextBodyIntent,
    HumanEmailDeliveryIntent,
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
    TemplateStructureIntent,
    VariableAggregatorStructureIntent,
)
from core.workflow.generator.graph.types import MinimalGraphDict
from core.workflow.generator.types import WorkflowGenerationMode
from core.workflow.generator.variables.declarations import declared_output_type, declared_outputs, declares_variable
from core.workflow.generator.variables.syntax import collect_exact_references, system_variable_names
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


ExpectedSourceType = str | tuple[str, ...] | None


def _required_bindings(intent: NodeBuildIntent) -> list[tuple[tuple[str, ...], str, str, ExpectedSourceType]]:
    bindings: list[tuple[tuple[str, ...], str, str, ExpectedSourceType]] = []
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
    elif isinstance(structure, DocumentExtractorStructureIntent):
        bindings.append((structure.source, "document", "structure.source", ("file", "array[file]")))
    elif isinstance(structure, LLMStructureIntent):
        for index, message in enumerate(structure.prompt):
            bindings.extend(
                (selector, "prompt", f"structure.prompt[{index}].text", None)
                for selector in collect_exact_references({"text": message.text})
            )
    elif isinstance(structure, IfElseStructureIntent):
        bindings.extend(
            (
                condition.source,
                case.id,
                f"structure.cases[{case_index}].conditions[{condition_index}].source",
                None,
            )
            for case_index, case in enumerate(structure.cases)
            for condition_index, condition in enumerate(case.conditions)
        )
    elif isinstance(structure, QuestionClassifierStructureIntent | ParameterExtractorStructureIntent):
        bindings.append((structure.query, "query", "structure.query", "string"))
    elif isinstance(structure, VariableAggregatorStructureIntent):
        bindings.extend(
            (source, "branch", f"structure.sources[{index}]", None) for index, source in enumerate(structure.sources)
        )
    elif isinstance(structure, ListOperatorStructureIntent):
        bindings.append((structure.source, "list", "structure.source", None))
    elif isinstance(structure, KnowledgeRetrievalStructureIntent):
        if structure.query is not None:
            bindings.append((structure.query, "query", "structure.query", "string"))
        if structure.attachment is not None:
            bindings.append((structure.attachment, "attachment", "structure.attachment", ("file", "array[file]")))
    elif isinstance(structure, HttpRequestStructureIntent):
        for selector in collect_exact_references(
            {
                "url": structure.url,
                "headers": [item.value for item in structure.headers],
                "params": [item.value for item in structure.params],
            }
        ):
            bindings.append((selector, "http-template", "structure", None))
        if isinstance(structure.body, HttpTextBodyIntent):
            for selector in collect_exact_references({"content": structure.body.content}):
                bindings.append((selector, "http-body", "structure.body.content", None))
        elif isinstance(structure.body, HttpBinaryBodyIntent):
            bindings.append((structure.body.source, "http-file", "structure.body.source", ("file", "array[file]")))
        elif isinstance(structure.body, HttpFormBodyIntent):
            for index, field in enumerate(structure.body.fields):
                if isinstance(field, HttpFileFieldIntent):
                    bindings.append(
                        (
                            field.source,
                            "http-file",
                            f"structure.body.fields[{index}].source",
                            ("file", "array[file]"),
                        )
                    )
                else:
                    for selector in collect_exact_references({"value": field.value}):
                        bindings.append((selector, "http-body", f"structure.body.fields[{index}].value", None))
    elif isinstance(structure, HumanInputStructureIntent):
        for selector in collect_exact_references({"form_content": structure.form_content}):
            bindings.append((selector, "form-content", "structure.form_content", None))
        for index, item in enumerate(structure.inputs):
            if isinstance(item, HumanParagraphInputIntent) and isinstance(item.default, HumanVariableStringIntent):
                bindings.append((item.default.source, "default", f"structure.inputs[{index}].default.source", "string"))
            elif isinstance(item, HumanSelectInputIntent) and isinstance(item.options, HumanVariableOptionsIntent):
                bindings.append(
                    (
                        item.options.source,
                        "options",
                        f"structure.inputs[{index}].options.source",
                        "array[string]",
                    )
                )
        for index, delivery in enumerate(structure.delivery):
            if isinstance(delivery, HumanEmailDeliveryIntent):
                for selector in collect_exact_references({"body": delivery.body}):
                    bindings.append((selector, "email-body", f"structure.delivery[{index}].body", None))
    return bindings


def validate_intent_reference_nodes(
    *,
    intent: NodeBuildIntent,
    graph: MinimalGraphDict,
    pending_nodes: tuple[PendingPlanNode, ...],
    mode: WorkflowGenerationMode | None = None,
    environment_variables: set[str] | None = None,
    conversation_variable_types: Mapping[str, str] | None = None,
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
    if conversation_variable_types is not None:
        available_variables.extend(f"conversation.{name}" for name in sorted(conversation_variable_types))
    if environment_variables is not None:
        available_variables.extend(f"env.{name}" for name in sorted(environment_variables))
    if mode is not None:
        available_variables.extend(f"sys.{name}" for name in sorted(system_variable_names(mode)))
    for source, _role, field_path, expected_type in _required_bindings(intent):
        system_type = _system_type(source, mode)
        if system_type is not None:
            issue = _source_type_issue(
                source=source,
                field_path=field_path,
                expected_type=expected_type,
                actual_type=system_type,
                available_variables=tuple(available_variables[:50]),
            )
            if issue is not None:
                return [issue]
            continue
        if source[0] == "env":
            if environment_variables is None:
                return [
                    IntentConfigIssue(
                        code="CAPABILITY_UNAVAILABLE",
                        detail="Environment variable snapshot is unavailable",
                        node_id="env",
                        field_path=field_path,
                        expected="available environment variable snapshot",
                        actual=None,
                        available_variables=tuple(available_variables[:50]),
                    )
                ]
            if len(source) != 2 or source[1] not in environment_variables:
                return [
                    IntentConfigIssue(
                        code="UNKNOWN_OUTPUT",
                        detail=f"Input {'.'.join(source)!r} references an unknown environment variable",
                        node_id="env",
                        field_path=field_path,
                        expected="declared environment variable",
                        actual=".".join(source),
                        available_variables=tuple(available_variables[:50]),
                    )
                ]
            issue = _source_type_issue(
                source=source,
                field_path=field_path,
                expected_type=expected_type,
                actual_type="string",
                available_variables=tuple(available_variables[:50]),
            )
            if issue is not None:
                return [issue]
            continue
        if source[0] == "conversation":
            if conversation_variable_types is None:
                return [
                    IntentConfigIssue(
                        code="CAPABILITY_UNAVAILABLE",
                        detail="Conversation variable type snapshot is unavailable",
                        node_id="conversation",
                        field_path=field_path,
                        expected="available conversation variable snapshot",
                        actual=None,
                        available_variables=tuple(available_variables[:50]),
                    )
                ]
            actual_type = conversation_variable_types.get(source[1]) if len(source) == 2 else None
            if actual_type is None:
                return [
                    IntentConfigIssue(
                        code="UNKNOWN_OUTPUT",
                        detail=f"Input {'.'.join(source)!r} references an unknown conversation variable",
                        node_id="conversation",
                        field_path=field_path,
                        expected="declared conversation variable",
                        actual=".".join(source),
                        available_variables=tuple(available_variables[:50]),
                    )
                ]
            issue = _source_type_issue(
                source=source,
                field_path=field_path,
                expected_type=expected_type,
                actual_type=actual_type,
                available_variables=tuple(available_variables[:50]),
            )
            if issue is not None:
                return [issue]
            continue
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
            if actual_type is not None:
                issue = _source_type_issue(
                    source=source,
                    field_path=field_path,
                    expected_type=expected_type,
                    actual_type=actual_type,
                    available_variables=tuple(available_variables[:50]),
                )
                if issue is not None:
                    return [issue]
    return []


def _system_type(
    source: tuple[str, ...],
    mode: WorkflowGenerationMode | None,
) -> str | None:
    if mode is None or len(source) != 2 or source[0] != "sys":
        return None
    if source[1] not in system_variable_names(mode):
        return None
    return {
        "files": "array[file]",
        "query": "string",
        "dialogue_count": "number",
        "timestamp": "number",
    }.get(source[1], "string")


def _source_type_issue(
    *,
    source: tuple[str, ...],
    field_path: str,
    expected_type: ExpectedSourceType,
    actual_type: str,
    available_variables: tuple[str, ...],
) -> IntentConfigIssue | None:
    if expected_type is None:
        return None
    expected_types = (expected_type,) if isinstance(expected_type, str) else expected_type
    canonical_expected = tuple(canonical_registry_type(item) for item in expected_types)
    canonical_actual = canonical_registry_type(actual_type)
    if canonical_actual in canonical_expected:
        return None
    return IntentConfigIssue(
        code="VARIABLE_TYPE_MISMATCH",
        detail=f"Input {'.'.join(source)!r} expects {expected_type!r}, got confirmed {actual_type!r}",
        node_id=source[0],
        field_path=field_path,
        expected=canonical_expected[0] if len(canonical_expected) == 1 else list(canonical_expected),
        actual=canonical_actual,
        available_variables=available_variables,
    )


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
