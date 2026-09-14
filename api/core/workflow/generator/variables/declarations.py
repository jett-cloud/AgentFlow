"""Derive available node outputs and selector types from node configuration."""

import logging
from typing import Any

from graphon.enums import BuiltinNodeTypes

logger = logging.getLogger(__name__)

from core.workflow.generator.variables.syntax import (
    _ARRAY_OUTPUT_TYPES,
    _CONTAINER_SCOPE_VARS,
    _FILE_OUTPUT_TYPES,
    _FILE_SUB_FIELDS,
    _HITL_BUILTIN_OUTPUTS,
    _OBJECT_OUTPUT_TYPES,
    _PE_BUILTIN_OUTPUTS,
    _is_selector_list,
)


def selector_type(nodes: list[dict[str, Any]], selector: object) -> str | None:
    if not _is_selector_list(selector):
        return None
    nodes_by_id = {node["id"]: node for node in nodes if isinstance(node.get("id"), str)}
    source = nodes_by_id.get(selector[0])
    if source is None:
        return None
    schema = _schema_for_variable(source, ".".join(selector[1:]), nodes_by_id)
    value = schema.get("type")
    return str(value) if value else None


def _declared_outputs(node: dict[str, Any]) -> list[str]:
    """Names this node exposes for ``{{#id.name#}}`` / selector references.

    Tool nodes also accept *any* name at validation time (dynamic plugin
    outputs); that exception lives in ``_declares_variable``, not here.
    Compact ``read_graph`` uses this list so the model sees the same names
    the validator grades against.
    """
    data = node.get("data") or {}
    node_type = data.get("type")
    if node_type == BuiltinNodeTypes.START:
        return [
            variable["variable"]
            for variable in (data.get("variables") or [])
            if isinstance(variable, dict) and isinstance(variable.get("variable"), str)
        ]
    if node_type == BuiltinNodeTypes.LLM:
        outputs = ["text", "reasoning_content", "usage"]
        if data.get("structured_output_enabled"):
            outputs.append("structured_output")
        return outputs
    if node_type == BuiltinNodeTypes.CODE:
        outputs = data.get("outputs")
        return [key for key in outputs if isinstance(key, str)] if isinstance(outputs, dict) else []
    if node_type == BuiltinNodeTypes.KNOWLEDGE_RETRIEVAL:
        return ["result"]
    if node_type == BuiltinNodeTypes.PARAMETER_EXTRACTOR:
        names = [
            parameter["name"]
            for parameter in (data.get("parameters") or [])
            if isinstance(parameter, dict) and isinstance(parameter.get("name"), str)
        ]
        names.extend(_PE_BUILTIN_OUTPUTS)
        return names
    if node_type == BuiltinNodeTypes.HTTP_REQUEST:
        return ["body", "status_code", "headers", "files"]
    if node_type == BuiltinNodeTypes.TEMPLATE_TRANSFORM:
        return ["output"]
    if node_type == BuiltinNodeTypes.TOOL:
        outputs = data.get("outputs")
        if isinstance(outputs, dict):
            return [key for key in outputs if isinstance(key, str)]
        return []
    if node_type == BuiltinNodeTypes.ITERATION:
        return ["output"]
    if node_type == BuiltinNodeTypes.LOOP:
        labels: list[str] = []
        seen: set[str] = set()
        for item in data.get("loop_variables") or []:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            if isinstance(label, str) and label and label not in seen:
                seen.add(label)
                labels.append(label)
        return labels
    if node_type == BuiltinNodeTypes.QUESTION_CLASSIFIER:
        return ["class_id", "class_name"]
    if node_type == BuiltinNodeTypes.DOCUMENT_EXTRACTOR:
        return ["text"]
    if node_type in (BuiltinNodeTypes.VARIABLE_AGGREGATOR, BuiltinNodeTypes.LEGACY_VARIABLE_AGGREGATOR):
        settings = data.get("advanced_settings") or {}
        if isinstance(settings, dict) and settings.get("group_enabled"):
            groups = settings.get("groups") or []
            names = [
                group["group_name"]
                for group in groups
                if isinstance(group, dict) and isinstance(group.get("group_name"), str) and group["group_name"]
            ]
            if names:
                return names
        return ["output"]
    if node_type == BuiltinNodeTypes.LIST_OPERATOR:
        return ["result", "first_record", "last_record"]
    if node_type == BuiltinNodeTypes.HUMAN_INPUT:
        names = [
            item["output_variable_name"]
            for item in (data.get("inputs") or [])
            if isinstance(item, dict) and isinstance(item.get("output_variable_name"), str)
        ]
        names.extend(_HITL_BUILTIN_OUTPUTS)
        return names
    if node_type == BuiltinNodeTypes.AGENT:
        declared = data.get("agent_declared_outputs")
        if isinstance(declared, list):
            names = [
                item["name"]
                for item in declared
                if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"]
            ]
            if names:
                return names
        return ["text", "files", "json"]
    return []


