"""Shared immutable container compilation requests, results, and cache keys."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from core.workflow.generator.compiler.intents.container_intent import (
    IterationBuildIntent,
    LoopBuildIntent,
)
from core.workflow.generator.graph.types import MinimalGraphDict, MinimalGraphNodeDict
from core.workflow.generator.resources.knowledge_catalogue import KnowledgeCatalogueEntry
from core.workflow.generator.resources.model_catalogue import AgentModelCatalogueEntry
from core.workflow.generator.resources.tool_catalogue import ToolCatalogueEntry
from core.workflow.generator.types import WorkflowGenerationMode
from core.workflow.generator.variables.variable_registry import (
    VariableRegistry,
)


class ContainerCompileError(ValueError):
    """Semantic failure while compiling a container; the candidate graph stays unchanged."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        path: str,
        child_ref: str | None = None,
        cause: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.path = path
        self.child_ref = child_ref
        self.cause = dict(cause) if cause is not None else {"error_code": code, "error": detail}


@dataclass(frozen=True)
class ContainerCompileCacheKey:
    container_id: str
    child_ref: str
    resolved_node_id: str
    intent_hash: str
    resource_snapshot_hash: str
    upstream_signature: str


@dataclass(frozen=True)
class CompiledChild:
    ref: str
    node: MinimalGraphNodeDict


type ContainerCompileCache = dict[ContainerCompileCacheKey, CompiledChild]


@dataclass(frozen=True)
class ContainerCompileRequest:
    kind: Literal["loop", "iteration"]
    container_id: str
    intent: LoopBuildIntent | IterationBuildIntent
    frozen_graph: MinimalGraphDict
    base_revision: int
    existing_child_ids: Mapping[str, str]
    tool_entries: Sequence[ToolCatalogueEntry]
    knowledge_entries: Sequence[KnowledgeCatalogueEntry]
    installed_tools: set[tuple[str, str]] | None
    generation_mode: WorkflowGenerationMode
    model_entries: Sequence[AgentModelCatalogueEntry] | None = None
    installed_dataset_ids: frozenset[str] | None = None
    http_credential_reference_ids: frozenset[str] | None = None
    human_input_delivery_capabilities: frozenset[str] | None = None
    human_input_member_reference_ids: frozenset[str] | None = None
    conversation_variable_types: Mapping[str, str] | None = None
    writable_conversation_variables: frozenset[str] | None = None
    title: str = ""
    compile_cache: ContainerCompileCache | None = None
    resource_snapshot_hash: str = ""


@dataclass(frozen=True)
class ChildCompileContext:
    container_id: str
    ref_map: Mapping[str, str]
    registry: VariableRegistry
    tool_entries: Sequence[ToolCatalogueEntry]
    knowledge_entries: Sequence[KnowledgeCatalogueEntry]
    layer_by_ref: Mapping[str, int]
    in_iteration: bool = False
    model_entries: Sequence[AgentModelCatalogueEntry] | None = None
    installed_dataset_ids: frozenset[str] | None = None
    http_credential_reference_ids: frozenset[str] | None = None
    human_input_delivery_capabilities: frozenset[str] | None = None
    human_input_member_reference_ids: frozenset[str] | None = None


@dataclass(frozen=True)
class CompiledContainer:
    graph: MinimalGraphDict
    base_revision: int
