from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass
class ToolPluginFill:
    provider_label: str
    tool_label: str
    tool_description: str
    parameters: list[dict[str, Any]] = field(default_factory=list)
    credentials: list[dict[str, Any]] = field(default_factory=list)
    invoke_python_body: str = ""
    readme: str = ""


def _render_template(template_name: str, **context: str) -> str:
    content = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
    for key, value in context.items():
        content = content.replace(f"{{{{ {key} }}}}", value)
    return content


def _to_class_name(name: str) -> str:
    parts = re.split(r"[^a-zA-Z0-9]+", name)
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def _format_invoke_python_body(body: str) -> str:
    """Normalize LLM invoke body indentation for insertion into tool_stub.py.j2.

    The template placeholder sits at column 0 under ``_invoke``, so every line of
    the body must carry the method indent. Using ``textwrap.indent`` after
    ``dedent`` avoids the classic bug where only the first replaced line keeps
    the template's leading spaces and later lines unindent.
    """
    cleaned = textwrap.dedent((body or "").strip("\n") + "\n").strip("\n")
    if not cleaned.strip():
        cleaned = 'yield self.create_text_message("")'
    return textwrap.indent(cleaned, " " * 8)


def _build_provider_yaml(
    *,
    author: str,
    plugin_name: str,
    fill: ToolPluginFill,
    tool_name: str,
) -> str:
    provider_doc: dict[str, Any] = {
        "identity": {
            "author": author,
            "name": plugin_name,
            "label": {"en_US": fill.provider_label},
            "description": {"en_US": fill.provider_label},
            # Filename only; CLI resolves icons from the plugin `_assets/` directory.
            "icon": "icon.svg",
        },
        "tools": [f"tools/{tool_name}.yaml"],
        "extra": {"python": {"source": f"provider/{plugin_name}.py"}},
    }
    if fill.credentials:
        credentials_for_provider: dict[str, Any] = {}
        for credential in fill.credentials:
            name = credential["name"]
            credentials_for_provider[name] = {k: v for k, v in credential.items() if k != "name"}
        provider_doc["credentials_for_provider"] = credentials_for_provider
    return yaml.dump(provider_doc, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _build_tool_yaml(
    *,
    author: str,
    tool_name: str,
    fill: ToolPluginFill,
) -> str:
    tool_doc: dict[str, Any] = {
        "identity": {
            "name": tool_name,
            "author": author,
            "label": {"en_US": fill.tool_label},
            "icon": "icon.svg",
        },
        "description": {
            "human": {"en_US": fill.tool_description},
            "llm": fill.tool_description,
        },
        "parameters": fill.parameters,
        "extra": {"python": {"source": f"tools/{tool_name}.py"}},
    }
    return yaml.dump(tool_doc, default_flow_style=False, allow_unicode=True, sort_keys=False)


def render_scaffold(
    *,
    author: str,
    plugin_name: str,
    tool_name: str,
    fill: ToolPluginFill,
) -> dict[str, str]:
    provider_class = _to_class_name(plugin_name)
    tool_class = _to_class_name(tool_name)

    files: dict[str, str] = {
        "manifest.yaml": _render_template(
            "manifest.yaml.j2",
            author=author,
            plugin_name=plugin_name,
            provider_label=fill.provider_label,
            provider_yaml=f"provider/{plugin_name}.yaml",
        ),
        "main.py": (TEMPLATES_DIR / "main.py.j2").read_text(encoding="utf-8"),
        "requirements.txt": (TEMPLATES_DIR / "requirements.txt").read_text(encoding="utf-8"),
        ".env.example": "",
        "README.md": fill.readme,
        "_assets/icon.svg": (TEMPLATES_DIR / "icon.svg").read_text(encoding="utf-8"),
        f"provider/{plugin_name}.yaml": _build_provider_yaml(
            author=author,
            plugin_name=plugin_name,
            fill=fill,
            tool_name=tool_name,
        ),
        f"provider/{plugin_name}.py": _render_template(
            "provider_stub.py.j2",
            provider_class=provider_class,
        ),
        f"tools/{tool_name}.yaml": _build_tool_yaml(
            author=author,
            tool_name=tool_name,
            fill=fill,
        ),
        f"tools/{tool_name}.py": _render_template(
            "tool_stub.py.j2",
            tool_class=tool_class,
            invoke_python_body=_format_invoke_python_body(fill.invoke_python_body),
        ),
    }
    return files


def list_tool_names(files: dict[str, str]) -> list[str]:
    names: list[str] = []
    for path in sorted(files):
        if path.startswith("tools/") and path.endswith((".yaml", ".yml")):
            name = path.removeprefix("tools/")
            name = name.removesuffix(".yaml").removesuffix(".yml")
            names.append(name)
    return names


def add_tool_to_plugin(
    files: dict[str, str],
    *,
    author: str,
    plugin_name: str,
    tool_name: str,
    fill: ToolPluginFill,
) -> dict[str, str]:
    """Add a new tool into an existing plugin file tree without wiping other tools."""
    if not tool_name or not tool_name.strip():
        raise ValueError("tool_name is required")
    tool_name = tool_name.strip()
    yaml_path = f"tools/{tool_name}.yaml"
    py_path = f"tools/{tool_name}.py"
    if yaml_path in files or py_path in files:
        raise ValueError(f"Tool already exists: {tool_name}")

    provider_path = f"provider/{plugin_name}.yaml"
    if provider_path not in files:
        raise ValueError(f"Missing provider yaml: {provider_path}")

    provider_doc = yaml.safe_load(files[provider_path]) or {}
    if not isinstance(provider_doc, dict):
        raise ValueError("Provider yaml must be a mapping")
    tools = provider_doc.get("tools") or []
    if not isinstance(tools, list):
        tools = []
    tool_ref = f"tools/{tool_name}.yaml"
    if tool_ref not in tools:
        tools.append(tool_ref)
    provider_doc["tools"] = tools

    updated = dict(files)
    updated[provider_path] = yaml.dump(provider_doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
    updated[yaml_path] = _build_tool_yaml(author=author, tool_name=tool_name, fill=fill)
    updated[py_path] = _render_template(
        "tool_stub.py.j2",
        tool_class=_to_class_name(tool_name),
        invoke_python_body=_format_invoke_python_body(fill.invoke_python_body),
    )
    return updated
