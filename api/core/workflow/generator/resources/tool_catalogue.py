"""Tool catalogue values, schema normalization, and in-memory lookup."""

import logging
from typing import NotRequired, TypedDict, cast

logger = logging.getLogger(__name__)


_MAX_TOOLS = 80


type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


class ToolParameterOptionSpec(TypedDict):
    value: JsonValue
    label: NotRequired[str]


class ToolParameterSpec(TypedDict):
    name: str
    type: str
    form: str
    required: bool
    description: NotRequired[str]
    default: NotRequired[JsonValue]
    options: NotRequired[tuple[ToolParameterOptionSpec, ...]]


class ToolOutputSpec(TypedDict):
    name: str
    type: str


class ToolCatalogueEntry(TypedDict):
    provider_name: str
    provider_type: str  # "builtin" | "mcp"  (plugin providers serialize as builtin)
    plugin_id: str  # empty string for hardcoded built-ins
    tool_name: str
    tool_label: str
    description: str  # one-line LLM-friendly description
    parameters: NotRequired[tuple[ToolParameterSpec, ...]]
    parameter_names: NotRequired[tuple[str, ...]]
    outputs: NotRequired[tuple[ToolOutputSpec, ...]]
    output_names: NotRequired[tuple[str, ...]]
    search_aliases: NotRequired[tuple[str, ...]]  # zh-Hans labels / human descriptions for search_tools


def _extract_tool_schema(
    tool: object,
) -> tuple[tuple[ToolParameterSpec, ...] | None, tuple[str, ...] | None, tuple[ToolOutputSpec, ...] | None]:
    """Extract parameter facts, output names, and typed outputs; ``None`` means unknown schema."""
    entity = getattr(tool, "entity", None)
    if entity is None:
        return None, None, None
    parameter_specs: tuple[ToolParameterSpec, ...] | None = None
    output_names: tuple[str, ...] | None = None
    outputs: tuple[ToolOutputSpec, ...] | None = None
    try:
        parameters = getattr(entity, "parameters", None)
        if parameters is not None:
            specs: list[ToolParameterSpec] = []
            for item in parameters:
                spec = _parameter_spec(item)
                if spec is not None:
                    specs.append(spec)
            parameter_specs = tuple(specs)
    except Exception:
        parameter_specs = None
    try:
        output_schema = getattr(entity, "output_schema", None) or {}
        if isinstance(output_schema, dict) and output_schema:
            properties = output_schema.get("properties")
            if not isinstance(properties, dict):
                properties = output_schema
            names: list[str] = []
            typed: list[ToolOutputSpec] = []
            for key, schema in properties.items():
                if not isinstance(key, str):
                    continue
                names.append(key)
                output_type = _normalize_output_type(schema)
                if output_type is not None:
                    typed.append(ToolOutputSpec(name=key, type=output_type))
            output_names = tuple(names) if names else None
            outputs = tuple(typed) if typed else None
    except Exception:
        output_names = None
        outputs = None
    return parameter_specs, output_names, outputs


def _normalize_output_type(schema: object) -> str | None:
    """Keep only a conservative nameable type; never copy plugin objects or secrets."""
    if not isinstance(schema, dict):
        return None
    raw = schema.get("type")
    if not isinstance(raw, str) or not raw:
        return None
    if raw != "array":
        return raw
    items = schema.get("items")
    if not isinstance(items, dict):
        return "array"
    item_type = items.get("type")
    if not isinstance(item_type, str) or not item_type:
        return "array"
    return f"array[{item_type}]"


def _parameter_spec(parameter: object) -> ToolParameterSpec | None:
    name = _field(parameter, "name")
    parameter_type = _enum_text(_field(parameter, "type"))
    form = _enum_text(_field(parameter, "form"))
    if not isinstance(name, str) or not name or not parameter_type or not form:
        return None
    spec = ToolParameterSpec(
        name=name,
        type=parameter_type,
        form=form,
        required=bool(_field(parameter, "required")),
    )
    llm_description = _field(parameter, "llm_description")
    description = llm_description.strip() if isinstance(llm_description, str) else ""
    if not description:
        description = _i18n_text(_field(parameter, "human_description"))
    if description:
        spec["description"] = description
    default = _json_value(_field(parameter, "default"))
    if parameter_type != "secret-input" and default is not _NO_JSON_VALUE and default is not None:
        spec["default"] = cast(JsonValue, default)
    options = _option_specs(_field(parameter, "options"))
    if options:
        spec["options"] = options
    return spec


_NO_JSON_VALUE = object()


def _json_value(value: object) -> JsonValue | object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        converted: list[JsonValue] = []
        for item in value:
            json_item = _json_value(item)
            if json_item is _NO_JSON_VALUE:
                return _NO_JSON_VALUE
            converted.append(cast(JsonValue, json_item))
        return converted
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        converted_dict: dict[str, JsonValue] = {}
        for key, item in value.items():
            json_item = _json_value(item)
            if json_item is _NO_JSON_VALUE:
                return _NO_JSON_VALUE
            converted_dict[key] = cast(JsonValue, json_item)
        return converted_dict
    return _NO_JSON_VALUE


def _option_specs(raw_options: object) -> tuple[ToolParameterOptionSpec, ...]:
    if not isinstance(raw_options, (list, tuple)):
        return ()
    specs: list[ToolParameterOptionSpec] = []
    for option in raw_options:
        value = _json_value(_field(option, "value"))
        if value is _NO_JSON_VALUE:
            continue
        spec = ToolParameterOptionSpec(value=cast(JsonValue, value))
        label = _i18n_text(_field(option, "label"))
        if label:
            spec["label"] = label
        specs.append(spec)
    return tuple(specs)


