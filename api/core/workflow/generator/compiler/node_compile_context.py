"""Immutable context shared by deterministic ordinary-node compilers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from core.workflow.generator.resources.model_catalogue import AgentModelCatalogueEntry
from core.workflow.generator.variables.variable_registry import (
    VariableRegistry,
    canonical_registry_type,
)

NodeCompileSurface = Literal["top_level", "container_child"]
NodeCompileMode = Literal["create", "update", "replace"]
SourceTypeResolver = Callable[[tuple[str, ...]], str | None]


@dataclass(frozen=True)
class NodeCompileContext:
    """Read-only inputs required to compile one typed ordinary node.

    Container compilation supplies a full ``VariableRegistry`` so scope and
    producer ordering are checked here. Top-level compilation currently uses
    the graph reference validator plus ``source_type_resolver``; phase 6 can
    replace that resolver with the shared top-level registry without changing
    the node compiler API.
    """

    node_id: str
    surface: NodeCompileSurface
    mode: NodeCompileMode
    old_config: Mapping[str, Any] = field(default_factory=dict)
    variable_registry: VariableRegistry | None = None
    source_type_resolver: SourceTypeResolver | None = None
    model_entries: Sequence[AgentModelCatalogueEntry] | None = None
    installed_dataset_ids: frozenset[str] | None = None
    http_credential_reference_ids: frozenset[str] | None = None
    human_input_delivery_capabilities: frozenset[str] | None = None
    human_input_member_reference_ids: frozenset[str] | None = None

    @property
    def can_resolve_source_types(self) -> bool:
        return self.variable_registry is not None or self.source_type_resolver is not None

    def resolve_source_type(self, selector: tuple[str, ...]) -> str | None:
        if self.variable_registry is not None:
            declaration = self.variable_registry.resolve(
                selector,
                referrer_id=self.node_id,
                expected_type=None,
            )
            return canonical_registry_type(declaration.value_type)
        if self.source_type_resolver is None:
            return None
        value_type = self.source_type_resolver(selector)
        return canonical_registry_type(value_type) if value_type is not None else None


__all__ = [
    "NodeCompileContext",
    "NodeCompileMode",
    "NodeCompileSurface",
    "SourceTypeResolver",
]
