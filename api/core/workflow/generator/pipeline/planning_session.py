"""Deterministic planning state transitions with monotonic revisions and verified resources."""

from __future__ import annotations

import copy
from typing import Any, Literal, cast

from core.workflow.generator.contracts.requirement_evidence import normalize_requirement_evidence
from core.workflow.generator.pipeline.planner_actions import (
    MultiChoiceRequirementAnswer,
    RequirementAnswer,
    RequirementResolution,
    ResolveRequirementsAction,
    ResolveResourceAction,
    ResourceModeRequirementAnswer,
    ResourceRequirementAnswer,
    SingleChoiceRequirementAnswer,
    TextRequirementAnswer,
    is_deferred_answer_text,
)
from core.workflow.generator.pipeline.planning_types import (
    ActiveUserTurn,
    PlannerRequirementInvalidError,
    PlanningBudgetState,
    PlanningSessionState,
    PlanningTransition,
    RequirementHistoryEntry,
    RequirementState,
    RequirementTransitionEvent,
    RequirementTransitionObservation,
    ResourceBindingState,
    ResourceBoundEvent,
    ResourceCandidate,
    ResourceIntentState,
    ResourceResolutionTransition,
    SearchObservation,
    UserTurn,
    VerifiedResourceSnapshot,
)


def _empty_budget() -> PlanningBudgetState:
    return PlanningBudgetState(
        model_actions=0,
        model_elapsed_ms=0,
        input_tokens=0,
        output_tokens=0,
        clarification_rounds=0,
    )


def empty_planning_session(goal_id: str, active_instruction: str) -> PlanningSessionState:
    """Create the canonical serializable state for one Planning Goal."""
    return PlanningSessionState(
        version=4,
        revision=0,
        goal_id=goal_id,
        phase="ready",
        active_instruction=active_instruction,
        active_turn=None,
        requirements={},
        requirement_history=[],
        pending_clarification={},
        searches=[],
        resource_intents={},
        resource_bindings={},
        search_observations=[],
        budget=_empty_budget(),
        truncation_recoveries=0,
    )


def begin_user_turn(session: PlanningSessionState, turn: UserTurn) -> PlanningSessionState:
    """Persist a new user turn and close the resource/plan gate until it is interpreted."""
    expected_revision = turn.get("expected_revision")
    if expected_revision is not None and expected_revision != session["revision"]:
        raise PlannerRequirementInvalidError(
            f"Planning Session revision conflict: expected {expected_revision}, current {session['revision']}",
        )
    message = turn.get("message", "")
    answers = turn.get("answers", [])
    if not message.strip() and not answers:
        raise PlannerRequirementInvalidError("Cannot begin an empty user turn")
    next_session = copy.deepcopy(session)
    active_turn = ActiveUserTurn(
        turn_id=turn["id"],
        kind=turn["kind"],
        status="pending_interpretation",
    )
    if message:
        active_turn["message"] = message
    if answers:
        active_turn["answers"] = copy.deepcopy(answers)
    if expected_revision is not None:
        active_turn["expected_revision"] = expected_revision
    next_session["active_turn"] = active_turn
    next_session["phase"] = "understanding"
    next_session["revision"] += 1
    return next_session


def acknowledge_user_turn(session: PlanningSessionState, *, turn_id: str) -> PlanningSessionState:
    """Mark the current turn interpreted when it adds no new Requirement."""
    active_turn = session["active_turn"]
    if active_turn is None or active_turn["turn_id"] != turn_id:
        raise PlannerRequirementInvalidError("Cannot acknowledge a turn that is not active")
    if active_turn["status"] != "pending_interpretation":
        raise PlannerRequirementInvalidError("The active user turn is already interpreted")
    next_session = copy.deepcopy(session)
    next_session["active_turn"]["status"] = "interpreted"  # type: ignore[index]
    next_session["phase"] = "ready"
    next_session["revision"] += 1
    return next_session


