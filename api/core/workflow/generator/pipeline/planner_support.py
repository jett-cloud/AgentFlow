"""Planner requests, outcomes, limits, schema checks, and resource-resolution helpers."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from core.workflow.generator.model_io.llm_response import (
    StageError,
    StageSchemaError,
)
from core.workflow.generator.pipeline.planner_actions import (
    RequestUserInputAction,
)
from core.workflow.generator.pipeline.planner_context import PlannerContextSession
from core.workflow.generator.pipeline.planner_context_values import PlannerContextCheckpoint, PlannerObservation
from core.workflow.generator.pipeline.planning_types import UserTurn
from core.workflow.generator.resources.knowledge_catalogue import KnowledgeCatalogueEntry
from core.workflow.generator.resources.tool_catalogue import ToolCatalogueEntry
from core.workflow.generator.types import (
    PlannerResultDict,
    WorkflowGenerationMode,
    WorkflowGenerationModeRequest,
)
from graphon.enums import BuiltinNodeTypes

logger = logging.getLogger(__name__)


_START_INPUT_TYPES = frozenset(
    {"text-input", "paragraph", "number", "select", "file", "file-list", "checkbox", "json_object"}
)


_MAX_PLANNER_ACTIONS = 24


_MAX_PLANNER_MODEL_SECONDS = 120


_MAX_PLANNER_CONTEXT_MULTIPLIER = 4


_MAX_CLARIFICATION_ROUNDS = 4


_MAX_SERIALIZED_PLAN_BYTES = 64 * 1024


_PLAN_FIELDS = frozenset(
    {"title", "description", "mode", "app_name", "icon", "start_inputs", "resource_requests", "nodes", "edges"}
)


_PLAN_NODE_FIELDS = frozenset({"id", "label", "node_type", "purpose", "parent", "action"})


_PLAN_EDGE_FIELDS = frozenset({"source", "target", "source_handle"})


PlannerPolicy = Literal["interactive", "assume_defaults"]


class PlannerNoProgressError(StageError):
    """Raised when the model repeats the exact same action without progress."""

    def __init__(self, detail: str = "Planner repeated an identical action without making progress") -> None:
        super().__init__("Planner", detail)


class PlannerBudgetExhaustedError(StageError):
    """Raised when a planning goal exhausts a persistent watchdog budget."""

    def __init__(self, detail: str) -> None:
        super().__init__("Planner", f"Planner budget exhausted: {detail}")


class PlannerActionLimitError(PlannerBudgetExhaustedError):
    """Backward-compatible alias for callers that handled the old action limit."""

    def __init__(self) -> None:
        super().__init__(f"{_MAX_PLANNER_ACTIONS} model actions")


class PlannerClarificationLimitError(StageError):
    """Raised when a goal asks for more user clarification than allowed."""

    def __init__(self) -> None:
        super().__init__("Planner", f"Planner reached the {_MAX_CLARIFICATION_ROUNDS} clarification rounds limit")


class PlannerPolicyDeniedError(StageError):
    """Raised when a policy denial cannot be corrected within the current turn."""

    def __init__(self, detail: str) -> None:
        super().__init__("Planner", f"Planner policy denied action: {detail}")


@dataclass(frozen=True)
class PlannerPlanOutcome:
    plan: PlannerResultDict
    assumptions: tuple[str, ...] = ()
    context_checkpoint: PlannerContextCheckpoint | None = None


@dataclass(frozen=True)
class PlannerClarificationOutcome:
    clarification_id: str
    questions: tuple[dict[str, Any], ...]
    context_checkpoint: PlannerContextCheckpoint
    message: str = ""


@dataclass(frozen=True)
class PlannerAssistantMessageOutcome:
    message: str
    context_checkpoint: PlannerContextCheckpoint


PlannerOutcome = PlannerPlanOutcome | PlannerClarificationOutcome | PlannerAssistantMessageOutcome


@dataclass(frozen=True)
class PlannerInput:
    mode: WorkflowGenerationModeRequest
    instruction: str
    ideal_output: str
    tool_catalogue_text: str
    knowledge_catalogue_text: str
    current_graph: dict[str, Any] | None
    policy: PlannerPolicy = "assume_defaults"
    tool_catalogue_entries: list[ToolCatalogueEntry] = field(default_factory=list)
    knowledge_catalogue_entries: list[KnowledgeCatalogueEntry] = field(default_factory=list)
    tool_catalogue_available: bool = True
    knowledge_catalogue_available: bool = True
    clarification_history: list[dict[str, Any]] = field(default_factory=list)
    context_checkpoint: PlannerContextCheckpoint | None = None
    user_turn: UserTurn | None = None
    goal_id: str = "current-goal"


def resolve_generation_mode(
    requested: WorkflowGenerationModeRequest,
    plan: PlannerResultDict | dict[str, Any],
) -> WorkflowGenerationMode:
    """Resolve an explicit or automatic request to one concrete mode."""
    if requested != "auto":
        return requested
    planner_mode = str(plan.get("mode") or "").strip().lower()
    if planner_mode in ("workflow", "advanced-chat"):
        return cast(WorkflowGenerationMode, planner_mode)
    node_types = {str(node.get("node_type") or "") for node in plan.get("nodes") or [] if isinstance(node, dict)}
    if BuiltinNodeTypes.ANSWER in node_types:
        return "advanced-chat"
    if BuiltinNodeTypes.END in node_types:
        return "workflow"
    return "advanced-chat"


def validate_planner_schema(parsed: dict[str, Any]) -> PlannerResultDict:
    """Require the planner topology and start-input contract."""
    serialized_size = len(json.dumps(parsed, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if serialized_size > _MAX_SERIALIZED_PLAN_BYTES:
        raise StageSchemaError("Planner", "serialized plan must not exceed 64 KiB")
    unexpected_plan_fields = sorted(set(parsed).difference(_PLAN_FIELDS))
    if unexpected_plan_fields:
        raise StageSchemaError("Planner", f"unexpected plan fields: {unexpected_plan_fields!r}")
    resource_requests = parsed.setdefault("resource_requests", [])
    if not isinstance(resource_requests, list):
        raise StageSchemaError("Planner", "'resource_requests' must be an array")
    start_inputs = parsed.setdefault("start_inputs", [])
    if not isinstance(start_inputs, list):
        raise StageSchemaError("Planner", "'start_inputs' must be an array")
    for index, start_input in enumerate(start_inputs):
        if not isinstance(start_input, dict):
            raise StageSchemaError("Planner", f"malformed start_inputs[{index}]: {start_input!r}")
        variable = start_input.get("variable")
        label = start_input.get("label")
        input_type = start_input.get("type")
        if not isinstance(variable, str) or not variable.strip():
            raise StageSchemaError("Planner", f"start_inputs[{index}].variable must be a non-empty string")
        if not isinstance(label, str) or not label.strip():
            raise StageSchemaError("Planner", f"start_inputs[{index}].label must be a non-empty string")
        if not isinstance(input_type, str) or input_type not in _START_INPUT_TYPES:
            raise StageSchemaError(
                "Planner",
                f"start_inputs[{index}].type must be one of {sorted(_START_INPUT_TYPES)!r}",
            )

    nodes = parsed.get("nodes")
    if not isinstance(nodes, list):
        raise StageSchemaError("Planner", "missing 'nodes' array")
    if not nodes:
        return cast(PlannerResultDict, parsed)

    node_ids: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict) or not node.get("node_type"):
            raise StageSchemaError("Planner", f"malformed node entry: {node!r}")
        unexpected_node_fields = sorted(set(node).difference(_PLAN_NODE_FIELDS))
        if unexpected_node_fields:
            raise StageSchemaError("Planner", f"unexpected node fields at nodes[{index}]: {unexpected_node_fields!r}")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            raise StageSchemaError("Planner", f"node missing non-empty id: {node!r}")
        if node_id in node_ids:
            raise StageSchemaError("Planner", f"duplicate node id: {node_id!r}")
        node_ids.add(node_id)

    edges = parsed.get("edges")
    if not isinstance(edges, list) or not edges:
        raise StageSchemaError("Planner", "missing non-empty 'edges' array")
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            raise StageSchemaError("Planner", f"malformed edge entry: {edge!r}")
        unexpected_edge_fields = sorted(set(edge).difference(_PLAN_EDGE_FIELDS))
        if unexpected_edge_fields:
            raise StageSchemaError("Planner", f"unexpected edge fields at edges[{index}]: {unexpected_edge_fields!r}")
        source = edge.get("source")
        target = edge.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            raise StageSchemaError("Planner", f"edge missing source or target: {edge!r}")
        if source not in node_ids or target not in node_ids:
            raise StageSchemaError("Planner", f"edge references unknown node: {edge!r}")
    return cast(PlannerResultDict, parsed)


def _ensure_budget_available(
    context: PlannerContextSession,
    *,
    next_input_tokens: int = 0,
    include_action_limit: bool = True,
) -> None:
    budget = context.budget
    if include_action_limit and budget["model_actions"] >= _MAX_PLANNER_ACTIONS:
        raise PlannerBudgetExhaustedError(f"{_MAX_PLANNER_ACTIONS} model actions")
    if budget["model_elapsed_ms"] >= _MAX_PLANNER_MODEL_SECONDS * 1000:
        raise PlannerBudgetExhaustedError(f"{_MAX_PLANNER_MODEL_SECONDS} seconds of model execution")
    cumulative_tokens = budget["input_tokens"] + budget["output_tokens"] + max(next_input_tokens, 0)
    token_budget = context.context_window * _MAX_PLANNER_CONTEXT_MULTIPLIER
    if cumulative_tokens >= token_budget:
        raise PlannerBudgetExhaustedError(f"cumulative token budget ({cumulative_tokens} used; limit {token_budget})")


def _default_answers(action: RequestUserInputAction) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []
    for question in action.questions:
        kind = question.get("kind", "single_choice")
        if kind == "single_choice":
            options = question.get("options", [])
            default_value = question.get("default_value") or (options[0]["value"] if options else "")
            label = next(
                (option["label"] for option in options if option["value"] == default_value),
                default_value,
            )
            answers.append(
                {"question_id": question["id"], "kind": kind, "selected_value": default_value, "label": label}
            )
        elif kind == "multi_choice":
            values = list(question.get("default_values", []))
            answers.append({"question_id": question["id"], "kind": kind, "values": values, "label": ", ".join(values)})
        elif kind == "resource_select":
            resource_ids = list(question.get("default_resource_ids", []))
            answers.append(
                {
                    "question_id": question["id"],
                    "kind": kind,
                    "resource_ids": resource_ids,
                    "label": ", ".join(resource_ids),
                }
            )
        else:
            answers.append(
                {
                    "question_id": question["id"],
                    "kind": "text",
                    "text": "Unspecified",
                    "selected_value": "Unspecified",
                    "label": "Unspecified",
                }
            )
    return answers


def _tool_resource_ids(entry: ToolCatalogueEntry) -> set[str]:
    provider_name = entry["provider_name"]
    tool_name = entry["tool_name"]
    return {tool_name, f"{provider_name}:{tool_name}", f"{provider_name}/{tool_name}"}


def _validate_resource_questions(
    action: RequestUserInputAction,
    searched_resource_ids: dict[str, set[str]],
) -> None:
    for question in action.questions:
        if question.get("kind") != "resource_select":
            continue
        resource_kind = question.get("resource_kind", "")
        authorized = searched_resource_ids.get(resource_kind, set())
        candidate_ids = {candidate["id"] for candidate in question.get("candidates", [])}
        if not authorized or not candidate_ids.issubset(authorized):
            raise StageSchemaError(
                "Planner",
                "resource candidate ids must come from deterministic search results in this planning goal",
            )
        if len(authorized) == 1:
            raise PlannerNoProgressError("Planner requested a resource that was already auto-bound")


def _record_unique_resource(
    *,
    resource_kind: Literal["dataset", "tool"],
    results: list[dict[str, object]],
    observation: PlannerObservation,
    context: PlannerContextSession,
) -> None:
    if len(results) != 1:
        return
    result = results[0]
    if resource_kind == "dataset":
        resource_id = str(result.get("id") or "")
        label = str(result.get("name") or resource_id)
        resource_label = "knowledge base"
    else:
        provider_name = str(result.get("provider_name") or "")
        tool_name = str(result.get("tool_name") or "")
        resource_id = f"{provider_name}:{tool_name}"
        label = str(result.get("tool_label") or tool_name or resource_id)
        resource_label = "tool"
    if not resource_id:
        return
    observation["auto_selected"] = {
        "resource_kind": resource_kind,
        "id": resource_id,
        "label": label,
    }
    context.add_assumption(f"Automatically selected {resource_label} {label} ({resource_id}).")


def _search_fingerprint(results: object, *, available: bool) -> str:
    return json.dumps(
        {"available": available, "results": results},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _search_key(kind: Literal["tool", "knowledge"], query: str) -> tuple[str, str]:
    return kind, " ".join(query.split()).casefold()
