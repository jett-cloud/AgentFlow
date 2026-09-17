"""Planner checkpoint values and deterministic observation compaction; no credentials or full catalogues."""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict, cast

from core.workflow.generator.model_io.llm_response import (
    StageError,
)
from core.workflow.generator.pipeline.planner_actions import (
    AcknowledgeTurnAction,
    PlannerAction,
    ReplaceInstructionAction,
    RequestUserInputAction,
    ResolveRequirementsAction,
    ResolveResourceAction,
    RespondToUserAction,
    SearchKnowledgeAction,
    SearchToolsAction,
    is_deferred_answer_text,
)
from core.workflow.generator.pipeline.planning_types import (
    PlanningSessionState,
    RequirementState,
)

if TYPE_CHECKING:
    from core.workflow.generator.pipeline.planner_support import PlannerInput

logger = logging.getLogger(__name__)


PLANNER_CONTEXT_VERSION = "planner-context-v4"


PLANNER_FALLBACK_CONTEXT_TOKENS = 16384


PLANNER_FALLBACK_MAX_OUTPUT_TOKENS = 8192


PLANNER_NORMAL_THRESHOLD = 0.70


PLANNER_CRITICAL_THRESHOLD = 0.85


PLANNER_RECENT_RECORDS = 2


PLANNER_SCHEMA_RETRY_HINT = (
    "Your action did not match the required topology schema. Return exactly one complete action again. "
    "For submit_plan, return the complete plan with a unique non-empty id on every node and a non-empty "
    "edges array whose source and target reference those ids. Return ONLY the JSON object."
)


PLANNER_COMPACT_RECOVERY_HINT = (
    "The previous Planner response was truncated. Return one complete compact action now. "
    "For submit_plan, include topology fields only: short metadata, start_inputs, resource_requests, "
    "nodes with id/label/node_type/purpose/parent/action, and edges with source/target/source_handle. "
    "Do not emit node configuration, prompts, code, examples, explanations, or Markdown."
)


PlannerCompactionMode = Literal["normal", "compact", "critical"]


class PlannerSearchIntent(TypedDict):
    kind: Literal["tool", "knowledge"]
    query: str
    empty: NotRequired[bool]
    exhausted: NotRequired[bool]


class PlannerResolvedRequirement(TypedDict):
    question_id: str
    requirement_key: str
    kind: str
    question: str
    answer: str
    label: str
    source: Literal["user", "default"]
    resource_kind: NotRequired[Literal["dataset", "tool"]]


class PlannerBudgetState(TypedDict):
    model_actions: int
    model_elapsed_ms: int
    input_tokens: int
    output_tokens: int
    clarification_rounds: int


class PlannerContextCheckpointV1(TypedDict):
    version: Literal[1]
    searches: list[PlannerSearchIntent]
    resolved_requirements: list[PlannerResolvedRequirement]


class PlannerContextCheckpointV2(TypedDict):
    version: Literal[2]
    searches: list[PlannerSearchIntent]
    resolved_requirements: list[PlannerResolvedRequirement]
    budget: PlannerBudgetState
    last_action_signature: NotRequired[str]
    assumptions: NotRequired[list[str]]


PlannerContextCheckpointV3 = PlanningSessionState


PlannerContextCheckpoint = PlannerContextCheckpointV1 | PlannerContextCheckpointV2 | PlannerContextCheckpointV3


class PlannerObservation(TypedDict):
    action: str
    status: str
    query: NotRequired[str]
    count: NotRequired[int]
    results: NotRequired[list[dict[str, object]]]
    answers: NotRequired[list[dict[str, Any]]]
    instruction: NotRequired[str]
    auto_selected: NotRequired[dict[str, str]]
    reason: NotRequired[str]


@dataclass(frozen=True)
class PlannerContextDiagnostics:
    provider: str
    model: str
    context_window: int
    context_window_source: Literal["schema", "fallback"]
    input_limit: int
    prompt_tokens: int
    utilization_ratio: float
    compaction_mode: PlannerCompactionMode
    action_count: int
    stable_prefix_tokens: int
    observation_count: int