def request_user_clarification(
    session: PlanningSessionState,
    *,
    clarification_id: str,
    questions: list[dict[str, Any]],
) -> PlanningSessionState:
    """Persist a clarification terminal and close the current UserTurn gate."""
    if not questions:
        raise PlannerRequirementInvalidError("Clarification must contain at least one question")
    next_session = copy.deepcopy(session)
    active_turn = next_session["active_turn"]
    if active_turn is not None and active_turn["status"] == "pending_interpretation":
        active_turn["status"] = "interpreted"
    next_session["pending_clarification"] = {
        "clarification_id": clarification_id,
        "questions": copy.deepcopy(questions),
    }
    next_session["phase"] = "waiting_user"
    next_session["revision"] += 1
    return next_session


def accept_default_clarification(session: PlanningSessionState) -> PlanningSessionState:
    """Commit non-interactive defaults and close the current interpretation gate."""
    next_session = copy.deepcopy(session)
    active_turn = next_session["active_turn"]
    if active_turn is not None and active_turn["status"] == "pending_interpretation":
        active_turn["status"] = "interpreted"
    next_session["phase"] = "ready"
    next_session["revision"] += 1
    return next_session


def complete_planning_session(session: PlanningSessionState) -> PlanningSessionState:
    """Persist a successfully submitted plan as the terminal Planning Session state."""
    if session["phase"] != "ready":
        raise PlannerRequirementInvalidError("A plan can be completed only from the ready phase")
    next_session = copy.deepcopy(session)
    next_session["phase"] = "completed"
    next_session["pending_clarification"] = {}
    next_session["revision"] += 1
    return next_session


def complete_user_turn_response(session: PlanningSessionState) -> PlanningSessionState:
    """Persist an explanatory assistant response without discarding pending questions."""
    active_turn = session["active_turn"]
    if active_turn is None or active_turn["status"] == "interpreted":
        return copy.deepcopy(session)
    next_session = copy.deepcopy(session)
    next_session["active_turn"]["status"] = "interpreted"  # type: ignore[index]
    has_pending_questions = bool(next_session["pending_clarification"].get("questions"))
    next_session["phase"] = "waiting_user" if has_pending_questions else "ready"
    next_session["revision"] += 1
    return next_session


def clear_pending_clarification(session: PlanningSessionState) -> PlanningSessionState:
    """Return to ready when a newly proposed clarification cannot be presented."""
    next_session = copy.deepcopy(session)
    next_session["pending_clarification"] = {}
    next_session["phase"] = "ready"
    next_session["revision"] += 1
    return next_session


def record_action_denial(
    session: PlanningSessionState,
    *,
    signature: str,
    reason: str,
) -> PlanningSessionState:
    """Persist a compact Policy denial before the model is allowed to correct it."""
    next_session = copy.deepcopy(session)
    next_session["last_action_signature"] = signature
    next_session["search_observations"].append({"kind": "action_denied", "reason": reason})
    next_session["revision"] += 1
    return next_session


def _normalized_query(query: str) -> str:
    return " ".join(query.split()).casefold()


def start_resource_resolution(
    session: PlanningSessionState,
    action: ResolveResourceAction,
) -> PlanningSessionState:
    """Create or refresh one approved Resource Intent before performing search."""
    previous = session["resource_intents"].get(action.intent_id)
    if previous is not None and previous["status"] == "exhausted":
        raise PlannerRequirementInvalidError(f"Resource Intent {action.intent_id!r} is exhausted")
    empty_queries = list(previous["empty_queries"]) if previous is not None else []
    next_session = copy.deepcopy(session)
    next_session["resource_intents"][action.intent_id] = ResourceIntentState(
        intent_id=action.intent_id,
        requirement_key=action.requirement_key,
        resource_kind=action.resource_kind,
        binding_time=action.binding_time,
        query=action.query,
        status="resolving",
        empty_queries=empty_queries,
    )
    next_session["phase"] = "resolving_resource"
    next_session["revision"] += 1
    return next_session


