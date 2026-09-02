from core.workflow.generator.planner_actions import (
    ResolveRequirementsAction,
    ResolveResourceAction,
    SearchKnowledgeAction,
    SubmitPlanAction,
)
from core.workflow.generator.planning_action_policy import PlanningActionPolicy
from core.workflow.generator.planning_session import (
    RequirementState,
    UserTurn,
    VerifiedResourceSnapshot,
    begin_user_turn,
    empty_planning_session,
)


def _snapshot() -> VerifiedResourceSnapshot:
    return VerifiedResourceSnapshot(dataset_ids=frozenset(), tool_ids=frozenset())


def _resolve_resource() -> ResolveResourceAction:
    return ResolveResourceAction(
        intent_id="rag-source",
        requirement_key="rag.source",
        resource_kind="dataset",
        binding_time="design_time",
        query="product docs",
    )


def _session_with_dataset_binding():
    session = empty_planning_session("goal-1", "Use product docs")
    session["requirements"]["rag.source"] = RequirementState(
        status="resolved",
        answer={
            "kind": "resource_mode",
            "resource_kind": "dataset",
            "source": "workspace",
            "binding_time": "design_time",
        },
        source_turn_id="turn-1",
        revision=1,
    )
    session["resource_intents"]["rag-source"] = {
        "intent_id": "rag-source",
        "requirement_key": "rag.source",
        "resource_kind": "dataset",
        "binding_time": "design_time",
        "query": "Product docs",
        "status": "bound",
        "empty_queries": [],
    }
    session["resource_bindings"]["rag-source"] = {
        "intent_id": "rag-source",
        "requirement_key": "rag.source",
        "resource_kind": "dataset",
        "resource_id": "dataset-1",
        "resource_name": "Product docs",
        "revision": 2,
    }
    return session


def test_understanding_phase_rejects_resource_resolution_and_plan_submission():
    session = begin_user_turn(
        empty_planning_session("goal-1", "Test RAG"),
        UserTurn(id="turn-1", kind="message", message="Test RAG", expected_revision=0),
    )
    policy = PlanningActionPolicy()

    resource_decision = policy.evaluate(session, _resolve_resource(), _snapshot())
    submit_decision = policy.evaluate(
        session,
        SubmitPlanAction(plan={"nodes": [], "edges": []}, assumptions=()),
        _snapshot(),
    )

    assert resource_decision.allowed is False
    assert resource_decision.denial is not None
    assert resource_decision.denial.reason == "turn_pending_interpretation"
    assert submit_decision.allowed is False


def test_pending_turn_status_rejects_submit_even_if_checkpoint_phase_is_inconsistent():
    session = begin_user_turn(
        empty_planning_session("goal-1", "Test RAG"),
        UserTurn(id="turn-1", kind="message", message="Test RAG", expected_revision=0),
    )
    session["phase"] = "ready"

    decision = PlanningActionPolicy().evaluate(
        session,
        SubmitPlanAction(plan={"nodes": [], "edges": []}, assumptions=()),
        _snapshot(),
    )

    assert decision.allowed is False
    assert decision.denial is not None
    assert decision.denial.reason == "turn_pending_interpretation"


def test_v4_policy_rejects_legacy_unscoped_search():
    session = empty_planning_session("goal-1", "Use product docs")

    decision = PlanningActionPolicy().evaluate(session, SearchKnowledgeAction(query="docs"), _snapshot())

    assert decision.allowed is False
    assert decision.denial is not None
    assert decision.denial.reason == "resource_intent_required"


def test_resource_resolution_requires_workspace_design_time_requirement():
    session = empty_planning_session("goal-1", "Test RAG")
    session["requirements"]["rag.source"] = RequirementState(
        status="resolved",
        answer={
            "kind": "resource_mode",
            "resource_kind": "dataset",
            "source": "runtime_input",
            "binding_time": "runtime",
        },
        source_turn_id="turn-1",
        revision=1,
    )

    decision = PlanningActionPolicy().evaluate(session, _resolve_resource(), _snapshot())

    assert decision.allowed is False
    assert decision.denial is not None
    assert decision.denial.reason == "workspace_design_time_required"


def test_resource_resolution_is_allowed_for_matching_workspace_requirement():
    session = empty_planning_session("goal-1", "Use product docs")
    session["requirements"]["rag.source"] = RequirementState(
        status="resolved",
        answer={
            "kind": "resource_mode",
            "resource_kind": "dataset",
            "source": "workspace",
            "binding_time": "design_time",
        },
        source_turn_id="turn-1",
        revision=1,
    )

    decision = PlanningActionPolicy().evaluate(session, _resolve_resource(), _snapshot())

    assert decision.allowed is True
    assert decision.denial is None


def test_ready_phase_rejects_reinterpreting_the_same_turn():
    session = empty_planning_session("goal-1", "Test RAG")

    decision = PlanningActionPolicy().evaluate(
        session,
        ResolveRequirementsAction(resolutions=()),
        _snapshot(),
    )

    assert decision.allowed is False
    assert decision.denial is not None
    assert decision.denial.reason == "turn_already_interpreted"


def test_submit_plan_rejects_resource_ids_outside_current_bindings():
    session = _session_with_dataset_binding()
    action = SubmitPlanAction(
        plan={
            "nodes": [],
            "edges": [],
            "resource_requests": [
                {
                    "kind": "dataset",
                    "dataset_id": "invented-dataset",
                    "dataset_name": "Invented",
                    "reason": "Use it",
                }
            ],
        },
        assumptions=(),
    )

    decision = PlanningActionPolicy().evaluate(session, action, _snapshot())

    assert decision.allowed is False
    assert decision.denial is not None
    assert decision.denial.reason == "unbound_plan_resource"


def test_submit_plan_rejects_a_binding_missing_from_current_tenant_snapshot():
    session = _session_with_dataset_binding()
    action = SubmitPlanAction(
        plan={
            "nodes": [],
            "edges": [],
            "resource_requests": [
                {
                    "kind": "dataset",
                    "dataset_id": "dataset-1",
                    "dataset_name": "Product docs",
                    "reason": "Use it",
                }
            ],
        },
        assumptions=(),
    )

    stale = PlanningActionPolicy().evaluate(session, action, _snapshot())
    current = PlanningActionPolicy().evaluate(
        session,
        action,
        VerifiedResourceSnapshot(dataset_ids=frozenset({"dataset-1"}), tool_ids=frozenset()),
    )

    assert stale.allowed is False
    assert stale.denial is not None
    assert stale.denial.reason == "resource_binding_stale"
    assert current.allowed is True
