"""Translate Tool intent into Dify parameter envelopes and normalize legacy nodes.

This module is the single semantic boundary for Tool intent, catalogue schemas,
and Dify's ``tool_parameters`` / ``tool_configurations`` representation. The
compiler handles new Workflow Assist mutations. The legacy normalizer remains
the deterministic backstop for builder-produced graphs.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, TypedDict

from core.workflow.generator.compiler.intents.node_intent import (
    ConstantToolArgument,
    TemplateToolArgument,
    ToolInvocationIntent,
    VariableToolArgument,
)
from core.workflow.generator.resources.tool_catalogue import ToolCatalogueEntry, ToolParameterSpec, tool_parameter_specs
from core.workflow.generator.types import WorkflowGenerateErrorDict
from core.workflow.generator.variables.declarations import declares_variable
from core.workflow.generator.variables.variable_references import VariableReferences
from core.workflow.generator.variables.variable_registry import VariableRegistry, VariableResolutionError
from graphon.enums import BuiltinNodeTypes

_FILE_PARAM_TYPES = frozenset({"file", "files", "system-files"})
_STRING_PARAM_TYPES = frozenset({"string", "secret-input", "text-input"})
_ITERATION_SCOPE_VARS = frozenset({"item", "index"})
_PLACEHOLDER_RE = VariableReferences._VAR_REF_RE
_VARIABLE_TYPES_BY_PARAMETER_TYPE: dict[str, str] = {
    "file": "file",
    "system-files": "file",
    "files": "array[file]",
    "boolean": "boolean",
    "bool": "boolean",
    "number": "number",
    "float": "number",
    "integer": "number",
    "int": "number",
    "array": "array",
    "list": "array",
    "object": "object",
    "dict": "object",
    "app-selector": "object",
    "model-selector": "object",
    "string": "string",
    "secret-input": "string",
    "text-input": "string",
    "paragraph": "string",
    "select": "string",
    "dynamic-select": "string",
}


class PendingSelectorSource(TypedDict):
    """Same-batch create facts the compiler may trust without a live node."""

    node_type: str
    outputs: frozenset[str]


class ToolNodeConfigError(ValueError):
    """A stable, user-safe failure raised by deterministic Tool compilation."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def compile_tool_node_config(
    *,
    invocation: ToolInvocationIntent,
    entry: ToolCatalogueEntry,
    nodes_by_id: dict[str, dict[str, object]] | None = None,
    pending_sources: dict[str, PendingSelectorSource] | None = None,
    referrer_ancestor_ids: set[str] | None = None,
    existing_config: dict[str, object] | None = None,
    variable_registry: VariableRegistry | None = None,
    referrer_id: str | None = None,
) -> dict[str, object]:
    """Compile typed Tool intent into canonical Dify node data without side effects.

    Prefer ``variable_registry`` plus ``referrer_id`` for selector checks. The
    ``nodes_by_id`` / ``pending_sources`` path remains as a compatibility adapter
    until public Tool builders migrate. Required file parameters use the same
    missing check as every other required parameter. Same-batch iteration
    ``item`` / ``index`` references are allowed only when the Tool node's parent
    chain includes that iteration.
    """
    binding = invocation.binding
    if (entry["provider_name"], entry["tool_name"]) != (binding.provider_name, binding.tool_name):
        raise ToolNodeConfigError("UNKNOWN_TOOL", "Tool binding is not present in the current catalogue")
    parameter_specs = entry.get("parameters")
    if parameter_specs is None:
        raise ToolNodeConfigError(
            "CAPABILITY_UNAVAILABLE",
            f"Parameter schema is unavailable for tool {binding.provider_name}/{binding.tool_name}",
        )

    same_binding = _has_binding(existing_config, binding.provider_name, binding.tool_name)
    config: dict[str, object] = deepcopy(existing_config) if same_binding and existing_config is not None else {}
    parameters = _copied_mapping(config.get("tool_parameters"))
    configurations = _copied_mapping(config.get("tool_configurations"))
    config.update(
        {
            "provider_id": entry["provider_name"],
            "provider_name": entry["provider_name"],
            "provider_type": entry["provider_type"],
            "tool_name": entry["tool_name"],
            "tool_label": entry["tool_label"],
            "tool_node_version": "2",
            "tool_parameters": parameters,
            "tool_configurations": configurations,
        }
    )

    specs_by_name = {spec["name"]: spec for spec in parameter_specs}
    unknown = sorted(set(invocation.arguments) - set(specs_by_name))
    if unknown:
        raise ToolNodeConfigError(
            "INVALID_NODE_CONFIG",
            f"Unknown tool argument {unknown[0]!r}",
        )

    for name, argument in invocation.arguments.items():
        spec = specs_by_name[name]
        value = _compile_tool_argument(
            name,
            argument,
            spec,
            nodes_by_id=nodes_by_id or {},
            pending_sources=pending_sources,
            referrer_ancestor_ids=referrer_ancestor_ids,
            variable_registry=variable_registry,
            referrer_id=referrer_id,
        )
        parameters[name] = value
        if spec["form"] != "llm":
            configurations[name] = deepcopy(value["value"])

    for spec in parameter_specs:
        name = spec["name"]
        if name not in parameters or _is_empty_envelope(parameters[name]):
            default = _default_envelope(spec)
            if default is not None:
                parameters[name] = default
        if spec["form"] != "llm" and name not in configurations and "default" in spec:
            configurations[name] = deepcopy(spec["default"])
        if spec["required"] and _is_empty_envelope(parameters.get(name)):
            raise ToolNodeConfigError(
                "INVALID_NODE_CONFIG",
                f"Required tool parameter {name!r} is missing",
            )

    return config