def complete_resource_resolution(
    session: PlanningSessionState,
    action: ResolveResourceAction,
    *,
    candidates: tuple[ResourceCandidate, ...],
    available: bool,
) -> ResourceResolutionTransition:
    """Apply deterministic search results without retaining a stale candidate snapshot."""
    intent = session["resource_intents"].get(action.intent_id)
    if intent is None or intent["status"] != "resolving":
        raise PlannerRequirementInvalidError(f"Resource Intent {action.intent_id!r} is not resolving")
    next_session = copy.deepcopy(session)
    next_intent = next_session["resource_intents"][action.intent_id]
    next_revision = session["revision"] + 1
    public_event: ResourceBoundEvent | None = None

    if not available:
        status: Literal["ok", "empty", "exhausted", "unavailable"] = "unavailable"
        next_intent["status"] = "pending"
        next_session["phase"] = "ready"
    elif len(candidates) == 1:
        status = "ok"
        candidate = candidates[0]
        next_intent["status"] = "bound"
        next_session["resource_bindings"][action.intent_id] = ResourceBindingState(
            intent_id=action.intent_id,
            requirement_key=action.requirement_key,
            resource_kind=action.resource_kind,
            resource_id=candidate["id"],
            resource_name=candidate["label"],
            revision=next_revision,
        )
        resource_label = "knowledge base" if action.resource_kind == "dataset" else "tool"
        assumption = f"Automatically selected {resource_label} {candidate['label']}."
        assumptions = next_session.setdefault("assumptions", [])
        if assumption not in assumptions:
            assumptions.append(assumption)
        next_session["phase"] = "ready"
        public_event = ResourceBoundEvent(
            action="resource_bound",
            intent_id=action.intent_id,
            resource_kind=action.resource_kind,
            resource_name=candidate["label"],
        )
    elif len(candidates) > 1:
        status = "ok"
        next_intent["status"] = "pending"
        next_session["phase"] = "waiting_user"
        next_session["pending_clarification"] = {
            "questions": [
                {
                    "id": f"resource:{action.intent_id}",
                    "requirement_key": action.requirement_key,
                    "kind": "resource_select",
                    "question": "Choose the workspace resource to bind.",
                    "resource_kind": action.resource_kind,
                    "multiple": False,
                    "candidates": copy.deepcopy(list(candidates)),
                    "default_resource_ids": [],
                }
            ]
        }
    else:
        normalized_query = _normalized_query(action.query)
        if normalized_query not in next_intent["empty_queries"]:
            next_intent["empty_queries"].append(normalized_query)
        exhausted = len(next_intent["empty_queries"]) >= 2
        status = "exhausted" if exhausted else "empty"
        next_intent["status"] = "exhausted" if exhausted else "pending"
        next_session["phase"] = "ready"

    observation = SearchObservation(
        intent_id=action.intent_id,
        resource_kind=action.resource_kind,
        query=action.query,
        status=status,
        count=len(candidates),
    )
    next_session["search_observations"].append(observation)
    next_session["revision"] = next_revision
    return ResourceResolutionTransition(
        session=next_session,
        observation=observation,
        public_event=public_event,
    )


def _structured_answer(raw: dict[str, Any], question: dict[str, Any]) -> RequirementAnswer:
    kind = raw.get("kind") or ("text" if raw.get("other_text") else question.get("kind")) or "single_choice"
    if kind == "text":
        text = raw.get("text") or raw.get("other_text")
        if not isinstance(text, str) or not text.strip():
            raise PlannerRequirementInvalidError("Structured text answer must be non-empty")
        return TextRequirementAnswer(kind="text", text=text.strip())
    if kind == "single_choice":
        value = raw.get("value") or raw.get("selected_value")
        if not isinstance(value, str) or value not in _option_values(question):
            raise PlannerRequirementInvalidError("Structured single-choice answer must match a pending option")
        return SingleChoiceRequirementAnswer(kind="single_choice", value=value)
    if kind == "multi_choice":
        values = raw.get("values")
        if not isinstance(values, list) or not values or not all(isinstance(item, str) for item in values):
            raise PlannerRequirementInvalidError("Structured multi-choice answer must be non-empty")
        if not set(values).issubset(_option_values(question)):
            raise PlannerRequirementInvalidError("Structured multi-choice answer must match pending options")
        return MultiChoiceRequirementAnswer(kind="multi_choice", values=cast(list[str], values))
    if kind == "resource_select":
        resource_kind = raw.get("resource_kind")
        resource_ids = raw.get("resource_ids")
        candidates = question.get("candidates")
        candidate_ids = {candidate.get("id") for candidate in candidates or [] if isinstance(candidate, dict)}
        if (
            resource_kind not in {"dataset", "tool"}
            or not isinstance(resource_ids, list)
            or not resource_ids
            or not all(isinstance(item, str) for item in resource_ids)
            or not set(resource_ids).issubset(candidate_ids)
        ):
            raise PlannerRequirementInvalidError("Structured resource answer must match verified candidates")
        return ResourceRequirementAnswer(
            kind="resource_select",
            resource_kind=cast(Any, resource_kind),
            resource_ids=cast(list[str], resource_ids),
        )
    raise PlannerRequirementInvalidError(f"Unsupported structured answer kind: {kind!r}")


