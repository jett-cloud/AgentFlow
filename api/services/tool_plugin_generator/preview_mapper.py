from __future__ import annotations

import re
from typing import Any

import yaml

_INVALID_PLUGIN_ID_SEGMENT_RE = re.compile(r"[^a-z0-9_-]+")
_MULTI_HYPHEN_RE = re.compile(r"-{2,}")
_MULTI_UNDERSCORE_RE = re.compile(r"_{2,}")


def sanitize_plugin_id_segment(value: str | None) -> str:
    """Normalize one org/plugin/provider segment for ToolProviderID (no dots/spaces)."""
    cleaned = _INVALID_PLUGIN_ID_SEGMENT_RE.sub("-", (value or "").strip().lower())
    cleaned = _MULTI_HYPHEN_RE.sub("-", cleaned)
    cleaned = _MULTI_UNDERSCORE_RE.sub("_", cleaned)
    return cleaned.strip("-_")


def _find_tool_yaml_path(files: dict[str, str], *, tool_name: str | None = None) -> str | None:
    tool_paths = sorted(path for path in files if path.startswith("tools/") and path.endswith((".yaml", ".yml")))
    if not tool_paths:
        return None
    if tool_name:
        for path in tool_paths:
            stem = path.removeprefix("tools/")
            stem = stem.removesuffix(".yaml").removesuffix(".yml")
            if stem == tool_name:
                return path
    return tool_paths[0]


def _default_tool_parameters(parameters_schema: list[dict[str, Any]]) -> dict[str, Any]:
    tool_parameters: dict[str, Any] = {}
    for parameter in parameters_schema:
        name = parameter.get("name")
        if name:
            tool_parameters[str(name)] = ""
    return tool_parameters


def _iter_provider_docs(files: dict[str, str]) -> list[tuple[str, dict[str, Any]]]:
    docs: list[tuple[str, dict[str, Any]]] = []
    provider_paths = sorted(
        path for path in files if path.startswith("provider/") and path.endswith((".yaml", ".yml"))
    )
    for path in provider_paths:
        try:
            doc = yaml.safe_load(files[path]) or {}
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict):
            docs.append((path, doc))
    return docs


def _extract_provider_identity_name(files: dict[str, str], *, fallback: str) -> str:
    for path, doc in _iter_provider_docs(files):
        identity = doc.get("identity") or {}
        if isinstance(identity, dict) and identity.get("name"):
            sanitized = sanitize_plugin_id_segment(str(identity["name"]))
            if sanitized:
                return sanitized
        stem = path.removeprefix("provider/")
        stem = stem.removesuffix(".yaml").removesuffix(".yml")
        # Skip dotted filenames like provider/remove.bg.yaml (invalid as identity).
        if stem and stem != "__init__" and "." not in stem:
            sanitized = sanitize_plugin_id_segment(stem)
            if sanitized:
                return sanitized
    return sanitize_plugin_id_segment(fallback) or fallback


def _extract_credentials_schema(files: dict[str, str]) -> list[dict[str, Any]]:
    """Parse credentials_for_provider from provider/*.yaml into a list of field schemas."""
    for _path, doc in _iter_provider_docs(files):
        raw = doc.get("credentials_for_provider") or {}
        if not isinstance(raw, dict):
            continue
        schema: list[dict[str, Any]] = []
        for name, spec in raw.items():
            if not name:
                continue
            entry: dict[str, Any] = {"name": str(name)}
            if isinstance(spec, dict):
                entry.update({key: value for key, value in spec.items() if key != "name"})
                if "type" not in entry:
                    entry["type"] = "secret-input"
                if "required" not in entry:
                    entry["required"] = True
            else:
                entry["type"] = "secret-input"
                entry["required"] = True
            schema.append(entry)
        if schema:
            return schema
    return []


def build_plugin_provider_id(*, author: str, plugin_name: str, provider_name: str | None = None) -> str:
    """Dify tool plugin ids are org/plugin/provider (three segments)."""
    org = sanitize_plugin_id_segment(author)
    plugin = sanitize_plugin_id_segment(plugin_name)
    provider = sanitize_plugin_id_segment(provider_name or plugin_name) or plugin
    return f"{org}/{plugin}/{provider}"


def normalize_plugin_provider_id(provider_id: str, *, provider_name: str | None = None) -> str:
    """Upgrade legacy two-segment ids and sanitize illegal characters (e.g. dots)."""
    value = (provider_id or "").strip()
    if not value:
        return value
    parts = value.split("/")
    if len(parts) == 3:
        return build_plugin_provider_id(
            author=parts[0],
            plugin_name=parts[1],
            provider_name=parts[2],
        )
    if len(parts) == 2:
        org, plugin = parts
        return build_plugin_provider_id(
            author=org,
            plugin_name=plugin,
            provider_name=provider_name or plugin,
        )
    return value


def map_files_to_preview_tool(
    files: dict[str, str],
    *,
    author: str,
    plugin_name: str,
    tool_name: str | None = None,
) -> dict[str, Any]:
    tool_yaml_path = _find_tool_yaml_path(files, tool_name=tool_name)
    if not tool_yaml_path:
        raise ValueError("No tool YAML found in generated files")

    tool_doc = yaml.safe_load(files[tool_yaml_path]) or {}
    identity = tool_doc.get("identity") or {}
    resolved_tool_name = identity.get("name") or tool_yaml_path.removeprefix("tools/")
    for suffix in (".yaml", ".yml"):
        if resolved_tool_name.endswith(suffix):
            resolved_tool_name = resolved_tool_name.removesuffix(suffix)
    parameters_schema = tool_doc.get("parameters") or []
    if not isinstance(parameters_schema, list):
        parameters_schema = []
    credentials_schema = _extract_credentials_schema(files)
    provider_name = _extract_provider_identity_name(files, fallback=plugin_name)

    label = identity.get("label") or {}
    tool_label = label.get("en_US") if isinstance(label, dict) else str(label or resolved_tool_name)

    description = tool_doc.get("description") or {}
    human_desc = description.get("human") if isinstance(description, dict) else {}
    tool_description = human_desc.get("en_US") if isinstance(human_desc, dict) else str(description or "")

    all_tool_names = []
    for path in sorted(files):
        if path.startswith("tools/") and path.endswith((".yaml", ".yml")):
            name = path.removeprefix("tools/")
            name = name.removesuffix(".yaml").removesuffix(".yml")
            all_tool_names.append(name)

    return {
        "provider_id": build_plugin_provider_id(
            author=author,
            plugin_name=plugin_name,
            provider_name=provider_name,
        ),
        "provider_name": provider_name,
        "provider_type": "plugin",
        "tool_name": resolved_tool_name,
        "tool_label": tool_label,
        "tool_description": tool_description,
        "parameters_schema": parameters_schema,
        "tool_parameters": _default_tool_parameters(parameters_schema),
        "credentials_schema": credentials_schema,
        "available_tool_names": all_tool_names,
    }
