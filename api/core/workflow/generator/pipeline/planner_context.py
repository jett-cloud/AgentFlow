"""Own provider-neutral planner state and budgeted prompt rendering; compact observations without deleting history."""

from __future__ import annotations

import copy
import logging
import math
from typing import TYPE_CHECKING, Any, Literal, cast

from core.workflow.generator.model_io.llm_response import (
    LLMJsonClient,
    ModelInvoker,
    clamp_for_planner,
    model_max_output_tokens,
)
from core.workflow.generator.pipeline.planner_actions import (
    PlannerAction,
    RequestUserInputAction,
    SearchKnowledgeAction,
    SearchToolsAction,
)
from core.workflow.generator.pipeline.planning_session import (
    begin_user_turn,
    normalize_planning_session,
    request_user_clarification,
)
from core.workflow.generator.pipeline.planning_types import (
    PlanningSessionState,
    PlanningTransition,
    UserTurn,
)
from core.workflow.generator.prompts.output_language import detect_output_language, output_language_name
from core.workflow.generator.prompts.planner_prompts import (
    PLANNER_SYSTEM_PROMPT,
    PLANNER_USER_PROMPT,
    format_existing_graph_section,
    format_ideal_output_section,
    format_knowledge_catalogue_section,
    format_tool_catalogue_section,
)
from graphon.model_runtime.entities.message_entities import (
    AssistantPromptMessage,
    PromptMessage,
    SystemPromptMessage,
    UserPromptMessage,
)
from graphon.model_runtime.entities.model_entities import ModelPropertyKey

if TYPE_CHECKING:
    from core.workflow.generator.pipeline.planner_support import PlannerInput

logger = logging.getLogger(__name__)

from core.workflow.generator.pipeline.planner_context_values import (
    PLANNER_COMPACT_RECOVERY_HINT,
    PLANNER_CONTEXT_VERSION,
    PLANNER_CRITICAL_THRESHOLD,
    PLANNER_FALLBACK_CONTEXT_TOKENS,
    PLANNER_FALLBACK_MAX_OUTPUT_TOKENS,
    PLANNER_NORMAL_THRESHOLD,
    PLANNER_RECENT_RECORDS,
    PLANNER_SCHEMA_RETRY_HINT,
    PlannerBudgetState,
    PlannerCompactionMode,
    PlannerContextCheckpoint,
    PlannerContextCheckpointV3,
    PlannerContextDiagnostics,
    PlannerContextLimitError,
    PlannerObservation,
    PlannerResolvedRequirement,
    PlannerSearchIntent,
    PlannerTokenCountError,
    _action_payload,
    _archived_action_payload,
    _capability_context,
    _compact_json,
    _compact_observation,
    _dedupe_requirements,
    _dedupe_search_records,
    _dedupe_searches,
    _merge_requirement_summaries_into_session,
    _normalized_query,
    _planner_prompt_mode,
    _requirement_summaries_from_session,
    _requirements_from_history,
    _resource_context,
    _TrajectoryRecord,
)


