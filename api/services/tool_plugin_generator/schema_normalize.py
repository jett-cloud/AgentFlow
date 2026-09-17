"""Normalize generated tool-plugin YAML fragments for Dify Plugin SDK schemas."""

from __future__ import annotations

import re
from typing import Any

import yaml

_ALLOWED_FORMS = frozenset({"llm", "form"})
_KEY_VALUE_LINE = re.compile(r"^(\s*(?:-\s+)?[^:#\n][^:#\n]*?:\s+)(.+)$")


def repair_yaml_unquoted_colon_scalars(content: str) -> str:
    """Quote plain YAML scalars that contain ``:`` so LLM-written descriptions parse.

    Example broken line::

        en_US: Optional image style. Supported values: realistic, anime

    becomes::

        en_US: "Optional image style. Supported values: realistic, anime"
    """
    repaired_lines: list[str] = []
    changed = 0
    for line in content.splitlines():
        match = _KEY_VALUE_LINE.match(line)
        if not match:
            repaired_lines.append(line)
            continue
        prefix, value = match.group(1), match.group(2)
        stripped = value.strip()
        already_quoted = stripped.startswith(("'", '"', "|", ">", "[", "{", "&", "*", "!"))
        if stripped and ":" in stripped and not already_quoted:
            escaped = stripped.replace("\\", "\\\\").replace('"', '\\"')
            repaired_lines.append(f'{prefix}"{escaped}"')
            changed += 1
        else:
            repaired_lines.append(line)
    ending = "\n" if content.endswith("\n") else ""
    return "\n".join(repaired_lines) + ending


def as_i18n(value: Any, *, fallback: str) -> dict[str, str]:
    """Coerce a plain string or partial map into an i18n object with required ``en_US``.

    Plugin SDK requires ``en_US`` on identity/credential labels. LLM output often
    only sets ``zh_Hans`` — copy that (or any non-empty locale) into ``en_US``.
    """
    if isinstance(value, dict):
        result = {str(key): str(item) for key, item in value.items() if item is not None}
        en_us = result.get("en_US")
        if en_us is not None and str(en_us).strip():
            return result
        for item in result.values():
            if str(item).strip():
                result["en_US"] = str(item)
                return result
        return {"en_US": fallback}
    if value is None or str(value).strip() == "":
        return {"en_US": fallback}
    return {"en_US": str(value)}


def normalize_tool_parameter(parameter: dict[str, Any]) -> dict[str, Any]:
    """Ensure a tool parameter satisfies SDK ``ToolParameter`` required fields."""
    name = str(parameter.get("name") or "").strip()
    label = as_i18n(parameter.get("label"), fallback=name or "Parameter")
    human = parameter.get("human_description")
    human_i18n = as_i18n(human if human is not None else label, fallback=label["en_US"])
    llm_description = parameter.get("llm_description")
    if llm_description is None or str(llm_description).strip() == "":
        llm_description = human_i18n["en_US"]
    form = str(parameter.get("form") or "llm").strip()
    if form not in _ALLOWED_FORMS:
        form = "llm"

    normalized: dict[str, Any] = {
        "name": name,
        "type": str(parameter.get("type") or "string"),
        "required": bool(parameter.get("required", False)),
        "label": label,
        "human_description": human_i18n,
        "llm_description": str(llm_description),
        "form": form,
    }
    for optional_key in ("options", "default", "min", "max", "placeholder"):
        if optional_key in parameter:
            normalized[optional_key] = parameter[optional_key]
    return normalized


