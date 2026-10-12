"""Structured, aggregate checks for canonical tool-plugin source."""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal

import yaml
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from services.tool_plugin_generator.dependency_resolver import resolve_requirements
from services.tool_plugin_generator.schema_validation import SCHEMA_VERSION, validate_yaml_document
from services.tool_plugin_generator.sdk_contract import load_sdk_contract
from services.tool_plugin_generator.validator import ToolPluginValidationError, collect_plugin_file_issues

Severity = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class BuildDiagnostic:
    stage: str
    code: str
    severity: Severity
    message: str
    path: str | None = None
    line: int | None = None
    column: int | None = None
    suggestion: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class PreflightReport:
    diagnostics: tuple[BuildDiagnostic, ...]

    @property
    def errors(self) -> tuple[BuildDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == "error")

    @property
    def ok(self) -> bool:
        return not self.errors


class ToolPluginPreflightError(ToolPluginValidationError):
    def __init__(
        self,
        diagnostics: list[BuildDiagnostic],
        *,
        draft_digest: str | None = None,
        canonical_digest: str | None = None,
    ) -> None:
        self.diagnostics = tuple(diagnostics)
        self.draft_digest = draft_digest
        self.canonical_digest = canonical_digest
        super().__init__([item.message for item in diagnostics if item.severity == "error"])

    def build_trace(self) -> dict[str, Any] | None:
        if not self.draft_digest or not self.canonical_digest:
            return None
        return {
            "draft_digest": self.draft_digest,
            "canonical_digest": self.canonical_digest,
            "completed_stages": ["canonicalize", "preflight"],
        }


def _legacy_validation_diagnostics(
    files: dict[str, str], *, author: str | None, plugin_name: str | None
) -> list[BuildDiagnostic]:
    return [
        BuildDiagnostic(
            stage="static",
            code=issue.code,
            severity="error",
            message=issue.message,
            path=issue.path,
            line=issue.line,
        )
        for issue in collect_plugin_file_issues(files, author=author, plugin_name=plugin_name)
    ]


def _manifest_diagnostics(files: Mapping[str, str]) -> list[BuildDiagnostic]:
    path = "manifest.yaml" if "manifest.yaml" in files else "manifest.yml"
    content = files.get(path)
    if content is None:
        return []
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError:
        return []  # The legacy YAML validator reports the parse failure.
    if not isinstance(document, dict):
        return []

    diagnostics: list[BuildDiagnostic] = []
    plugin_type = document.get("type")
    if plugin_type is not None and plugin_type != "plugin":
        diagnostics.append(
            BuildDiagnostic(
                stage="yaml_schema",
                code="INVALID_MANIFEST_TYPE",
                severity="error",
                path=path,
                message=f"{path}: type must be 'plugin'",
            )
        )
    created_at = document.get("created_at")
    if created_at is not None:
        value = created_at.isoformat() if isinstance(created_at, datetime) else str(created_at)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value) is None:
            diagnostics.append(
                BuildDiagnostic(
                    stage="yaml_schema",
                    code="INVALID_MANIFEST_TIMESTAMP",
                    severity="error",
                    path=path,
                    message=f"{path}: created_at must use RFC3339 format (for example 2025-01-01T00:00:00Z)",
                    suggestion="Quote the timestamp and use T between date/time plus Z or an explicit UTC offset.",
                )
            )

    privacy = document.get("privacy")
    if isinstance(privacy, str) and privacy.strip() and privacy.strip() not in files:
        diagnostics.append(
            BuildDiagnostic(
                stage="cross_file",
                code="MISSING_REFERENCED_FILE",
                severity="error",
                path=path,
                message=f"{path}: privacy references missing file {privacy.strip()}",
                suggestion="Add the referenced privacy file or remove the manifest field.",
                details={"referenced_path": privacy.strip()},
            )
        )

    plugins = document.get("plugins")
    tool_providers = plugins.get("tools") if isinstance(plugins, dict) else None
    if isinstance(tool_providers, list):
        for referenced_path in tool_providers:
            if isinstance(referenced_path, str) and referenced_path.strip() not in files:
                diagnostics.append(
                    BuildDiagnostic(
                        stage="cross_file",
                        code="MISSING_REFERENCED_FILE",
                        severity="error",
                        path=path,
                        message=f"{path}: plugins.tools references missing file {referenced_path.strip()}",
                        suggestion="Add the provider YAML file or correct plugins.tools.",
                        details={"referenced_path": referenced_path.strip(), "field": "plugins.tools"},
                    )
                )

    meta = document.get("meta")
    runner = meta.get("runner") if isinstance(meta, dict) else None
    entrypoint = runner.get("entrypoint") if isinstance(runner, dict) else None
    if isinstance(entrypoint, str) and entrypoint.strip():
        entrypoint_path = entrypoint.strip()
        if not entrypoint_path.endswith(".py"):
            entrypoint_path = f"{entrypoint_path}.py"
        if entrypoint_path not in files:
            diagnostics.append(
                BuildDiagnostic(
                    stage="cross_file",
                    code="MISSING_REFERENCED_FILE",
                    severity="error",
                    path=path,
                    message=f"{path}: runner entrypoint references missing file {entrypoint_path}",
                    suggestion="Add the Python entrypoint or correct meta.runner.entrypoint.",
                    details={"referenced_path": entrypoint_path, "field": "meta.runner.entrypoint"},
                )
            )
    return diagnostics


