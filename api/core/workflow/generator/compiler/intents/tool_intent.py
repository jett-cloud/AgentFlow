"""Tool-node intent: bindings, argument variants, and dedicated build intent.

``node_intent`` re-exports these models so existing imports keep working.
This module must not import ``node_intent`` (that would cycle).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.workflow.generator.resources.tool_catalogue import JsonValue


class ToolBinding(BaseModel):
    provider_name: str
    tool_name: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("provider_name", "tool_name")
    @classmethod
    def _non_empty_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("binding names must be non-empty")
        return value


class VariableToolArgument(BaseModel):
    kind: Literal["variable"]
    selector: tuple[str, ...]

    model_config = ConfigDict(extra="forbid")

    @field_validator("selector")
    @classmethod
    def _non_empty_selector(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) < 2:
            raise ValueError("selector requires a node id and output path")
        if any(not item.strip() for item in value):
            raise ValueError("selector parts must be non-empty")
        return tuple(item.strip() for item in value)


class TemplateToolArgument(BaseModel):
    kind: Literal["template"]
    text: str

    model_config = ConfigDict(extra="forbid")


class ConstantToolArgument(BaseModel):
    kind: Literal["constant"]
    value: JsonValue

    model_config = ConfigDict(extra="forbid")


ToolArgument = Annotated[
    VariableToolArgument | TemplateToolArgument | ConstantToolArgument,
    Field(discriminator="kind"),
]


class ToolInvocationIntent(BaseModel):
    binding: ToolBinding
    arguments: dict[str, ToolArgument] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class ToolNodeBuildIntent(BaseModel):
    binding: ToolBinding
    arguments: dict[str, ToolArgument] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")
