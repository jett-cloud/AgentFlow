from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from services.tool_plugin_generator.llm_fill import parse_llm_fill_payload
from services.tool_plugin_generator.preview_mapper import (
    map_files_to_preview_tool,
)
from services.tool_plugin_generator.scaffold import add_tool_to_plugin, list_tool_names
from services.tool_plugin_generator.service import generate_tool_plugin
from services.tool_plugin_generator.validator import ToolPluginValidationError, validate_plugin_files

ALLOWED_WRITE_PREFIXES: tuple[str, ...] = (
    "provider/",
    "tools/",
    "_assets/",
)
ALLOWED_WRITE_FILES: frozenset[str] = frozenset(
    {
        "manifest.yaml",
        "main.py",
        "requirements.txt",
        "README.md",
        ".env.example",
    }
)


@dataclass
class AgentWorkspace:
    author: str
    plugin_name: str
    tool_name: str
    tenant_id: str
    user_id: str
    files: dict[str, str] = field(default_factory=dict)
    bootstrap_llm: Any | None = None
    llm_event_callback: Callable[[str], None] | None = None

    def snapshot(self) -> dict[str, str]:
        return dict(self.files)

    def preview_tool(self) -> dict[str, Any] | None:
        if not self.files:
            return None
        try:
            return map_files_to_preview_tool(
                self.files,
                author=self.author,
                plugin_name=self.plugin_name,
                tool_name=self.tool_name or None,
            )
        except Exception:
            return None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[AgentWorkspace, dict[str, Any]], str]
    mutates_files: bool
    timeout_seconds: int


_TOOL_SPECS: tuple[ToolSpec, ...] | None = None


def _normalize_path(path: str) -> str:
    normalized = PurePosixPath(path)
    if "\\" in path or normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError("file path must be a relative POSIX path without '..'")
    return str(normalized)


def _is_allowed_write_path(path: str) -> bool:
    if path in ALLOWED_WRITE_FILES:
        return True
    return any(path.startswith(prefix) for prefix in ALLOWED_WRITE_PREFIXES)


def tool_specs() -> tuple[ToolSpec, ...]:
    global _TOOL_SPECS
    if _TOOL_SPECS is None:
        _TOOL_SPECS = (
            ToolSpec(
                name="bootstrap_scaffold",
                description=(
                    "Generate the initial tool plugin scaffold when no files exist yet. "
                    "Do not use when files already exist."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "user_prompt": {"type": "string"},
                        "api_doc": {"type": "string"},
                    },
                    "required": ["user_prompt"],
                },
                handler=_bootstrap_scaffold,
                mutates_files=True,
                timeout_seconds=120,
            ),
            ToolSpec(
                name="add_tool",
                description=(
                    "Add a second (or later) tool into the current plugin without wiping existing tools. "
                    "Requires existing scaffold files. Updates provider.yaml tools list."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "tool_name": {"type": "string"},
                        "tool_label": {"type": "string"},
                        "tool_description": {"type": "string"},
                        "parameters": {"type": "array"},
                        "invoke_python_body": {"type": "string"},
                        "credentials": {"type": "array"},
                        "readme": {"type": "string"},
                    },
                    "required": ["tool_name", "tool_label", "invoke_python_body"],
                },
                handler=_add_tool,
                mutates_files=True,
                timeout_seconds=120,
            ),
            ToolSpec(
                name="list_files",
                description="List relative paths in the current plugin working copy.",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=_list_files,
                mutates_files=False,
                timeout_seconds=10,
            ),
            ToolSpec(
                name="read_file",
                description="Read one file from the working copy.",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                handler=_read_file,
                mutates_files=False,
                timeout_seconds=10,
            ),
            ToolSpec(
                name="write_file",
                description="Create or overwrite one allowed scaffold file in the working copy.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
                handler=_write_file,
                mutates_files=True,
                timeout_seconds=30,
            ),
            ToolSpec(
                name="validate",
                description="Validate the current plugin files.",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=_validate,
                mutates_files=False,
                timeout_seconds=30,
            ),
        )
    return _TOOL_SPECS


def tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        }
        for spec in tool_specs()
    ]


def execute_tool(workspace: AgentWorkspace, name: str, arguments: dict[str, Any]) -> str:
    spec = next((item for item in tool_specs() if item.name == name), None)
    if spec is None:
        return json.dumps({"ok": False, "error": f"Unknown tool: {name}"})
    try:
        return spec.handler(workspace, arguments or {})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