def _yaml_schema_diagnostics(files: Mapping[str, str]) -> list[BuildDiagnostic]:
    diagnostics: list[BuildDiagnostic] = []
    for path, content in files.items():
        if not path.endswith((".yaml", ".yml")):
            continue
        _, issues = validate_yaml_document(path, content)
        diagnostics.extend(
            BuildDiagnostic(
                stage="yaml_schema",
                code="YAML_SCHEMA_VIOLATION",
                severity="error",
                path=issue.path,
                message=f"{issue.path}: {issue.location}: {issue.message}",
                suggestion="Correct the field to match the versioned tool-plugin schema.",
                details={
                    "schema_version": SCHEMA_VERSION,
                    "location": issue.location,
                    "error_type": issue.error_type,
                },
            )
            for issue in issues
        )
    return diagnostics


def _referenced_asset_path(value: str) -> str:
    normalized = value.strip()
    return normalized if "/" in normalized else f"_assets/{normalized}"


def _cross_file_diagnostics(files: Mapping[str, str]) -> list[BuildDiagnostic]:
    diagnostics: list[BuildDiagnostic] = []
    provider_tool_refs: dict[str, list[str]] = {}
    actual_tool_paths = {
        path for path in files if path.startswith("tools/") and path.endswith((".yaml", ".yml"))
    }
    for path, content in files.items():
        if not path.endswith((".yaml", ".yml")):
            continue
        try:
            document = yaml.safe_load(content)
        except yaml.YAMLError:
            continue
        if not isinstance(document, dict):
            continue

        identity = document.get("identity")
        icon = identity.get("icon") if isinstance(identity, dict) else None
        if path in {"manifest.yaml", "manifest.yml"}:
            icon = document.get("icon")
        if isinstance(icon, str) and icon.strip():
            asset_path = _referenced_asset_path(icon)
            if asset_path not in files:
                diagnostics.append(
                    BuildDiagnostic(
                        stage="cross_file",
                        code="MISSING_REFERENCED_FILE",
                        severity="error",
                        path=path,
                        message=f"{path}: icon references missing file {asset_path}",
                        suggestion="Add the icon under _assets/ or correct the icon field.",
                        details={"referenced_path": asset_path, "field": "icon"},
                    )
                )

        extra = document.get("extra")
        python = extra.get("python") if isinstance(extra, dict) else None
        source = python.get("source") if isinstance(python, dict) else None
        if isinstance(source, str) and source.strip() and source.strip() not in files:
            diagnostics.append(
                BuildDiagnostic(
                    stage="cross_file",
                    code="MISSING_REFERENCED_FILE",
                    severity="error",
                    path=path,
                    message=f"{path}: extra.python.source references missing file {source.strip()}",
                    suggestion="Add the referenced Python source or correct extra.python.source.",
                    details={"referenced_path": source.strip(), "field": "extra.python.source"},
                )
            )
        elif isinstance(source, str) and source.strip() and source.strip().endswith(".py"):
            source_path = source.strip()
            try:
                tree = ast.parse(files[source_path])
            except SyntaxError:
                tree = None
            expected_base = "ToolProvider" if path.startswith("provider/") else "Tool"
            if tree is not None and path.startswith(("provider/", "tools/")):
                matching_classes = [
                    node
                    for node in tree.body
                    if isinstance(node, ast.ClassDef)
                    and any(
                        (isinstance(base, ast.Name) and base.id == expected_base)
                        or (isinstance(base, ast.Attribute) and base.attr == expected_base)
                        for base in node.bases
                    )
                ]
                if len(matching_classes) != 1:
                    diagnostics.append(
                        BuildDiagnostic(
                            stage="cross_file",
                            code="INVALID_SOURCE_CLASS_COUNT",
                            severity="error",
                            path=source_path,
                            message=(
                                f"{source_path}: expected exactly one class inheriting "
                                f"{expected_base}, found {len(matching_classes)}"
                            ),
                            suggestion=f"Define exactly one {expected_base} implementation in the referenced source.",
                            details={"expected_base": expected_base, "count": len(matching_classes)},
                        )
                    )

        if path.startswith("provider/"):
            tools = document.get("tools")
            if isinstance(tools, list):
                for tool_path in tools:
                    if not isinstance(tool_path, str):
                        continue
                    provider_tool_refs.setdefault(tool_path, []).append(path)
                    if tool_path not in files:
                        diagnostics.append(
                            BuildDiagnostic(
                                stage="cross_file",
                                code="MISSING_REFERENCED_FILE",
                                severity="error",
                                path=path,
                                message=f"{path}: tools references missing file {tool_path}",
                                suggestion="Add the tool YAML or remove the stale provider reference.",
                                details={"referenced_path": tool_path, "field": "tools"},
                            )
                        )

    for tool_path in sorted(actual_tool_paths - provider_tool_refs.keys()):
        if not any(path.startswith("provider/") for path in files):
            break
        diagnostics.append(
            BuildDiagnostic(
                stage="cross_file",
                code="UNREFERENCED_TOOL",
                severity="error",
                path=tool_path,
                message=f"{tool_path}: no provider YAML references this tool",
                suggestion="Add the tool path to exactly one provider tools list.",
            )
        )
    for tool_path, providers in sorted(provider_tool_refs.items()):
        if len(providers) > 1:
            diagnostics.append(
                BuildDiagnostic(
                    stage="cross_file",
                    code="DUPLICATE_TOOL_PROVIDER_REFERENCE",
                    severity="error",
                    path=tool_path,
                    message=f"{tool_path}: referenced by multiple providers",
                    suggestion="Reference each tool YAML from exactly one provider.",
                    details={"providers": providers},
                )
            )
    return diagnostics


