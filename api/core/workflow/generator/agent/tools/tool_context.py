"""Frozen run dependencies and mutable candidate state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.workflow.generator.acceptance.evidence import AcceptanceAttempt, AcceptanceRunner
from core.workflow.generator.compiler.node_builder import BuilderInput
from core.workflow.generator.graph.types import MinimalGraphDict
from core.workflow.generator.model_io.llm_response import LLMJsonClient
from core.workflow.generator.resources.knowledge_catalogue import KnowledgeCatalogueEntry
from core.workflow.generator.resources.model_catalogue import AgentModelCatalogueEntry
from core.workflow.generator.resources.tool_catalogue import ToolCatalogueEntry
from core.workflow.generator.types import WorkflowGenerationMode

if TYPE_CHECKING:
    from core.workflow.generator.compiler.container_types import CompiledChild, ContainerCompileCacheKey

from core.workflow.generator.model_io.budget import ModelCallBudget


@dataclass(frozen=True)
class PendingPlanNode:
    """Same-batch create visible to parallel compiles. Threads must only read it.

    ``iterator_input_type`` is copied from same-reply ``build_iteration`` args so
    Tool compile can type ``item`` the same way ``iteration_scope_declarations`` does.
    """

    id: str
    type: str
    title: str
    purpose: str
    parent: str | None
    provisional_outputs: tuple[str, ...]
    iterator_input_type: str | None = None


@dataclass(frozen=True)
class ToolEnv:
    """Read-only inputs for one agent run.

    Catalogue snapshot contract (shared by search / ``build_node`` /
    ``validate_graph``):

    * ``knowledge_available`` / ``tools_available`` / ``models_available`` are
      False when that side's
      catalogue pull failed. The matching ``installed_*`` MUST then be ``None``,
      which skips core membership for that side rather than rejecting every id.
      Production validation requires resource context and returns
      ``CAPABILITY_UNAVAILABLE`` when the graph needs the unavailable family.
    * An empty ``set()`` means the tenant really has none; unknown ids are
      ``UNKNOWN_DATASET`` / ``UNKNOWN_TOOL``. Empty is not ``None``.

    ``hydrate_graph`` is injected by the service layer. ``None`` is identity.
    Do not import ``hydrate_agent_bindings`` here. ``run_acceptance`` hydrates
    first so Evidence matches the bound graph; ``finish`` hydrate is idempotent.

    ``acceptance_runner`` is optional so existing unit tests keep the
    hydrate+validate finish path. Production chat always injects a runner;
    then ``finish`` requires matching Evidence. ``authorize_live_acceptance``
    reserves one graph-bound execution durably; missing or consumed grants deny it.

    ``contract_rollout_stage`` is a service-owned snapshot. Core uses it only
    to keep edit contracts disabled until that rollout phase is reached.
    """

    tenant_id: str
    mode: WorkflowGenerationMode
    tool_entries: list[ToolCatalogueEntry]
    knowledge_entries: list[KnowledgeCatalogueEntry]
    installed_tools: set[tuple[str, str]] | None
    installed_dataset_ids: set[str] | None
    knowledge_available: bool
    tools_available: bool
    builder_input: BuilderInput
    llm_client: LLMJsonClient
    agent_model_entries: tuple[AgentModelCatalogueEntry, ...]
    models_available: bool
    hydrate_graph: Callable[[MinimalGraphDict], MinimalGraphDict] | None = None
    acceptance_runner: AcceptanceRunner | None = None
    authorize_live_acceptance: Callable[[int, str], bool] | None = None
    environment_variables: set[str] | None = None
    conversation_variables: set[str] | None = None
    require_resource_context: bool = False
    run_id: str | None = None
    run_epoch: int | None = None
    contract_rollout_stage: str = "default"


@dataclass
class ToolTurnState:
    """Mutable candidate state for one agent run.

    ``graph`` is rebound by graph-mutating tools. ``last_mutation_changed`` is
    sticky across queries and no-ops; ``note_graph_mutation`` sets it when a
    non-finish tool returns ``changed=true``. Validate consumes it for
    ``repeated_after_repair``, then clears it. Finish hydrates and validates
    itself and must not go through that dispatch path, or the next validate
    would look like a repeated repair. ``model_call_budget`` is installed only
    for the lifetime of ``iter_agent_events`` so direct tool compilation stays
    deterministic and main-agent, compactor, and nested Builder calls consume
    the same logical-call allowance.
    """

    graph: MinimalGraphDict
    candidate_revision: int = 0
    last_validation_revision: int | None = None
    last_error_signature: tuple[str, ...] | None = None
    last_mutation_changed: bool = False
    attempts: dict[str, AcceptanceAttempt] = field(default_factory=dict)
    graph_hash: str | None = None
    pending_plan_nodes: tuple[PendingPlanNode, ...] = ()
    compile_cache: dict[ContainerCompileCacheKey, CompiledChild] = field(default_factory=dict)
    model_call_budget: ModelCallBudget | None = field(default=None, repr=False)
    contract_protocol_version: int | None = None
    workflow_contract: dict[str, object] | None = None
    contract_revision: int = 0
    contract_hash: str | None = None
    candidate_base_hash: str | None = None
    user_turn_evidence: Mapping[str, str] = field(default_factory=dict)


@dataclass
class ToolContext:
    """Everything a tool may touch during one agent run.

    ``env`` is the frozen snapshot for the run. ``state`` is the candidate
    graph and revision-bound flags that mutating tools rebind.
    """

    env: ToolEnv
    state: ToolTurnState
