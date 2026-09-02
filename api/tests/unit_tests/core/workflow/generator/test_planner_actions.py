import pytest

from core.workflow.generator.llm_response import StageSchemaError
from core.workflow.generator.planner_actions import (
    AcknowledgeTurnAction,
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


def test_parse_understanding_and_resource_actions():
    acknowledge = parse_planner_action({"action": "acknowledge_turn"})
    resolve_resource = parse_planner_action(
        {
            "action": "resolve_resource",
            "intent_id": "rag-source",
            "requirement_key": "rag.source",
            "resource_kind": "dataset",
            "binding_time": "design_time",
            "query": "product knowledge",
        }
    )

    assert acknowledge == AcknowledgeTurnAction()
    assert resolve_resource == ResolveResourceAction(
        intent_id="rag-source",
        requirement_key="rag.source",
        resource_kind="dataset",
        binding_time="design_time",
        query="product knowledge",
    )


def test_parse_resource_mode_requirement_answer():
    action = parse_planner_action(
        {
            "action": "resolve_requirements",
            "resolutions": [
                {
                    "requirement_key": "rag.source",
                    "answer": {
                        "kind": "resource_mode",
                        "resource_kind": "dataset",
                        "source": "runtime_input",
                        "binding_time": "runtime",
                    },
                    "evidence": "测试的时候再上传",
                }
            ],
        }
    )

    assert isinstance(action, ResolveRequirementsAction)
    assert action.resolutions[0]["answer"] == {
        "kind": "resource_mode",
        "resource_kind": "dataset",
        "source": "runtime_input",
        "binding_time": "runtime",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {
            "action": "resolve_resource",
            "intent_id": "rag-source",
            "requirement_key": "rag.source",
            "resource_kind": "dataset",
            "binding_time": "runtime",
            "query": "docs",
        },
        {
            "action": "resolve_resource",
            "intent_id": "rag-source",
            "requirement_key": "rag.source",
            "resource_kind": "unknown",
            "binding_time": "design_time",
            "query": "docs",
        },
    ],
)
def test_parse_resolve_resource_rejects_invalid_fields(payload):
    with pytest.raises(StageSchemaError):
        parse_planner_action(payload)


def test_parse_resolve_requirements_action():
    action = parse_planner_action(
        {
            "action": "resolve_requirements",
            "resolutions": [
                {
                    "requirement_key": "rag.source",
                    "answer": {"kind": "text", "text": "Runtime upload"},
                    "evidence": "测试的时候我再上传",
                },
                {
                    "requirement_key": "testset.source",
                    "answer": {"kind": "multi_choice", "values": ["agent_generated", "manual"]},
                    "evidence": "测试集不能由agent节点生成吗",
                },
            ],
        }
    )

    assert isinstance(action, ResolveRequirementsAction)
    assert action.resolutions[0]["requirement_key"] == "rag.source"
    assert action.resolutions[1]["answer"] == {
        "kind": "multi_choice",
        "values": ["agent_generated", "manual"],
    }


@pytest.mark.parametrize(
    ("resolutions", "expected"),
    [
        ([], "between 1 and 16"),
        (
            [
                {
                    "requirement_key": f"requirement.{index}",
                    "answer": {"kind": "text", "text": "value"},
                    "evidence": "evidence",
                }
                for index in range(17)
            ],
            "between 1 and 16",
        ),
        (
            [
                {
                    "requirement_key": "RAG source",
                    "answer": {"kind": "text", "text": "value"},
                    "evidence": "evidence",
                }
            ],
            "requirement_key",
        ),
        (
            [
                {
                    "requirement_key": "rag.source",
                    "answer": {"kind": "text", "text": "one"},
                    "evidence": "one",
                },
                {
                    "requirement_key": "rag.source",
                    "answer": {"kind": "text", "text": "two"},
                    "evidence": "two",
                },
            ],
            "duplicate requirement_key",
        ),
        (
            [
                {
                    "requirement_key": "rag.source",
                    "answer": {"kind": "text", "text": "value"},
                    "evidence": " ",
                }
            ],
            "evidence",
        ),
        (
            [
                {
                    "requirement_key": "rag.source",
                    "answer": {"kind": "text", "text": "value"},
                    "evidence": "x" * 501,
                }
            ],
            "evidence",
        ),
    ],
)
def test_parse_resolve_requirements_rejects_invalid_collection(resolutions, expected):
    with pytest.raises(StageSchemaError, match=expected):
        parse_planner_action({"action": "resolve_requirements", "resolutions": resolutions})