class PlannerContextSession:
    """Stateful context owner for one bounded planner action loop.

    ``record`` accepts only validated, observable actions and deterministic
    observations. ``messages`` may compact those records, but never mutates
    the immutable task prompt or removes graph topology and resolved user
    requirements. A session is request-local and not safe for concurrent use.
    """

    _request: PlannerInput
    _model_instance: ModelInvoker
    _model_parameters: dict[str, Any]
    _context_window: int
    _context_window_source: Literal["schema", "fallback"]
    _input_limit: int
    _base_messages: list[PromptMessage]
    _records: list[_TrajectoryRecord]
    _searches: list[PlannerSearchIntent]
    _requirements: list[PlannerResolvedRequirement]
    _planning_session: PlanningSessionState
    _compaction_mode: PlannerCompactionMode
    _prompt_tokens: int
    _stable_prefix_tokens: int
    _budget: PlannerBudgetState
    _last_action_signature: str
    _assumptions: list[str]

    def __init__(
        self,
        *,
        request: PlannerInput,
        model_instance: ModelInvoker,
        model_parameters: dict[str, Any],
        context_window: int,
        context_window_source: Literal["schema", "fallback"],
        input_limit: int,
        searches: list[PlannerSearchIntent],
        requirements: list[PlannerResolvedRequirement],
        planning_session: PlanningSessionState,
        budget: PlannerBudgetState,
        last_action_signature: str,
        assumptions: list[str],
    ) -> None:
        self._request = request
        self._model_instance = model_instance
        self._model_parameters = model_parameters
        self._context_window = context_window
        self._context_window_source = context_window_source
        self._input_limit = input_limit
        self._records = []
        self._searches = searches
        self._requirements = requirements
        self._planning_session = planning_session
        self._budget = budget
        self._last_action_signature = last_action_signature
        self._assumptions = assumptions
        self._compaction_mode = "normal"
        self._prompt_tokens = 0
        self._base_messages = self._build_base_messages()
        self._stable_prefix_tokens = self._count_tokens(self._base_messages)

    @classmethod
    def start(
        cls,
        *,
        request: PlannerInput,
        model_instance: ModelInvoker,
        model_parameters: dict[str, object],
        checkpoint: PlannerContextCheckpoint | None = None,
    ) -> PlannerContextSession:
        """Create a request-local session and derive a matching input/output budget."""
        context_window, source = cls._resolve_context_window(model_instance)
        parameters = clamp_for_planner(
            cast(dict[str, Any], model_parameters),
            model_max_output_tokens(model_instance),
        )
        desired_output = model_parameters.get("max_tokens", PLANNER_FALLBACK_MAX_OUTPUT_TOKENS)
        desired_output = int(desired_output) if isinstance(desired_output, (int, float)) else 8192
        output_candidates = [max(desired_output, 1), max(1024, int(context_window * 0.25))]
        model_ceiling = model_max_output_tokens(model_instance)
        if model_ceiling is not None and model_ceiling > 0:
            output_candidates.append(model_ceiling)
        output_reserve = min(output_candidates)
        parameters["max_tokens"] = output_reserve
        safety_margin = max(256, math.ceil(context_window * 0.02))
        input_limit = max(context_window - output_reserve - safety_margin, 0)

        checkpoint = checkpoint if checkpoint and checkpoint.get("version") in {1, 2, 3, 4} else None
        planning_session = normalize_planning_session(
            checkpoint,
            goal_id=request.goal_id,
            active_instruction=request.instruction.strip(),
        )
        incoming_turn = request.user_turn
        if incoming_turn is None:
            for history_turn in reversed(request.clarification_history):
                user_message = history_turn.get("user_message")
                if isinstance(user_message, str) and user_message.strip():
                    incoming_turn = UserTurn(
                        id=str(
                            history_turn.get("turn_id") or history_turn.get("clarification_id") or "latest-user-turn"
                        ),
                        kind="message",
                        message=user_message,
                    )
                    break
        if incoming_turn is not None:
            active_turn = planning_session["active_turn"]
            if active_turn is None or active_turn["turn_id"] != incoming_turn["id"]:
                planning_session = begin_user_turn(planning_session, incoming_turn)
        for turn in request.clarification_history:
            requirements_from_turn = _requirements_from_history([turn])
            source_turn_id = str(turn.get("clarification_id") or "legacy-turn")
            _merge_requirement_summaries_into_session(
                planning_session,
                requirements_from_turn,
                source_turn_id=source_turn_id,
            )
        requirements = _requirement_summaries_from_session(planning_session)
        searches = cast(list[PlannerSearchIntent], copy.deepcopy(planning_session["searches"]))
        budget = cast(PlannerBudgetState, copy.deepcopy(planning_session["budget"]))
        last_action_signature = str(planning_session.get("last_action_signature") or "")
        assumptions = list(planning_session.get("assumptions") or [])
        return cls(
            request=request,
            model_instance=model_instance,
            model_parameters=parameters,
            context_window=context_window,
            context_window_source=source,
            input_limit=input_limit,
            searches=_dedupe_searches(searches),
            requirements=_dedupe_requirements(requirements),
            planning_session=planning_session,
            budget=cast(PlannerBudgetState, budget),
            last_action_signature=last_action_signature,
            assumptions=assumptions,
        )

    @staticmethod
    def _resolve_context_window(
        model_instance: ModelInvoker,
    ) -> tuple[int, Literal["schema", "fallback"]]:
        try:
            schema = model_instance.get_model_schema()
            value = schema.model_properties.get(ModelPropertyKey.CONTEXT_SIZE)
            if isinstance(value, (int, float)) and int(value) > 0:
                return int(value), "schema"
        except Exception:
            logger.info("Workflow generator: could not read planner context window", exc_info=True)
        return PLANNER_FALLBACK_CONTEXT_TOKENS, "fallback"

    def _build_base_messages(self) -> list[PromptMessage]:
        planning_state = {
            "phase": self._planning_session["phase"],
            "active_turn": self._planning_session["active_turn"],
        }
        requirement_context = (
            "# Planning state\n\n"
            f"{_compact_json(planning_state)}\n\n"
            "The current UserTurn must be interpreted before resource resolution or plan submission.\n\n"
        )
        if self._planning_session["requirements"]:
            requirement_context = (
                "# Resolved user requirements\n\n"
                f"{_compact_json(self._planning_session['requirements'])}\n\n"
                "Treat these structured answers as user requirements.\n\n"
            )
        pending_turns = [
            {
                "clarification_id": turn.get("clarification_id"),
                "questions": turn.get("questions") or [],
                "user_message": turn.get("user_message"),
            }
            for turn in self._request.clarification_history
            if isinstance(turn, dict) and isinstance(turn.get("user_message"), str)
        ]
        if pending_turns:
            requirement_context += (
                "# Latest conversation turn while clarification is pending\n\n"
                f"{_compact_json(pending_turns[-1])}\n\n"
                "Interpret the user message in context. If it answers the pending question, continue planning. "
                "If it asks for an explanation, use respond_to_user. If it clearly replaces the task, use "
                "replace_instruction. Do not discard the pending question merely because the user sent text.\n\n"
            )
        user_prompt = PLANNER_USER_PROMPT.format(
            mode=_planner_prompt_mode(self._request.mode),
            output_language=output_language_name(detect_output_language(self._request.instruction)),
            instruction=self._request.instruction.strip(),
            existing_graph_section=format_existing_graph_section(self._request.current_graph),
            ideal_output_section=format_ideal_output_section(self._request.ideal_output),
            resource_context_section=_resource_context(self._request),
            clarification_context_section=f"{_capability_context()}{requirement_context}",
            observation_section="",
            tool_catalogue_section=(
                ""
                if self._request.tool_catalogue_entries
                else format_tool_catalogue_section(self._request.tool_catalogue_text)
            ),
            knowledge_catalogue_section=(
                ""
                if self._request.knowledge_catalogue_entries
                else format_knowledge_catalogue_section(self._request.knowledge_catalogue_text)
            ),
        )
        system_prompt = f"{PLANNER_SYSTEM_PROMPT}\n\n# Protocol version\n\n{PLANNER_CONTEXT_VERSION}"
        return [SystemPromptMessage(content=system_prompt), UserPromptMessage(content=user_prompt)]

    def _count_tokens(self, messages: list[PromptMessage]) -> int:
        try:
            return max(self._model_instance.get_llm_num_tokens(messages), 0)
        except Exception as exc:
            logger.warning("Workflow generator: planner token count failed", exc_info=True)
            raise PlannerTokenCountError() from exc

    def _state_after(self, *, action_count: int | None = None) -> dict[str, object]:
        return {
            "action_count": len(self._records) if action_count is None else action_count,
            "resolved_requirements": self._requirements,
            "searches": self._searches,
        }

    def _render_records(self, records: list[_TrajectoryRecord], *, compact: bool) -> list[PromptMessage]:
        messages: list[PromptMessage] = []
        for record in records:
            observation = (
                _compact_observation(record.observation, identifiers_only=False)
                if compact
                else copy.deepcopy(record.observation)
            )
            messages.append(AssistantPromptMessage(content=_compact_json(_action_payload(record.action))))
            messages.append(
                UserPromptMessage(
                    content=_compact_json({"observation": observation, "state_after": record.state_after})
                )
            )
        return messages

    def _critical_messages(self) -> list[PromptMessage]:
        old_records = _dedupe_search_records(self._records[:-PLANNER_RECENT_RECORDS])
        recent_records = self._records[-PLANNER_RECENT_RECORDS:]
        messages = list(self._base_messages)
        if old_records:
            archived = [
                {
                    "action": _archived_action_payload(record.action),
                    "observation": _compact_observation(record.observation, identifiers_only=True),
                }
                for record in old_records
            ]
            messages.append(
                UserPromptMessage(
                    content=_compact_json(
                        {
                            "archived_trajectory": archived,
                            "state_after": self._state_after(),
                            "instruction": "Continue from this deterministic planner checkpoint.",
                        }
                    )
                )
            )
        messages.extend(self._render_records(recent_records, compact=True))
        return messages

    def messages(self, *, schema_retry: bool = False, truncation_recovery: bool = False) -> list[PromptMessage]:
        """Render a token-bounded prompt or raise before invoking the model."""
        full = [*self._base_messages, *self._render_records(self._records, compact=False)]
        full_tokens = self._count_tokens(full)
        if full_tokens <= self._input_limit * PLANNER_NORMAL_THRESHOLD:
            messages = full
            mode: PlannerCompactionMode = "normal"
        else:
            compact_records = _dedupe_search_records(self._records)
            compact = [*self._base_messages, *self._render_records(compact_records, compact=True)]
            compact_tokens = self._count_tokens(compact)
            if compact_tokens <= self._input_limit * PLANNER_CRITICAL_THRESHOLD:
                messages = compact
                mode = "compact"
            else:
                messages = self._critical_messages()
                mode = "critical"

        if schema_retry:
            messages.append(UserPromptMessage(content=PLANNER_SCHEMA_RETRY_HINT))
        if truncation_recovery:
            messages.append(UserPromptMessage(content=PLANNER_COMPACT_RECOVERY_HINT))
        prompt_tokens = self._count_tokens(messages)
        self._compaction_mode = mode
        self._prompt_tokens = prompt_tokens
        if prompt_tokens > self._input_limit:
            raise PlannerContextLimitError(prompt_tokens=prompt_tokens, input_limit=self._input_limit)
        return messages

    def record(self, *, action: PlannerAction, observation: PlannerObservation | None) -> None:
        """Append one validated observable action and its deterministic result."""
        if observation is None:
            return
        copied = copy.deepcopy(observation)
        if isinstance(action, SearchToolsAction) and copied.get("status") != "denied":
            intent = PlannerSearchIntent(kind="tool", query=_normalized_query(action.query))
            if observation.get("count") == 0:
                intent["empty"] = True
            if observation.get("status") == "exhausted":
                intent["exhausted"] = True
            self._searches.append(intent)
            self._searches = _dedupe_searches(self._searches)
        elif isinstance(action, SearchKnowledgeAction) and copied.get("status") != "denied":
            intent = PlannerSearchIntent(kind="knowledge", query=_normalized_query(action.query))
            if observation.get("count") == 0:
                intent["empty"] = True
            if observation.get("status") == "exhausted":
                intent["exhausted"] = True
            self._searches.append(intent)
            self._searches = _dedupe_searches(self._searches)
        elif isinstance(action, RequestUserInputAction) and observation.get("status") == "defaults_applied":
            answers = {answer["question_id"]: answer for answer in observation.get("answers", [])}
            for question in action.questions:
                answer = answers.get(question["id"])
                if answer is None:
                    continue
                value = answer.get("selected_value", "")
                label = answer.get("label", value)
                self._requirements.append(
                    PlannerResolvedRequirement(
                        question_id=question["id"],
                        requirement_key=question.get("requirement_key", question["id"]),
                        kind=question.get("kind", "single_choice"),
                        question=question["question"],
                        answer=value,
                        label=label,
                        source="default",
                    )
                )
            self._requirements = _dedupe_requirements(self._requirements)
            _merge_requirement_summaries_into_session(
                self._planning_session,
                self._requirements,
                source_turn_id="planner-default",
            )
        self._records.append(
            _TrajectoryRecord(
                action=action,
                observation=copied,
                state_after=copy.deepcopy(self._state_after(action_count=len(self._records) + 1)),
            )
        )

    def checkpoint(self) -> PlannerContextCheckpointV3:
        """Return the small serializable state permitted across clarification requests."""
        checkpoint = copy.deepcopy(self._planning_session)
        checkpoint["searches"] = cast(list[dict[str, Any]], copy.deepcopy(_dedupe_searches(self._searches)))
        checkpoint["budget"] = cast(Any, copy.deepcopy(self._budget))
        if self._last_action_signature:
            checkpoint["last_action_signature"] = self._last_action_signature
        else:
            checkpoint.pop("last_action_signature", None)
        if self._assumptions:
            checkpoint["assumptions"] = list(self._assumptions)
        else:
            checkpoint.pop("assumptions", None)
        return checkpoint

    def apply_requirement_transition(self, transition: PlanningTransition) -> None:
        """Install one reducer-validated transition and refresh the stable prompt."""
        self._planning_session = copy.deepcopy(transition.session)
        self._requirements = _requirement_summaries_from_session(self._planning_session)
        self._base_messages = self._build_base_messages()
        self._stable_prefix_tokens = self._count_tokens(self._base_messages)

    def apply_planning_session(self, session: PlanningSessionState) -> None:
        """Install a reducer-produced session and refresh prompt state."""
        self._planning_session = copy.deepcopy(session)
        self._requirements = _requirement_summaries_from_session(self._planning_session)
        self._assumptions = list(self._planning_session.get("assumptions") or [])
        self._base_messages = self._build_base_messages()
        self._stable_prefix_tokens = self._count_tokens(self._base_messages)

    def note_truncation_recovery(self) -> None:
        self._planning_session["truncation_recoveries"] += 1

    def set_pending_clarification(self, *, clarification_id: str, questions: list[dict[str, Any]]) -> None:
        self.apply_planning_session(
            request_user_clarification(
                self._planning_session,
                clarification_id=clarification_id,
                questions=questions,
            )
        )

    def add_assumption(self, assumption: str) -> None:
        normalized = assumption.strip()
        if normalized and normalized not in self._assumptions:
            self._assumptions.append(normalized)

    @property
    def assumptions(self) -> tuple[str, ...]:
        return tuple(self._assumptions)

    def action_signature(self, action: PlannerAction) -> str:
        """Return a stable signature for cross-request no-progress detection."""
        return _compact_json(_action_payload(action))

    def is_repeated_action(self, action: PlannerAction) -> bool:
        return bool(self._last_action_signature) and self.action_signature(action) == self._last_action_signature

    def note_action(self, action: PlannerAction) -> None:
        self._last_action_signature = self.action_signature(action)

    def note_model_call(
        self,
        *,
        input_tokens: int,
        output: object,
        elapsed_ms: int,
        provider_usage: tuple[int, int] | None = None,
    ) -> None:
        """Accumulate observable model usage for the current planning goal."""
        output_message = [AssistantPromptMessage(content=_compact_json(output))]
        self._budget["model_actions"] += 1
        self._budget["model_elapsed_ms"] += max(elapsed_ms, 0)
        if provider_usage is None:
            measured_input_tokens = input_tokens
            measured_output_tokens = self._count_tokens(output_message)
        else:
            measured_input_tokens, measured_output_tokens = provider_usage
        self._budget["input_tokens"] += max(measured_input_tokens, 0)
        self._budget["output_tokens"] += max(measured_output_tokens, 0)

    def note_clarification(self) -> None:
        self._budget["clarification_rounds"] += 1

    @property
    def budget(self) -> PlannerBudgetState:
        return copy.deepcopy(self._budget)

    @property
    def context_window(self) -> int:
        return self._context_window

    @property
    def planning_session(self) -> PlanningSessionState:
        return copy.deepcopy(self._planning_session)

    @property
    def current_user_turn(self) -> UserTurn | None:
        active_turn = self._planning_session["active_turn"]
        if active_turn is not None:
            turn = UserTurn(id=active_turn["turn_id"], kind=active_turn["kind"])
            message = active_turn.get("message")
            if message:
                turn["message"] = message
            answers = active_turn.get("answers")
            if answers:
                turn["answers"] = copy.deepcopy(answers)
            return turn
        return None

    @property
    def resolved_requirement_keys(self) -> frozenset[str]:
        return frozenset(requirement["requirement_key"] for requirement in self._requirements)

    @property
    def pending_searches(self) -> tuple[PlannerSearchIntent, ...]:
        """Expose checkpoint search intents so the planner can refresh current resource results."""
        return tuple(copy.deepcopy(self._searches))

    @property
    def model_parameters(self) -> dict[str, Any]:
        return dict(self._model_parameters)

    @property
    def diagnostics(self) -> PlannerContextDiagnostics:
        utilization = self._prompt_tokens / self._input_limit if self._input_limit else 1.0
        return PlannerContextDiagnostics(
            provider=str(getattr(self._model_instance, "provider", "")),
            model=str(getattr(self._model_instance, "model_name", "")),
            context_window=self._context_window,
            context_window_source=self._context_window_source,
            input_limit=self._input_limit,
            prompt_tokens=self._prompt_tokens,
            utilization_ratio=utilization,
            compaction_mode=self._compaction_mode,
            action_count=len(self._records),
            stable_prefix_tokens=self._stable_prefix_tokens,
            observation_count=len(self._records),
        )


def start_planner_context(*, client: LLMJsonClient, request: PlannerInput) -> PlannerContextSession:
    """Narrow construction helper used by the planner control loop."""
    return PlannerContextSession.start(
        request=request,
        model_instance=client.model_instance,
        model_parameters=client.model_parameters,
        checkpoint=request.context_checkpoint,
    )