def _declares_variable(
    node: dict[str, Any],
    var: str,
    *,
    ancestor_ids: set[str] | None = None,
    nodes_by_id: dict[str, dict[str, Any]] | None = None,
    tool_output_names: dict[tuple[str, str], frozenset[str]] | None = None,
) -> bool:
    """
    Does ``node`` expose ``var``? Nested paths follow VariablePool: dict
    fields only. Array values cannot be drilled into. Iteration ``item`` /
    ``index`` are legal only for descendants. Loop has no synthetic item.
    """
    data = node.get("data") or {}
    node_type = data.get("type")
    if node_type == BuiltinNodeTypes.TOOL:
        if tool_output_names is None:
            return True
        provider = str(data.get("provider_id") or data.get("provider_name") or "").strip()
        tool_name = str(data.get("tool_name") or "").strip()
        names = tool_output_names.get((provider, tool_name))
        if names is None:
            return True
        parts = [part for part in var.split(".") if part]
        return bool(parts) and parts[0] in names
    parts = [part for part in var.split(".") if part]
    if not parts:
        return False
    base, rest = parts[0], parts[1:]
    node_id = node.get("id")
    is_descendant = isinstance(node_id, str) and ancestor_ids is not None and node_id in ancestor_ids
    if node_type == BuiltinNodeTypes.ITERATION and base in _CONTAINER_SCOPE_VARS:
        if not is_descendant:
            return False
        if base == "index":
            return not rest
        return _item_path_allowed(node, rest, nodes_by_id)
    if base not in _declared_outputs(node):
        return False
    if not rest:
        return True
    return _output_path_allowed(node, base, rest, nodes_by_id)


def _item_path_allowed(
    iteration_node: dict[str, Any],
    rest: list[str],
    nodes_by_id: dict[str, dict[str, Any]] | None,
) -> bool:
    if not rest:
        return True
    selector = (iteration_node.get("data") or {}).get("iterator_selector")
    if not _is_selector_list(selector):
        return True
    source = (nodes_by_id or {}).get(selector[0])
    if source is None:
        return True
    schema = _schema_for_variable(source, ".".join(selector[1:]), nodes_by_id)
    raw_type = str(schema.get("type") or "")
    if raw_type not in _ARRAY_OUTPUT_TYPES:
        return True
    return _schema_allows_path(_element_schema(schema), rest)


def _output_path_allowed(
    node: dict[str, Any],
    base: str,
    rest: list[str],
    nodes_by_id: dict[str, dict[str, Any]] | None,
) -> bool:
    return _schema_allows_path(_schema_for_variable(node, base, nodes_by_id), rest)