def normalize_tool_parameters(parameters: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, parameter in enumerate(parameters):
        if not isinstance(parameter, dict):
            raise ValueError(f"parameters[{index}] must be an object")
        name = parameter.get("name")
        if not name or not str(name).strip():
            raise ValueError(f"parameters[{index}] must have a non-empty name")
        normalized.append(normalize_tool_parameter(parameter))
    return normalized


def _load_yaml_document(content: str) -> dict[str, Any] | None:
    document: Any | None = None
    for candidate in (content, repair_yaml_unquoted_colon_scalars(content)):
        try:
            document = yaml.safe_load(candidate)
            break
        except yaml.YAMLError:
            document = None
    if document is None:
        return None
    if not isinstance(document, dict):
        return None
    return document


def _normalize_identity_i18n(identity: dict[str, Any], *, fallback_name: str) -> None:
    identity["label"] = as_i18n(identity.get("label"), fallback=fallback_name or "Tool")
    description = identity.get("description")
    if isinstance(description, (dict, str)):
        identity["description"] = as_i18n(description, fallback=identity["label"]["en_US"])


def normalize_tool_yaml_content(content: str) -> str:
    """Rewrite tool YAML so identity/parameters include required ``en_US`` i18n and ``form``."""
    document = _load_yaml_document(content)
    if document is None:
        return content

    parameters = document.get("parameters")
    if isinstance(parameters, list):
        fixed: list[Any] = []
        for parameter in parameters:
            if isinstance(parameter, dict) and parameter.get("name"):
                fixed.append(normalize_tool_parameter(parameter))
            else:
                fixed.append(parameter)
        document["parameters"] = fixed

    identity = document.get("identity")
    tool_fallback = "Tool"
    if isinstance(identity, dict):
        tool_fallback = str(identity.get("name") or "Tool")
        _normalize_identity_i18n(identity, fallback_name=tool_fallback)
        icon = identity.get("icon")
        if isinstance(icon, str) and icon.startswith("_assets/"):
            identity["icon"] = icon.split("/", 1)[1]
        elif not icon:
            identity["icon"] = "icon.svg"

    description = document.get("description")
    if isinstance(description, dict):
        human = description.get("human")
        description["human"] = as_i18n(human, fallback=tool_fallback)
        llm = description.get("llm")
        if llm is None or (isinstance(llm, str) and not llm.strip()):
            description["llm"] = description["human"]["en_US"]
        elif isinstance(llm, dict):
            description["llm"] = as_i18n(llm, fallback=description["human"]["en_US"]).get(
                "en_US", description["human"]["en_US"]
            )

    return yaml.dump(document, default_flow_style=False, allow_unicode=True, sort_keys=False)


def normalize_provider_yaml_content(content: str) -> str:
    """Ensure provider identity/credential labels include required ``en_US``."""
    document = _load_yaml_document(content)
    if document is None:
        return content

    identity = document.get("identity")
    if isinstance(identity, dict):
        fallback = str(identity.get("name") or "Provider")
        _normalize_identity_i18n(identity, fallback_name=fallback)
        icon = identity.get("icon")
        if isinstance(icon, str) and icon.startswith("_assets/"):
            identity["icon"] = icon.split("/", 1)[1]
        elif not icon:
            identity["icon"] = "icon.svg"

    credentials = document.get("credentials_for_provider")
    if isinstance(credentials, dict):
        for name, spec in list(credentials.items()):
            if not isinstance(spec, dict):
                continue
            spec["label"] = as_i18n(spec.get("label"), fallback=str(name))
            help_text = spec.get("help")
            if help_text is not None:
                spec["help"] = as_i18n(help_text, fallback=str(name))
            placeholder = spec.get("placeholder")
            if placeholder is not None:
                spec["placeholder"] = as_i18n(placeholder, fallback="")

    return yaml.dump(document, default_flow_style=False, allow_unicode=True, sort_keys=False)


def normalize_manifest_yaml_content(content: str) -> str:
    """Ensure manifest label/description include required ``en_US``."""
    document = _load_yaml_document(content)
    if document is None:
        return content

    fallback = str(document.get("name") or "Plugin")
    document["label"] = as_i18n(document.get("label"), fallback=fallback)
    document["description"] = as_i18n(document.get("description"), fallback=document["label"]["en_US"])
    return yaml.dump(document, default_flow_style=False, allow_unicode=True, sort_keys=False)