def _has_binding(config: dict[str, object] | None, provider_name: str, tool_name: str) -> bool:
    if config is None:
        return False
    provider = config.get("provider_id") or config.get("provider_name")
    return provider == provider_name and config.get("tool_name") == tool_name


def _copied_mapping(value: object) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def _compile_tool_argument(
    name: str,
    argument: VariableToolArgument | TemplateToolArgument | ConstantToolArgument,
    spec: ToolParameterSpec,
    *,
    nodes_by_id: dict[str, dict[str, object]],
    pending_sources: dict[str, PendingSelectorSource] | None,
    referrer_ancestor_ids: set[str] | None,
    variable_registry: VariableRegistry | None,
    referrer_id: str | None,
) -> dict[str, Any]:
    parameter_type = spec["type"]
    if spec["form"] != "llm" and not isinstance(argument, ConstantToolArgument):
        raise ToolNodeConfigError(
            "INVALID_NODE_CONFIG",
            f"Form parameter {name!r} requires a constant value",
        )
    if parameter_type in _FILE_PARAM_TYPES and not isinstance(argument, VariableToolArgument):
        raise ToolNodeConfigError(
            "INVALID_NODE_CONFIG",
            f"File parameter {name!r} requires a variable selector",
        )

    if isinstance(argument, VariableToolArgument):
        if variable_registry is not None:
            if not referrer_id:
                raise ToolNodeConfigError("UNKNOWN_NODE_REFERENCE", "Tool parameter requires a referrer node")
            try:
                variable_registry.resolve(
                    tuple(argument.selector),
                    referrer_id=referrer_id,
                    expected_type=_expected_variable_type(spec),
                )
            except VariableResolutionError as exc:
                raise ToolNodeConfigError(exc.code, exc.detail) from exc
            return {"type": "variable", "value": list(argument.selector)}
        source_id = argument.selector[0]
        variable = ".".join(argument.selector[1:])
        source = nodes_by_id.get(source_id)
        declared_live = source is not None and declares_variable(
            source,
            variable,
            ancestor_ids=referrer_ancestor_ids,
            nodes_by_id=nodes_by_id,
        )
        declared_pending = _pending_declares_variable(
            source_id,
            variable,
            pending_sources=pending_sources,
            referrer_ancestor_ids=referrer_ancestor_ids,
        )
        if not declared_live and not declared_pending:
            raise ToolNodeConfigError(
                "UNKNOWN_NODE_REFERENCE",
                f"Tool parameter {name!r} references unknown output {source_id}.{variable}",
            )
        return {"type": "variable", "value": list(argument.selector)}

    if isinstance(argument, TemplateToolArgument):
        if parameter_type not in _STRING_PARAM_TYPES or spec["form"] != "llm":
            raise ToolNodeConfigError(
                "INVALID_NODE_CONFIG",
                f"Tool parameter {name!r} does not accept a template",
            )
        return {"type": "mixed", "value": argument.text}

    _validate_constant(name, argument.value, spec)
    return {"type": "constant", "value": deepcopy(argument.value)}


def _expected_variable_type(spec: ToolParameterSpec) -> str | None:
    return _VARIABLE_TYPES_BY_PARAMETER_TYPE.get(spec["type"])