def _bootstrap_scaffold(workspace: AgentWorkspace, arguments: dict[str, Any]) -> str:
    if workspace.files:
        return json.dumps(
            {
                "ok": False,
                "error": (
                    "Scaffold already exists. Use add_tool to create another tool, "
                    f"or edit files in place. Existing tools: {list_tool_names(workspace.files)}"
                ),
            }
        )
    if workspace.bootstrap_llm is None:
        return json.dumps({"ok": False, "error": "Bootstrap LLM client is not configured"})
    user_prompt = str(arguments.get("user_prompt") or "").strip()
    if not user_prompt:
        return json.dumps({"ok": False, "error": "user_prompt is required"})
    result = generate_tool_plugin(
        author=workspace.author,
        plugin_name=workspace.plugin_name,
        tool_name=workspace.tool_name,
        user_prompt=user_prompt,
        api_doc=str(arguments.get("api_doc") or ""),
        llm_client=workspace.bootstrap_llm,
        on_llm_event=workspace.llm_event_callback,
    )
    workspace.files = dict(result.files)
    return json.dumps(
        {
            "ok": True,
            "file_count": len(workspace.files),
            "paths": sorted(workspace.files),
            "preview_tool": result.preview_tool,
            "tool_names": list_tool_names(workspace.files),
        }
    )


def _add_tool(workspace: AgentWorkspace, arguments: dict[str, Any]) -> str:
    if not workspace.files:
        return json.dumps({"ok": False, "error": "No scaffold yet; call bootstrap_scaffold first"})
    tool_name = str(arguments.get("tool_name") or "").strip()
    if not tool_name:
        return json.dumps({"ok": False, "error": "tool_name is required"})
    try:
        fill = parse_llm_fill_payload(
            {
                "provider_label": workspace.plugin_name,
                "tool_label": arguments.get("tool_label") or tool_name,
                "tool_description": arguments.get("tool_description") or arguments.get("tool_label") or tool_name,
                "parameters": arguments.get("parameters") or [],
                "credentials": arguments.get("credentials") or [],
                "invoke_python_body": arguments.get("invoke_python_body"),
                "readme": arguments.get("readme") or "",
            }
        )
        workspace.files = add_tool_to_plugin(
            workspace.files,
            author=workspace.author,
            plugin_name=workspace.plugin_name,
            tool_name=tool_name,
            fill=fill,
        )
        workspace.tool_name = tool_name
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    preview = map_files_to_preview_tool(
        workspace.files,
        author=workspace.author,
        plugin_name=workspace.plugin_name,
        tool_name=tool_name,
    )
    return json.dumps(
        {
            "ok": True,
            "tool_name": tool_name,
            "tool_names": list_tool_names(workspace.files),
            "preview_tool": preview,
        }
    )


def _list_files(workspace: AgentWorkspace, _arguments: dict[str, Any]) -> str:
    return json.dumps({"ok": True, "paths": sorted(workspace.files)})


def _read_file(workspace: AgentWorkspace, arguments: dict[str, Any]) -> str:
    path = _normalize_path(str(arguments.get("path") or ""))
    if path not in workspace.files:
        return json.dumps({"ok": False, "error": f"File not found: {path}"})
    return json.dumps({"ok": True, "path": path, "content": workspace.files[path]})


def _write_file(workspace: AgentWorkspace, arguments: dict[str, Any]) -> str:
    from services.tool_plugin_generator.schema_normalize import (
        normalize_manifest_yaml_content,
        normalize_provider_yaml_content,
        normalize_tool_yaml_content,
    )

    path = _normalize_path(str(arguments.get("path") or ""))
    if not _is_allowed_write_path(path):
        return json.dumps({"ok": False, "error": f"Write not allowed for path: {path}"})
    content = arguments.get("content")
    if content is None:
        return json.dumps({"ok": False, "error": "content is required"})
    text = str(content)
    if path.startswith("tools/") and path.endswith((".yaml", ".yml")):
        text = normalize_tool_yaml_content(text)
    elif path.startswith("provider/") and path.endswith((".yaml", ".yml")):
        text = normalize_provider_yaml_content(text)
    elif path in {"manifest.yaml", "manifest.yml"}:
        text = normalize_manifest_yaml_content(text)
    workspace.files[path] = text
    return json.dumps({"ok": True, "path": path, "bytes": len(text)})


def _validate(workspace: AgentWorkspace, _arguments: dict[str, Any]) -> str:
    from services.tool_plugin_generator.packager import normalize_plugin_source_files

    workspace.files = normalize_plugin_source_files(workspace.files)
    try:
        validate_plugin_files(workspace.files)
    except ToolPluginValidationError as exc:
        return json.dumps({"ok": False, "errors": exc.errors})
    return json.dumps({"ok": True, "errors": []})
