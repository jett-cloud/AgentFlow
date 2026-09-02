from types import SimpleNamespace
from typing import Any

import pytest

from core.workflow.generator.planner import PlannerInput
from core.workflow.generator.planner_actions import (
    RequestUserInputAction,
    ResolveRequirementsAction,
    SearchKnowledgeAction,
    SearchToolsAction,
)
from core.workflow.generator.planner_context import (
    PlannerContextLimitError,
    PlannerContextSession,
    PlannerTokenCountError,
)
from core.workflow.generator.planning_session import UserTurn, VerifiedResourceSnapshot, reduce_planning_session
from graphon.model_runtime.entities.model_entities import ModelPropertyKey


class _TokenCountingModel:
    def __init__(self, *, context_size: int | None = 32768, output_ceiling: int | None = 16384) -> None:
        parameter_rules = []
        if output_ceiling is not None:
            parameter_rules.append(SimpleNamespace(name="max_tokens", max=output_ceiling))
        properties = {} if context_size is None else {ModelPropertyKey.CONTEXT_SIZE: context_size}
        self.schema = SimpleNamespace(parameter_rules=parameter_rules, model_properties=properties)

    def get_model_schema(self):
        return self.schema

    def get_llm_num_tokens(self, prompt_messages):
        return sum(len(str(message.content or "")) for message in prompt_messages) // 4

    def invoke_llm(self, **_kwargs):
        raise AssertionError("PlannerContextSession tests do not invoke the model")


def _request(**overrides) -> PlannerInput:
    values: dict[str, Any] = {
        "mode": "workflow",
        "instruction": "Summarize web results",
        "ideal_output": "",
        "tool_catalogue_text": "",
        "knowledge_catalogue_text": "",
        "current_graph": None,
    }
    values.update(overrides)
    return PlannerInput(**values)


def _contents(messages) -> list[str]:
    return [str(message.content or "") for message in messages]


def test_start_reserves_model_aware_output_budget() -> None:
    session = PlannerContextSession.start(
        request=_request(),
        model_instance=_TokenCountingModel(context_size=32768, output_ceiling=16000),
        model_parameters={"max_tokens": 12000, "temperature": 0.8},
    )

    assert session.model_parameters["max_tokens"] == 8192
    assert session.model_parameters["temperature"] == 0.2
    assert session.diagnostics.context_window == 32768
    assert session.diagnostics.context_window_source == "schema"
    assert session.diagnostics.input_limit == 23920


def test_prompt_includes_active_user_turn_and_planning_phase() -> None:
    session = PlannerContextSession.start(
        request=_request(
            instruction="Test RAG retrieval accuracy",
            user_turn=UserTurn(
                id="turn-1",
                kind="message",
                message="Test RAG retrieval accuracy",
                expected_revision=0,
            ),
        ),
        model_instance=_TokenCountingModel(),
        model_parameters={},
    )

    rendered = "\n".join(_contents(session.messages()))

    assert '"phase":"understanding"' in rendered
    assert '"turn_id":"turn-1"' in rendered
    assert '"status":"pending_interpretation"' in rendered


def test_start_uses_conservative_context_fallback_when_schema_omits_size() -> None:
    session = PlannerContextSession.start(
        request=_request(),
        model_instance=_TokenCountingModel(context_size=None, output_ceiling=None),
        model_parameters={},
    )

    assert session.model_parameters["max_tokens"] == 4096
    assert session.diagnostics.context_window == 16384
    assert session.diagnostics.context_window_source == "fallback"
    assert session.diagnostics.input_limit == 11960


