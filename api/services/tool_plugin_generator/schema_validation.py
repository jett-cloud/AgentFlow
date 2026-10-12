"""Versioned structural schemas for Dify tool-plugin YAML documents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SCHEMA_VERSION = "tool-plugin-v1"


class _ExtensibleModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ManifestDocument(_ExtensibleModel):
    version: str = Field(min_length=1)
    author: str = Field(min_length=1)
    name: str = Field(min_length=1)
    type: Literal["plugin"] | None = None
    privacy: str | None = None
    icon: str | None = None
    label: dict[str, str] | None = None
    description: dict[str, str] | None = None
    resource: ResourceDocument | None = None
    plugins: dict[str, Any] | None = None
    meta: MetaDocument | None = None

    @field_validator("label", "description")
    @classmethod
    def require_english_text(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is not None and not value.get("en_US"):
            raise ValueError("en_US translation is required")
        return value


class IdentityDocument(_ExtensibleModel):
    name: str = Field(min_length=1)
    author: str | None = None
    label: dict[str, str] | None = None
    description: dict[str, str] | None = None
    icon: str | None = None

    @field_validator("label", "description")
    @classmethod
    def require_english_text(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is not None and not value.get("en_US"):
            raise ValueError("en_US translation is required")
        return value


class ToolPermission(_ExtensibleModel):
    enabled: bool


class PermissionDocument(_ExtensibleModel):
    tool: ToolPermission | None = None


class ResourceDocument(_ExtensibleModel):
    memory: int = Field(gt=0)
    permission: PermissionDocument | None = None


class RunnerDocument(_ExtensibleModel):
    language: Literal["python"]
    version: str = Field(min_length=1)
    entrypoint: str = Field(min_length=1)


class MetaDocument(_ExtensibleModel):
    version: str = Field(min_length=1)
    arch: list[Literal["amd64", "arm64"]] = Field(min_length=1)
    runner: RunnerDocument


class PythonSource(_ExtensibleModel):
    source: str = Field(min_length=1)


class ExtraDocument(_ExtensibleModel):
    python: PythonSource


class CredentialDocument(_ExtensibleModel):
    type: Literal["secret-input", "text-input", "select", "radio", "checkbox"]
    required: bool | None = None
    label: dict[str, str] | None = None


class ProviderDocument(_ExtensibleModel):
    identity: IdentityDocument
    tools: list[str] = Field(default_factory=list)
    credentials_for_provider: dict[str, CredentialDocument] = Field(default_factory=dict)
    extra: ExtraDocument | None = None


class ToolParameterDocument(_ExtensibleModel):
    name: str = Field(min_length=1)
    type: Literal["string", "number", "boolean", "select", "file", "files", "system-files"]
    required: bool | None = None
    form: Literal["llm", "form"]


class ToolDescription(_ExtensibleModel):
    human: dict[str, str] | None = None
    llm: str | None = None

    @field_validator("human")
    @classmethod
    def require_english_text(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is not None and not value.get("en_US"):
            raise ValueError("en_US translation is required")
        return value


class ToolDocument(_ExtensibleModel):
    identity: IdentityDocument
    description: ToolDescription | None = None
    parameters: list[ToolParameterDocument] = Field(default_factory=list)
    extra: ExtraDocument | None = None

    @field_validator("parameters")
    @classmethod
    def unique_parameter_names(cls, value: list[ToolParameterDocument]) -> list[ToolParameterDocument]:
        names = [item.name for item in value]
        if len(names) != len(set(names)):
            raise ValueError("parameter names must be unique")
        return value


ManifestDocument.model_rebuild()


@dataclass(frozen=True)
class SchemaIssue:
    path: str
    location: str
    message: str
    error_type: str


def validate_yaml_document(path: str, content: str) -> tuple[BaseModel | None, list[SchemaIssue]]:
    """Parse and validate one recognized YAML document without stopping other checks."""
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError:
        return None, []  # The legacy parser reports line-aware YAML errors.
    if not isinstance(document, dict):
        return None, []

    model: type[BaseModel] | None
    if path in {"manifest.yaml", "manifest.yml"}:
        model = ManifestDocument
    elif path.startswith("provider/") and path.endswith((".yaml", ".yml")):
        model = ProviderDocument
    elif path.startswith("tools/") and path.endswith((".yaml", ".yml")):
        model = ToolDocument
    else:
        model = None
    if model is None:
        return None, []
    try:
        return model.model_validate(document), []
    except ValidationError as exc:
        issues = []
        for error in exc.errors(include_url=False):
            location = ".".join(str(part) for part in error["loc"])
            issues.append(
                SchemaIssue(
                    path=path,
                    location=location,
                    message=str(error["msg"]),
                    error_type=str(error["type"]),
                )
            )
        return None, issues