def reduce_structured_clarification(session: PlanningSessionState, turn: UserTurn) -> PlanningSessionState:
    """Apply validated card answers without asking the model to reinterpret them."""
    if turn["kind"] != "clarification_response":
        raise PlannerRequirementInvalidError("Structured clarification requires a clarification_response UserTurn")
    expected_revision = turn.get("expected_revision")
    if expected_revision is not None and expected_revision != session["revision"]:
        raise PlannerRequirementInvalidError(
            f"Planning Session revision conflict: expected {expected_revision}, current {session['revision']}",
        )
    answers = turn.get("answers") or []
    questions = session["pending_clarification"].get("questions")
    if not answers or not isinstance(questions, list):
        raise PlannerRequirementInvalidError("Structured clarification has no pending questions or answers")
    question_by_id = {
        str(question.get("id")): question for question in questions if isinstance(question, dict) and question.get("id")
    }
    next_session = copy.deepcopy(session)
    next_revision = session["revision"] + 1
    seen: set[str] = set()
    for raw_answer in answers:
        question_id = raw_answer.get("question_id")
        if not isinstance(question_id, str) or question_id in seen or question_id not in question_by_id:
            raise PlannerRequirementInvalidError("Structured answer does not match a pending question")
        seen.add(question_id)
        question = question_by_id[question_id]
        requirement_key = str(question.get("requirement_key") or question_id)
        answer = _structured_answer(raw_answer, question)
        if answer["kind"] == "resource_select" and question_id.startswith("resource:"):
            intent_id = question_id.removeprefix("resource:")
            intent = next_session["resource_intents"].get(intent_id)
            candidate_by_id = {
                candidate["id"]: candidate
                for candidate in question.get("candidates") or []
                if isinstance(candidate, dict)
                and isinstance(candidate.get("id"), str)
                and isinstance(candidate.get("label"), str)
            }
            resource_id = answer["resource_ids"][0]
            candidate = candidate_by_id.get(resource_id)
            if intent is None or candidate is None or intent["resource_kind"] != answer["resource_kind"]:
                raise PlannerRequirementInvalidError("Structured resource answer does not match its Resource Intent")
            next_session["resource_bindings"][intent_id] = ResourceBindingState(
                intent_id=intent_id,
                requirement_key=requirement_key,
                resource_kind=answer["resource_kind"],
                resource_id=resource_id,
                resource_name=str(candidate["label"]),
                revision=next_revision,
            )
            intent["status"] = "bound"
        else:
            previous = session["requirements"].get(requirement_key)
            if previous is not None and previous["answer"] != answer:
                next_session["requirement_history"].append(
                    RequirementHistoryEntry(
                        requirement_key=requirement_key,
                        answer=copy.deepcopy(previous["answer"]),
                        source_turn_id=previous["source_turn_id"],
                        revision=previous["revision"],
                        superseded_by_revision=next_revision,
                    )
                )
            next_session["requirements"][requirement_key] = RequirementState(
                status="resolved",
                answer=answer,
                source_turn_id=turn["id"],
                revision=next_revision,
                label=str(question.get("question") or requirement_key),
            )
    next_session["active_turn"] = ActiveUserTurn(
        turn_id=turn["id"],
        kind="clarification_response",
        status="interpreted",
        answers=copy.deepcopy(answers),
    )
    if expected_revision is not None:
        next_session["active_turn"]["expected_revision"] = expected_revision
    next_session["pending_clarification"] = {}
    next_session["phase"] = "ready"
    next_session["revision"] = next_revision
    return next_session