def _pending_declares_variable(
    source_id: str,
    variable: str,
    *,
    pending_sources: dict[str, PendingSelectorSource] | None,
    referrer_ancestor_ids: set[str] | None,
) -> bool:
    """Trust same-batch outputs, but keep iteration item/index inside the container."""
    if not pending_sources:
        return False
    pending = pending_sources.get(source_id)
    if pending is None:
        return False
    base, _, rest = variable.partition(".")
    if pending["node_type"] == BuiltinNodeTypes.ITERATION and base in _ITERATION_SCOPE_VARS:
        if referrer_ancestor_ids is None or source_id not in referrer_ancestor_ids:
            return False
        if base == "index":
            return not rest
        return True
    return base in pending["outputs"]


def _validate_constant(name: str, value: object, spec: ToolParameterSpec) -> None:
    parameter_type = spec["type"]
    options = spec.get("options")
    valid = True
    if parameter_type in _STRING_PARAM_TYPES | {"checkbox", "dynamic-select"}:
        valid = isinstance(value, str)
    elif parameter_type == "select":
        valid = isinstance(value, str) if options is None else True
    elif parameter_type in {"boolean", "bool"}:
        valid = isinstance(value, bool)
    elif parameter_type in {"number", "float"}:
        valid = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif parameter_type in {"integer", "int"}:
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif parameter_type in {"array", "list"}:
        valid = isinstance(value, list)
    elif parameter_type in {"object", "dict", "app-selector", "model-selector"}:
        valid = isinstance(value, dict)
    if not valid:
        raise ToolNodeConfigError(
            "INVALID_NODE_CONFIG",
            f"Tool parameter {name!r} has an invalid {parameter_type} value",
        )
    if options is not None and not any(value == option["value"] for option in options):
        raise ToolNodeConfigError(
            "INVALID_NODE_CONFIG",
            f"Tool parameter {name!r} must use a declared option",
        )


def apply_tool_parameters_to_graph(
    nodes: list[dict[str, Any]],
    entries: list[ToolCatalogueEntry] | None = None,
) -> None:
    """Mutate every tool node's parameters in place. Idempotent."""
    specs = tool_parameter_specs(entries or [])
    nodes_by_id = {str(node.get("id")): node for node in nodes if isinstance(node, dict) and node.get("id")}
    for node in nodes:
        data = node.get("data")
        if not isinstance(data, dict) or data.get("type") != BuiltinNodeTypes.TOOL:
            continue
        provider = str(data.get("provider_id") or data.get("provider_name") or "").strip()
        tool_name = str(data.get("tool_name") or "").strip()
        apply_tool_parameter_schema(
            data,
            specs.get((provider, tool_name), ()),
            nodes_by_id=nodes_by_id,
        )


def apply_tool_parameter_schema(
    data: dict[str, Any],
    parameter_specs: tuple[ToolParameterSpec, ...] | list[ToolParameterSpec],
    *,
    nodes_by_id: dict[str, dict[str, Any]],
) -> None:
    """Fill defaults and rewrite references on one tool node's ``data``."""
    if "tool_parameters" in data and not isinstance(data["tool_parameters"], dict):
        return
    if "tool_configurations" in data and not isinstance(data["tool_configurations"], dict):
        return
    parameters = data.get("tool_parameters")
    if not isinstance(parameters, dict):
        parameters = {}
        data["tool_parameters"] = parameters
    configurations = data.get("tool_configurations")
    if not isinstance(configurations, dict):
        configurations = {}
        data["tool_configurations"] = configurations

    spec_by_name = {spec["name"]: spec for spec in parameter_specs if spec.get("name")}
    for spec in spec_by_name.values():
        name = spec["name"]
        if spec["form"] != "llm":
            if name not in configurations and "default" in spec:
                configurations[name] = spec["default"]
        if name not in parameters or _is_empty_envelope(parameters.get(name)):
            filled = _default_envelope(spec)
            if filled is not None:
                parameters[name] = filled

    for name, envelope in list(parameters.items()):
        rewritten = _rewrite_envelope(
            envelope,
            spec_by_name.get(name),
            nodes_by_id=nodes_by_id,
        )
        if rewritten is not None:
            parameters[name] = rewritten