def _sdk_contract_diagnostics(files: Mapping[str, str]) -> list[BuildDiagnostic]:
    diagnostics: list[BuildDiagnostic] = []
    contract = load_sdk_contract()
    runtime_version = os.environ.get("PLUGIN_DAEMON_SDK_VERSION", "").strip()
    if runtime_version and runtime_version != contract.version:
        diagnostics.append(
            BuildDiagnostic(
                stage="sdk_contract",
                code="SDK_CONTRACT_VERSION_MISMATCH",
                severity="error",
                message=(
                    f"Plugin daemon SDK {runtime_version} does not match generated contract "
                    f"{contract.version}"
                ),
                suggestion="Regenerate the SDK contract from the deployed plugin-daemon SDK before publishing.",
                details={
                    "runtime_version": runtime_version,
                    "contract_version": contract.version,
                    "generator_version": contract.generator_version,
                },
            )
        )
    tool_methods = contract.classes.get("dify_plugin.Tool", {}).get("methods", {})
    for path, content in files.items():
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            exports = contract.exports(node.module)
            if exports is None:
                continue
            for alias in node.names:
                if alias.name == "*" or alias.name in exports:
                    continue
                qualified_name = f"{node.module}.{alias.name}"
                diagnostics.append(
                    BuildDiagnostic(
                        stage="sdk_contract",
                        code="SDK_SYMBOL_NOT_FOUND",
                        severity="error",
                        path=path,
                        line=node.lineno,
                        column=node.col_offset + 1,
                        message=(
                            f"{path}:{node.lineno}: {node.module} does not export "
                            f"{alias.name} in {contract.distribution} {contract.version}"
                        ),
                        suggestion=contract.symbol_suggestions.get(
                            qualified_name,
                            "Use a symbol exported by the configured plugin SDK version.",
                        ),
                        details={
                            "module": node.module,
                            "symbol": alias.name,
                            "sdk_version": contract.version,
                            "sdk_requirement": contract.compatible_requirement,
                        },
                    )
                )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "self":
                continue
            method = tool_methods.get(node.func.attr)
            if not isinstance(method, dict):
                continue
            required = [str(item) for item in method.get("required", [])]
            optional = [str(item) for item in method.get("optional", [])]
            allowed = set(required + optional)
            if any(keyword.arg is None for keyword in node.keywords):
                continue
            supplied_keywords = {keyword.arg for keyword in node.keywords if keyword.arg is not None}
            unknown = sorted(supplied_keywords - allowed)
            supplied_positionally = set(required[: len(node.args)])
            missing = sorted(set(required) - supplied_positionally - supplied_keywords)
            if not unknown and not missing:
                continue
            parts = []
            if unknown:
                parts.append(f"unexpected keyword(s): {', '.join(unknown)}")
            if missing:
                parts.append(f"missing required argument(s): {', '.join(missing)}")
            diagnostics.append(
                BuildDiagnostic(
                    stage="sdk_contract",
                    code="SDK_CALL_SIGNATURE_MISMATCH",
                    severity="error",
                    path=path,
                    line=node.lineno,
                    column=node.col_offset + 1,
                    message=f"{path}:{node.lineno}: self.{node.func.attr} has {'; '.join(parts)}",
                    suggestion=(
                        f"Use self.{node.func.attr}({', '.join(required + [name + '=...' for name in optional])})."
                    ),
                    details={
                        "class": "dify_plugin.Tool",
                        "method": node.func.attr,
                        "required": required,
                        "optional": optional,
                    },
                )
            )
    return diagnostics