def _legacy_answer(raw: dict[str, Any]) -> RequirementAnswer:
    kind = raw.get("kind")
    answer = raw.get("answer")
    if kind == "multi_choice" and isinstance(answer, list):
        return MultiChoiceRequirementAnswer(
            kind="multi_choice", values=[item for item in answer if isinstance(item, str) and item]
        )
    if kind == "resource_select" and isinstance(answer, list):
        resource_kind = raw.get("resource_kind")
        if resource_kind not in {"dataset", "tool"}:
            resource_kind = "dataset"
        return ResourceRequirementAnswer(
            kind="resource_select",
            resource_kind=cast(Any, resource_kind),
            resource_ids=[item for item in answer if isinstance(item, str) and item],
        )
    if kind == "resource_mode" and isinstance(answer, dict):
        resource_kind = answer.get("resource_kind")
        source = answer.get("source")
        binding_time = answer.get("binding_time")
        valid_resource_kind = resource_kind in {"dataset", "tool"}
        valid_source = source in {"workspace", "runtime_input", "external"}
        valid_binding_time = binding_time in {"design_time", "runtime"}
        if valid_resource_kind and valid_source and valid_binding_time:
            return ResourceModeRequirementAnswer(
                kind="resource_mode",
                resource_kind=cast(Any, resource_kind),
                source=cast(Any, source),
                binding_time=cast(Any, binding_time),
            )
    if kind in {None, "single_choice"} and isinstance(answer, str):
        return SingleChoiceRequirementAnswer(kind="single_choice", value=answer)
    text = answer if isinstance(answer, str) else str(answer or raw.get("label") or "")
    return TextRequirementAnswer(kind="text", text=text)


def _normalize_budget(raw: object) -> PlanningBudgetState:
    budget = _empty_budget()
    if not isinstance(raw, dict):
        return budget
    for key in budget:
        value = raw.get(key)
        if isinstance(value, int) and value >= 0:
            budget[key] = value  # type: ignore[literal-required]
    return budget


