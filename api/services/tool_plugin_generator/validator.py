from __future__ import annotations

import ast
import re

import yaml

from services.tool_plugin_generator.preview_mapper import sanitize_plugin_id_segment

REQUIRED_PATHS: tuple[str, ...] = (
    "manifest.yaml",
    "main.py",
    "requirements.txt",
    "README.md",
)

# Pattern -> remediation shown to Agent when validation fails.
FORBIDDEN_CODE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("os.system", "do not call os.system"),
    ("subprocess.Popen", "do not spawn subprocesses"),
    ("shutil.rmtree", "do not delete files with shutil.rmtree"),
    (
        "self.fetch_file",
        "file params are File objects — use `.blob` / `.filename`, not self.fetch_file",
    ),
    (
        "self.session.post",
        "self.session is the plugin runtime Session, not HTTP — use httpx or requests",
    ),
    (
        "self.session.get",
        "self.session is the plugin runtime Session, not HTTP — use httpx or requests",
    ),
    (
        "self.session.request",
        "self.session is the plugin runtime Session, not HTTP — use httpx or requests",
    ),
    (
        "create_image_message(blob=",
        "create_image_message accepts a URL string only — return bytes with "
        "create_blob_message(blob=..., meta={'mime_type': 'image/png'})",
    ),
)

# Backward-compatible alias for callers/tests that still import the old name.
FORBIDDEN_PATTERNS: tuple[str, ...] = tuple(pattern for pattern, _ in FORBIDDEN_CODE_PATTERNS)

_TOOL_YAML_RE = re.compile(r"^tools/([^/]+)\.ya?ml$")


class ToolPluginValidationError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_plugin_files(
    files: dict[str, str],
    *,
    author: str | None = None,
    plugin_name: str | None = None,
) -> None:
    errors: list[str] = []

    for required_path in REQUIRED_PATHS:
        if required_path not in files:
            errors.append(f"Missing required file: {required_path}")

    tool_yaml_paths = [path for path in files if _TOOL_YAML_RE.match(path)]
    if not tool_yaml_paths:
        errors.append("Missing required tool YAML under tools/")
    for yaml_path in tool_yaml_paths:
        match = _TOOL_YAML_RE.match(yaml_path)
        if not match:
            continue
        tool_name = match.group(1)
        py_path = f"tools/{tool_name}.py"
        if py_path not in files:
            errors.append(f"Missing required tool Python file: {py_path}")

    for path, content in files.items():
        if path.endswith((".yaml", ".yml")):
            try:
                loaded = yaml.safe_load(content)
            except yaml.YAMLError as exc:
                errors.append(f"Invalid YAML in {path}: {exc}")
                continue
            if not isinstance(loaded, dict):
                errors.append(f"{path}: YAML root must be an object")
                continue
            if path.startswith("tools/"):
                parameters = loaded.get("parameters") or []
                if isinstance(parameters, list):
                    for index, parameter in enumerate(parameters):
                        if not isinstance(parameter, dict):
                            errors.append(f"{path}: parameters[{index}] must be an object")
                            continue
                        if not parameter.get("form"):
                            errors.append(
                                f"{path}: parameters[{index}] ({parameter.get('name')}) missing required field 'form'"
                            )

    for path, content in files.items():
        if not path.endswith(".py"):
            continue
        for pattern, hint in FORBIDDEN_CODE_PATTERNS:
            if pattern in content:
                errors.append(f"Forbidden pattern '{pattern}' found in {path}: {hint}")
        try:
            ast.parse(content)
        except SyntaxError as exc:
            errors.append(f"Invalid Python syntax in {path}: {exc.msg} (line {exc.lineno})")

    if author is not None and plugin_name is not None:
        manifest_content = files.get("manifest.yaml") or files.get("manifest.yml") or ""
        try:
            manifest = yaml.safe_load(manifest_content) or {}
        except yaml.YAMLError:
            manifest = {}
        if isinstance(manifest, dict):
            actual_identity = (
                sanitize_plugin_id_segment(str(manifest.get("author") or "")),
                sanitize_plugin_id_segment(str(manifest.get("name") or "")),
            )
            expected_identity = (
                sanitize_plugin_id_segment(author),
                sanitize_plugin_id_segment(plugin_name),
            )
            if actual_identity != expected_identity:
                errors.append("Manifest identity must match the server-owned studio session identity")

    if errors:
        raise ToolPluginValidationError(errors)