def _requirements_diagnostics(files: Mapping[str, str]) -> list[BuildDiagnostic]:
    content = files.get("requirements.txt")
    if content is None:
        return []
    diagnostics: list[BuildDiagnostic] = []
    seen: dict[str, list[tuple[int, Requirement]]] = {}
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement as exc:
            diagnostics.append(
                BuildDiagnostic(
                    stage="dependency_resolve",
                    code="INVALID_REQUIREMENT",
                    severity="error",
                    path="requirements.txt",
                    line=line_number,
                    message=f"requirements.txt:{line_number}: invalid requirement: {exc}",
                )
            )
            continue
        if requirement.url is not None:
            diagnostics.append(
                BuildDiagnostic(
                    stage="dependency_resolve",
                    code="UNSAFE_REQUIREMENT_SOURCE",
                    severity="error",
                    path="requirements.txt",
                    line=line_number,
                    message=f"requirements.txt:{line_number}: direct URL requirements are not allowed",
                    suggestion="Use a versioned package from the configured Python package index.",
                )
            )
            continue
        seen.setdefault(canonicalize_name(requirement.name), []).append((line_number, requirement))

    for name, entries in seen.items():
        exact_versions = {
            Version(spec.version)
            for _, requirement in entries
            for spec in requirement.specifier
            if spec.operator == "==" and "*" not in spec.version
        }
        if len(exact_versions) > 1:
            diagnostics.append(
                BuildDiagnostic(
                    stage="dependency_resolve",
                    code="UNSATISFIABLE_REQUIREMENTS",
                    severity="error",
                    path="requirements.txt",
                    line=entries[0][0],
                    message=f"requirements.txt: {name} requires multiple incompatible exact versions",
                    details={"requirements": [str(item) for _, item in entries]},
                )
            )
        elif len(entries) > 1:
            diagnostics.append(
                BuildDiagnostic(
                    stage="dependency_resolve",
                    code="DUPLICATE_REQUIREMENT",
                    severity="warning",
                    path="requirements.txt",
                    line=entries[1][0],
                    message=f"requirements.txt: {name} is declared more than once",
                    suggestion="Merge constraints into one requirement line.",
                )
            )
    return diagnostics


def _uv_resolution_diagnostics(files: Mapping[str, str]) -> list[BuildDiagnostic]:
    content = files.get("requirements.txt")
    if content is None:
        return []
    result = resolve_requirements(content)
    if result.ok:
        return []
    return [
        BuildDiagnostic(
            stage="dependency_resolve",
            code=f"UV_{(result.error_type or 'resolution_failed').upper()}",
            severity="error",
            path="requirements.txt",
            message="requirements.txt: uv could not resolve a compatible dependency set",
            suggestion=(
                "Make package version ranges compatible and ensure binary distributions exist "
                "for Python 3.12/Linux."
            ),
            details={
                "resolver_output": result.message,
                "error_type": result.error_type,
                "elapsed_ms": result.elapsed_ms,
                "cache_hit": result.cache_hit,
            },
        )
    ]


def run_preflight(
    files: dict[str, str],
    *,
    author: str | None = None,
    plugin_name: str | None = None,
    resolve_dependencies: bool = False,
) -> PreflightReport:
    diagnostics = [
        *_legacy_validation_diagnostics(files, author=author, plugin_name=plugin_name),
        *_yaml_schema_diagnostics(files),
        *_manifest_diagnostics(files),
        *_cross_file_diagnostics(files),
        *_requirements_diagnostics(files),
        *(_uv_resolution_diagnostics(files) if resolve_dependencies else []),
        *_sdk_contract_diagnostics(files),
    ]
    return PreflightReport(diagnostics=tuple(diagnostics))