def normalize_planning_session(
    raw: object,
    *,
    goal_id: str,
    active_instruction: str,
) -> PlanningSessionState:
    """Normalize persisted checkpoint/session versions 1-4 into version 4."""
    session = empty_planning_session(goal_id, active_instruction)
    if not isinstance(raw, dict):
        return session
    if raw.get("version") in {3, 4}:
        revision = raw.get("revision")
        session["revision"] = revision if isinstance(revision, int) and revision >= 0 else 0
        stored_goal_id = raw.get("goal_id")
        if isinstance(stored_goal_id, str) and stored_goal_id:
            session["goal_id"] = stored_goal_id
        stored_instruction = raw.get("active_instruction")
        if isinstance(stored_instruction, str) and stored_instruction:
            session["active_instruction"] = stored_instruction
        raw_requirements = raw.get("requirements")
        if isinstance(raw_requirements, dict):
            session["requirements"] = copy.deepcopy(cast(dict[str, RequirementState], raw_requirements))
        raw_history = raw.get("requirement_history")
        if isinstance(raw_history, list):
            session["requirement_history"] = copy.deepcopy(cast(list[RequirementHistoryEntry], raw_history))
        raw_pending = raw.get("pending_clarification")
        if isinstance(raw_pending, dict):
            session["pending_clarification"] = copy.deepcopy(raw_pending)
        recoveries = raw.get("truncation_recoveries")
        if isinstance(recoveries, int) and recoveries >= 0:
            session["truncation_recoveries"] = recoveries
        if raw.get("version") == 4:
            phase = raw.get("phase")
            valid_phases = {
                "understanding",
                "ready",
                "resolving_resource",
                "waiting_user",
                "completed",
                "failed_recoverable",
            }
            if phase in valid_phases:
                session["phase"] = cast(Any, phase)
            active_turn = raw.get("active_turn")
            if isinstance(active_turn, dict):
                session["active_turn"] = copy.deepcopy(cast(ActiveUserTurn, active_turn))
                turn_status = active_turn.get("status")
                if turn_status == "pending_interpretation":
                    session["phase"] = "understanding"
                elif turn_status == "interpreted" and session["phase"] == "understanding":
                    session["phase"] = "waiting_user" if session["pending_clarification"].get("questions") else "ready"
            for key in ("resource_intents", "resource_bindings"):
                value = raw.get(key)
                if isinstance(value, dict):
                    session[key] = copy.deepcopy(value)  # type: ignore[literal-required]
            observations = raw.get("search_observations")
            if isinstance(observations, list):
                session["search_observations"] = copy.deepcopy(
                    [item for item in observations if isinstance(item, dict)]
                )
    else:
        legacy_requirements = raw.get("resolved_requirements")
        if isinstance(legacy_requirements, list):
            for legacy in legacy_requirements:
                if not isinstance(legacy, dict):
                    continue
                requirement_key = legacy.get("requirement_key") or legacy.get("question_id")
                if not isinstance(requirement_key, str) or not requirement_key:
                    continue
                legacy_answer = legacy.get("answer")
                if isinstance(legacy_answer, str) and is_deferred_answer_text(legacy_answer):
                    continue
                session["requirements"][requirement_key] = RequirementState(
                    status="resolved",
                    answer=_legacy_answer(legacy),
                    source_turn_id="legacy",
                    revision=0,
                    label=str(legacy.get("label") or legacy.get("question") or requirement_key),
                )
    raw_searches = raw.get("searches")
    if isinstance(raw_searches, list):
        legacy_search_observations = [
            {**copy.deepcopy(item), "legacy": True} for item in raw_searches if isinstance(item, dict)
        ]
        session["search_observations"].extend(legacy_search_observations)
    session["budget"] = _normalize_budget(raw.get("budget"))
    signature = raw.get("last_action_signature")
    if isinstance(signature, str) and signature:
        session["last_action_signature"] = signature
    assumptions = raw.get("assumptions")
    if isinstance(assumptions, list):
        session["assumptions"] = [item for item in assumptions if isinstance(item, str) and item]
    return session


def _pending_question(session: PlanningSessionState, requirement_key: str) -> dict[str, Any] | None:
    questions = session["pending_clarification"].get("questions")
    if not isinstance(questions, list):
        return None
    for question in questions:
        if isinstance(question, dict) and question.get("requirement_key", question.get("id")) == requirement_key:
            return question
    return None


def _option_values(question: dict[str, Any]) -> frozenset[str]:
    options = question.get("options")
    if not isinstance(options, list):
        return frozenset()
    return frozenset(
        option["value"] for option in options if isinstance(option, dict) and isinstance(option.get("value"), str)
    )


def _validate_answer(
    resolution: RequirementResolution,
    *,
    pending_question: dict[str, Any] | None,
    resources: VerifiedResourceSnapshot,
) -> None:
    answer = resolution["answer"]
    if answer["kind"] == "single_choice":
        allowed = _option_values(pending_question or {})
        if not allowed or answer["value"] not in allowed:
            raise PlannerRequirementInvalidError(
                f"Requirement {resolution['requirement_key']!r} answer must match a pending option; "
                "store a user-proposed alternative as text",
            )
    elif answer["kind"] == "multi_choice":
        allowed = _option_values(pending_question or {})
        if not allowed or not set(answer["values"]).issubset(allowed):
            raise PlannerRequirementInvalidError(
                f"Requirement {resolution['requirement_key']!r} answer must match pending options"
            )
    elif answer["kind"] == "resource_select":
        verified = resources.dataset_ids if answer["resource_kind"] == "dataset" else resources.tool_ids
        if not set(answer["resource_ids"]).issubset(verified):
            raise PlannerRequirementInvalidError(
                f"Requirement {resolution['requirement_key']!r} contains an unverified resource ID"
            )


