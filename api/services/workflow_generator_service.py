"""
Workflow generator service.

Thin facade over ``core.workflow.generator.WorkflowGenerator`` that owns the
model-manager / model-instance plumbing. Controllers call this; the pure
domain class never touches the model registry directly.

Pattern mirrors ``LLMGenerator.generate_rule_config`` — see
``core/llm_generator/llm_generator.py`` — but lives in ``services/`` because
the generator output is consumed at the application layer (sync_draft_workflow,
createApp) rather than from inside another workflow.
"""

import logging
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from core.app.app_config.entities import ModelConfig
from core.model_manager import ModelInstance, ModelManager
from core.workflow.generator import WorkflowGenerator
from core.workflow.generator.knowledge_catalogue import (
    KnowledgeCatalogueEntry,
    build_knowledge_catalogue,
    format_knowledge_catalogue,  # noqa: F401 - retained as a stable test patch seam
    installed_dataset_keys,
)
from core.workflow.generator.planner import PlannerPolicy
from core.workflow.generator.planner_context import PlannerContextCheckpoint
from core.workflow.generator.planning_session import UserTurn, begin_user_turn, empty_planning_session
from core.workflow.generator.tool_catalogue import (
    ToolCatalogueEntry,
    build_tool_catalogue,
    format_tool_catalogue,  # noqa: F401 - retained as a stable test patch seam
    installed_tool_keys,
)
from core.workflow.generator.types import (
    WorkflowGenerateResultDict,
    WorkflowGenerationModeRequest,
)
from graphon.model_runtime.entities.model_entities import ModelType

logger = logging.getLogger(__name__)


def _initial_planning_checkpoint(
    instruction: str,
    checkpoint: PlannerContextCheckpoint | None,
    clarification_history: list[dict[str, Any]] | None,
) -> PlannerContextCheckpoint | None:
    """Create the ephemeral UserTurn gate for direct generator requests."""
    if checkpoint is not None or clarification_history:
        return checkpoint
    session = empty_planning_session(uuid4().hex, instruction)
    return begin_user_turn(
        session,
        UserTurn(
            id=uuid4().hex,
            kind="message",
            message=instruction,
            expected_revision=0,
        ),
    )