@pytest.mark.parametrize(
    "answer",
    [
        {"kind": "text", "text": "paste_id"},
        {"kind": "single_choice", "value": "provide_later"},
        {"kind": "multi_choice", "values": []},
        {"kind": "multi_choice", "values": ["one", "one"]},
        {"kind": "resource_select", "resource_kind": "dataset", "resource_ids": []},
        {"kind": "resource_select", "resource_kind": "unknown", "resource_ids": ["resource-1"]},
        {"kind": "resource_select", "resource_kind": "tool", "resource_ids": ["tool-1", "tool-1"]},
        {"kind": "unsupported", "text": "value"},
    ],
)
def test_parse_resolve_requirements_rejects_malformed_answers(answer):
    with pytest.raises(StageSchemaError, match="answer"):
        parse_planner_action(
            {
                "action": "resolve_requirements",
                "resolutions": [
                    {
                        "requirement_key": "rag.source",
                        "answer": answer,
                        "evidence": "user evidence",
                    }
                ],
            }
        )


def test_parse_search_tools_requires_only_a_non_empty_query():
    action = parse_planner_action({"action": "search_tools", "query": "  web search  "})

    assert action == SearchToolsAction(query="web search")


def test_parse_search_knowledge_action():
    action = parse_planner_action({"action": "search_knowledge", "query": "product docs"})

    assert action == SearchKnowledgeAction(query="product docs")


def test_parse_clarification_requires_recommended_first_and_other():
    action = parse_planner_action(
        {
            "action": "request_user_input",
            "questions": [
                {
                    "id": "format",
                    "question": "Which format?",
                    "options": [
                        {
                            "value": "markdown",
                            "label": "Markdown",
                            "description": "Readable output.",
                            "recommended": True,
                        },
                        {
                            "value": "json",
                            "label": "JSON",
                            "description": "Machine-readable output.",
                            "recommended": False,
                        },
                    ],
                    "allow_other": True,
                }
            ],
        }
    )

    assert isinstance(action, RequestUserInputAction)
    assert action.questions[0]["id"] == "format"
    assert action.questions[0]["kind"] == "single_choice"
    assert action.questions[0]["requirement_key"] == "format"


def test_parse_clarification_supports_mixed_typed_questions():
    action = parse_planner_action(
        {
            "action": "request_user_input",
            "message": "I need two details before I can finish the workflow.",
            "questions": [
                {
                    "id": "dataset_id",
                    "requirement_key": "knowledge.dataset_id",
                    "kind": "text",
                    "question": "Paste the dataset ID.",
                    "required": True,
                },
                {
                    "id": "formats",
                    "requirement_key": "output.formats",
                    "kind": "multi_choice",
                    "question": "Which output formats are required?",
                    "options": [
                        {
                            "value": "markdown",
                            "label": "Markdown",
                            "description": "Readable output.",
                            "recommended": True,
                        },
                        {
                            "value": "json",
                            "label": "JSON",
                            "description": "Machine-readable output.",
                            "recommended": False,
                        },
                    ],
                    "default_values": ["markdown"],
                },
                {
                    "id": "knowledge",
                    "requirement_key": "knowledge.selection",
                    "kind": "resource_select",
                    "question": "Choose the knowledge base.",
                    "resource_kind": "dataset",
                    "multiple": False,
                    "candidates": [
                        {"id": "dataset-1", "label": "Product docs", "description": "Workspace dataset."},
                        {"id": "dataset-2", "label": "Support docs", "description": "Workspace dataset."},
                    ],
                    "default_resource_ids": ["dataset-1"],
                },
            ],
        }
    )

    assert isinstance(action, RequestUserInputAction)
    assert action.message == "I need two details before I can finish the workflow."
    assert [question["kind"] for question in action.questions] == ["text", "multi_choice", "resource_select"]
    assert action.questions[2]["candidates"][0]["id"] == "dataset-1"