def _field(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _enum_text(value: object) -> str:
    raw = _field(value, "value")
    if raw is None:
        raw = value
    return raw if isinstance(raw, str) else ""


def _with_schema(entry: ToolCatalogueEntry, tool: object) -> ToolCatalogueEntry:
    parameter_specs, output_names, outputs = _extract_tool_schema(tool)
    if parameter_specs is not None:
        entry["parameters"] = parameter_specs
        entry["parameter_names"] = tuple(spec["name"] for spec in parameter_specs)
    if output_names is not None:
        entry["output_names"] = output_names
    if outputs is not None:
        entry["outputs"] = outputs
    return entry


def tool_parameter_specs(
    entries: list[ToolCatalogueEntry],
) -> dict[tuple[str, str], tuple[ToolParameterSpec, ...]]:
    """Return known parameter schemas keyed by exact catalogue binding."""
    return {
        (entry["provider_name"], entry["tool_name"]): entry["parameters"] for entry in entries if "parameters" in entry
    }


def find_tool_entry(
    entries: list[ToolCatalogueEntry],
    *,
    provider_name: str,
    tool_name: str,
) -> ToolCatalogueEntry | None:
    """Find one exact binding in this run's immutable catalogue snapshot."""
    return next(
        (entry for entry in entries if entry["provider_name"] == provider_name and entry["tool_name"] == tool_name),
        None,
    )


def tool_schema_lookups(
    entries: list[ToolCatalogueEntry],
) -> tuple[dict[tuple[str, str], frozenset[str]], dict[tuple[str, str], frozenset[str]]]:
    """Split catalogue schema into parameter and output lookups.

    A missing key means that tool's schema was not available — validators skip
    membership instead of treating every name as unknown.
    """
    parameters: dict[tuple[str, str], frozenset[str]] = {}
    outputs: dict[tuple[str, str], frozenset[str]] = {}
    for entry in entries:
        key = (entry["provider_name"], entry["tool_name"])
        if "parameter_names" in entry:
            parameters[key] = frozenset(entry["parameter_names"])
        if "output_names" in entry:
            outputs[key] = frozenset(entry["output_names"])
    return parameters, outputs


def installed_tool_keys(entries: list[ToolCatalogueEntry]) -> set[tuple[str, str]]:
    """
    Return the set of ``(provider_name, tool_name)`` pairs available for the
    tenant. The validator in ``runner.py`` consults this set so a planner /
    builder that hallucinates a tool name fails loudly at generation time
    instead of producing a runtime-broken graph.

    The set is keyed on ``provider_name`` (not ``provider_id``) because the
    builder prompt is instructed to put the provider's catalogue name into
    BOTH ``data.provider_id`` and ``data.provider_name`` on tool nodes —
    they are the same value for both built-in and plugin providers.
    """
    return {(e["provider_name"], e["tool_name"]) for e in entries}


def format_tool_catalogue(entries: list[ToolCatalogueEntry]) -> str:
    """
    Render the catalogue as a compact multi-line block for prompt injection.
    Returns an empty string when no tools are installed — callers should skip
    the section entirely in that case.
    """
    if not entries:
        return ""
    lines = []
    for e in entries:
        desc = e["description"].replace("\n", " ").strip()
        if len(desc) > 120:
            desc = desc[:117] + "..."
        line = f"- {e['provider_name']}/{e['tool_name']}"
        if e["provider_type"] == "mcp":
            line += " [mcp]"
        if e["tool_label"] and e["tool_label"] != e["tool_name"]:
            line += f" ({e['tool_label']})"
        if desc:
            line += f" — {desc}"
        lines.append(line)
    return "\n".join(lines)


def _i18n_text(label) -> str:
    """Pull the English label out of an I18nObject (falls back to .name)."""
    if label is None:
        return ""
    en = getattr(label, "en_US", None)
    if en:
        return en
    return getattr(label, "zh_Hans", "") or ""


def _i18n_all_texts(label) -> tuple[str, ...]:
    """Deduped locale strings. Search must see zh-Hans even when en_US is set."""
    if label is None:
        return ()
    seen: list[str] = []
    for attr in ("en_US", "zh_Hans", "zh_Hant", "ja_JP", "pt_BR"):
        value = getattr(label, attr, None)
        if not isinstance(value, str):
            continue
        text = value.strip()
        if text and text not in seen:
            seen.append(text)
    return tuple(seen)


def _search_aliases(tool: object) -> tuple[str, ...]:
    entity = getattr(tool, "entity", None)
    if entity is None:
        return ()
    identity = getattr(entity, "identity", None)
    description = getattr(entity, "description", None)
    texts: list[str] = []
    for blob in (getattr(identity, "label", None), getattr(description, "human", None)):
        for text in _i18n_all_texts(blob):
            if text not in texts:
                texts.append(text)
    return tuple(texts)


def _with_search_aliases(entry: ToolCatalogueEntry, tool: object) -> ToolCatalogueEntry:
    aliases = _search_aliases(tool)
    if aliases:
        entry["search_aliases"] = aliases
    return entry


def _tool_description(description) -> str:
    """Pull the LLM-facing description (``.llm``) from a ToolDescription."""
    if description is None:
        return ""
    return getattr(description, "llm", "") or ""
