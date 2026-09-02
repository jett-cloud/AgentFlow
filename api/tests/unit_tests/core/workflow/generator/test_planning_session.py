import pytest

from core.workflow.generator.llm_response import StageSchemaError
from core.workflow.generator.planner_actions import (
    RequirementResolution,
    ResolveRequirementsAction,
    ResolveResourceAction,
)
from core.workflow.generator.planning_session import (
    ResourceCandidate,
    UserTurn,
    VerifiedResourceSnapshot,
    acknowledge_user_turn,
    begin_user_turn,
    complete_planning_session,
    complete_resource_resolution,
    empty_planning_session,
    normalize_planning_session,
    reduce_planning_session,
    reduce_structured_clarification,
    request_user_clarification,
    start_resource_resolution,
)


def _resolution(
    requirement_key: str,
    text: str,
    evidence: str,
) -> RequirementResolution:
    return RequirementResolution(
        requirement_key=requirement_key,
        answer={"kind": "text", "text": text},
        evidence=evidence,
    )


def _turn(message: str, *, expected_revision: int | None = None) -> UserTurn:
    turn = UserTurn(id="turn-1", kind="message", message=message)
    if expected_revision is not None:
        turn["expected_revision"] = expected_revision
    return turn


def test_user_turn_gate_moves_from_understanding_to_ready():
    initial = empty_planning_session("goal-1", "Test RAG")
    understanding = begin_user_turn(initial, _turn("Test RAG", expected_revision=0))

    assert understanding["version"] == 4
    assert understanding["revision"] == 1
    assert understanding["phase"] == "understanding"
    assert understanding["active_turn"] == {
        "turn_id": "turn-1",
        "kind": "message",
        "status": "pending_interpretation",
        "message": "Test RAG",
        "expected_revision": 0,
    }

    ready = acknowledge_user_turn(understanding, turn_id="turn-1")

    assert ready["revision"] == 2


def test_clarification_and_plan_are_revisioned_terminal_transitions():
    understanding = begin_user_turn(
        empty_planning_session("goal-1", "Test RAG"),
        _turn("Test RAG", expected_revision=0),
    )

    waiting = request_user_clarification(
        understanding,
        clarification_id="clarification-1",
        questions=[{"id": "source", "requirement_key": "rag.source", "question": "Which source?"}],
    )
    assert waiting["phase"] == "waiting_user"
    assert waiting["active_turn"]["status"] == "interpreted"
    assert waiting["revision"] == 2

    ready = acknowledge_user_turn(understanding, turn_id="turn-1")
    completed = complete_planning_session(ready)
    assert completed["phase"] == "completed"
    assert completed["revision"] == 3
    assert ready["phase"] == "ready"
    assert ready["active_turn"]["status"] == "interpreted"


def test_begin_user_turn_rejects_stale_revision():
    session = empty_planning_session("goal-1", "Test RAG")

    with pytest.raises(StageSchemaError, match="revision"):
        begin_user_turn(session, _turn("Test RAG", expected_revision=1))


def _workspace_resource_session():
    session = empty_planning_session("goal-1", "Use product docs")
    session["requirements"]["rag.source"] = {
        "status": "resolved",
        "answer": {
            "kind": "resource_mode",
            "resource_kind": "dataset",
            "source": "workspace",
            "binding_time": "design_time",
        },
        "source_turn_id": "turn-1",
        "revision": 1,
    }
    return session


def _resource_action(query: str = "product docs") -> ResolveResourceAction:
    return ResolveResourceAction(
        intent_id="rag-source",
        requirement_key="rag.source",
        resource_kind="dataset",
        binding_time="design_time",
        query=query,
    )


def test_unique_resource_candidate_creates_binding_and_assumption():
    resolving = start_resource_resolution(_workspace_resource_session(), _resource_action())
    transition = complete_resource_resolution(
        resolving,
        _resource_action(),
        candidates=(ResourceCandidate(id="dataset-1", label="Product docs", description="Workspace dataset"),),
        available=True,
    )

    assert resolving["phase"] == "resolving_resource"
    assert transition.session["phase"] == "ready"
    assert transition.session["resource_bindings"]["rag-source"]["resource_id"] == "dataset-1"
    assert transition.session["assumptions"] == ["Automatically selected knowledge base Product docs."]
    assert transition.public_event == {
        "action": "resource_bound",
        "intent_id": "rag-source",
        "resource_kind": "dataset",
        "resource_name": "Product docs",
    }