def collect_missing_required_tool_parameters(
    nodes: list[dict[str, Any]],
    entries: list[ToolCatalogueEntry] | None,
) -> list[WorkflowGenerateErrorDict]:
    """Return structured errors for required parameters that are still empty."""
    if not entries:
        return []
    specs = tool_parameter_specs(entries)
    errors: list[WorkflowGenerateErrorDict] = []
    for node in nodes:
        data = node.get("data") if isinstance(node, dict) else None
        if not isinstance(data, dict) or data.get("type") != BuiltinNodeTypes.TOOL:
            continue
        provider = str(data.get("provider_id") or data.get("provider_name") or "").strip()
        tool_name = str(data.get("tool_name") or "").strip()
        parameters = data.get("tool_parameters")
        if not isinstance(parameters, dict):
            parameters = {}
        node_id = str(node.get("id") or "")
        for spec in specs.get((provider, tool_name), ()):
            if not spec.get("required"):
                continue
            if not _is_empty_envelope(parameters.get(spec["name"])):
                continue
            errors.append(
                {
                    "code": "INVALID_NODE_CONFIG",
                    "node_id": node_id,
                    "detail": (f"Tool node {node_id!r} is missing required parameter {spec['name']!r}"),
                }
            )
    return errors


def _default_envelope(spec: ToolParameterSpec) -> dict[str, Any] | None:
    if spec["type"] in _FILE_PARAM_TYPES:
        return None
    if "default" not in spec:
        return None
    default = spec["default"]
    if spec["type"] in _STRING_PARAM_TYPES:
        return {"type": "mixed", "value": "" if default is None else str(default)}
    return {"type": "constant", "value": default}


def _is_empty_envelope(value: object) -> bool:
    if value is None or value == "":
        return True
    if isinstance(value, list):
        return len(value) < 2
    if not isinstance(value, dict):
        return False
    inner = value.get("value")
    if value.get("type") == "variable":
        return not isinstance(inner, list) or len(inner) < 2
    return inner is None or inner == ""


def _rewrite_envelope(
    envelope: object,
    spec: ToolParameterSpec | None,
    *,
    nodes_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if isinstance(envelope, list) and VariableReferences._is_selector_list(envelope):
        return {"type": "variable", "value": envelope}
    if isinstance(envelope, str):
        parsed = _parse_ref(envelope)
        if parsed is None:
            return None
        return _envelope_for_ref(parsed, spec, nodes_by_id=nodes_by_id)
    if not isinstance(envelope, dict):
        return None
    value = envelope.get("value")
    if isinstance(value, list) and VariableReferences._is_selector_list(value):
        return None
    if not isinstance(value, str):
        return None
    parsed = _parse_ref(value)
    if parsed is None:
        return None
    source_id, var = parsed
    wants_file = _wants_file_param(spec, source_id, var, nodes_by_id)
    if envelope.get("type") == "mixed" and value.startswith("{{#") and not wants_file:
        return None
    return _envelope_for_ref(parsed, spec, nodes_by_id=nodes_by_id)


def _envelope_for_ref(
    parsed: tuple[str, str],
    spec: ToolParameterSpec | None,
    *,
    nodes_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    source_id, var = parsed
    source = nodes_by_id.get(source_id)
    if source is None:
        return None
    if not VariableReferences._declares_variable(source, var, nodes_by_id=nodes_by_id):
        return None
    if _wants_file_param(spec, source_id, var, nodes_by_id):
        return {"type": "variable", "value": [source_id, var]}
    return {"type": "mixed", "value": f"{{{{#{source_id}.{var}#}}}}"}


def _wants_file_param(
    spec: ToolParameterSpec | None,
    source_id: str,
    var: str,
    nodes_by_id: dict[str, dict[str, Any]],
) -> bool:
    if spec is not None:
        return spec["type"] in _FILE_PARAM_TYPES
    source = nodes_by_id.get(source_id)
    if source is None:
        return False
    schema = VariableReferences._schema_for_variable(source, var.split(".", 1)[0], nodes_by_id)
    return str(schema.get("type") or "") in VariableReferences._FILE_OUTPUT_TYPES | {"file-list"}


def _parse_ref(value: str) -> tuple[str, str] | None:
    text = value.strip()
    match = _PLACEHOLDER_RE.fullmatch(text)
    if match is not None:
        return match.group(1), match.group(2)
    match = VariableReferences._VAR_REF_RE.fullmatch(f"{{{{#{text}#}}}}")
    if match is not None and "." in text and "{{#" not in text:
        return match.group(1), match.group(2)
    return None
