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
        return config
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
            item.name: {"type": item.type, "children": None} for item in intent.outputs if item.type is not None
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
    return config


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