def test_two_distinct_empty_resource_queries_exhaust_intent():
    first_action = _resource_action("missing docs")
    first = complete_resource_resolution(
        start_resource_resolution(_workspace_resource_session(), first_action),
        first_action,
        candidates=(),
        available=True,
    ).session
    second_action = _resource_action("other docs")
    second = complete_resource_resolution(
        start_resource_resolution(first, second_action),
        second_action,
        candidates=(),
        available=True,
    )

    assert second.session["resource_intents"]["rag-source"]["status"] == "exhausted"
    assert second.observation["status"] == "exhausted"


def test_multiple_resource_candidates_create_real_selection_question():
    transition = complete_resource_resolution(
        start_resource_resolution(_workspace_resource_session(), _resource_action()),
        _resource_action(),
        candidates=(
            ResourceCandidate(id="dataset-1", label="Product docs", description="Workspace dataset"),
            ResourceCandidate(id="dataset-2", label="Support docs", description="Workspace dataset"),
        ),
        available=True,
    )

    assert transition.session["phase"] == "waiting_user"
    question = transition.session["pending_clarification"]["questions"][0]
    assert question["kind"] == "resource_select"
    assert [candidate["label"] for candidate in question["candidates"]] == ["Product docs", "Support docs"]


def test_structured_clarification_is_resolved_without_model_interpretation():
    session = empty_planning_session("goal-1", "Test RAG")
    session["pending_clarification"] = {
        "clarification_id": "clarification-1",
        "questions": [
            {
                "id": "rag-source",
                "requirement_key": "rag.source",
                "kind": "single_choice",
                "question": "How is RAG supplied?",
                "options": [{"value": "runtime"}, {"value": "workspace"}],
            }
        ],
    }
    turn = UserTurn(
        id="turn-answer",
        kind="clarification_response",
        answers=[{"question_id": "rag-source", "kind": "single_choice", "value": "runtime"}],
        expected_revision=0,
    )

    transition = reduce_structured_clarification(session, turn)

    assert transition["revision"] == 1
    assert transition["phase"] == "ready"
    assert transition["active_turn"]["status"] == "interpreted"
    assert transition["requirements"]["rag.source"]["answer"] == {
        "kind": "single_choice",
        "value": "runtime",
    }
    assert transition["pending_clarification"] == {}


def test_structured_resource_selection_creates_binding_for_pending_intent():
    candidates = (
        ResourceCandidate(id="dataset-1", label="Product docs", description="Workspace dataset"),
        ResourceCandidate(id="dataset-2", label="Support docs", description="Workspace dataset"),
    )
    waiting = complete_resource_resolution(
        start_resource_resolution(_workspace_resource_session(), _resource_action()),
        _resource_action(),
        candidates=candidates,
        available=True,
    ).session

    resolved = reduce_structured_clarification(
        waiting,
        UserTurn(
            id="turn-answer",
            kind="clarification_response",
            answers=[
                {
                    "question_id": "resource:rag-source",
                    "kind": "resource_select",
                    "resource_kind": "dataset",
                    "resource_ids": ["dataset-2"],
                }
            ],
            expected_revision=waiting["revision"],
        ),
    )

    assert resolved["resource_bindings"]["rag-source"]["resource_id"] == "dataset-2"
    assert resolved["resource_bindings"]["rag-source"]["resource_name"] == "Support docs"
    assert resolved["resource_intents"]["rag-source"]["status"] == "bound"
    assert resolved["requirements"]["rag.source"]["answer"] == {
        "kind": "resource_mode",
        "resource_kind": "dataset",
        "source": "workspace",
        "binding_time": "design_time",
    }


def _resources(
    *, dataset_ids: frozenset[str] = frozenset(), tool_ids: frozenset[str] = frozenset()
) -> VerifiedResourceSnapshot:
    return VerifiedResourceSnapshot(dataset_ids=dataset_ids, tool_ids=tool_ids)