def _remove_resolved_pending(session: PlanningSessionState, resolved_keys: frozenset[str]) -> dict[str, Any]:
    pending = copy.deepcopy(session["pending_clarification"])
    questions = pending.get("questions")
    if not isinstance(questions, list):
        return pending
    remaining = [
        question
        for question in questions
        if not isinstance(question, dict) or question.get("requirement_key", question.get("id")) not in resolved_keys
    ]
    if not remaining:
        return {}
    pending["questions"] = remaining
    return pending


def reduce_planning_session(
    session: PlanningSessionState,
    action: ResolveRequirementsAction,
    turn: UserTurn,
    resources: VerifiedResourceSnapshot,
) -> PlanningTransition:
    """Validate one user-backed transition without model or database access."""
    expected_revision = turn.get("expected_revision")
    if expected_revision is not None and expected_revision != session["revision"]:
        raise PlannerRequirementInvalidError(
            f"Planning Session revision conflict: expected {expected_revision}, current {session['revision']}",
        )
    normalized_turn = normalize_requirement_evidence(turn.get("message", ""))
    if not normalized_turn:
        raise PlannerRequirementInvalidError("Cannot resolve Requirements from an empty user turn")

    next_session = copy.deepcopy(session)
    next_revision = session["revision"] + 1
    changed_keys: list[str] = []
    labels: list[str] = []
    for resolution in action.resolutions:
        normalized_evidence = normalize_requirement_evidence(resolution["evidence"])
        if not normalized_evidence or normalized_evidence not in normalized_turn:
            raise PlannerRequirementInvalidError(
                f"Requirement {resolution['requirement_key']!r} evidence is absent from the current user turn",
            )
        requirement_key = resolution["requirement_key"]
        pending_question = _pending_question(session, requirement_key)
        _validate_answer(resolution, pending_question=pending_question, resources=resources)
        previous = session["requirements"].get(requirement_key)
        if previous is not None and previous["answer"] == resolution["answer"]:
            continue
        if previous is not None:
            next_session["requirement_history"].append(
                RequirementHistoryEntry(
                    requirement_key=requirement_key,
                    answer=copy.deepcopy(previous["answer"]),
                    source_turn_id=previous["source_turn_id"],
                    revision=previous["revision"],
                    superseded_by_revision=next_revision,
                )
            )
        label = requirement_key
        if pending_question is not None and isinstance(pending_question.get("question"), str):
            label = pending_question["question"]
        next_session["requirements"][requirement_key] = RequirementState(
            status="resolved",
            answer=copy.deepcopy(resolution["answer"]),
            source_turn_id=turn["id"],
            revision=next_revision,
            label=label,
        )
        changed_keys.append(requirement_key)
        labels.append(label)
        dependent_intents = {
            intent_id
            for intent_id, intent in next_session["resource_intents"].items()
            if intent["requirement_key"] == requirement_key
        }
        for intent_id in dependent_intents:
            next_session["resource_intents"].pop(intent_id, None)
            next_session["resource_bindings"].pop(intent_id, None)
    if not changed_keys:
        raise PlannerRequirementInvalidError("Requirement resolution produced no changes")

    next_session["revision"] = next_revision
    active_turn = next_session["active_turn"]
    if active_turn is not None and active_turn["turn_id"] == turn["id"]:
        active_turn["status"] = "interpreted"
    next_session["phase"] = "ready"
    next_session["pending_clarification"] = _remove_resolved_pending(next_session, frozenset(changed_keys))
    return PlanningTransition(
        session=next_session,
        observation=RequirementTransitionObservation(
            action="requirements_resolved",
            status="applied",
            resolved_requirement_keys=changed_keys,
            revision=next_revision,
        ),
        public_event=RequirementTransitionEvent(
            action="requirements_resolved",
            count=len(changed_keys),
            requirement_keys=changed_keys,
            labels=labels,
        ),
    )