@dataclass(frozen=True)
class _TrajectoryRecord:
    action: PlannerAction
    observation: PlannerObservation
    state_after: dict[str, object]


class PlannerContextLimitError(StageError):
    """Raised before invocation when lossless planner state cannot fit."""

    def __init__(self, *, prompt_tokens: int, input_limit: int) -> None:
        super().__init__(
            "Planner",
            f"Planner context limit exceeded ({prompt_tokens} input tokens; limit {input_limit})",
        )


class PlannerTokenCountError(StageError):
    """Raised when the provider tokenizer cannot establish a safe input budget."""

    def __init__(self) -> None:
        super().__init__("Planner", "Planner token count is unavailable; refusing an unbudgeted model call")


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def _normalized_query(query: str) -> str:
    return " ".join(query.split())


def _planner_prompt_mode(mode: str) -> str:
    return "auto (choose workflow or advanced-chat)" if mode == "auto" else mode


def _resource_context(request: PlannerInput) -> str:
    if request.tool_catalogue_text or request.knowledge_catalogue_text:
        return ""
    tool_status = str(len(request.tool_catalogue_entries)) if request.tool_catalogue_available else "unavailable"
    knowledge_status = (
        str(len(request.knowledge_catalogue_entries)) if request.knowledge_catalogue_available else "unavailable"
    )
    return (
        "# Resource catalogue overview\n\n"
        f"Installed tools: {tool_status}. Installed knowledge bases: {knowledge_status}. "
        "The full catalogues are not embedded. First resolve a resource_mode Requirement; "
        "only then use resolve_resource for workspace resources bound at design time.\n\n"
    )


def _capability_context() -> str:
    """Return provider-neutral platform facts without selecting a user solution."""
    return (
        "# Platform capability facts\n\n"
        "- Runtime inputs may include files, file lists, text, and numbers.\n"
        "- Agent nodes can generate content and perform multi-step reasoning.\n"
        "- Knowledge retrieval nodes query Dify datasets selected during planning.\n"
        "- HTTP request nodes can call external APIs supplied by the user.\n"
        "- Code nodes can perform deterministic evaluation and aggregation.\n\n"
        "These are available mechanisms, not recommendations. Select topology only from the user's active "
        "Requirements.\n\n"
    )


def _requirements_from_history(history: list[dict[str, Any]]) -> list[PlannerResolvedRequirement]:
    requirements: list[PlannerResolvedRequirement] = []
    for turn in history:
        questions = turn.get("questions")
        answers = turn.get("answers")
        if not isinstance(questions, list) or not isinstance(answers, list):
            continue
        question_by_id = {
            str(question.get("id")): question
            for question in questions
            if isinstance(question, dict) and question.get("id")
        }
        for answer in answers:
            if not isinstance(answer, dict):
                continue
            question_id = str(answer.get("question_id") or "").strip()
            question = question_by_id.get(question_id)
            if not question_id or question is None:
                continue
            kind = str(answer.get("kind") or question.get("kind") or "single_choice")
            raw_values: list[str]
            if kind == "text":
                raw_values = [str(answer.get("text") or answer.get("other_text") or "").strip()]
            elif kind == "multi_choice":
                values = answer.get("values")
                raw_values = [str(value).strip() for value in values] if isinstance(values, list) else []
            elif kind == "resource_select":
                resource_ids = answer.get("resource_ids")
                raw_values = [str(value).strip() for value in resource_ids] if isinstance(resource_ids, list) else []
            else:
                raw_values = [
                    str(answer.get("value") or answer.get("selected_value") or answer.get("other_text") or "").strip()
                ]
            raw_values = [value for value in raw_values if value]
            if not raw_values or any(is_deferred_answer_text(value) for value in raw_values):
                continue
            answer_value = ", ".join(raw_values)
            if not answer_value:
                continue
            labels_by_value = {
                str(option.get("value")): str(option.get("label") or option.get("value"))
                for option in question.get("options") or []
                if isinstance(option, dict) and option.get("value")
            }
            labels_by_value.update(
                {
                    str(candidate.get("id")): str(candidate.get("label") or candidate.get("id"))
                    for candidate in question.get("candidates") or []
                    if isinstance(candidate, dict) and candidate.get("id")
                }
            )
            label = ", ".join(labels_by_value.get(value, value) for value in raw_values)
            requirements.append(
                PlannerResolvedRequirement(
                    question_id=question_id,
                    requirement_key=str(question.get("requirement_key") or question_id),
                    kind=kind,
                    question=str(question.get("question") or question_id),
                    answer=answer_value,
                    label=label,
                    source="user",
                )
            )
            if kind == "resource_select" and question.get("resource_kind") in {"dataset", "tool"}:
                requirements[-1]["resource_kind"] = cast(Any, question["resource_kind"])
    return _dedupe_requirements(requirements)