def test_reducer_resolves_two_independent_requirements():
    transition = reduce_planning_session(
        empty_planning_session("goal-1", "Test RAG"),
        ResolveRequirementsAction(
            resolutions=(
                _resolution("rag.source", "Runtime upload", "测试时上传"),
                _resolution("testset.source", "Agent generated", "Agent 生成"),
            )
        ),
        _turn("测试时上传，测试集由 Agent   生成"),
        _resources(),
    )

    assert transition.session["revision"] == 1
    assert set(transition.session["requirements"]) == {"rag.source", "testset.source"}
    assert transition.observation["resolved_requirement_keys"] == ["rag.source", "testset.source"]
    assert transition.public_event == {
        "action": "requirements_resolved",
        "count": 2,
        "requirement_keys": ["rag.source", "testset.source"],
        "labels": ["rag.source", "testset.source"],
    }


def test_reducer_normalizes_case_and_whitespace_when_matching_evidence():
    transition = reduce_planning_session(
        empty_planning_session("goal-1", "Test RAG"),
        ResolveRequirementsAction(
            resolutions=(_resolution("rag.source", "Runtime upload", "rag source at runtime"),)
        ),
        _turn("Use RAG\n\tSource At Runtime, please."),
        _resources(),
    )

    assert transition.session["requirements"]["rag.source"]["source_turn_id"] == "turn-1"


def test_reducer_rejects_evidence_absent_from_current_turn():
    with pytest.raises(StageSchemaError, match="evidence"):
        reduce_planning_session(
            empty_planning_session("goal-1", "Test RAG"),
            ResolveRequirementsAction(
                resolutions=(_resolution("rag.source", "Runtime upload", "upload at runtime"),)
            ),
            _turn("Use the workspace knowledge base."),
            _resources(),
        )


def test_reducer_accepts_user_alternative_as_text_for_pending_choice():
    session = empty_planning_session("goal-1", "Test RAG")
    session["pending_clarification"] = {
        "questions": [
            {
                "id": "rag-source",
                "requirement_key": "rag.source",
                "kind": "single_choice",
                "question": "Which source?",
                "options": [{"value": "dify"}, {"value": "external_api"}],
            }
        ]
    }

    transition = reduce_planning_session(
        session,
        ResolveRequirementsAction(
            resolutions=(_resolution("rag.source", "Upload only when running the test", "测试时再上传"),)
        ),
        _turn("我希望测试时再上传，不使用这两个选项。"),
        _resources(),
    )

    assert transition.session["requirements"]["rag.source"]["answer"] == {
        "kind": "text",
        "text": "Upload only when running the test",
    }
    assert transition.session["pending_clarification"] == {}


def test_reducer_revises_requirement_and_retains_supersession_history():
    first = reduce_planning_session(
        empty_planning_session("goal-1", "Test RAG"),
        ResolveRequirementsAction(resolutions=(_resolution("rag.source", "Workspace dataset", "知识库"),)),
        _turn("先使用知识库"),
        _resources(),
    ).session

    second = reduce_planning_session(
        first,
        ResolveRequirementsAction(resolutions=(_resolution("rag.source", "Runtime upload", "改成运行时上传"),)),
        UserTurn(id="turn-2", message="改成运行时上传"),
        _resources(),
    ).session

    assert second["revision"] == 2
    assert second["requirements"]["rag.source"]["answer"] == {"kind": "text", "text": "Runtime upload"}
    assert second["requirement_history"] == [
        {
            "requirement_key": "rag.source",
            "answer": {"kind": "text", "text": "Workspace dataset"},
            "source_turn_id": "turn-1",
            "revision": 1,
            "superseded_by_revision": 2,
        }
    ]


def test_superseding_a_resource_mode_invalidates_dependent_intent_and_binding():
    bound = complete_resource_resolution(
        start_resource_resolution(_workspace_resource_session(), _resource_action()),
        _resource_action(),
        candidates=(ResourceCandidate(id="dataset-1", label="Product docs", description="Docs"),),
        available=True,
    ).session
    turn = UserTurn(
        id="turn-runtime",
        kind="message",
        message="改成运行时上传",
        expected_revision=bound["revision"],
    )
    action = ResolveRequirementsAction(
        resolutions=(
            RequirementResolution(
                requirement_key="rag.source",
                answer={
                    "kind": "resource_mode",
                    "resource_kind": "dataset",
                    "source": "runtime_input",
                    "binding_time": "runtime",
                },
                evidence="运行时上传",
            ),
        )
    )

    updated = reduce_planning_session(bound, action, turn, _resources()).session

    assert updated["resource_intents"] == {}
    assert updated["resource_bindings"] == {}


