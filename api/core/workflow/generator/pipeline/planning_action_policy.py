"""Deterministic authorization for typed workflow planning actions.

The planner model proposes actions; this module decides whether an action is
valid for the current phase and verified Requirement state. It has no model,
database, or resource-search side effects.
"""

from __future__ import annotations

from dataclasses import dataclass

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
)
from core.workflow.generator.pipeline.planning_types import PlanningSessionState, VerifiedResourceSnapshot


@dataclass(frozen=True)
class PlanningActionDenial:
    reason: str
    message: str


@dataclass(frozen=True)
class PlanningActionDecision:
    allowed: bool
    denial: PlanningActionDenial | None = None


def _deny(reason: str, message: str) -> PlanningActionDecision:
    return PlanningActionDecision(allowed=False, denial=PlanningActionDenial(reason=reason, message=message))


class PlanningActionPolicy:
    """Authorize one action against a serializable Planning Session snapshot."""

    def evaluate(
        self,
        session: PlanningSessionState,
        action: PlannerAction,
        resources: VerifiedResourceSnapshot,
    ) -> PlanningActionDecision:
        active_turn = session["active_turn"]
        if (
            active_turn is not None
            and active_turn["status"] == "pending_interpretation"
            and isinstance(action, (ResolveResourceAction, SubmitPlanAction))
        ):
            return _deny(
                "turn_pending_interpretation",
                "Interpret the active UserTurn before resolving resources or submitting a plan.",
            )
        if isinstance(action, (SearchKnowledgeAction, SearchToolsAction)):
            return _deny(
                "resource_intent_required",
                "Legacy resource searches must be replaced by resolve_resource linked to a Requirement.",
            )

        if session["phase"] == "understanding":
            if isinstance(action, (ResolveResourceAction, SubmitPlanAction)):
                return _deny(
                    "turn_pending_interpretation",
                    "Interpret the active UserTurn before resolving resources or submitting a plan.",
                )
            if isinstance(
                action,
                (
                    ResolveRequirementsAction,
                    AcknowledgeTurnAction,
                    RequestUserInputAction,
                    RespondToUserAction,
                    ReplaceInstructionAction,
                ),
            ):
                return PlanningActionDecision(allowed=True)

        if session["phase"] == "ready":
            if isinstance(action, (ResolveRequirementsAction, AcknowledgeTurnAction)):
                return _deny("turn_already_interpreted", "The active UserTurn has already been interpreted.")
            if isinstance(action, SubmitPlanAction):
                return self._evaluate_plan_resources(session, action, resources)
            if isinstance(
                action,
                (RequestUserInputAction, ReplaceInstructionAction, RespondToUserAction),
            ):
                return PlanningActionDecision(allowed=True)
            if isinstance(action, ResolveResourceAction):
                return self._evaluate_resource(session, action)

        return _deny("action_not_allowed_in_phase", f"The action is not allowed in phase {session['phase']!r}.")

    def _evaluate_resource(
        self,
        session: PlanningSessionState,
        action: ResolveResourceAction,
    ) -> PlanningActionDecision:
        requirement = session["requirements"].get(action.requirement_key)
        if requirement is None or requirement["status"] != "resolved":
            return _deny("requirement_not_resolved", "resolve_resource must reference a resolved Requirement.")
        answer = requirement["answer"]
        if answer["kind"] != "resource_mode":
            return _deny("resource_mode_required", "The referenced Requirement must contain resource_mode.")
        if answer["source"] != "workspace" or answer["binding_time"] != "design_time":
            return _deny(
                "workspace_design_time_required",
                "Workspace search is allowed only for workspace resources bound at design time.",
            )
        if answer["resource_kind"] != action.resource_kind:
            return _deny("resource_kind_mismatch", "Resource kind does not match the referenced Requirement.")
        binding = session["resource_bindings"].get(action.intent_id)
        if binding is not None and binding.get("requirement_key") != action.requirement_key:
            return _deny("resource_binding_conflict", "The Resource Intent already has a conflicting Binding.")
        intent = session["resource_intents"].get(action.intent_id)
        if intent is not None and intent["status"] == "exhausted":
            return _deny("resource_intent_exhausted", "The Resource Intent is exhausted after two empty queries.")
        return PlanningActionDecision(allowed=True)

    def _evaluate_plan_resources(
        self,
        session: PlanningSessionState,
        action: SubmitPlanAction,
        resources: VerifiedResourceSnapshot,
    ) -> PlanningActionDecision:
        valid_bindings = []
        for binding in session["resource_bindings"].values():
            requirement = session["requirements"].get(binding["requirement_key"])
            intent = session["resource_intents"].get(binding["intent_id"])
            if requirement is None or requirement["answer"]["kind"] != "resource_mode":
                continue
            answer = requirement["answer"]
            if answer["source"] != "workspace" or answer["binding_time"] != "design_time":
                continue
            if answer["resource_kind"] != binding["resource_kind"]:
                continue
            if intent is None or intent["status"] != "bound" or intent["requirement_key"] != binding["requirement_key"]:
                continue
            valid_bindings.append(binding)
        bound_dataset_ids = {
            binding["resource_id"] for binding in valid_bindings if binding["resource_kind"] == "dataset"
        }
        bound_tool_ids = {binding["resource_id"] for binding in valid_bindings if binding["resource_kind"] == "tool"}
        requests = action.plan.get("resource_requests", [])
        if not isinstance(requests, list):
            return _deny("unbound_plan_resource", "Plan resource_requests must be a list of bound resources.")
        for request in requests:
            if not isinstance(request, dict):
                return _deny("unbound_plan_resource", "Plan resource request is malformed.")
            if request.get("kind") == "dataset":
                resource_id = request.get("dataset_id")
                if not isinstance(resource_id, str) or resource_id not in bound_dataset_ids:
                    return _deny("unbound_plan_resource", "Plan references a dataset outside Resource Bindings.")
                if resource_id not in resources.dataset_ids:
                    return _deny("resource_binding_stale", "The bound dataset is no longer available to this tenant.")
            elif request.get("kind") == "tool":
                provider_name = request.get("provider_name")
                tool_name = request.get("tool_name")
                resource_id = f"{provider_name}:{tool_name}"
                if (
                    not isinstance(provider_name, str)
                    or not isinstance(tool_name, str)
                    or resource_id not in bound_tool_ids
                ):
                    return _deny("unbound_plan_resource", "Plan references a tool outside Resource Bindings.")
                if resource_id not in resources.tool_ids:
                    return _deny("resource_binding_stale", "The bound tool is no longer available to this tenant.")
            else:
                return _deny("unbound_plan_resource", "Plan resource kind is unsupported.")
        return PlanningActionDecision(allowed=True)
