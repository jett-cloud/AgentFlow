"""Run environment and turn state for workflow-agent tools.

Handlers and the loop access ``context.env`` and ``context.state`` explicitly.
``ToolEnv`` is frozen for the run; tests that need a different catalogue or
client replace the whole env. ``ToolTurnState`` is rebound by mutating tools.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from core.workflow.generator.agent.evidence import AcceptanceAttempt, AcceptanceRunner
from core.workflow.generator.agent.types import MinimalGraphDict
from core.workflow.generator.knowledge_catalogue import KnowledgeCatalogueEntry
from core.workflow.generator.llm_response import LLMJsonClient
from core.workflow.generator.node_builder import BuilderInput
from core.workflow.generator.tool_catalogue import ToolCatalogueEntry
from core.workflow.generator.types import WorkflowGenerationMode


@dataclass(frozen=True)
class ToolEnv:
    """Read-only inputs for one agent run.

    Catalogue snapshot contract (shared by search / ``build_node`` /
    ``validate_graph``):

    * ``knowledge_available`` / ``tools_available`` are False when that side's
      catalogue pull failed. The matching ``installed_*`` MUST then be ``None``,
      which skips membership for that side — it does not reject every id, and
      it is not ``CAPABILITY_UNAVAILABLE``.
    * An empty ``set()`` means the tenant really has none; unknown ids are
      ``UNKNOWN_DATASET`` / ``UNKNOWN_TOOL``. Empty is not ``None``.

    ``hydrate_graph`` is injected by the service layer. ``None`` is identity.
    Do not import ``hydrate_agent_bindings`` here.

    ``acceptance_runner`` is optional so existing unit tests keep the
    hydrate+validate finish path. Production chat always injects a runner;
    then ``finish`` requires matching Evidence. ``live_run_authorized`` is
    request-scoped and never implied by a later ordinary user message.
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
    hydrate_graph: Callable[[MinimalGraphDict], MinimalGraphDict] | None = None
    acceptance_runner: AcceptanceRunner | None = None
    live_run_authorized: bool = False


@dataclass
class ToolTurnState:
    """Mutable candidate state for one agent run.

    ``graph`` is rebound by graph-mutating tools. ``last_mutation_changed`` is
    sticky across queries and no-ops; ``note_graph_mutation`` sets it when a
    non-finish tool returns ``changed=true``. Validate consumes it for
    ``repeated_after_repair``, then clears it. Finish hydrates and validates
    itself and must not go through that dispatch path, or the next validate
    would look like a repeated repair.
    """

    graph: MinimalGraphDict
    candidate_revision: int = 0
    last_validation_revision: int | None = None
    last_error_signature: tuple[str, ...] | None = None
    last_mutation_changed: bool = False
    attempts: dict[str, AcceptanceAttempt] = field(default_factory=dict)
    graph_hash: str | None = None


@dataclass
class ToolContext:
    """Everything a tool may touch during one agent run.

    ``env`` is the frozen snapshot for the run. ``state`` is the candidate
    graph and revision-bound flags that mutating tools rebind.
    """

    env: ToolEnv
    state: ToolTurnState
