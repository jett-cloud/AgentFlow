"""Single-source request contracts for specialized Workflow Assist builders."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.workflow.generator.compiler.intents.agent_intent import AgentInputIntent, AgentModelIntent
from core.workflow.generator.compiler.intents.container_intent import (
    ContainerChildIntent,
    ContainerEdgeIntent,
    LoopBreakConditionIntent,
    LoopVariableIntent,
)
from core.workflow.generator.compiler.intents.node_intent import AgentKnowledgeIntent, NodeOutputIntent
from core.workflow.generator.compiler.intents.tool_intent import ToolArgument, ToolBinding

_ANY_JSON_SCHEMA: dict[str, object] = {
    "oneOf": [
        {"type": "string"},
        {"type": "number"},
        {"type": "integer"},
        {"type": "boolean"},
        {"type": "null"},
        {"type": "array"},
        {"type": "object"},
    ]
}


class _BuildArgs(BaseModel):
    mode: Literal["create", "update", "replace"]
    id: str
    title: str | None = None
    parent: str | None = None

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"mode": {"const": "create"}}, "required": ["mode"]},
                    "then": {"required": ["title"]},
                }
            ]
        },
    )

    @field_validator("id")
    @classmethod
    def _non_empty_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("id is required")
        return normalized

    @model_validator(mode="after")
    def _create_requires_title(self) -> Self:
        if self.mode == "create" and not (self.title or "").strip():
            raise ValueError("title is required when creating a node")
        return self


class BuildToolNodeArgs(_BuildArgs):
    tool: ToolBinding
    arguments: dict[str, ToolArgument]


class BuildAgentNodeArgs(_BuildArgs):
    model: AgentModelIntent
    instruction: str
    inputs: list[AgentInputIntent]
    outputs: list[NodeOutputIntent]
    tools: list[ToolBinding] = Field(default_factory=list)
    mcp_tools: list[ToolBinding] = Field(default_factory=list)
    knowledge: AgentKnowledgeIntent | None = None


class BuildLoopArgs(_BuildArgs):
    loop_count: int = Field(ge=1, le=100)
    loop_variables: list[LoopVariableIntent]
    children: list[ContainerChildIntent]
    edges: list[ContainerEdgeIntent]
    break_conditions: list[LoopBreakConditionIntent]
    outputs: list[NodeOutputIntent]
    logical_operator: Literal["and", "or"]


class BuildIterationArgs(_BuildArgs):
    iterator_selector: tuple[str, ...]
    iterator_input_type: str
    output_selector: tuple[str, ...]
    children: list[ContainerChildIntent]
    edges: list[ContainerEdgeIntent]
    outputs: list[NodeOutputIntent]
    is_parallel: bool
    parallel_nums: int = Field(ge=1, le=10)
    error_handle_mode: str
    flatten_output: bool


def parameters_schema(model: type[BaseModel]) -> dict[str, object]:
    """Return a model-facing schema while retaining refs only for recursive values."""
    schema = model.model_json_schema(mode="validation")
    definitions = schema.get("$defs")
    resolved = _resolve_schema(schema, definitions if isinstance(definitions, dict) else {}, ())
    resolved.pop("title", None)
    return resolved


def _resolve_schema(
    value: object,
    definitions: dict[str, Any],
    resolving: tuple[str, ...],
) -> Any:
    if isinstance(value, list):
        return [_resolve_schema(item, definitions, resolving) for item in value]
    if not isinstance(value, dict):
        return value
    if not value:
        return deepcopy(_ANY_JSON_SCHEMA)

    ref = value.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        name = ref.removeprefix("#/$defs/")
        if name not in resolving and isinstance(definitions.get(name), dict):
            merged = deepcopy(definitions[name])
            merged.update({key: item for key, item in value.items() if key != "$ref"})
            return _resolve_schema(merged, definitions, (*resolving, name))

    result: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = "oneOf" if key == "anyOf" else key
        if key == "discriminator" and isinstance(item, dict):
            property_name = item.get("propertyName")
            if property_name:
                result[key] = {"propertyName": property_name}
            continue
        result[normalized_key] = _resolve_schema(item, definitions, resolving)
    if not result or set(result) == {"title"}:
        arbitrary = deepcopy(_ANY_JSON_SCHEMA)
        if "title" in result:
            arbitrary["title"] = result["title"]
        return arbitrary
    return result
