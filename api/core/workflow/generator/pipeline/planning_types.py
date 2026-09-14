"""Typed planning state, user turns, requirements, and transition errors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict

from core.workflow.generator.model_io.llm_response import StageSchemaError
from core.workflow.generator.pipeline.planner_actions import (
    RequirementAnswer,
)


class PlannerRequirementInvalidError(StageSchemaError):
    """Raised when a proposed Requirement transition fails deterministic validation."""

    def __init__(self, detail: str) -> None:
        super().__init__("Planner", detail)


class UserTurn(TypedDict):
    id: str
    kind: Literal["message", "clarification_response"]
    message: NotRequired[str]
    answers: NotRequired[list[dict[str, Any]]]
    expected_revision: NotRequired[int]


class ActiveUserTurn(TypedDict):
    turn_id: str
    kind: Literal["message", "clarification_response"]
    status: Literal["pending_interpretation", "interpreted"]
    message: NotRequired[str]
    answers: NotRequired[list[dict[str, Any]]]
    expected_revision: NotRequired[int]


@dataclass(frozen=True)
class VerifiedResourceSnapshot:
    dataset_ids: frozenset[str]
    tool_ids: frozenset[str]


class RequirementState(TypedDict):
    status: Literal["resolved"]
    answer: RequirementAnswer
    source_turn_id: str
    revision: int
    label: NotRequired[str]


class RequirementHistoryEntry(TypedDict):
    requirement_key: str
    answer: RequirementAnswer
    source_turn_id: str
    revision: int
    superseded_by_revision: int


class PlanningBudgetState(TypedDict):
    model_actions: int
    model_elapsed_ms: int
    input_tokens: int
    output_tokens: int
    clarification_rounds: int


class ResourceCandidate(TypedDict):
    id: str
    label: str
    description: str


class ResourceIntentState(TypedDict):
    intent_id: str
    requirement_key: str
    resource_kind: Literal["dataset", "tool"]
    binding_time: Literal["design_time"]
    query: str
    status: Literal["resolving", "pending", "bound", "exhausted"]
    empty_queries: list[str]


class ResourceBindingState(TypedDict):
    intent_id: str
    requirement_key: str
    resource_kind: Literal["dataset", "tool"]
    resource_id: str
    resource_name: str
    revision: int


class SearchObservation(TypedDict):
    intent_id: str
    resource_kind: Literal["dataset", "tool"]
    query: str
    status: Literal["ok", "empty", "exhausted", "unavailable"]
    count: int


class PlanningSessionState(TypedDict):
    version: Literal[4]
    revision: int
    goal_id: str
    phase: Literal[
        "understanding",
        "ready",
        "resolving_resource",
        "waiting_user",
        "completed",
        "failed_recoverable",
    ]
    active_instruction: str
    active_turn: ActiveUserTurn | None
    requirements: dict[str, RequirementState]
    requirement_history: list[RequirementHistoryEntry]
    pending_clarification: dict[str, Any]
    searches: list[dict[str, Any]]
    resource_intents: dict[str, ResourceIntentState]
    resource_bindings: dict[str, ResourceBindingState]
    search_observations: list[SearchObservation | dict[str, Any]]
    budget: PlanningBudgetState
    truncation_recoveries: int
    last_action_signature: NotRequired[str]
    assumptions: NotRequired[list[str]]


class RequirementTransitionObservation(TypedDict):
    action: Literal["requirements_resolved"]
    status: Literal["applied"]
    resolved_requirement_keys: list[str]
    revision: int


class RequirementTransitionEvent(TypedDict):
    action: Literal["requirements_resolved"]
    count: int
    requirement_keys: list[str]
    labels: list[str]


class ResourceBoundEvent(TypedDict):
    action: Literal["resource_bound"]
    intent_id: str
    resource_kind: Literal["dataset", "tool"]
    resource_name: str


@dataclass(frozen=True)
class PlanningTransition:
    session: PlanningSessionState
    observation: RequirementTransitionObservation
    public_event: RequirementTransitionEvent


@dataclass(frozen=True)
class ResourceResolutionTransition:
    session: PlanningSessionState
    observation: SearchObservation
    public_event: ResourceBoundEvent | None