def _dedupe_requirements(
    requirements: list[PlannerResolvedRequirement],
) -> list[PlannerResolvedRequirement]:
    by_id: dict[str, PlannerResolvedRequirement] = {}
    for requirement in requirements:
        by_id[requirement["requirement_key"]] = requirement
    return list(by_id.values())


def _normalize_checkpoint_requirement(requirement: object) -> PlannerResolvedRequirement | None:
    if not isinstance(requirement, dict):
        return None
    question_id = str(requirement.get("question_id") or "").strip()
    answer = str(requirement.get("answer") or "").strip()
    if not question_id or not answer or is_deferred_answer_text(answer):
        return None
    return PlannerResolvedRequirement(
        question_id=question_id,
        requirement_key=str(requirement.get("requirement_key") or question_id),
        kind=str(requirement.get("kind") or "single_choice"),
        question=str(requirement.get("question") or question_id),
        answer=answer,
        label=str(requirement.get("label") or answer),
        source="default" if requirement.get("source") == "default" else "user",
    )


def _typed_answer_from_summary(requirement: PlannerResolvedRequirement) -> dict[str, Any]:
    kind = requirement["kind"]
    if kind == "single_choice":
        return {"kind": "single_choice", "value": requirement["answer"]}
    if kind == "multi_choice":
        return {
            "kind": "multi_choice",
            "values": [item.strip() for item in requirement["answer"].split(",") if item.strip()],
        }
    if kind == "resource_select":
        return {
            "kind": "resource_select",
            "resource_kind": requirement.get("resource_kind", "dataset"),
            "resource_ids": [item.strip() for item in requirement["answer"].split(",") if item.strip()],
        }
    return {"kind": "text", "text": requirement["answer"]}


def _merge_requirement_summaries_into_session(
    session: PlanningSessionState,
    requirements: list[PlannerResolvedRequirement],
    *,
    source_turn_id: str,
) -> None:
    for requirement in requirements:
        session["requirements"][requirement["requirement_key"]] = cast(
            RequirementState,
            {
                "status": "resolved",
                "answer": _typed_answer_from_summary(requirement),
                "source_turn_id": source_turn_id,
                "revision": session["revision"],
                "label": requirement["label"],
            },
        )


def _requirement_summaries_from_session(session: PlanningSessionState) -> list[PlannerResolvedRequirement]:
    summaries: list[PlannerResolvedRequirement] = []
    for requirement_key, requirement in session["requirements"].items():
        answer = requirement["answer"]
        kind = answer["kind"]
        if kind == "text":
            value = answer["text"]
        elif kind == "single_choice":
            value = answer["value"]
        elif kind == "multi_choice":
            value = ", ".join(answer["values"])
        elif kind == "resource_select":
            value = ", ".join(answer["resource_ids"])
        else:
            value = f"{answer['source']}:{answer['resource_kind']}:{answer['binding_time']}"
        summary = PlannerResolvedRequirement(
            question_id=requirement_key,
            requirement_key=requirement_key,
            kind=kind,
            question=str(requirement.get("label") or requirement_key),
            answer=value,
            label=str(requirement.get("label") or value),
            source="user",
        )
        if kind == "resource_select":
            summary["resource_kind"] = answer["resource_kind"]
        summaries.append(summary)
    return summaries