def test_record_appends_actions_and_observations_without_rewriting_prefix() -> None:
    session = PlannerContextSession.start(
        request=_request(),
        model_instance=_TokenCountingModel(),
        model_parameters={},
    )
    first = _contents(session.messages())

    session.record(
        action=SearchToolsAction(query="web search"),
        observation={
            "action": "search_tools",
            "query": "web search",
            "status": "ok",
            "count": 1,
            "results": [
                {
                    "provider_name": "google",
                    "provider_type": "builtin",
                    "plugin_id": "",
                    "tool_name": "search",
                    "tool_label": "Web Search",
                    "description": "Search the web.",
                }
            ],
        },
    )
    second = _contents(session.messages())
    session.record(
        action=SearchKnowledgeAction(query="manual"),
        observation={"action": "search_knowledge", "query": "manual", "status": "ok", "count": 0, "results": []},
    )
    third = _contents(session.messages())

    assert second[:2] == first
    assert third[:4] == second
    assert second[2] == '{"action":"search_tools","query":"web search"}'
    assert '"state_after"' in second[3]
    assert "google" in second[3]


def test_compact_mode_drops_resource_descriptions_but_keeps_authorization_identifiers() -> None:
    session = PlannerContextSession.start(
        request=_request(),
        model_instance=_TokenCountingModel(context_size=16384),
        model_parameters={},
    )
    session.record(
        action=SearchToolsAction(query="web"),
        observation={
            "action": "search_tools",
            "query": "web",
            "status": "ok",
            "count": 1,
            "results": [
                {
                    "provider_name": "google",
                    "provider_type": "builtin",
                    "plugin_id": "",
                    "tool_name": "search",
                    "tool_label": "Web Search",
                    "description": "x" * 42000,
                }
            ],
        },
    )

    rendered = "\n".join(_contents(session.messages()))

    assert session.diagnostics.compaction_mode == "compact"
    assert "google" in rendered
    assert "search" in rendered
    assert "x" * 100 not in rendered


def test_checkpoint_v3_contains_search_intents_requirements_and_persistent_budget() -> None:
    session = PlannerContextSession.start(
        request=_request(
            clarification_history=[
                {
                    "clarification_id": "clarify-1",
                    "questions": [
                        {
                            "id": "format",
                            "requirement_key": "output.format",
                            "kind": "single_choice",
                            "question": "Which format?",
                            "options": [
                                {"value": "markdown", "label": "Markdown", "description": "Readable"},
                                {"value": "json", "label": "JSON", "description": "Structured"},
                            ],
                        }
                    ],
                    "answers": [{"question_id": "format", "kind": "single_choice", "value": "markdown"}],
                }
            ]
        ),
        model_instance=_TokenCountingModel(),
        model_parameters={},
    )
    session.record(
        action=SearchToolsAction(query=" Web   Search "),
        observation={"action": "search_tools", "query": "Web Search", "status": "ok", "count": 0, "results": []},
    )

    checkpoint = session.checkpoint()
    assert checkpoint["version"] == 4
    assert checkpoint["phase"] == "ready"
    assert checkpoint["active_turn"] is None
    assert checkpoint["resource_intents"] == {}
    assert checkpoint["resource_bindings"] == {}
    assert checkpoint["search_observations"] == []
    assert {key: checkpoint[key] for key in (
        "revision",
        "goal_id",
        "active_instruction",
        "searches",
        "requirements",
        "requirement_history",
        "pending_clarification",
        "budget",
        "truncation_recoveries",
    )} == {
        "revision": 0,
        "goal_id": "current-goal",
        "active_instruction": "Summarize web results",
        "searches": [{"kind": "tool", "query": "Web Search", "empty": True}],
        "requirements": {
            "output.format": {
                "status": "resolved",
                "answer": {"kind": "single_choice", "value": "markdown"},
                "source_turn_id": "clarify-1",
                "revision": 0,
                "label": "Markdown",
            }
        },
        "requirement_history": [],
        "pending_clarification": {},
        "budget": {
            "model_actions": 0,
            "model_elapsed_ms": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "clarification_rounds": 0,
        },
        "truncation_recoveries": 0,
    }