@pytest.mark.parametrize("deferred_value", ["paste_id", "provide_later", "next_message"])
def test_parse_clarification_rejects_deferred_meta_answer_as_recommended(deferred_value):
    with pytest.raises(StageSchemaError, match="immediately submit"):
        parse_planner_action(
            {
                "action": "request_user_input",
                "questions": [
                    {
                        "id": "dataset_id",
                        "requirement_key": "knowledge.dataset_id",
                        "kind": "single_choice",
                        "question": "How should the dataset ID be provided?",
                        "options": [
                            {
                                "value": deferred_value,
                                "label": "Paste it in the next message",
                                "description": "The user will provide it later.",
                                "recommended": True,
                            },
                            {
                                "value": "skip_knowledge",
                                "label": "Skip knowledge",
                                "description": "Build without a dataset.",
                                "recommended": False,
                            },
                        ],
                        "allow_other": True,
                    }
                ],
            }
        )


def test_parse_resource_select_rejects_default_not_in_candidates():
    with pytest.raises(StageSchemaError, match="candidate"):
        parse_planner_action(
            {
                "action": "request_user_input",
                "questions": [
                    {
                        "id": "knowledge",
                        "requirement_key": "knowledge.selection",
                        "kind": "resource_select",
                        "question": "Choose the knowledge base.",
                        "resource_kind": "dataset",
                        "multiple": False,
                        "candidates": [{"id": "dataset-1", "label": "Product docs", "description": "Docs."}],
                        "default_resource_ids": ["invented-dataset"],
                    }
                ],
            }
        )


def test_parse_conversation_actions():
    respond = parse_planner_action(
        {"action": "respond_to_user", "message": "I will search the selected knowledge base, then summarize matches."}
    )
    replace = parse_planner_action(
        {"action": "replace_instruction", "instruction": "Build a customer support routing workflow."}
    )

    assert respond == RespondToUserAction(
        message="I will search the selected knowledge base, then summarize matches."
    )
    assert replace == ReplaceInstructionAction(instruction="Build a customer support routing workflow.")


@pytest.mark.parametrize(
    ("questions", "expected"),
    [
        ([], "between 1 and 3"),
        ([{"id": str(index)} for index in range(4)], "between 1 and 3"),
        (
            [
                {
                    "id": "format",
                    "question": "Which format?",
                    "options": [
                        {
                            "value": "json",
                            "label": "JSON",
                            "description": "Machine-readable.",
                            "recommended": False,
                        },
                        {
                            "value": "markdown",
                            "label": "Markdown",
                            "description": "Readable.",
                            "recommended": True,
                        },
                    ],
                    "allow_other": True,
                }
            ],
            "first option",
        ),
    ],
)
def test_parse_clarification_rejects_invalid_question_contract(questions, expected):
    with pytest.raises(StageSchemaError, match=expected):
        parse_planner_action({"action": "request_user_input", "questions": questions})


def test_parse_action_rejects_fields_from_another_union_member():
    with pytest.raises(StageSchemaError, match="unexpected fields"):
        parse_planner_action({"action": "search_tools", "query": "web", "questions": []})


def test_parse_submit_plan_validates_plan_and_assumptions():
    plan = {
        "title": "Summary",
        "description": "Summarize input.",
        "nodes": [
            {"id": "node1", "node_type": "start"},
            {"id": "node2", "node_type": "end"},
        ],
        "edges": [{"source": "node1", "target": "node2"}],
    }

    action = parse_planner_action({"action": "submit_plan", "plan": plan, "assumptions": ["Use Markdown."]})

    assert action == SubmitPlanAction(plan=plan, assumptions=("Use Markdown.",))


def test_legacy_plan_is_treated_as_submit_plan_for_compatibility():
    legacy = {
        "nodes": [
            {"id": "node1", "node_type": "start"},
            {"id": "node2", "node_type": "end"},
        ],
        "edges": [{"source": "node1", "target": "node2"}],
    }

    action = parse_planner_action(legacy)

    assert isinstance(action, SubmitPlanAction)
    assert action.plan is legacy