def _dedupe_searches(searches: list[PlannerSearchIntent]) -> list[PlannerSearchIntent]:
    result: list[PlannerSearchIntent] = []
    positions: dict[tuple[str, str], int] = {}
    for search in searches:
        normalized = _normalized_query(search["query"])
        key = (search["kind"], normalized.casefold())
        item = PlannerSearchIntent(kind=search["kind"], query=normalized)
        if search.get("empty") is True:
            item["empty"] = True
        if search.get("exhausted") is True:
            item["exhausted"] = True
        existing = positions.get(key)
        if existing is None:
            positions[key] = len(result)
            result.append(item)
        else:
            result[existing] = item
    return result


def _action_payload(action: PlannerAction) -> dict[str, object]:
    if isinstance(action, SearchToolsAction):
        return {"action": "search_tools", "query": action.query}
    if isinstance(action, SearchKnowledgeAction):
        return {"action": "search_knowledge", "query": action.query}
    if isinstance(action, RequestUserInputAction):
        return {"action": "request_user_input", "message": action.message, "questions": list(action.questions)}
    if isinstance(action, RespondToUserAction):
        return {"action": "respond_to_user", "message": action.message}
    if isinstance(action, ReplaceInstructionAction):
        return {"action": "replace_instruction", "instruction": action.instruction}
    if isinstance(action, ResolveRequirementsAction):
        return {"action": "resolve_requirements", "resolutions": list(action.resolutions)}
    if isinstance(action, AcknowledgeTurnAction):
        return {"action": "acknowledge_turn"}
    if isinstance(action, ResolveResourceAction):
        return {
            "action": "resolve_resource",
            "intent_id": action.intent_id,
            "requirement_key": action.requirement_key,
            "resource_kind": action.resource_kind,
            "binding_time": action.binding_time,
            "query": action.query,
        }
    return {"action": "submit_plan", "plan": action.plan, "assumptions": list(action.assumptions)}


def _archived_action_payload(action: PlannerAction) -> dict[str, object]:
    """Keep the meaning of old actions without retaining verbose question options."""
    if isinstance(action, RequestUserInputAction):
        return {
            "action": "request_user_input",
            "question_ids": [question["id"] for question in action.questions],
        }
    return _action_payload(action)


def _compact_result(result: dict[str, object], *, identifiers_only: bool) -> dict[str, object]:
    if "tool_name" in result:
        keys = (
            ("provider_name", "tool_name")
            if identifiers_only
            else (
                "provider_name",
                "provider_type",
                "plugin_id",
                "tool_name",
                "tool_label",
            )
        )
    elif "id" in result:
        keys = ("id",) if identifiers_only else ("id", "name")
    else:
        keys = tuple(key for key in result if key != "description")
    return {key: result[key] for key in keys if key in result}


def _compact_observation(
    observation: PlannerObservation,
    *,
    identifiers_only: bool,
) -> PlannerObservation:
    compact = cast(PlannerObservation, {key: copy.deepcopy(value) for key, value in observation.items()})
    compact.pop("instruction", None)
    results = compact.get("results")
    if isinstance(results, list):
        compact["results"] = [
            _compact_result(result, identifiers_only=identifiers_only) for result in results if isinstance(result, dict)
        ]
    return compact


def _dedupe_search_records(records: list[_TrajectoryRecord]) -> list[_TrajectoryRecord]:
    """Retain the newest observation for each normalized search intent."""
    seen: set[tuple[str, str]] = set()
    retained: list[_TrajectoryRecord] = []
    for record in reversed(records):
        if isinstance(record.action, SearchToolsAction):
            key = ("tool", _normalized_query(record.action.query).casefold())
        elif isinstance(record.action, SearchKnowledgeAction):
            key = ("knowledge", _normalized_query(record.action.query).casefold())
        else:
            retained.append(record)
            continue
        if key in seen:
            continue
        seen.add(key)
        retained.append(record)
    retained.reverse()
    return retained