def _schema_for_variable(
    node: dict[str, Any],
    var: str,
    nodes_by_id: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    parts = [part for part in var.split(".") if part]
    if not parts:
        return {"type": "object"}
    base, rest = parts[0], parts[1:]
    schema = _declared_output_schema(node, base)
    if rest:
        if not _schema_allows_path(schema, rest):
            return {"type": "string"}
        schema = _schema_at_path(schema, rest)
    return schema


def _declared_output_schema(node: dict[str, Any], base: str) -> dict[str, Any]:
    data = node.get("data") or {}
    node_type = data.get("type")
    if node_type == BuiltinNodeTypes.LLM and base == "structured_output":
        properties = ((data.get("structured_output") or {}).get("schema") or {}).get("properties") or {}
        return {"type": "object", "properties": properties if isinstance(properties, dict) else {}}
    if node_type == BuiltinNodeTypes.LLM and base == "usage":
        return {"type": "object"}
    if node_type == BuiltinNodeTypes.LLM:
        return {"type": "string"}
    if node_type == BuiltinNodeTypes.CODE:
        output = (data.get("outputs") or {}).get(base)
        return output if isinstance(output, dict) else {"type": "object"}
    if node_type == BuiltinNodeTypes.START:
        for item in data.get("variables") or []:
            if isinstance(item, dict) and item.get("variable") == base:
                raw_type = item.get("type") or item.get("value_type") or "string"
                schema: dict[str, Any] = {"type": str(raw_type)}
                if item.get("json_schema"):
                    raw_schema = item["json_schema"]
                    parsed = raw_schema if isinstance(raw_schema, dict) else None
                    if parsed:
                        schema["properties"] = parsed.get("properties") or {}
                return schema
        return {"type": "string"}
    if node_type == BuiltinNodeTypes.KNOWLEDGE_RETRIEVAL:
        return {"type": "array[object]"}
    if node_type == BuiltinNodeTypes.ITERATION:
        return {"type": "array"}
    if node_type == BuiltinNodeTypes.LOOP:
        for item in data.get("loop_variables") or []:
            if isinstance(item, dict) and item.get("label") == base:
                return {"type": str(item.get("var_type") or "string")}
        return {"type": "string"}
    if node_type == BuiltinNodeTypes.HTTP_REQUEST and base == "files":
        return {"type": "arrayFile"}
    if node_type == BuiltinNodeTypes.HTTP_REQUEST and base == "headers":
        return {"type": "object"}
    if node_type == BuiltinNodeTypes.AGENT:
        for item in data.get("agent_declared_outputs") or []:
            if isinstance(item, dict) and item.get("name") == base:
                raw_type = str(item.get("type") or "string")
                schema = {"type": raw_type}
                if isinstance(item.get("array_item"), dict):
                    schema["items"] = item["array_item"]
                return schema
    return {"type": "object"}


def _element_schema(schema: dict[str, Any]) -> dict[str, Any]:
    raw_type = str(schema.get("type") or "")
    if raw_type in {"array[object]", "arrayObject"}:
        items = schema.get("items") or schema.get("children")
        if isinstance(items, dict) and items:
            return items if "type" in items or "properties" in items else {"type": "object", "properties": items}
        properties = schema.get("properties")
        if isinstance(properties, dict) and properties:
            return {"type": "object", "properties": properties}
        return {"type": "object"}
    if raw_type in {"array[string]", "arrayString"}:
        return {"type": "string"}
    if raw_type in {"array[number]", "arrayNumber"}:
        return {"type": "number"}
    if raw_type in {"array[boolean]", "arrayBoolean"}:
        return {"type": "boolean"}
    if raw_type in {"array[file]", "arrayFile"}:
        return {"type": "file"}
    if raw_type in {"array", "array[any]"}:
        return {"type": "object"}
    return schema


def _schema_at_path(schema: dict[str, Any], rest: list[str]) -> dict[str, Any]:
    current = schema
    for part in rest:
        properties = current.get("properties") or current.get("children")
        if isinstance(properties, dict) and part in properties:
            child = properties[part]
            current = child if isinstance(child, dict) else {"type": "object"}
            continue
        if str(current.get("type") or "") in _OBJECT_OUTPUT_TYPES or not current.get("type"):
            return {"type": "object"}
        return {"type": "string"}
    return current


def _schema_allows_path(schema: dict[str, Any], rest: list[str]) -> bool:
    if not rest:
        return True
    raw_type = str(schema.get("type") or "")
    if raw_type in _ARRAY_OUTPUT_TYPES:
        return False
    if raw_type in _FILE_OUTPUT_TYPES:
        return len(rest) == 1 and rest[0] in _FILE_SUB_FIELDS
    properties = schema.get("properties")
    if properties is None:
        properties = schema.get("children")
    if isinstance(properties, dict):
        head, tail = rest[0], rest[1:]
        if not properties or head not in properties:
            return False
        child = properties[head]
        child_schema = child if isinstance(child, dict) else {"type": "object"}
        if "type" not in child_schema and ("properties" in child_schema or "children" in child_schema):
            child_schema = {"type": "object", **child_schema}
        return _schema_allows_path(child_schema, tail)
    if raw_type in _OBJECT_OUTPUT_TYPES or raw_type in {"", "any"}:
        return True
    return False


def _sole_declared_variable(node: dict[str, Any]) -> str | None:
    """Return the only output exposed by ``node``, or ``None`` when ambiguous."""
    data = node.get("data") or {}
    if data.get("type") == BuiltinNodeTypes.TOOL:
        return None
    names = _declared_outputs(node)
    return names[0] if len(names) == 1 else None


def declares_variable(
    node: dict[str, Any],
    variable: str,
    *,
    ancestor_ids: set[str] | None = None,
    nodes_by_id: dict[str, dict[str, Any]] | None = None,
    tool_output_names: dict[tuple[str, str], frozenset[str]] | None = None,
) -> bool:
    return _declares_variable(
        node,
        variable,
        ancestor_ids=ancestor_ids,
        nodes_by_id=nodes_by_id,
        tool_output_names=tool_output_names,
    )


def declared_outputs(node: dict[str, Any]) -> list[str]:
    """Return the output names ``node`` exposes for references and compact graphs."""
    return _declared_outputs(node)


def declared_output_type(node: dict[str, Any], output_name: str) -> str | None:
    """Return the declared top-level output type when the runtime contract exposes it."""
    if output_name not in _declared_outputs(node):
        return None
    schema = _declared_output_schema(node, output_name)
    value_type = schema.get("type")
    return value_type if isinstance(value_type, str) and value_type else None