def test_reducer_rejects_forged_resource_ids():
    action = ResolveRequirementsAction(
        resolutions=(
            RequirementResolution(
                requirement_key="rag.dataset",
                answer={
                    "kind": "resource_select",
                    "resource_kind": "dataset",
                    "resource_ids": ["invented-dataset"],
                },
                evidence="产品知识库",
            ),
        )
    )

    with pytest.raises(StageSchemaError, match="verified"):
        reduce_planning_session(
            empty_planning_session("goal-1", "Test RAG"),
            action,
            _turn("使用产品知识库"),
            _resources(dataset_ids=frozenset({"dataset-1"})),
        )


def test_reducer_accepts_verified_resource_ids():
    action = ResolveRequirementsAction(
        resolutions=(
            RequirementResolution(
                requirement_key="rag.dataset",
                answer={
                    "kind": "resource_select",
                    "resource_kind": "dataset",
                    "resource_ids": ["dataset-1"],
                },
                evidence="产品知识库",
            ),
        )
    )

    transition = reduce_planning_session(
        empty_planning_session("goal-1", "Test RAG"),
        action,
        _turn("使用产品知识库"),
        _resources(dataset_ids=frozenset({"dataset-1"})),
    )

    assert transition.session["requirements"]["rag.dataset"]["answer"]["resource_ids"] == ["dataset-1"]


def test_reducer_rejects_no_op_and_stale_transitions():
    first = reduce_planning_session(
        empty_planning_session("goal-1", "Test RAG"),
        ResolveRequirementsAction(resolutions=(_resolution("rag.source", "Runtime upload", "运行时上传"),)),
        _turn("运行时上传"),
        _resources(),
    ).session

    with pytest.raises(StageSchemaError, match="no changes"):
        reduce_planning_session(
            first,
            ResolveRequirementsAction(resolutions=(_resolution("rag.source", "Runtime upload", "运行时上传"),)),
            UserTurn(id="turn-2", message="还是运行时上传"),
            _resources(),
        )
    with pytest.raises(StageSchemaError, match="revision"):
        reduce_planning_session(
            first,
            ResolveRequirementsAction(resolutions=(_resolution("rag.source", "External API", "外部 API"),)),
            UserTurn(id="turn-3", message="改成外部 API", expected_revision=0),
            _resources(),
        )


@pytest.mark.parametrize(
    "legacy",
    [
        None,
        {"version": 1, "searches": [], "resolved_requirements": []},
        {
            "version": 2,
            "searches": [{"kind": "knowledge", "query": "docs"}],
            "resolved_requirements": [
                {
                    "question_id": "source",
                    "requirement_key": "rag.source",
                    "kind": "single_choice",
                    "question": "Which source?",
                    "answer": "runtime",
                    "label": "Runtime upload",
                    "source": "user",
                }
            ],
            "budget": {
                "model_actions": 3,
                "model_elapsed_ms": 25,
                "input_tokens": 100,
                "output_tokens": 20,
                "clarification_rounds": 1,
            },
        },
    ],
)
def test_normalize_v1_v2_state_to_v4_without_replaying_legacy_search(legacy):
    normalized = normalize_planning_session(legacy, goal_id="goal-1", active_instruction="Test RAG")

    assert normalized["version"] == 4
    assert normalized["revision"] == 0
    assert normalized["goal_id"] == "goal-1"
    assert normalized["active_instruction"] == "Test RAG"
    assert normalized["truncation_recoveries"] == 0
    assert normalized["resource_intents"] == {}
    assert normalized["resource_bindings"] == {}
    assert normalized["search_observations"] == (
        [{"kind": "knowledge", "query": "docs", "legacy": True}]
        if isinstance(legacy, dict) and legacy.get("version") == 2
        else []
    )
    if isinstance(legacy, dict) and legacy.get("version") == 2:
        assert normalized["requirements"]["rag.source"]["answer"] == {
            "kind": "single_choice",
            "value": "runtime",
        }
        assert normalized["budget"]["model_actions"] == 3