def test_start_restores_v1_checkpoint_and_emits_v4() -> None:
    session = PlannerContextSession.start(
        request=_request(),
        model_instance=_TokenCountingModel(),
        model_parameters={},
        checkpoint={
            "version": 1,
            "searches": [{"kind": "knowledge", "query": "Product docs"}],
            "resolved_requirements": [
                {
                    "question_id": "format",
                    "question": "Which format?",
                    "answer": "markdown",
                    "label": "Markdown",
                    "source": "user",
                }
            ],
        },
    )

    checkpoint = session.checkpoint()

    assert checkpoint["version"] == 4
    assert checkpoint["searches"] == []
    assert checkpoint["search_observations"] == [
        {"kind": "knowledge", "query": "Product docs", "legacy": True}
    ]
    assert checkpoint["requirements"]["format"]["answer"] == {
        "kind": "single_choice",
        "value": "markdown",
    }


def test_deferred_legacy_meta_answer_is_not_a_resolved_requirement() -> None:
    session = PlannerContextSession.start(
        request=_request(
            clarification_history=[
                {
                    "clarification_id": "clarify-1",
                    "questions": [
                        {
                            "id": "dataset_id",
                            "question": "Provide the dataset ID.",
                            "options": [
                                {"value": "paste_id", "label": "Paste in next message", "description": "Later"},
                                {"value": "skip", "label": "Skip", "description": "Skip knowledge"},
                            ],
                        }
                    ],
                    "answers": [{"question_id": "dataset_id", "selected_value": "paste_id"}],
                }
            ]
        ),
        model_instance=_TokenCountingModel(),
        model_parameters={},
    )

    assert session.checkpoint()["requirements"] == {}


def test_typed_text_and_resource_answers_are_preserved() -> None:
    session = PlannerContextSession.start(
        request=_request(
            clarification_history=[
                {
                    "clarification_id": "clarify-typed",
                    "questions": [
                        {
                            "id": "audience",
                            "requirement_key": "content.audience",
                            "kind": "text",
                            "question": "Who is the audience?",
                        },
                        {
                            "id": "knowledge",
                            "requirement_key": "knowledge.selection",
                            "kind": "resource_select",
                            "question": "Choose knowledge.",
                            "resource_kind": "dataset",
                            "candidates": [{"id": "dataset-1", "label": "Product docs", "description": "Docs"}],
                        },
                    ],
                    "answers": [
                        {"question_id": "audience", "kind": "text", "text": "New customers"},
                        {
                            "question_id": "knowledge",
                            "kind": "resource_select",
                            "resource_kind": "dataset",
                            "resource_ids": ["dataset-1"],
                        },
                    ],
                }
            ]
        ),
        model_instance=_TokenCountingModel(),
        model_parameters={},
    )

    requirements = session.checkpoint()["requirements"]

    assert requirements["content.audience"]["answer"] == {"kind": "text", "text": "New customers"}
    assert requirements["content.audience"]["label"] == "New customers"
    assert requirements["knowledge.selection"]["answer"] == {
        "kind": "resource_select",
        "resource_kind": "dataset",
        "resource_ids": ["dataset-1"],
    }
    assert requirements["knowledge.selection"]["label"] == "Product docs"


def test_v2_checkpoint_is_emitted_as_v4_and_requirements_appear_once_in_prompt() -> None:
    session = PlannerContextSession.start(
        request=_request(
            clarification_history=[
                {
                    "clarification_id": "turn-4",
                    "questions": [],
                    "user_message": "测试时上传，测试集由 Agent 生成",
                }
            ]
        ),
        model_instance=_TokenCountingModel(),
        model_parameters={},
        checkpoint={
            "version": 2,
            "searches": [],
            "resolved_requirements": [
                {
                    "question_id": "rag-source",
                    "requirement_key": "rag.source",
                    "kind": "text",
                    "question": "RAG source?",
                    "answer": "Runtime upload",
                    "label": "Runtime upload",
                    "source": "user",
                }
            ],
            "budget": {
                "model_actions": 1,
                "model_elapsed_ms": 20,
                "input_tokens": 100,
                "output_tokens": 20,
                "clarification_rounds": 1,
            },
        },
    )

    checkpoint = session.checkpoint()
    rendered = "\n".join(_contents(session.messages()))

    assert checkpoint["version"] == 4
    assert checkpoint["revision"] == 1
    assert checkpoint["truncation_recoveries"] == 0
    assert rendered.count('"rag.source"') == 1
    assert rendered.count("测试时上传，测试集由 Agent 生成") == 1
    assert "Runtime inputs may include files" in rendered
    assert "Agent nodes can generate content" in rendered


