"""Deterministically overlay typed ordinary-node intent onto Builder output.

The Builder may still supply prose-oriented or optional fields. Runtime
bindings, model identity, declared outputs, and other mechanically checkable
fields in ``intent.structure`` always win.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.workflow.generator.compiler.intents.node_intent import (
    AnswerStructureIntent,
    CodeStructureIntent,
    EndStructureIntent,
    IfElseStructureIntent,
    LLMStructureIntent,
    NodeBuildIntent,
    StartStructureIntent,
    StartVariableIntent,
    TemplateStructureIntent,
)


def compile_structured_node_config(
    *,
    intent: NodeBuildIntent,
    builder_config: dict[str, Any],
) -> dict[str, Any]:
    """Return Builder config with every structured field compiled by code."""
    config = deepcopy(builder_config)
    structure = intent.structure
    if structure is None:
        return _restore_declared_input_selectors(config, intent)
    if isinstance(structure, StartStructureIntent):
        config["variables"] = [_start_variable(item) for item in structure.variables]
    elif isinstance(structure, EndStructureIntent):
        config["outputs"] = [
            {
                "variable": item.name,
                "value_selector": list(item.source),
                "value_type": item.type,
            }
            for item in structure.outputs
        ]
    elif isinstance(structure, AnswerStructureIntent):
        config["variables"] = []
        config["answer"] = structure.content
    elif isinstance(structure, TemplateStructureIntent):
        config["template"] = structure.template
        config["variables"] = [
            {"variable": item.name, "value_selector": list(item.source)} for item in structure.bindings
        ]
    elif isinstance(structure, LLMStructureIntent):
        config["model"] = structure.model.model_dump(mode="python")
        config["prompt_template"] = [item.model_dump(mode="python") for item in structure.prompt]
        config.setdefault("context", {"enabled": False, "variable_selector": []})
        config.setdefault("vision", {"enabled": False})
    elif isinstance(structure, CodeStructureIntent):
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
        config["cases"] = [
            {
                "case_id": case.id,
                "logical_operator": case.logical_operator,
                "conditions": [
                    {
                        "variable_selector": list(condition.source),
                        "comparison_operator": condition.operator,
                        "value": condition.value,
                        "varType": condition.type,
                    }
                    for condition in case.conditions
                ],
            }
            for case in structure.cases
        ]
    return _restore_declared_input_selectors(config, intent)


def _restore_declared_input_selectors(config: dict[str, Any], intent: NodeBuildIntent) -> dict[str, Any]:
    """Restore nested selector paths that the prose Builder flattened.

    Builder prompts render a selector as a Dify placeholder such as
    ``{{#iteration.item.question#}}``.  Some node builders infer the runtime
    selector as ``["iteration", "item.question"]`` from that text, but Dify's
    variable pool expects ``["iteration", "item", "question"]``.  The main
    Agent already supplied the typed path in ``intent.inputs``; use that path
    as the source of truth for every matching selector in the generated config.
    """
    expanded_by_flattened = {
        (item.source[0], ".".join(item.source[1:])): list(item.source) for item in intent.inputs if len(item.source) > 2
    }
    if not expanded_by_flattened:
        return config

    def restore(value: Any) -> Any:
        if isinstance(value, list):
            if value and all(isinstance(part, str) for part in value):
                expanded = expanded_by_flattened.get(tuple(value))
                if expanded is not None:
                    return expanded
            return [restore(item) for item in value]
        if isinstance(value, dict):
            return {key: restore(item) for key, item in value.items()}
        return value

    restored = restore(config)
    return restored if isinstance(restored, dict) else config


def _compile_output_children(children: dict[str, Any] | None) -> dict[str, Any] | None:
    if not children:
        return None
    return {
        name: {
            "type": child.type,
            "children": _compile_output_children(child.children),
        }
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
