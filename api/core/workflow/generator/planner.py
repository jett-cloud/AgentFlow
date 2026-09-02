"""High-level workflow planning independent of orchestration."""

import json
import logging
import time
from collections.abc import Generator
from dataclasses import dataclass, field, replace
from typing import Any, Literal, cast
from uuid import uuid4

from core.workflow.generator.knowledge_catalogue import KnowledgeCatalogueEntry
from core.workflow.generator.llm_response import (
    LLMJsonClient,
    StageError,
    StageSchemaError,
    StageTruncatedError,
)
from core.workflow.generator.planner_actions import (
    AcknowledgeTurnAction,
    PlannerAction,
    ReplaceInstructionAction,
    RequestUserInputAction,
    ResolveRequirementsAction,
    ResolveResourceAction,
    RespondToUserAction,
    SearchKnowledgeAction,
    SearchToolsAction,
    SubmitPlanAction,
    parse_planner_action,
)
from core.workflow.generator.planner_context import (
    PlannerContextCheckpoint,
    PlannerContextSession,
    PlannerObservation,
    start_planner_context,
)
from core.workflow.generator.planning_action_policy import PlanningActionPolicy
from core.workflow.generator.planning_session import (
    ResourceCandidate,
    UserTurn,
    VerifiedResourceSnapshot,
    accept_default_clarification,
    acknowledge_user_turn,
    clear_pending_clarification,
    complete_planning_session,
    complete_resource_resolution,
    complete_user_turn_response,
    record_action_denial,
    reduce_planning_session,
    start_resource_resolution,
)
from core.workflow.generator.resource_search import search_knowledge, search_tools
from core.workflow.generator.tool_catalogue import ToolCatalogueEntry
from core.workflow.generator.types import (
    PlannerResultDict,
    WorkflowGenerationMode,
    WorkflowGenerationModeRequest,
)
from graphon.enums import BuiltinNodeTypes

logger = logging.getLogger(__name__)

_START_INPUT_TYPES = frozenset({"text-input", "paragraph", "number", "select", "file", "file-list"})
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
            raise StageSchemaError(
                "Planner", f"unexpected node fields at nodes[{index}]: {unexpected_node_fields!r}"
            )
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
            raise StageSchemaError(
                "Planner", f"unexpected edge fields at edges[{index}]: {unexpected_edge_fields!r}"
            )
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
        raise PlannerBudgetExhaustedError(
            f"cumulative token budget ({cumulative_tokens} used; limit {token_budget})"
        )


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


