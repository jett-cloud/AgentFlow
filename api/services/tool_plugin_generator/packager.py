"""Package generated plugin source files with the official Dify Plugin CLI.

The packager writes the generated source tree to a temporary plugin directory,
then invokes ``dify plugin package`` using the binary configured by
``DIFY_PLUGIN_CLI_PATH``. The CLI emits the ``.difypkg`` beside that directory.
If the binary is not configured or packaging fails, this module fails closed
with an actionable error; it never substitutes a raw ZIP for a real package.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

import yaml

# CLI resolves icons from `_assets/` by filename only. Prefixed paths like
# `_assets/icon.svg` produce: tool icon not found / assets invalid.
_ICON_PATH_PREFIX_RE = re.compile(
    r"^(\s*icon:\s*)(?:['\"]?)_assets/([^'\"\n]+)(?:['\"]?)\s*$",
    re.MULTILINE,
)


class PluginPackagingError(RuntimeError):
    """Raised when source files cannot be packaged as a valid Dify plugin."""


# 0.10.0 on PyPI is broken (imports LLMPollingResult missing from llm.py).
# Keep Studio plugins on the last known-good 0.9.x line.
_DIFY_PLUGIN_REQ_RE = re.compile(r"(?m)^[ \t]*dify-plugin[^\n]*$")
_CURRENT_DIFY_PLUGIN_PIN = "dify-plugin>=0.9.0,<0.10.0"
_BARE_PLUGIN_CTOR_RE = re.compile(r"Plugin\s*\(\s*\)")
_CANONICAL_MAIN_PY = """from dify_plugin import Plugin, DifyPluginEnv

plugin = Plugin(DifyPluginEnv())

if __name__ == "__main__":
    plugin.run()
