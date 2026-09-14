"""Typed intent for the dedicated Agent V2 builder.

The main Agent submits model, instruction, inputs, outputs, and exact
catalogue bindings. It never submits Soul config, binding ids, or a sibling
knowledge-retrieval node. ``knowledge=None`` means preserve on update.
"""

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.workflow.generator.compiler.intents.node_intent import AgentKnowledgeIntent, NodeOutputIntent
from core.workflow.generator.compiler.intents.tool_intent import ToolBinding


class AgentModelIntent(BaseModel):
    provider: str
    name: str
    mode: str = "chat"
    completion_params: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("provider", "name")
    @classmethod
    def _non_empty_model_field(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("model provider and name must be non-empty")
        return value


class AgentInputIntent(BaseModel):
    source: tuple[str, ...]
    role: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("source")
    @classmethod
    def _non_empty_source(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) < 2:
            raise ValueError("source requires a node id and output path")
        if any(not item.strip() for item in value):
            raise ValueError("source parts must be non-empty")
        return tuple(item.strip() for item in value)

    @field_validator("role")
    @classmethod
    def _non_empty_role(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("role must be non-empty")
        return value


class AgentBindingManifest(BaseModel):
    binding_id: str
    tool_keys: tuple[tuple[str, str], ...]
    dataset_ids: tuple[str, ...]

    model_config = ConfigDict(frozen=True, extra="forbid")


class AgentNodeBuildIntent(BaseModel):
    model: AgentModelIntent
    instruction: str
    inputs: list[AgentInputIntent]
    outputs: list[NodeOutputIntent]
    tools: list[ToolBinding] = Field(default_factory=list)
    mcp_tools: list[ToolBinding] = Field(default_factory=list)
    knowledge: AgentKnowledgeIntent | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("instruction")
    @classmethod
    def _non_empty_instruction(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("instruction must be non-empty")
        return value

    @model_validator(mode="after")
    def _unique_bindings(self) -> Self:
        keys = [(binding.provider_name, binding.tool_name) for binding in (*self.tools, *self.mcp_tools)]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate exact tool binding")
        return self