def test_apply_requirement_transition_and_note_truncation_recovery() -> None:
    session = PlannerContextSession.start(
        request=_request(
            clarification_history=[
                {"clarification_id": "turn-1", "questions": [], "user_message": "测试时上传"}
            ]
        ),
        model_instance=_TokenCountingModel(),
        model_parameters={},
    )
    transition = reduce_planning_session(
        session.planning_session,
        ResolveRequirementsAction(
            resolutions=(
                {
                    "requirement_key": "rag.source",
                    "answer": {"kind": "text", "text": "Runtime upload"},
                    "evidence": "测试时上传",
                },
            )
        ),
        UserTurn(id="turn-1", message="测试时上传"),
        VerifiedResourceSnapshot(dataset_ids=frozenset(), tool_ids=frozenset()),
    )

    session.apply_requirement_transition(transition)
    session.note_truncation_recovery()

    assert session.checkpoint()["requirements"]["rag.source"]["answer"] == {
        "kind": "text",
        "text": "Runtime upload",
    }
    assert session.checkpoint()["truncation_recoveries"] == 1


def test_messages_fail_before_invocation_when_lossless_context_cannot_fit() -> None:
    session = PlannerContextSession.start(
        request=_request(instruction="required" * 10000),
        model_instance=_TokenCountingModel(context_size=4096),
        model_parameters={},
    )

    with pytest.raises(PlannerContextLimitError, match="context limit"):
        session.messages()


def test_start_fails_when_provider_token_count_is_unavailable() -> None:
    model = _TokenCountingModel()

    def fail_token_count(prompt_messages):
        del prompt_messages
        raise RuntimeError("tokenizer unavailable")

    model.get_llm_num_tokens = fail_token_count

    with pytest.raises(PlannerTokenCountError, match="token count"):
        PlannerContextSession.start(
            request=_request(),
            model_instance=model,
            model_parameters={},
        )


def test_compact_mode_keeps_only_latest_duplicate_search_observation() -> None:
    session = PlannerContextSession.start(
        request=_request(),
        model_instance=_TokenCountingModel(context_size=16384),
        model_parameters={},
    )
    for marker in ("old-result", "latest-result"):
        session.record(
            action=SearchToolsAction(query=" Web   Search "),
            observation={
                "action": "search_tools",
                "query": "Web Search",
                "status": "ok",
                "count": 1,
                "results": [
                    {
                        "provider_name": marker,
                        "tool_name": "search",
                        "description": "x" * 42000,
                    }
                ],
            },
        )

    rendered = "\n".join(_contents(session.messages()))

    assert session.diagnostics.compaction_mode == "compact"
    assert "old-result" not in rendered
    assert "latest-result" in rendered


def test_critical_compaction_folds_old_default_questions_into_requirements() -> None:
    session = PlannerContextSession.start(
        request=_request(),
        model_instance=_TokenCountingModel(context_size=32768),
        model_parameters={},
    )
    for index in range(6):
        action = RequestUserInputAction(
            questions=(
                {
                    "id": f"choice-{index}",
                    "question": f"Choose {index}",
                    "options": [
                        {
                            "value": "safe",
                            "label": "Safe",
                            "description": f"description-{index}-" + "x" * 8000,
                            "recommended": True,
                        },
                        {
                            "value": "fast",
                            "label": "Fast",
                            "description": f"alternative-{index}-" + "x" * 8000,
                            "recommended": False,
                        },
                    ],
                    "allow_other": True,
                },
            )
        )
        session.record(
            action=action,
            observation={
                "action": "request_user_input",
                "status": "defaults_applied",
                "answers": [{"question_id": f"choice-{index}", "selected_value": "safe", "label": "Safe"}],
            },
        )

    rendered = "\n".join(_contents(session.messages()))

    assert session.diagnostics.compaction_mode == "critical"
    assert '"question_id":"choice-0"' in rendered
    assert "description-0-" not in rendered
    assert "description-5-" in rendered
