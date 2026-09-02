"""Typed, provider-neutral actions accepted from the workflow planner model.

The planner uses a JSON action protocol instead of native function calling so
the same behavior works across all configured LLM providers. This module is the
single validation seam: orchestration code only handles the frozen action
types below and never branches on untrusted model dictionaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict, cast

from core.workflow.generator.llm_response import StageSchemaError
from core.workflow.generator.types import PlannerResultDict


class ClarificationOptionDict(TypedDict):
    value: str
    label: str
    description: str
    recommended: bool


class ResourceCandidateDict(TypedDict):
    id: str
    label: str
    description: str


class ClarificationQuestionDict(TypedDict):
    id: str
    requirement_key: str
    kind: Literal["text", "single_choice", "multi_choice", "resource_select"]
    question: str
    required: NotRequired[bool]
    options: NotRequired[list[ClarificationOptionDict]]
    allow_other: NotRequired[bool]
    default_value: NotRequired[str]
    default_values: NotRequired[list[str]]
    resource_kind: NotRequired[Literal["dataset", "tool"]]
    multiple: NotRequired[bool]
    candidates: NotRequired[list[ResourceCandidateDict]]
    default_resource_ids: NotRequired[list[str]]


class TextRequirementAnswer(TypedDict):
    kind: Literal["text"]
    text: str


class SingleChoiceRequirementAnswer(TypedDict):
    kind: Literal["single_choice"]
    value: str


class MultiChoiceRequirementAnswer(TypedDict):
    kind: Literal["multi_choice"]
    values: list[str]


class ResourceRequirementAnswer(TypedDict):
    kind: Literal["resource_select"]
    resource_kind: Literal["dataset", "tool"]
    resource_ids: list[str]


class ResourceModeRequirementAnswer(TypedDict):
    kind: Literal["resource_mode"]
    resource_kind: Literal["dataset", "tool"]
    source: Literal["workspace", "runtime_input", "external"]
    binding_time: Literal["design_time", "runtime"]


RequirementAnswer = (
    TextRequirementAnswer
    | SingleChoiceRequirementAnswer
    | MultiChoiceRequirementAnswer
    | ResourceRequirementAnswer
    | ResourceModeRequirementAnswer
)


class RequirementResolution(TypedDict):
    requirement_key: str
    answer: RequirementAnswer
    evidence: str


@dataclass(frozen=True)
class SearchToolsAction:
    query: str


@dataclass(frozen=True)
class SearchKnowledgeAction:
    query: str


@dataclass(frozen=True)
class RequestUserInputAction:
    questions: tuple[ClarificationQuestionDict, ...]
    message: str = ""


@dataclass(frozen=True)
class RespondToUserAction:
    message: str


@dataclass(frozen=True)
class ReplaceInstructionAction:
    instruction: str


@dataclass(frozen=True)
class ResolveRequirementsAction:
    resolutions: tuple[RequirementResolution, ...]


@dataclass(frozen=True)
class AcknowledgeTurnAction:
    pass


@dataclass(frozen=True)
class ResolveResourceAction:
    intent_id: str
    requirement_key: str
    resource_kind: Literal["dataset", "tool"]
    binding_time: Literal["design_time"]
    query: str


@dataclass(frozen=True)
class SubmitPlanAction:
    plan: PlannerResultDict | dict[str, Any]
    assumptions: tuple[str, ...]


PlannerAction = (
    SearchToolsAction
    | SearchKnowledgeAction
    | RequestUserInputAction
    | RespondToUserAction
    | ReplaceInstructionAction
    | ResolveRequirementsAction
    | AcknowledgeTurnAction
    | ResolveResourceAction
    | SubmitPlanAction
)


_REQUIREMENT_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


def _require_exact_fields(parsed: dict[str, Any], expected: set[str]) -> None:
    unexpected = sorted(set(parsed).difference(expected))
    if unexpected:
        raise StageSchemaError("Planner", f"action contains unexpected fields: {unexpected!r}")


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StageSchemaError("Planner", f"'{field}' must be a non-empty string")
    return value.strip()


def is_deferred_answer_text(value: str) -> bool:
    """Return whether a value describes a future input action instead of an answer."""
    combined = value.casefold()
    deferred_markers = (
        "paste_",
        "provide_later",
        "next_message",
        "next message",
        "will provide",
        "provide it later",
        "paste it in",
        "稍后",
        "下一条",
        "下一步粘贴",
        "稍后提供",
    )
    return any(marker in combined for marker in deferred_markers)


def _is_deferred_meta_answer(option: ClarificationOptionDict) -> bool:
    combined = " ".join((option["value"], option["label"], option["description"]))
    return is_deferred_answer_text(combined)


def _parse_options(value: object, question_index: int) -> list[ClarificationOptionDict]:
    if not isinstance(value, list) or not 2 <= len(value) <= 5:
        raise StageSchemaError("Planner", f"questions[{question_index}].options must contain between 2 and 5 items")
    options: list[ClarificationOptionDict] = []
    seen_values: set[str] = set()
    for option_index, raw_option in enumerate(value):
        if not isinstance(raw_option, dict):
            raise StageSchemaError("Planner", f"questions[{question_index}].options[{option_index}] must be an object")
        _require_exact_fields(raw_option, {"value", "label", "description", "recommended"})
        value_text = _non_empty_string(
            raw_option.get("value"), f"questions[{question_index}].options[{option_index}].value"
        )
        if value_text in seen_values:
            raise StageSchemaError("Planner", f"duplicate option value: {value_text!r}")
        seen_values.add(value_text)
        options.append(
            ClarificationOptionDict(
                value=value_text,
                label=_non_empty_string(
                    raw_option.get("label"), f"questions[{question_index}].options[{option_index}].label"
                ),
                description=_non_empty_string(
                    raw_option.get("description"),
                    f"questions[{question_index}].options[{option_index}].description",
                ),
                recommended=raw_option.get("recommended") is True,
            )
        )
    if not options[0]["recommended"]:
        raise StageSchemaError("Planner", f"questions[{question_index}] first option must be recommended")
    if sum(option["recommended"] for option in options) != 1:
        raise StageSchemaError("Planner", f"questions[{question_index}] must have exactly one recommended option")
    if _is_deferred_meta_answer(options[0]):
        raise StageSchemaError(
            "Planner",
            f"questions[{question_index}] recommended option must be an answer the user can immediately submit",
        )
    return options


def _parse_resource_candidates(value: object, question_index: int) -> list[ResourceCandidateDict]:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise StageSchemaError("Planner", f"questions[{question_index}].candidates must contain between 1 and 20 items")
    candidates: list[ResourceCandidateDict] = []
    seen_ids: set[str] = set()
    for candidate_index, raw_candidate in enumerate(value):
        if not isinstance(raw_candidate, dict):
            raise StageSchemaError(
                "Planner", f"questions[{question_index}].candidates[{candidate_index}] must be an object"
            )
        _require_exact_fields(raw_candidate, {"id", "label", "description"})
        candidate_id = _non_empty_string(
            raw_candidate.get("id"), f"questions[{question_index}].candidates[{candidate_index}].id"
        )
        if candidate_id in seen_ids:
            raise StageSchemaError("Planner", f"duplicate resource candidate id: {candidate_id!r}")
        seen_ids.add(candidate_id)
        candidates.append(
            ResourceCandidateDict(
                id=candidate_id,
                label=_non_empty_string(
                    raw_candidate.get("label"), f"questions[{question_index}].candidates[{candidate_index}].label"
                ),
                description=_non_empty_string(
                    raw_candidate.get("description"),
                    f"questions[{question_index}].candidates[{candidate_index}].description",
                ),
            )
        )
    return candidates


def _parse_requirement_answer(value: object, resolution_index: int) -> RequirementAnswer:
    field = f"resolutions[{resolution_index}].answer"
    if not isinstance(value, dict):
        raise StageSchemaError("Planner", f"'{field}' must be an object")
    kind = value.get("kind")
    if kind == "text":
        _require_exact_fields(value, {"kind", "text"})
        text = _non_empty_string(value.get("text"), f"{field}.text")
        if is_deferred_answer_text(text):
            raise StageSchemaError("Planner", f"'{field}.text' must be an actual answer")
        return TextRequirementAnswer(kind="text", text=text)
    if kind == "single_choice":
        _require_exact_fields(value, {"kind", "value"})
        selected = _non_empty_string(value.get("value"), f"{field}.value")
        if is_deferred_answer_text(selected):
            raise StageSchemaError("Planner", f"'{field}.value' must be an actual answer")
        return SingleChoiceRequirementAnswer(kind="single_choice", value=selected)
    if kind == "multi_choice":
        _require_exact_fields(value, {"kind", "values"})
        raw_values = value.get("values")
        if not isinstance(raw_values, list) or not 1 <= len(raw_values) <= 16:
            raise StageSchemaError("Planner", f"'{field}.values' must contain between 1 and 16 answers")
        selected_values = [_non_empty_string(item, f"{field}.values") for item in raw_values]
        if len(set(selected_values)) != len(selected_values):
            raise StageSchemaError("Planner", f"'{field}.values' must not contain duplicates")
        if any(is_deferred_answer_text(item) for item in selected_values):
            raise StageSchemaError("Planner", f"'{field}.values' must contain actual answers")
        return MultiChoiceRequirementAnswer(kind="multi_choice", values=selected_values)
    if kind == "resource_select":
        _require_exact_fields(value, {"kind", "resource_kind", "resource_ids"})
        resource_kind = value.get("resource_kind")
        if resource_kind not in {"dataset", "tool"}:
            raise StageSchemaError("Planner", f"'{field}.resource_kind' must be dataset or tool")
        raw_resource_ids = value.get("resource_ids")
        if not isinstance(raw_resource_ids, list) or not 1 <= len(raw_resource_ids) <= 20:
            raise StageSchemaError("Planner", f"'{field}.resource_ids' must contain between 1 and 20 IDs")
        resource_ids = [_non_empty_string(item, f"{field}.resource_ids") for item in raw_resource_ids]
        if len(set(resource_ids)) != len(resource_ids):
            raise StageSchemaError("Planner", f"'{field}.resource_ids' must not contain duplicates")
        return ResourceRequirementAnswer(
            kind="resource_select",
            resource_kind=cast(Any, resource_kind),
            resource_ids=resource_ids,
        )
    if kind == "resource_mode":
        _require_exact_fields(value, {"kind", "resource_kind", "source", "binding_time"})
        resource_kind = value.get("resource_kind")
        source = value.get("source")
        binding_time = value.get("binding_time")
        if resource_kind not in {"dataset", "tool"}:
            raise StageSchemaError("Planner", f"'{field}.resource_kind' must be dataset or tool")
        if source not in {"workspace", "runtime_input", "external"}:
            raise StageSchemaError("Planner", f"'{field}.source' is unsupported: {source!r}")
        if binding_time not in {"design_time", "runtime"}:
            raise StageSchemaError("Planner", f"'{field}.binding_time' is unsupported: {binding_time!r}")
        return ResourceModeRequirementAnswer(
            kind="resource_mode",
            resource_kind=cast(Any, resource_kind),
            source=cast(Any, source),
            binding_time=cast(Any, binding_time),
        )
    raise StageSchemaError("Planner", f"'{field}.kind' is unsupported: {kind!r}")


def _parse_requirement_resolutions(value: object) -> tuple[RequirementResolution, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        raise StageSchemaError("Planner", "'resolutions' must contain between 1 and 16 items")
    resolutions: list[RequirementResolution] = []
    seen_keys: set[str] = set()
    for resolution_index, raw_resolution in enumerate(value):
        if not isinstance(raw_resolution, dict):
            raise StageSchemaError("Planner", f"resolutions[{resolution_index}] must be an object")
        _require_exact_fields(raw_resolution, {"requirement_key", "answer", "evidence"})
        requirement_key = _non_empty_string(
            raw_resolution.get("requirement_key"), f"resolutions[{resolution_index}].requirement_key"
        )
        if _REQUIREMENT_KEY_PATTERN.fullmatch(requirement_key) is None:
            raise StageSchemaError(
                "Planner", f"resolutions[{resolution_index}].requirement_key has an invalid format"
            )
        if requirement_key in seen_keys:
            raise StageSchemaError("Planner", f"duplicate requirement_key: {requirement_key!r}")
        seen_keys.add(requirement_key)
        evidence = _non_empty_string(raw_resolution.get("evidence"), f"resolutions[{resolution_index}].evidence")
        if len(evidence) > 500:
            raise StageSchemaError(
                "Planner", f"resolutions[{resolution_index}].evidence must be at most 500 characters"
            )
        resolutions.append(
            RequirementResolution(
                requirement_key=requirement_key,
                answer=_parse_requirement_answer(raw_resolution.get("answer"), resolution_index),
                evidence=evidence,
            )
        )
    return tuple(resolutions)


def _parse_questions(value: object) -> tuple[ClarificationQuestionDict, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        raise StageSchemaError("Planner", "'questions' must contain between 1 and 3 items")
    questions: list[ClarificationQuestionDict] = []
    seen_question_ids: set[str] = set()
    for question_index, raw_question in enumerate(value):
        if not isinstance(raw_question, dict):
            raise StageSchemaError("Planner", f"questions[{question_index}] must be an object")
        kind = raw_question.get("kind", "single_choice")
        if kind not in {"text", "single_choice", "multi_choice", "resource_select"}:
            raise StageSchemaError("Planner", f"questions[{question_index}].kind is unsupported: {kind!r}")
        common_fields = {"id", "requirement_key", "kind", "question"}
        fields_by_kind = {
            "text": common_fields | {"required"},
            "single_choice": common_fields | {"options", "allow_other", "default_value"},
            "multi_choice": common_fields | {"options", "default_values"},
            "resource_select": common_fields
            | {"resource_kind", "multiple", "candidates", "default_resource_ids"},
        }
        _require_exact_fields(raw_question, fields_by_kind[cast(str, kind)])
        question_id = _non_empty_string(raw_question.get("id"), f"questions[{question_index}].id")
        if question_id in seen_question_ids:
            raise StageSchemaError("Planner", f"duplicate question id: {question_id!r}")
        seen_question_ids.add(question_id)
        requirement_key = _non_empty_string(
            raw_question.get("requirement_key", question_id), f"questions[{question_index}].requirement_key"
        )
        question_text = _non_empty_string(raw_question.get("question"), f"questions[{question_index}].question")
        base_question: ClarificationQuestionDict = {
            "id": question_id,
            "requirement_key": requirement_key,
            "kind": cast(Any, kind),
            "question": question_text,
        }
        if kind == "text":
            required = raw_question.get("required", True)
            if not isinstance(required, bool):
                raise StageSchemaError("Planner", f"questions[{question_index}].required must be a boolean")
            base_question["required"] = required
        elif kind in {"single_choice", "multi_choice"}:
            options = _parse_options(raw_question.get("options"), question_index)
            base_question["options"] = options
            option_values = {option["value"] for option in options}
            if kind == "single_choice":
                allow_other = raw_question.get("allow_other", True)
                if not isinstance(allow_other, bool):
                    raise StageSchemaError("Planner", f"questions[{question_index}].allow_other must be a boolean")
                base_question["allow_other"] = allow_other
                default_value = raw_question.get("default_value", options[0]["value"])
                if not isinstance(default_value, str) or default_value not in option_values:
                    raise StageSchemaError("Planner", f"questions[{question_index}].default_value must match an option")
                base_question["default_value"] = default_value
            else:
                default_values = raw_question.get(
                    "default_values", [option["value"] for option in options if option["recommended"]]
                )
                if (
                    not isinstance(default_values, list)
                    or not all(isinstance(item, str) for item in default_values)
                    or not set(default_values).issubset(option_values)
                ):
                    raise StageSchemaError("Planner", f"questions[{question_index}].default_values must match options")
                base_question["default_values"] = cast(list[str], default_values)
        else:
            resource_kind = raw_question.get("resource_kind")
            if resource_kind not in {"dataset", "tool"}:
                raise StageSchemaError("Planner", f"questions[{question_index}].resource_kind must be dataset or tool")
            multiple = raw_question.get("multiple", False)
            if not isinstance(multiple, bool):
                raise StageSchemaError("Planner", f"questions[{question_index}].multiple must be a boolean")
            candidates = _parse_resource_candidates(raw_question.get("candidates"), question_index)
            candidate_ids = {candidate["id"] for candidate in candidates}
            default_resource_ids = raw_question.get("default_resource_ids", [])
            if (
                not isinstance(default_resource_ids, list)
                or not all(isinstance(item, str) for item in default_resource_ids)
                or not set(default_resource_ids).issubset(candidate_ids)
                or (not multiple and len(default_resource_ids) > 1)
            ):
                raise StageSchemaError(
                    "Planner", f"questions[{question_index}].default_resource_ids must match a resource candidate"
                )
            base_question["resource_kind"] = cast(Any, resource_kind)
            base_question["multiple"] = multiple
            base_question["candidates"] = candidates
            base_question["default_resource_ids"] = cast(list[str], default_resource_ids)
        questions.append(base_question)
    return tuple(questions)


def parse_planner_action(parsed: dict[str, Any]) -> PlannerAction:
    """Validate one model object and return the corresponding typed action.

    A legacy object containing ``nodes`` but no ``action`` is accepted as a
    submit action. This keeps existing non-interactive callers and recorded
    model fixtures compatible while the prompt migrates to the action protocol.
    """
    action_name = parsed.get("action")
    if action_name is None and "nodes" in parsed:
        return SubmitPlanAction(plan=cast(dict[str, Any], parsed), assumptions=())
    if action_name == "search_tools":
        _require_exact_fields(parsed, {"action", "query"})
        return SearchToolsAction(query=_non_empty_string(parsed.get("query"), "query"))
    if action_name == "search_knowledge":
        _require_exact_fields(parsed, {"action", "query"})
        return SearchKnowledgeAction(query=_non_empty_string(parsed.get("query"), "query"))
    if action_name == "request_user_input":
        _require_exact_fields(parsed, {"action", "message", "questions"})
        message = parsed.get("message", "")
        if not isinstance(message, str):
            raise StageSchemaError("Planner", "'message' must be a string")
        return RequestUserInputAction(questions=_parse_questions(parsed.get("questions")), message=message.strip())
    if action_name == "respond_to_user":
        _require_exact_fields(parsed, {"action", "message"})
        return RespondToUserAction(message=_non_empty_string(parsed.get("message"), "message"))
    if action_name == "replace_instruction":
        _require_exact_fields(parsed, {"action", "instruction"})
        return ReplaceInstructionAction(instruction=_non_empty_string(parsed.get("instruction"), "instruction"))
    if action_name == "resolve_requirements":
        _require_exact_fields(parsed, {"action", "resolutions"})
        return ResolveRequirementsAction(resolutions=_parse_requirement_resolutions(parsed.get("resolutions")))
    if action_name == "acknowledge_turn":
        _require_exact_fields(parsed, {"action"})
        return AcknowledgeTurnAction()
    if action_name == "resolve_resource":
        _require_exact_fields(
            parsed,
            {"action", "intent_id", "requirement_key", "resource_kind", "binding_time", "query"},
        )
        requirement_key = _non_empty_string(parsed.get("requirement_key"), "requirement_key")
        if _REQUIREMENT_KEY_PATTERN.fullmatch(requirement_key) is None:
            raise StageSchemaError("Planner", "'requirement_key' has an invalid format")
        resource_kind = parsed.get("resource_kind")
        if resource_kind not in {"dataset", "tool"}:
            raise StageSchemaError("Planner", "'resource_kind' must be dataset or tool")
        if parsed.get("binding_time") != "design_time":
            raise StageSchemaError("Planner", "'binding_time' must be design_time")
        return ResolveResourceAction(
            intent_id=_non_empty_string(parsed.get("intent_id"), "intent_id"),
            requirement_key=requirement_key,
            resource_kind=cast(Any, resource_kind),
            binding_time="design_time",
            query=_non_empty_string(parsed.get("query"), "query"),
        )
    if action_name == "submit_plan":
        _require_exact_fields(parsed, {"action", "plan", "assumptions"})
        plan = parsed.get("plan")
        assumptions = parsed.get("assumptions")
        if not isinstance(plan, dict):
            raise StageSchemaError("Planner", "'plan' must be an object")
        if not isinstance(assumptions, list) or not all(isinstance(item, str) for item in assumptions):
            raise StageSchemaError("Planner", "'assumptions' must be an array of strings")
        return SubmitPlanAction(
            plan=cast(dict[str, Any], plan),
            assumptions=tuple(item.strip() for item in assumptions if item.strip()),
        )
    raise StageSchemaError("Planner", f"unknown planner action: {action_name!r}")