class WorkflowGeneratorService:
    """
    Coordinates model resolution with the workflow generator domain logic.

    Single public method (``generate_workflow_graph``) keeps the surface area
    minimal — the cmd+k `/create` flow is the only caller today.
    """

    @classmethod
    def generate_workflow_graph(
        cls,
        *,
        tenant_id: str,
        mode: WorkflowGenerationModeRequest,
        instruction: str,
        model_config: ModelConfig,
        ideal_output: str = "",
        current_graph: dict[str, Any] | None = None,
        planner_policy: PlannerPolicy = "assume_defaults",
        clarification_history: list[dict[str, Any]] | None = None,
        context_checkpoint: PlannerContextCheckpoint | None = None,
    ) -> WorkflowGenerateResultDict:
        """
        Resolve a model instance for the tenant and run the generator.

        ``mode`` accepts the ``"auto"`` sentinel — the planner itself picks the
        concrete ``workflow`` / ``advanced-chat`` mode (no extra LLM call) and
        the resolution is echoed back under the result's ``mode`` key.

        ``current_graph`` is the existing draft graph for the cmd+k `/refine`
        flow — when present the generator refines it instead of creating a new
        graph from scratch. ``None`` is the `/create` path.

        Errors from the LLM call (auth, quota, invoke) propagate so the
        controller can map them to existing HTTP error envelopes (same
        envelope as ``/rule-generate``).
        """
        (
            model_instance,
            model_parameters,
            tool_catalogue_text,
            knowledge_catalogue_text,
            tool_entries,
            knowledge_entries,
            tool_catalogue_available,
            knowledge_catalogue_available,
            installed_tools,
            installed_datasets,
        ) = cls._resolve_generation_context(tenant_id=tenant_id, model_config=model_config)

        context_checkpoint = _initial_planning_checkpoint(
            instruction,
            context_checkpoint,
            clarification_history,
        )
        return WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters=model_parameters,
            provider=model_config.provider,
            model_name=model_config.name,
            model_mode=model_config.mode.value,
            mode=mode,
            instruction=instruction,
            ideal_output=ideal_output,
            tool_catalogue_text=tool_catalogue_text,
            knowledge_catalogue_text=knowledge_catalogue_text,
            tool_catalogue_entries=tool_entries,
            knowledge_catalogue_entries=knowledge_entries,
            tool_catalogue_available=tool_catalogue_available,
            knowledge_catalogue_available=knowledge_catalogue_available,
            planner_policy=planner_policy,
            clarification_history=clarification_history,
            context_checkpoint=context_checkpoint,
            installed_tools=installed_tools,
            installed_dataset_ids=installed_datasets,
            current_graph=current_graph,
        )

    @classmethod
    def generate_workflow_graph_stream(
        cls,
        *,
        tenant_id: str,
        mode: WorkflowGenerationModeRequest,
        instruction: str,
        model_config: ModelConfig,
        ideal_output: str = "",
        current_graph: dict[str, Any] | None = None,
        planner_policy: PlannerPolicy = "assume_defaults",
        clarification_history: list[dict[str, Any]] | None = None,
        context_checkpoint: PlannerContextCheckpoint | None = None,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """
        Streaming sibling of ``generate_workflow_graph``.

        Resolves the same model instance / resource catalogues, then delegates to
        ``WorkflowGenerator.generate_workflow_graph_stream`` and yields its
        ``(event_name, payload)`` tuples through to the controller's SSE
        writer. Provider-init / invoke errors raised while resolving the model
        instance propagate to the caller (the controller emits them as a
        single ``result`` SSE event).
        """
        (
            model_instance,
            model_parameters,
            tool_catalogue_text,
            knowledge_catalogue_text,
            tool_entries,
            knowledge_entries,
            tool_catalogue_available,
            knowledge_catalogue_available,
            installed_tools,
            installed_datasets,
        ) = cls._resolve_generation_context(tenant_id=tenant_id, model_config=model_config)

        context_checkpoint = _initial_planning_checkpoint(
            instruction,
            context_checkpoint,
            clarification_history,
        )
        yield from WorkflowGenerator.generate_workflow_graph_stream(
            model_instance=model_instance,
            model_parameters=model_parameters,
            provider=model_config.provider,
            model_name=model_config.name,
            model_mode=model_config.mode.value,
            mode=mode,
            instruction=instruction,
            ideal_output=ideal_output,
            tool_catalogue_text=tool_catalogue_text,
            knowledge_catalogue_text=knowledge_catalogue_text,
            tool_catalogue_entries=tool_entries,
            knowledge_catalogue_entries=knowledge_entries,
            tool_catalogue_available=tool_catalogue_available,
            knowledge_catalogue_available=knowledge_catalogue_available,
            planner_policy=planner_policy,
            clarification_history=clarification_history,
            context_checkpoint=context_checkpoint,
            installed_tools=installed_tools,
            installed_dataset_ids=installed_datasets,
            current_graph=current_graph,
        )

    @classmethod
    def _resolve_generation_context(
        cls,
        *,
        tenant_id: str,
        model_config: ModelConfig,
    ) -> tuple[
        ModelInstance,
        dict[str, Any],
        str,
        str,
        list[ToolCatalogueEntry],
        list[KnowledgeCatalogueEntry],
        bool,
        bool,
        set[tuple[str, str]] | None,
        set[str] | None,
    ]:
        """Resolve the model instance, completion params, and resource catalogues.

        Build the installed-tool catalogue for this tenant so the planner /
        builder can pick concrete tools instead of inventing names, AND so the
        runner's validator can reject hallucinated tool names BEFORE the user
        clicks Apply. A failure here (plugin daemon unreachable, etc.) must not
        block generation — log and fall back to the no-tool path, which also
        disables tool validation in the runner (``None`` sentinel rather than
        empty set, so we don't reject every tool node just because we couldn't
        enumerate the catalogue). The knowledge catalogue follows the same
        best-effort rule — both the formatted text (for prompts) and the
        structured id set (for validation) degrade gracefully.
        """
        model_manager = ModelManager.for_tenant(tenant_id=tenant_id)
        model_instance = model_manager.get_model_instance(
            tenant_id=tenant_id,
            model_type=ModelType.LLM,
            provider=model_config.provider,
            model=model_config.name,
        )

        model_parameters: dict[str, Any] = dict(model_config.completion_params or {})

        tool_catalogue_text = ""
        knowledge_catalogue_text = ""
        installed_tools: set[tuple[str, str]] | None = None
        installed_datasets: set[str] | None = None
        tool_entries: list[ToolCatalogueEntry] = []
        knowledge_entries: list[KnowledgeCatalogueEntry] = []
        tool_catalogue_available = True
        knowledge_catalogue_available = True
        try:
            tool_entries = build_tool_catalogue(tenant_id, limit=None)
            installed_tools = installed_tool_keys(tool_entries)
        except Exception:
            tool_catalogue_available = False
            logger.exception("Workflow generator: failed to build tool catalogue for tenant %s", tenant_id)

        try:
            knowledge_entries = build_knowledge_catalogue(tenant_id, limit=None, raise_on_error=True)
            installed_datasets = installed_dataset_keys(knowledge_entries)
        except Exception:
            knowledge_catalogue_available = False
            logger.exception("Workflow generator: failed to build knowledge catalogue for tenant %s", tenant_id)

        return (
            model_instance,
            model_parameters,
            tool_catalogue_text,
            knowledge_catalogue_text,
            tool_entries,
            knowledge_entries,
            tool_catalogue_available,
            knowledge_catalogue_available,
            installed_tools,
            installed_datasets,
        )
