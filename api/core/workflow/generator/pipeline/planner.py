"""Drive planner actions through policy, persistent budgets, and explicit terminal outcomes."""

import logging
import time
from collections.abc import Generator
from dataclasses import dataclass, replace
from typing import Any, cast
from uuid import uuid4

from core.workflow.generator.model_io.llm_response import (
    LLMJsonClient,
    StageError,
    StageSchemaError,
    StageTruncatedError,
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
    SubmitPlanAction,
    parse_planner_action,
)
from core.workflow.generator.pipeline.planner_context import PlannerContextSession, start_planner_context
from core.workflow.generator.pipeline.planner_context_values import PlannerObservation
from core.workflow.generator.pipeline.planning_action_policy import PlanningActionPolicy
from core.workflow.generator.pipeline.planning_session import (
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
from core.workflow.generator.pipeline.planning_types import ResourceCandidate, UserTurn, VerifiedResourceSnapshot
from core.workflow.generator.resources.resource_search import search_knowledge, search_tools
from core.workflow.generator.types import (
    PlannerResultDict,
)

logger = logging.getLogger(__name__)

from core.workflow.generator.pipeline.planner_support import (
    _MAX_CLARIFICATION_ROUNDS,
    PlannerAssistantMessageOutcome,
    PlannerBudgetExhaustedError,
    PlannerClarificationLimitError,
    PlannerClarificationOutcome,
    PlannerInput,
    PlannerNoProgressError,
    PlannerOutcome,
    PlannerPlanOutcome,
    _default_answers,
    _ensure_budget_available,
    _record_unique_resource,
    _search_fingerprint,
    _search_key,
    _tool_resource_ids,
    _validate_resource_questions,
    validate_planner_schema,
)


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
                raise PlannerNoProgressError(f"Planner repeated a denied action: {policy_decision.denial.reason}")
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
                question.get("requirement_key", question["id"]) for question in action.questions
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
                raise PlannerNoProgressError("Planner knowledge search is exhausted after two distinct empty queries")
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