"""


def _normalize_icon_refs(content: str) -> str:
    """Rewrite ``icon: _assets/foo.svg`` → ``icon: foo.svg`` for CLI packaging."""
    return _ICON_PATH_PREFIX_RE.sub(r"\1\2", content)


def _normalize_requirements(content: str) -> str:
    """Force a known-good ``dify-plugin`` pin; Agent scaffolds often use ``>=0.0.1``."""
    text = content or ""
    if _DIFY_PLUGIN_REQ_RE.search(text):
        return _DIFY_PLUGIN_REQ_RE.sub(_CURRENT_DIFY_PLUGIN_PIN, text)
    stripped = text.strip()
    if not stripped:
        return f"{_CURRENT_DIFY_PLUGIN_PIN}\n"
    return f"{stripped.rstrip()}\n{_CURRENT_DIFY_PLUGIN_PIN}\n"


def _normalize_main_py(content: str) -> str:
    """Ensure entrypoint matches SDK: ``Plugin(DifyPluginEnv())`` (not bare ``Plugin()``)."""
    text = (content or "").strip()
    if "DifyPluginEnv" in text and _BARE_PLUGIN_CTOR_RE.search(text) is None and "plugin.run()" in text:
        return content if content.endswith("\n") else f"{content}\n"
    return _CANONICAL_MAIN_PY


def _ensure_provider_and_tool_wiring(normalized: dict[str, str]) -> None:
    """Fill required ``extra.python.source`` / provider ``tools`` lists Agent often drops."""
    tool_yamls = sorted(
        path
        for path in normalized
        if path.startswith("tools/") and path.endswith((".yaml", ".yml"))
    )
    provider_pys = sorted(
        path for path in normalized if path.startswith("provider/") and path.endswith(".py")
    )

    for path in list(normalized):
        if path.startswith("provider/") and path.endswith((".yaml", ".yml")):
            document = yaml.safe_load(normalized[path]) or {}
            if not isinstance(document, dict):
                continue
            changed = False
            tools = document.get("tools")
            if (not isinstance(tools, list) or not tools) and tool_yamls:
                document["tools"] = tool_yamls
                changed = True
            extra = document.get("extra") if isinstance(document.get("extra"), dict) else {}
            python = extra.get("python") if isinstance(extra.get("python"), dict) else {}
            if not python.get("source"):
                stem = Path(path).stem
                candidate = f"provider/{stem}.py"
                if candidate not in normalized and provider_pys:
                    candidate = provider_pys[0]
                document["extra"] = {"python": {"source": candidate}}
                changed = True
            if changed:
                normalized[path] = yaml.dump(
                    document, default_flow_style=False, allow_unicode=True, sort_keys=False
                )

        if path.startswith("tools/") and path.endswith((".yaml", ".yml")):
            document = yaml.safe_load(normalized[path]) or {}
            if not isinstance(document, dict):
                continue
            extra = document.get("extra") if isinstance(document.get("extra"), dict) else {}
            python = extra.get("python") if isinstance(extra.get("python"), dict) else {}
            if not python.get("source"):
                stem = Path(path).stem
                document["extra"] = {"python": {"source": f"tools/{stem}.py"}}
                normalized[path] = yaml.dump(
                    document, default_flow_style=False, allow_unicode=True, sort_keys=False
                )


def normalize_plugin_source_files(files: dict[str, str]) -> dict[str, str]:
    """Return a copy of plugin files with packaging-safe icon and dependency pins."""
    from services.tool_plugin_generator.schema_normalize import (
        normalize_manifest_yaml_content,
        normalize_provider_yaml_content,
        normalize_tool_yaml_content,
    )

    normalized: dict[str, str] = {}
    for relative_path, content in files.items():
        written = content
        if relative_path.endswith((".yaml", ".yml")):
            written = _normalize_icon_refs(written)
        if relative_path.startswith("tools/") and relative_path.endswith((".yaml", ".yml")):
            written = normalize_tool_yaml_content(written)
        elif relative_path.startswith("provider/") and relative_path.endswith((".yaml", ".yml")):
            written = normalize_provider_yaml_content(written)
        elif relative_path in {"manifest.yaml", "manifest.yml"}:
            written = normalize_manifest_yaml_content(written)
        if relative_path == "requirements.txt":
            written = _normalize_requirements(written)
        if relative_path == "main.py":
            written = _normalize_main_py(written)
        normalized[relative_path] = written
    if "main.py" not in normalized:
        normalized["main.py"] = _CANONICAL_MAIN_PY
    _ensure_provider_and_tool_wiring(normalized)
    return normalized


def _run_plugin_package_cli(files_dir: str) -> bytes:
    plugin_dir = Path(files_dir)
    cli_path_value = os.environ.get("DIFY_PLUGIN_CLI_PATH")
    if not cli_path_value:
        raise PluginPackagingError(
            "DIFY_PLUGIN_CLI_PATH is not configured; install the Dify Plugin CLI "
            "and set this variable to its binary path."
        )

    cli_path = Path(cli_path_value)
    if not cli_path.is_file():
        raise PluginPackagingError(
            f"Dify Plugin CLI binary not found at {cli_path}; install the CLI "
            "and update DIFY_PLUGIN_CLI_PATH."
        )

    try:
        result = subprocess.run(
            [str(cli_path), "plugin", "package", f"./{plugin_dir.name}"],
            cwd=plugin_dir.parent,
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as exc:
        raise PluginPackagingError(f"Failed to start Dify Plugin CLI: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise PluginPackagingError(f"Dify Plugin CLI packaging failed: {detail}")

    package_path = plugin_dir.parent / f"{plugin_dir.name}.difypkg"
    if not package_path.is_file():
        raise PluginPackagingError(f"Dify Plugin CLI did not create the expected package: {package_path.name}")

    return package_path.read_bytes()


def package_plugin_files(files: dict[str, str]) -> bytes:
    """Write a plugin source tree to temporary storage and return its packaged bytes."""
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_dir = Path(temp_dir) / "plugin"
        plugin_dir.mkdir()

        prepared = normalize_plugin_source_files(files)
        for relative_path, content in prepared.items():
            destination = (plugin_dir / relative_path).resolve()
            if not destination.is_relative_to(plugin_dir.resolve()):
                raise PluginPackagingError(f"Plugin file path escapes the package directory: {relative_path}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")

        return _run_plugin_package_cli(str(plugin_dir))