def _iter_plan_events(
    *,
    client: LLMJsonClient,
    request: PlannerInput,
    context: PlannerContextSession | None = None,
) -> Generator[tuple[str, dict[str, Any]], None, PlannerOutcome]:
    """Execute the bounded planner action loop and return a terminal outcome.

    Raw model deltas are intentionally consumed internally. Callers observe
    only resource-search operations, a clarification outcome, or a plan.
    """
    context = context or start_planner_context(client=client, request=request)
    action_policy = PlanningActionPolicy()
    parameters = context.model_parameters
    previous_action: PlannerAction | None = None
    replacement_count = 0
    searched_resource_ids: dict[str, set[str]] = {"dataset": set(), "tool": set()}
    verified_resource_ids = VerifiedResourceSnapshot(
        dataset_ids=frozenset(entry["id"] for entry in request.knowledge_catalogue_entries),
        tool_ids=frozenset(
            f"{entry['provider_name']}:{entry['tool_name']}" for entry in request.tool_catalogue_entries
        ),
    )
    search_fingerprints: dict[tuple[str, str], str] = {}
    empty_search_queries: dict[str, set[str]] = {"tool": set(), "knowledge": set()}
    exhausted_search_kinds: set[str] = set()

    # A persisted checkpoint carries search intent, never stale resource
    # results. Re-run each query against this request's tenant snapshot before
    # asking the model to continue.
    for search in context.pending_searches:
        if search["kind"] == "tool":
            restored_action: PlannerAction = SearchToolsAction(query=search["query"])
            tool_results = search_tools(request.tool_catalogue_entries, search["query"])
            search_fingerprints[_search_key("tool", search["query"])] = _search_fingerprint(
                tool_results,
                available=request.tool_catalogue_available,
            )
            searched_resource_ids["tool"].update(
                resource_id for result in tool_results for resource_id in _tool_resource_ids(result)
            )
            restored_observation = PlannerObservation(
                action="search_tools",
                query=search["query"],
                status="ok" if request.tool_catalogue_available else "unavailable",
                results=cast(list[dict[str, object]], tool_results),
                count=len(tool_results),
            )
            _record_unique_resource(
                resource_kind="tool",
                results=cast(list[dict[str, object]], tool_results),
                observation=restored_observation,
                context=context,
            )
        else:
            restored_action = SearchKnowledgeAction(query=search["query"])
            knowledge_results = search_knowledge(request.knowledge_catalogue_entries, search["query"])
            search_fingerprints[_search_key("knowledge", search["query"])] = _search_fingerprint(
                knowledge_results,
                available=request.knowledge_catalogue_available,
            )
            searched_resource_ids["dataset"].update(result["id"] for result in knowledge_results)
            restored_observation = PlannerObservation(
                action="search_knowledge",
                query=search["query"],
                status="ok" if request.knowledge_catalogue_available else "unavailable",
                results=cast(list[dict[str, object]], knowledge_results),
                count=len(knowledge_results),
            )
            _record_unique_resource(
                resource_kind="dataset",
                results=cast(list[dict[str, object]], knowledge_results),
                observation=restored_observation,
                context=context,
            )
        context.record(action=restored_action, observation=restored_observation)
        if restored_observation["count"] == 0:
            empty_search_queries[search["kind"]].add(_search_key(search["kind"], search["query"])[1])
            if len(empty_search_queries[search["kind"]]) >= 2:
                exhausted_search_kinds.add(search["kind"])
        yield (
            "operation",
            {
                "stage": "planning",
                "action": restored_observation["action"],
                "query": search["query"],
                "count": restored_observation["count"],
                "message": (
                    "Searching available tools" if search["kind"] == "tool" else "Searching available knowledge bases"
                ),
            },
        )

    while True:
        action: PlannerAction | None = None
        truncation_recovery = False
        for schema_attempt in range(2):
            parsed: dict[str, Any] = {}
            while True:
                messages = context.messages(
                    schema_retry=bool(schema_attempt),
                    truncation_recovery=truncation_recovery,
                )
                diagnostics = context.diagnostics
                try:
                    _ensure_budget_available(context, next_input_tokens=diagnostics.prompt_tokens)
                except PlannerBudgetExhaustedError as exc:
                    exc.context_checkpoint = cast(dict[str, object], context.checkpoint())
                    raise
                yield (
                    "planner_thinking",
                    {
                        "phase": context.planning_session["phase"],
                        "message": "Planning the next workflow action",
                    },
                )
                logger.info(
                    "Workflow generator planner context: provider=%s model=%s context_window=%s "
                    "context_window_source=%s input_limit=%s prompt_tokens=%s utilization_ratio=%.4f "
                    "compaction_mode=%s action_count=%s stable_prefix_tokens=%s observation_count=%s",
                    diagnostics.provider,
                    diagnostics.model,
                    diagnostics.context_window,
                    diagnostics.context_window_source,
                    diagnostics.input_limit,
                    diagnostics.prompt_tokens,
                    diagnostics.utilization_ratio,
                    diagnostics.compaction_mode,
                    context.budget["model_actions"] + 1,
                    diagnostics.stable_prefix_tokens,
                    diagnostics.observation_count,
                )
                response = client.iter_json(messages=messages, stage="Planner", model_parameters=parameters)
                started_at = time.perf_counter()
                try:
                    while True:
                        next(response)
                except StopIteration as stop:
                    parsed = cast(dict[str, Any], stop.value)
                except StageTruncatedError as exc:
                    elapsed_ms = round((time.perf_counter() - started_at) * 1000)
                    context.note_model_call(
                        input_tokens=diagnostics.prompt_tokens,
                        output={"action": "truncated"},
                        elapsed_ms=elapsed_ms,
                        provider_usage=getattr(client, "last_usage", None),
                    )
                    if context.planning_session["truncation_recoveries"] >= 1:
                        exc.context_checkpoint = cast(dict[str, object], context.checkpoint())
                        raise
                    context.note_truncation_recovery()
                    truncation_recovery = True
                    logger.info("Workflow generator: Planner output truncated; requesting one compact recovery")
                    continue
                elapsed_ms = round((time.perf_counter() - started_at) * 1000)
                context.note_model_call(
                    input_tokens=diagnostics.prompt_tokens,
                    output=parsed,
                    elapsed_ms=elapsed_ms,
                    provider_usage=getattr(client, "last_usage", None),
                )
                break
            try:
                action = parse_planner_action(parsed)
                if isinstance(action, SubmitPlanAction):
                    validate_planner_schema(cast(dict[str, Any], action.plan))
                break
            except StageSchemaError:
                if schema_attempt == 1:
                    raise
                logger.info("Workflow generator: planner action schema invalid; retrying once")
        assert action is not None
        policy_decision = action_policy.evaluate(context.planning_session, action, verified_resource_ids)
        if not policy_decision.allowed:
            assert policy_decision.denial is not None
            if policy_decision.denial.reason == "resource_intent_exhausted":
                raise PlannerNoProgressError(policy_decision.denial.message)
            if action == previous_action or context.is_repeated_action(action):
                raise PlannerNoProgressError(
                    f"Planner repeated a denied action: {policy_decision.denial.reason}"
                )
            previous_action = action
            context.note_action(action)
            context.apply_planning_session(
                record_action_denial(
                    context.planning_session,
                    signature=context.action_signature(action),
                    reason=policy_decision.denial.reason,
                )
            )
            denial_observation = PlannerObservation(
                action="action_denied",
                status="denied",
                reason=policy_decision.denial.reason,
                instruction=policy_decision.denial.message,
            )
            context.record(action=action, observation=denial_observation)
            yield (
                "operation",
                {
                    "stage": "planning",
                    "action": "action_denied",
                    "reason": policy_decision.denial.reason,
                    "checkpoint": context.checkpoint(),
                    "message": "Planner action was denied and will be corrected",
                },
            )
            continue
        if isinstance(action, RequestUserInputAction):
            _validate_resource_questions(action, searched_resource_ids)
        if action == previous_action or context.is_repeated_action(action):
            raise PlannerNoProgressError()
        if isinstance(action, RequestUserInputAction):
            repeated_keys = {
                question.get("requirement_key", question["id"])
                for question in action.questions
            }.intersection(context.resolved_requirement_keys)
            if repeated_keys:
                repeated = ", ".join(sorted(repeated_keys))
                raise PlannerNoProgressError(f"Planner repeated a resolved requirement: {repeated}")
        previous_action = action
        context.note_action(action)

        if isinstance(action, AcknowledgeTurnAction):
            user_turn = context.current_user_turn
            if user_turn is None:
                raise StageSchemaError("Planner", "acknowledge_turn requires an active user turn")
            next_session = acknowledge_user_turn(context.planning_session, turn_id=user_turn["id"])
            context.apply_planning_session(next_session)
            context.record(
                action=action,
                observation=PlannerObservation(action="acknowledge_turn", status="applied"),
            )
            yield (
                "turn_interpreted",
                {
                    "stage": "planning",
                    "action": "turn_interpreted",
                    "checkpoint": context.checkpoint(),
                    "message": "Understood the current request",
                },
            )
            continue

        if isinstance(action, ResolveRequirementsAction):
            user_turn = context.current_user_turn
            if user_turn is None:
                raise StageSchemaError("Planner", "resolve_requirements requires a latest free-form user turn")
            transition = reduce_planning_session(
                context.planning_session,
                action,
                user_turn,
                VerifiedResourceSnapshot(
                    dataset_ids=frozenset(searched_resource_ids["dataset"]),
                    tool_ids=frozenset(searched_resource_ids["tool"]),
                ),
            )
            context.apply_requirement_transition(transition)
            context.record(action=action, observation=cast(PlannerObservation, transition.observation))
            yield (
                "requirements_resolved",
                {
                    "stage": "planning",
                    **transition.public_event,
                    "checkpoint": context.checkpoint(),
                    "message": f"Understood {transition.public_event['count']} requirement(s)",
                },
            )
            continue

        if isinstance(action, ResolveResourceAction):
            resolving_session = start_resource_resolution(context.planning_session, action)
            context.apply_planning_session(resolving_session)
            yield (
                "resource_resolving",
                {
                    "stage": "planning",
                    "action": "resource_resolving",
                    "resource_kind": action.resource_kind,
                    "checkpoint": context.checkpoint(),
                    "message": "Resolving an approved workspace resource",
                },
            )
            candidates: tuple[ResourceCandidate, ...]
            if action.resource_kind == "dataset":
                results = search_knowledge(request.knowledge_catalogue_entries, action.query)
                searched_resource_ids["dataset"].update(result["id"] for result in results)
                candidates = tuple(
                    ResourceCandidate(
                        id=result["id"],
                        label=result["name"],
                        description=result["description"],
                    )
                    for result in results
                )
                available = request.knowledge_catalogue_available
            else:
                tool_results = search_tools(request.tool_catalogue_entries, action.query)
                searched_resource_ids["tool"].update(
                    resource_id for result in tool_results for resource_id in _tool_resource_ids(result)
                )
                candidates = tuple(
                    ResourceCandidate(
                        id=f"{result['provider_name']}:{result['tool_name']}",
                        label=result["tool_label"],
                        description=result["description"],
                    )
                    for result in tool_results
                )
                available = request.tool_catalogue_available
            transition = complete_resource_resolution(
                context.planning_session,
                action,
                candidates=candidates,
                available=available,
            )
            context.apply_planning_session(transition.session)
            context.record(
                action=action,
                observation=PlannerObservation(
                    action="resolve_resource",
                    status=transition.observation["status"],
                    query=action.query,
                    count=transition.observation["count"],
                ),
            )
            if transition.public_event is not None:
                yield (
                    "resource_bound",
                    {
                        "stage": "planning",
                        **transition.public_event,
                        "checkpoint": context.checkpoint(),
                        "message": f"Bound {transition.public_event['resource_name']}",
                    },
                )
                continue
            if candidates:
                if context.budget["clarification_rounds"] >= _MAX_CLARIFICATION_ROUNDS:
                    context.apply_planning_session(clear_pending_clarification(context.planning_session))
                    raise PlannerClarificationLimitError()
                clarification_id = uuid4().hex
                questions = context.planning_session["pending_clarification"].get("questions", [])
                context.set_pending_clarification(
                    clarification_id=clarification_id,
                    questions=cast(list[dict[str, Any]], questions),
                )
                context.note_clarification()
                return PlannerClarificationOutcome(
                    clarification_id=clarification_id,
                    questions=cast(tuple[dict[str, Any], ...], tuple(questions)),
                    context_checkpoint=context.checkpoint(),
                    message="Choose the workspace resource to bind.",
                )
            yield (
                "operation",
                {
                    "stage": "planning",
                    "action": "resolve_resource",
                    "status": transition.observation["status"],
                    "resource_kind": action.resource_kind,
                    "count": 0,
                    "checkpoint": context.checkpoint(),
                    "message": "No matching workspace resource was found",
                },
            )
            continue

        if isinstance(action, SearchToolsAction):
            if "tool" in exhausted_search_kinds:
                raise PlannerNoProgressError("Planner tool search is exhausted after two distinct empty queries")
            tool_results = search_tools(request.tool_catalogue_entries, action.query)
            search_key = _search_key("tool", action.query)
            fingerprint = _search_fingerprint(tool_results, available=request.tool_catalogue_available)
            if search_fingerprints.get(search_key) == fingerprint:
                raise PlannerNoProgressError("Planner repeated a tool search whose results did not change")
            search_fingerprints[search_key] = fingerprint
            searched_resource_ids["tool"].update(
                resource_id for result in tool_results for resource_id in _tool_resource_ids(result)
            )
            observation = PlannerObservation(
                action="search_tools",
                query=action.query,
                status="ok" if request.tool_catalogue_available else "unavailable",
                results=cast(list[dict[str, object]], tool_results),
                count=len(tool_results),
            )
            if not tool_results:
                empty_search_queries["tool"].add(search_key[1])
                if len(empty_search_queries["tool"]) >= 2:
                    exhausted_search_kinds.add("tool")
                    observation["status"] = "exhausted"
                    observation["instruction"] = "Do not search tools again for this planning goal."
            _record_unique_resource(
                resource_kind="tool",
                results=cast(list[dict[str, object]], tool_results),
                observation=observation,
                context=context,
            )
            context.record(action=action, observation=observation)
            yield (
                "operation",
                {
                    "stage": "planning",
                    "action": "search_tools",
                    "query": action.query,
                    "count": len(tool_results),
                    "message": "Searching available tools",
                },
            )
            continue

        if isinstance(action, SearchKnowledgeAction):
            if "knowledge" in exhausted_search_kinds:
                raise PlannerNoProgressError(
                    "Planner knowledge search is exhausted after two distinct empty queries"
                )
            knowledge_results = search_knowledge(request.knowledge_catalogue_entries, action.query)
            search_key = _search_key("knowledge", action.query)
            fingerprint = _search_fingerprint(knowledge_results, available=request.knowledge_catalogue_available)
            if search_fingerprints.get(search_key) == fingerprint:
                raise PlannerNoProgressError("Planner repeated a knowledge search whose results did not change")
            search_fingerprints[search_key] = fingerprint
            searched_resource_ids["dataset"].update(result["id"] for result in knowledge_results)
            observation = PlannerObservation(
                action="search_knowledge",
                query=action.query,
                status="ok" if request.knowledge_catalogue_available else "unavailable",
                results=cast(list[dict[str, object]], knowledge_results),
                count=len(knowledge_results),
            )
            if not knowledge_results:
                empty_search_queries["knowledge"].add(search_key[1])
                if len(empty_search_queries["knowledge"]) >= 2:
                    exhausted_search_kinds.add("knowledge")
                    observation["status"] = "exhausted"
                    observation["instruction"] = (
                        "Do not search knowledge bases again for this planning goal. Resolve another input "
                        "mechanism with the user or continue without a workspace dataset."
                    )
            _record_unique_resource(
                resource_kind="dataset",
                results=cast(list[dict[str, object]], knowledge_results),
                observation=observation,
                context=context,
            )
            context.record(action=action, observation=observation)
            yield (
                "operation",
                {
                    "stage": "planning",
                    "action": "search_knowledge",
                    "query": action.query,
                    "count": len(knowledge_results),
                    "message": "Searching available knowledge bases",
                },
            )
            continue

        if isinstance(action, RequestUserInputAction):
            if request.policy == "interactive":
                if context.budget["clarification_rounds"] >= _MAX_CLARIFICATION_ROUNDS:
                    raise PlannerClarificationLimitError()
                context.note_clarification()
                clarification_id = uuid4().hex
                context.set_pending_clarification(
                    clarification_id=clarification_id,
                    questions=cast(list[dict[str, Any]], list(action.questions)),
                )
                return PlannerClarificationOutcome(
                    clarification_id=clarification_id,
                    questions=cast(tuple[dict[str, Any], ...], action.questions),
                    context_checkpoint=context.checkpoint(),
                    message=action.message,
                )
            defaults = _default_answers(action)
            context.record(
                action=action,
                observation=PlannerObservation(
                    action="request_user_input",
                    status="defaults_applied",
                    answers=defaults,
                    instruction=(
                        "Interactive input is unavailable. Submit the plan using these defaults "
                        "and list them in assumptions."
                    ),
                ),
            )
            context.apply_planning_session(accept_default_clarification(context.planning_session))
            continue

        if isinstance(action, RespondToUserAction):
            context.apply_planning_session(complete_user_turn_response(context.planning_session))
            return PlannerAssistantMessageOutcome(
                message=action.message,
                context_checkpoint=context.checkpoint(),
            )

        if isinstance(action, ReplaceInstructionAction):
            if replacement_count >= 1:
                raise PlannerNoProgressError("Planner repeatedly replaced the active instruction")
            replacement_count += 1
            previous_revision = context.planning_session["revision"]
            request = replace(
                request,
                instruction=action.instruction,
                clarification_history=[],
                context_checkpoint=None,
                user_turn=UserTurn(
                    id=uuid4().hex,
                    kind="message",
                    message=action.instruction,
                    expected_revision=0,
                ),
                goal_id=uuid4().hex,
            )
            context = start_planner_context(client=client, request=request)
            replacement_session = context.planning_session
            replacement_session["revision"] = previous_revision + 1
            if replacement_session["active_turn"] is not None:
                replacement_session["active_turn"]["expected_revision"] = previous_revision
            context.apply_planning_session(replacement_session)
            parameters = context.model_parameters
            previous_action = None
            searched_resource_ids = {"dataset": set(), "tool": set()}
            search_fingerprints = {}
            empty_search_queries = {"tool": set(), "knowledge": set()}
            exhausted_search_kinds = set()
            yield (
                "operation",
                {
                    "stage": "planning",
                    "action": "replace_instruction",
                    "instruction": action.instruction,
                    "checkpoint": context.checkpoint(),
                    "message": "Replacing the active planning instruction",
                },
            )
            continue

        if isinstance(action, SubmitPlanAction):
            context.apply_planning_session(complete_planning_session(context.planning_session))
            return PlannerPlanOutcome(
                plan=cast(PlannerResultDict, action.plan),
                assumptions=tuple(dict.fromkeys((*context.assumptions, *action.assumptions))),
                context_checkpoint=context.checkpoint(),
            )


@dataclass(frozen=True)
class PlanningEngine:
    """Own the phase-gated, budgeted ReAct loop for one Planning Goal."""

    client: LLMJsonClient
    request: PlannerInput

    def iter_events(self) -> Generator[tuple[str, dict[str, Any]], None, PlannerOutcome]:
        context = start_planner_context(client=self.client, request=self.request)
        try:
            return (yield from _iter_plan_events(client=self.client, request=self.request, context=context))
        except StageError as exc:
            if exc.context_checkpoint is None:
                exc.context_checkpoint = cast(dict[str, object], context.checkpoint())
            raise
        except Exception as exc:
            wrapped = StageError("Planner", f"Planner execution failed: {exc}")
            wrapped.context_checkpoint = cast(dict[str, object], context.checkpoint())
            raise wrapped from exc


def iter_plan(
    *,
    client: LLMJsonClient,
    request: PlannerInput,
) -> Generator[tuple[str, dict[str, Any]], None, PlannerOutcome]:
    """Backward-compatible entry point delegated to :class:`PlanningEngine`."""
    return (yield from PlanningEngine(client=client, request=request).iter_events())
