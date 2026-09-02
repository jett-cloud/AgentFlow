from types import SimpleNamespace

import pytest

from core.workflow.generator.llm_response import StageSchemaError, StageTruncatedError
from core.workflow.generator.planner import (
    PlannerAssistantMessageOutcome,
    PlannerBudgetExhaustedError,
    PlannerClarificationLimitError,
    PlannerClarificationOutcome,
    PlannerInput,
    PlannerNoProgressError,
    PlannerPlanOutcome,
    PlanningEngine,
    iter_plan,
    resolve_generation_mode,
    validate_planner_schema,
)
from core.workflow.generator.planner_context import PlannerContextLimitError
from core.workflow.generator.planning_session import UserTurn
from graphon.model_runtime.entities.model_entities import ModelPropertyKey


class _ActionClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []
        self.model_parameters = {}
        self.model_instance = SimpleNamespace(
            get_model_schema=lambda: SimpleNamespace(
                parameter_rules=[],
                model_properties={ModelPropertyKey.CONTEXT_SIZE: 32768},
            ),
            get_llm_num_tokens=lambda messages: sum(len(str(message.content or "")) for message in messages) // 4,
        )

    def iter_json(self, *, messages, stage, model_parameters):
        self.messages.append(messages)
        response = self.responses.pop(0)
        if False:
            yield ""
        return response


class _TruncatingActionClient(_ActionClient):
    def iter_json(self, *, messages, stage, model_parameters):
        self.messages.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            if False:
                yield ""
            raise response
        if False:
            yield ""
        return response


def _planner_request(**overrides):
    values = {
        "mode": "workflow",
        "instruction": "Summarize web results",
        "ideal_output": "",
        "tool_catalogue_text": "",
        "knowledge_catalogue_text": "",
        "current_graph": None,
    }
    values.update(overrides)
    return PlannerInput(**values)


def _collect_planner(generator, *, include_thinking=False):
    events = []
    while True:
        try:
            event = next(generator)
            if include_thinking or event[0] != "planner_thinking":
                events.append(event)
        except StopIteration as stop:
            return events, stop.value


def _submitted_plan():
    return {
        "title": "Summary",
        "description": "Summarize results.",
        "nodes": [
            {"id": "node1", "node_type": "start"},
            {"id": "node2", "node_type": "end"},
        ],
        "edges": [{"source": "node1", "target": "node2"}],
    }


def _query_matching_tool():
    return {
        "provider_name": "test",
        "provider_type": "builtin",
        "plugin_id": "",
        "tool_name": "search",
        "tool_label": "Test Search",
        "description": " ".join(f"query-{index}" for index in range(24)),
    }


def _clarification_action():
    return {
        "action": "request_user_input",
        "questions": [
            {
                "id": "format",
                "question": "Which output format?",
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


def _resolve_action(requirement_key, text, evidence):
    return {
        "action": "resolve_requirements",
        "resolutions": [
            {
                "requirement_key": requirement_key,
                "answer": {"kind": "text", "text": text},
                "evidence": evidence,
            }
        ],
    }


def _resolve_resource_mode_action(requirement_key, *, resource_kind, source, binding_time, evidence):
    return {
        "action": "resolve_requirements",
        "resolutions": [
            {
                "requirement_key": requirement_key,
                "answer": {
                    "kind": "resource_mode",
                    "resource_kind": resource_kind,
                    "source": source,
                    "binding_time": binding_time,
                },
                "evidence": evidence,
            }
        ],
    }


def test_freeform_answer_resolves_before_submit():
    client = _ActionClient(
        [
            _resolve_action("rag.source", "Runtime upload", "测试时上传"),
            {"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []},
        ]
    )

    events, outcome = _collect_planner(
        iter_plan(
            client=client,
            request=_planner_request(
                policy="interactive",
                clarification_history=[
                    {
                        "clarification_id": "turn-1",
                        "questions": [],
                        "user_message": "RAG 数据源测试时上传",
                    }
                ],
            ),
        )
    )

    assert events[0][1]["action"] == "requirements_resolved"
    assert events[0][1]["requirement_keys"] == ["rag.source"]
    assert events[0][1]["checkpoint"]["requirements"]["rag.source"]["answer"] == {
        "kind": "text",
        "text": "Runtime upload",
    }
    assert isinstance(outcome, PlannerPlanOutcome)


def test_initial_user_turn_must_be_interpreted_before_resource_search():
    client = _ActionClient(
        [
            {"action": "search_knowledge", "query": "knowledge"},
            _resolve_action("workflow.goal", "Evaluate RAG retrieval accuracy", "测试rag数据库的检索正确率"),
            {"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []},
        ]
    )

    events, outcome = _collect_planner(
        iter_plan(
            client=client,
            request=_planner_request(
                instruction="想写个测试rag数据库的检索正确率的工作流",
                user_turn=UserTurn(
                    id="turn-initial",
                    kind="message",
                    message="想写个测试rag数据库的检索正确率的工作流",
                    expected_revision=0,
                ),
            ),
        )
    )

    assert [event[1]["action"] for event in events] == ["action_denied", "requirements_resolved"]
    assert isinstance(outcome, PlannerPlanOutcome)
    assert all(event[1]["action"] != "search_knowledge" for event in events)
    assert events[0][1]["checkpoint"]["searches"] == []


def test_runtime_rag_and_agent_generated_testset_never_search_the_workspace():
    message = "运行时提供 RAG，测试集由 Agent 生成"
    client = _ActionClient(
        [
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
                        "evidence": "运行时提供 RAG",
                    },
                    {
                        "requirement_key": "testset.source",
                        "answer": {"kind": "text", "text": "Agent generated"},
                        "evidence": "测试集由 Agent 生成",
                    },
                ],
            },
            {"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []},
        ]
    )

    events, outcome = _collect_planner(
        iter_plan(
            client=client,
            request=_planner_request(
                instruction=message,
                user_turn=UserTurn(
                    id="turn-runtime-rag",
                    kind="message",
                    message=message,
                    expected_revision=0,
                ),
            ),
        )
    )

    assert isinstance(outcome, PlannerPlanOutcome)
    assert [event[0] for event in events] == ["requirements_resolved"]
    assert outcome.context_checkpoint["resource_intents"] == {}
    assert outcome.context_checkpoint["resource_bindings"] == {}


def test_terminal_plan_is_delivered_when_completed_call_crosses_time_budget(monkeypatch):
    ticks = iter([0.0, 121.0])
    monkeypatch.setattr("core.workflow.generator.planner.time.perf_counter", lambda: next(ticks))
    client = _ActionClient([{"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []}])

    _, outcome = _collect_planner(iter_plan(client=client, request=_planner_request()))

    assert isinstance(outcome, PlannerPlanOutcome)
    assert outcome.context_checkpoint["budget"]["model_elapsed_ms"] == 121_000


def test_budget_error_after_nonterminal_action_carries_latest_checkpoint(monkeypatch):
    ticks = iter([0.0, 121.0])
    monkeypatch.setattr("core.workflow.generator.planner.time.perf_counter", lambda: next(ticks))
    client = _ActionClient([{"action": "acknowledge_turn"}])

    with pytest.raises(PlannerBudgetExhaustedError) as raised:
        _collect_planner(
            iter_plan(
                client=client,
                request=_planner_request(
                    user_turn=UserTurn(
                        id="turn-1",
                        kind="message",
                        message="Summarize web results",
                        expected_revision=0,
                    )
                ),
            )
        )

    assert raised.value.context_checkpoint["version"] == 4
    assert raised.value.context_checkpoint["phase"] == "ready"
    assert raised.value.context_checkpoint["budget"]["model_elapsed_ms"] == 121_000


def test_planning_engine_emits_phase_without_exposing_reasoning():
    client = _ActionClient([{"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []}])

    events, outcome = _collect_planner(
        PlanningEngine(client=client, request=_planner_request()).iter_events(),
        include_thinking=True,
    )

    assert events[0] == (
        "planner_thinking",
        {"phase": "ready", "message": "Planning the next workflow action"},
    )
    assert isinstance(outcome, PlannerPlanOutcome)


def test_workspace_design_time_requirement_authorizes_resource_resolution():
    client = _ActionClient(
        [
            _resolve_resource_mode_action(
                "rag.source",
                resource_kind="dataset",
                source="workspace",
                binding_time="design_time",
                evidence="产品知识库",
            ),
            {
                "action": "resolve_resource",
                "intent_id": "rag-source",
                "requirement_key": "rag.source",
                "resource_kind": "dataset",
                "binding_time": "design_time",
                "query": "产品知识库",
            },
            {"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []},
        ]
    )
    knowledge = [{"id": "dataset-1", "name": "产品知识库", "description": "Product documentation."}]

    events, outcome = _collect_planner(
        iter_plan(
            client=client,
            request=_planner_request(
                instruction="使用工作区产品知识库",
                knowledge_catalogue_entries=knowledge,
                user_turn=UserTurn(
                    id="turn-1",
                    kind="message",
                    message="使用工作区产品知识库",
                    expected_revision=0,
                ),
            ),
        )
    )

    assert [event[1]["action"] for event in events] == [
        "requirements_resolved",
        "resource_resolving",
        "resource_bound",
    ]
    assert isinstance(outcome, PlannerPlanOutcome)
    assert outcome.context_checkpoint["resource_bindings"]["rag-source"]["resource_id"] == "dataset-1"
    assert outcome.assumptions == ("Automatically selected knowledge base 产品知识库.",)


def test_resource_resolver_does_not_create_a_fifth_clarification_round():
    client = _ActionClient(
        [
            {
                "action": "resolve_resource",
                "intent_id": "rag-source",
                "requirement_key": "rag.source",
                "resource_kind": "dataset",
                "binding_time": "design_time",
                "query": "docs",
            }
        ]
    )
    checkpoint = {
        "version": 4,
        "phase": "ready",
        "requirements": {
            "rag.source": {
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
        },
        "budget": {
            "model_actions": 0,
            "model_elapsed_ms": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "clarification_rounds": 4,
        },
    }
    knowledge = [
        {"id": "dataset-1", "name": "Product docs", "description": "Product documentation."},
        {"id": "dataset-2", "name": "Support docs", "description": "Support documentation."},
    ]

    with pytest.raises(PlannerClarificationLimitError) as raised:
        _collect_planner(
            iter_plan(
                client=client,
                request=_planner_request(
                    context_checkpoint=checkpoint,
                    knowledge_catalogue_entries=knowledge,
                ),
            )
        )

    assert raised.value.context_checkpoint["version"] == 4


def test_freeform_answer_can_resolve_then_receive_an_explanation():
    client = _ActionClient(
        [
            _resolve_action("testset.source", "Agent generated", "Agent 生成"),
            {"action": "respond_to_user", "message": "可以，Agent 节点会在运行时生成测试集。"},
        ]
    )

    _, outcome = _collect_planner(
        iter_plan(
            client=client,
            request=_planner_request(
                policy="interactive",
                clarification_history=[
                    {"clarification_id": "turn-2", "questions": [], "user_message": "测试集由 Agent 生成"}
                ],
            ),
        )
    )

    assert isinstance(outcome, PlannerAssistantMessageOutcome)
    assert "testset.source" in outcome.context_checkpoint["requirements"]


def test_resolve_requirements_rejects_evidence_not_in_latest_turn():
    client = _ActionClient([_resolve_action("rag.source", "Runtime upload", "不存在的原话")])

    with pytest.raises(StageSchemaError, match="evidence"):
        _collect_planner(
            iter_plan(
                client=client,
                request=_planner_request(
                    policy="interactive",
                    clarification_history=[
                        {"clarification_id": "turn-3", "questions": [], "user_message": "使用知识库"}
                    ],
                ),
            )
        )


def test_two_distinct_empty_searches_exhaust_resource_kind_and_third_fails():
    client = _ActionClient(
        [
            _resolve_resource_mode_action(
                "rag.source",
                resource_kind="dataset",
                source="workspace",
                binding_time="design_time",
                evidence="工作区知识库",
            ),
            {
                "action": "resolve_resource",
                "intent_id": "rag-source",
                "requirement_key": "rag.source",
                "resource_kind": "dataset",
                "binding_time": "design_time",
                "query": "knowledge",
            },
            {
                "action": "resolve_resource",
                "intent_id": "rag-source",
                "requirement_key": "rag.source",
                "resource_kind": "dataset",
                "binding_time": "design_time",
                "query": "rag",
            },
            {
                "action": "resolve_resource",
                "intent_id": "rag-source",
                "requirement_key": "rag.source",
                "resource_kind": "dataset",
                "binding_time": "design_time",
                "query": "documents",
            },
        ]
    )

    with pytest.raises(PlannerNoProgressError, match="exhausted"):
        _collect_planner(
            iter_plan(
                client=client,
                request=_planner_request(
                    instruction="使用工作区知识库",
                    user_turn=UserTurn(
                        id="turn-1",
                        kind="message",
                        message="使用工作区知识库",
                        expected_revision=0,
                    ),
                ),
            )
        )

    second_observation = str(client.messages[3][-1].content)
    assert '"status":"exhausted"' in second_observation


def test_iter_plan_resolves_approved_tool_then_submits_a_plan():
    client = _ActionClient(
        [
            _resolve_resource_mode_action(
                "search.tool",
                resource_kind="tool",
                source="workspace",
                binding_time="design_time",
                evidence="workspace web search tool",
            ),
            {
                "action": "resolve_resource",
                "intent_id": "search-tool",
                "requirement_key": "search.tool",
                "resource_kind": "tool",
                "binding_time": "design_time",
                "query": "web search",
            },
            {"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []},
        ]
    )
    tools = [
        {
            "provider_name": "google",
            "provider_type": "builtin",
            "plugin_id": "",
            "tool_name": "search",
            "tool_label": "Web Search",
            "description": "Search the web.",
        }
    ]

    events, outcome = _collect_planner(
        iter_plan(
            client=client,
            request=_planner_request(
                instruction="Use the workspace web search tool",
                tool_catalogue_entries=tools,
                user_turn=UserTurn(
                    id="turn-1",
                    kind="message",
                    message="Use the workspace web search tool",
                    expected_revision=0,
                ),
            ),
        )
    )

    assert [event[1]["action"] for event in events] == [
        "requirements_resolved",
        "resource_resolving",
        "resource_bound",
    ]
    assert isinstance(outcome, PlannerPlanOutcome)
    assert outcome.plan["title"] == "Summary"
    assert outcome.context_checkpoint["resource_bindings"]["search-tool"]["resource_name"] == "Web Search"


def test_iter_plan_interactive_policy_returns_clarification_without_another_model_call():
    client = _ActionClient([_clarification_action()])

    events, outcome = _collect_planner(iter_plan(client=client, request=_planner_request(policy="interactive")))

    assert events == []
    assert isinstance(outcome, PlannerClarificationOutcome)
    assert outcome.questions[0]["id"] == "format"
    assert len(outcome.clarification_id) == 32
    assert outcome.context_checkpoint["version"] == 4
    assert outcome.context_checkpoint["requirements"] == {}
    assert outcome.context_checkpoint["pending_clarification"]["clarification_id"] == outcome.clarification_id
    assert outcome.context_checkpoint["pending_clarification"]["questions"] == list(outcome.questions)
    assert outcome.context_checkpoint["budget"] == {
        "model_actions": 1,
        "model_elapsed_ms": pytest.approx(0, abs=1000),
        "input_tokens": pytest.approx(0, abs=32768),
        "output_tokens": pytest.approx(0, abs=1000),
        "clarification_rounds": 1,
    }
    assert outcome.context_checkpoint["last_action_signature"]
    assert client.responses == []


def test_iter_plan_does_not_replay_unscoped_legacy_search() -> None:
    client = _ActionClient([{"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []}])
    tools = [
        {
            "provider_name": "google",
            "provider_type": "builtin",
            "plugin_id": "",
            "tool_name": "search",
            "tool_label": "Web Search",
            "description": "Current description.",
        }
    ]
    request = _planner_request(
        tool_catalogue_entries=tools,
        context_checkpoint={
            "version": 1,
            "searches": [{"kind": "tool", "query": "web search"}],
            "resolved_requirements": [],
        },
    )

    events, outcome = _collect_planner(iter_plan(client=client, request=request))

    assert isinstance(outcome, PlannerPlanOutcome)
    assert events == []
    assert outcome.context_checkpoint["search_observations"] == [
        {"kind": "tool", "query": "web search", "legacy": True}
    ]


def test_iter_plan_rejects_oversized_lossless_context_before_model_call() -> None:
    client = _ActionClient([{"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []}])
    client.model_instance.get_model_schema = lambda: SimpleNamespace(
        parameter_rules=[],
        model_properties={ModelPropertyKey.CONTEXT_SIZE: 4096},
    )

    with pytest.raises(PlannerContextLimitError, match="context limit"):
        _collect_planner(iter_plan(client=client, request=_planner_request(instruction="required" * 10000)))

    assert client.messages == []


def test_iter_plan_assume_defaults_policy_feeds_recommendation_back_to_model():
    client = _ActionClient(
        [
            _clarification_action(),
            {"action": "submit_plan", "plan": _submitted_plan(), "assumptions": ["Use Markdown."]},
        ]
    )

    _, outcome = _collect_planner(iter_plan(client=client, request=_planner_request(policy="assume_defaults")))

    assert isinstance(outcome, PlannerPlanOutcome)
    assert outcome.assumptions == ("Use Markdown.",)
    assert "markdown" in str(client.messages[1][-1].content).lower()
    assert outcome.context_checkpoint["phase"] == "completed"
    assert outcome.context_checkpoint["revision"] == 2


def test_iter_plan_assume_defaults_interprets_an_active_user_turn():
    client = _ActionClient(
        [
            _clarification_action(),
            {"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []},
        ]
    )

    _, outcome = _collect_planner(
        iter_plan(
            client=client,
            request=_planner_request(
                policy="assume_defaults",
                user_turn=UserTurn(id="turn-1", kind="message", message="Summarize web results"),
            ),
        )
    )

    assert isinstance(outcome, PlannerPlanOutcome)
    assert outcome.context_checkpoint["active_turn"] == {
        "turn_id": "turn-1",
        "kind": "message",
        "status": "interpreted",
        "message": "Summarize web results",
    }


def test_iter_plan_rejects_an_identical_consecutive_action():
    client = _ActionClient(
        [
            {"action": "search_tools", "query": "web"},
            {"action": "search_tools", "query": "web"},
        ]
    )

    with pytest.raises(PlannerNoProgressError, match="repeated a denied action"):
        _collect_planner(iter_plan(client=client, request=_planner_request()))


def test_iter_plan_stops_after_twenty_four_cumulative_model_actions():
    client = _ActionClient([{"action": "search_tools", "query": f"query-{index}"} for index in range(24)])
    client.model_instance.get_model_schema = lambda: SimpleNamespace(
        parameter_rules=[],
        model_properties={ModelPropertyKey.CONTEXT_SIZE: 131072},
    )

    with pytest.raises(PlannerBudgetExhaustedError, match="24 model actions"):
        _collect_planner(
            iter_plan(client=client, request=_planner_request(tool_catalogue_entries=[_query_matching_tool()]))
        )


def test_iter_plan_allows_submit_plan_as_the_twenty_fourth_action() -> None:
    responses = [{"action": "search_tools", "query": f"query-{index}"} for index in range(23)]
    responses.append({"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []})
    client = _ActionClient(responses)
    client.model_instance.get_model_schema = lambda: SimpleNamespace(
        parameter_rules=[],
        model_properties={ModelPropertyKey.CONTEXT_SIZE: 131072},
    )

    _, outcome = _collect_planner(
        iter_plan(client=client, request=_planner_request(tool_catalogue_entries=[_query_matching_tool()]))
    )

    assert isinstance(outcome, PlannerPlanOutcome)
    assert len(client.messages) == 24


def test_iter_plan_budget_is_restored_across_requests() -> None:
    client = _ActionClient([{"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []}])
    request = _planner_request(
        context_checkpoint={
            "version": 2,
            "searches": [],
            "resolved_requirements": [],
            "budget": {
                "model_actions": 24,
                "model_elapsed_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "clarification_rounds": 0,
            },
        }
    )

    with pytest.raises(PlannerBudgetExhaustedError, match="24 model actions"):
        _collect_planner(iter_plan(client=client, request=request))

    assert client.messages == []


def test_iter_plan_keeps_v2_search_as_history_without_replaying_it() -> None:
    client = _ActionClient([{"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []}])
    tools = [
        {
            "provider_name": "google",
            "provider_type": "builtin",
            "plugin_id": "",
            "tool_name": "search",
            "tool_label": "Web Search",
            "description": "Search the web.",
        }
    ]
    request = _planner_request(
        tool_catalogue_entries=tools,
        context_checkpoint={
            "version": 2,
            "searches": [{"kind": "tool", "query": "web search"}],
            "resolved_requirements": [],
            "budget": {
                "model_actions": 1,
                "model_elapsed_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "clarification_rounds": 0,
            },
        },
    )

    events, outcome = _collect_planner(iter_plan(client=client, request=request))

    assert events == []
    assert isinstance(outcome, PlannerPlanOutcome)
    assert outcome.context_checkpoint["search_observations"] == [
        {"kind": "tool", "query": "web search", "legacy": True}
    ]


@pytest.mark.parametrize(
    ("budget_field", "budget_value", "expected"),
    [
        ("model_elapsed_ms", 120_000, "120 seconds"),
        ("input_tokens", 4 * 32768, "token budget"),
    ],
)
def test_iter_plan_enforces_persistent_time_and_token_budgets(budget_field, budget_value, expected) -> None:
    budget = {
        "model_actions": 0,
        "model_elapsed_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "clarification_rounds": 0,
    }
    budget[budget_field] = budget_value
    client = _ActionClient([{"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []}])

    with pytest.raises(PlannerBudgetExhaustedError, match=expected):
        _collect_planner(
            iter_plan(
                client=client,
                request=_planner_request(
                    context_checkpoint={
                        "version": 2,
                        "searches": [],
                        "resolved_requirements": [],
                        "budget": budget,
                    }
                ),
            )
        )

    assert client.messages == []


def test_iter_plan_rejects_a_requirement_resolved_in_an_earlier_request() -> None:
    repeated_question = _clarification_action()
    repeated_question["questions"][0]["requirement_key"] = "output.format"
    repeated_question["questions"][0]["kind"] = "single_choice"
    client = _ActionClient([repeated_question, repeated_question])
    request = _planner_request(
        policy="interactive",
        context_checkpoint={
            "version": 2,
            "searches": [],
            "resolved_requirements": [
                {
                    "question_id": "format-old",
                    "requirement_key": "output.format",
                    "kind": "single_choice",
                    "question": "Old format question",
                    "answer": "markdown",
                    "label": "Markdown",
                    "source": "user",
                }
            ],
            "budget": {
                "model_actions": 1,
                "model_elapsed_ms": 10,
                "input_tokens": 100,
                "output_tokens": 20,
                "clarification_rounds": 1,
            },
        },
    )

    with pytest.raises(PlannerNoProgressError, match="resolved requirement"):
        _collect_planner(iter_plan(client=client, request=request))


def test_iter_plan_stops_after_four_clarification_rounds() -> None:
    client = _ActionClient([_clarification_action()])
    request = _planner_request(
        policy="interactive",
        context_checkpoint={
            "version": 2,
            "searches": [],
            "resolved_requirements": [],
            "budget": {
                "model_actions": 4,
                "model_elapsed_ms": 10,
                "input_tokens": 100,
                "output_tokens": 20,
                "clarification_rounds": 4,
            },
        },
    )

    with pytest.raises(PlannerClarificationLimitError, match="4 clarification rounds"):
        _collect_planner(iter_plan(client=client, request=request))


def test_iter_plan_returns_assistant_message_without_losing_checkpoint() -> None:
    client = _ActionClient(
        [{"action": "respond_to_user", "message": "I will retrieve relevant passages, then summarize them."}]
    )

    _, outcome = _collect_planner(iter_plan(client=client, request=_planner_request(policy="interactive")))

    assert outcome == PlannerAssistantMessageOutcome(
        message="I will retrieve relevant passages, then summarize them.",
        context_checkpoint=outcome.context_checkpoint,
    )
    assert outcome.context_checkpoint["version"] == 4


def test_iter_plan_replace_instruction_resets_goal_and_continues_planning() -> None:
    client = _ActionClient(
        [
            {"action": "replace_instruction", "instruction": "Build a support routing workflow"},
            {"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []},
            {"action": "acknowledge_turn"},
            {"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []},
        ]
    )

    events, outcome = _collect_planner(iter_plan(client=client, request=_planner_request(policy="interactive")))

    assert isinstance(outcome, PlannerPlanOutcome)
    assert "Build a support routing workflow" in str(client.messages[1][1].content)
    assert [event[1]["action"] for event in events] == [
        "replace_instruction",
        "action_denied",
        "turn_interpreted",
    ]
    assert outcome.context_checkpoint["goal_id"] != "current-goal"
    assert outcome.context_checkpoint["budget"]["model_actions"] == 3


def test_iter_plan_rejects_resource_candidates_not_returned_by_search() -> None:
    client = _ActionClient(
        [
            {"action": "search_knowledge", "query": "docs"},
            {
                "action": "request_user_input",
                "questions": [
                    {
                        "id": "knowledge",
                        "requirement_key": "knowledge.selection",
                        "kind": "resource_select",
                        "question": "Choose knowledge.",
                        "resource_kind": "dataset",
                        "multiple": False,
                        "candidates": [
                            {"id": "invented-dataset", "label": "Invented", "description": "Not searched."}
                        ],
                        "default_resource_ids": [],
                    }
                ],
            },
        ]
    )
    knowledge = [
        {"id": "dataset-1", "name": "Product docs", "description": "Product documentation."},
        {"id": "dataset-2", "name": "Support docs", "description": "Support documentation."},
    ]

    with pytest.raises(StageSchemaError, match="resource candidate"):
        _collect_planner(
            iter_plan(
                client=client,
                request=_planner_request(
                    policy="interactive",
                    knowledge_catalogue_entries=knowledge,
                ),
            )
        )


def test_iter_plan_auto_binds_a_unique_knowledge_search_result() -> None:
    client = _ActionClient(
        [
            {"action": "search_knowledge", "query": "拼"},
            {"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []},
        ]
    )
    knowledge = [{"id": "dataset-ping", "name": "拼", "description": "Only matching knowledge base."}]

    events, outcome = _collect_planner(
        iter_plan(
            client=client,
            request=_planner_request(knowledge_catalogue_entries=knowledge),
        )
    )

    assert isinstance(outcome, PlannerPlanOutcome)
    assert events[0][1]["action"] == "action_denied"
    assert outcome.assumptions == ()
    assert outcome.context_checkpoint["resource_bindings"] == {}


def test_validate_planner_schema_rejects_non_string_start_variable():
    with pytest.raises(StageSchemaError, match="start_inputs"):
        validate_planner_schema(
            {
                "nodes": [{"id": "start", "node_type": "start"}],
                "edges": [{"source": "start", "target": "start"}],
                "start_inputs": [{"variable": 1, "label": "Input", "type": "text-input"}],
            }
        )


def test_plan_rejects_builder_configuration_fields():
    plan = _submitted_plan()
    plan["nodes"][0]["data"] = {"variables": []}

    with pytest.raises(StageSchemaError, match="unexpected node fields"):
        validate_planner_schema(plan)


def test_plan_rejects_oversized_serialized_payload():
    plan = _submitted_plan()
    plan["description"] = "x" * (64 * 1024)

    with pytest.raises(StageSchemaError, match="64 KiB"):
        validate_planner_schema(plan)


def test_planner_recovers_once_from_truncation_with_compact_instruction():
    client = _TruncatingActionClient(
        [
            StageTruncatedError("Planner", "first output limit"),
            {"action": "submit_plan", "plan": _submitted_plan(), "assumptions": []},
        ]
    )

    _, outcome = _collect_planner(iter_plan(client=client, request=_planner_request()))

    assert isinstance(outcome, PlannerPlanOutcome)
    assert len(client.messages) == 2
    assert "previous Planner response was truncated" in str(client.messages[1][-1].content)


def test_second_planner_truncation_includes_recoverable_v4_checkpoint():
    client = _TruncatingActionClient(
        [
            StageTruncatedError("Planner", "first output limit"),
            StageTruncatedError("Planner", "second output limit"),
        ]
    )

    with pytest.raises(StageTruncatedError) as raised:
        _collect_planner(iter_plan(client=client, request=_planner_request()))

    checkpoint = raised.value.context_checkpoint
    assert checkpoint["version"] == 4
    assert checkpoint["truncation_recoveries"] == 1


def test_auto_mode_uses_end_terminal_for_workflow():
    plan = {"nodes": [{"node_type": "start"}, {"node_type": "end"}]}

    assert resolve_generation_mode("auto", plan) == "workflow"


from ._runner_test_support import (
    Any,
    MagicMock,
    WorkflowGenerator,
    _GraphFixtureModel,
    _llm_result,
    _ParallelBuilderModel,
    _stream_text,
    cast,
    json,
)


class TestAutoModeResolution:
    """``mode="auto"`` resolves from the planner output — no extra LLM call."""

    _WORKFLOW_PLANNER: dict[str, Any] = {
        "title": "URL Summarizer",
        "description": "Summarize a URL.",
        "nodes": [
            {"id": "node1", "label": "Start", "node_type": "start", "purpose": "Receive URL."},
            {"id": "node2", "label": "End", "node_type": "end", "purpose": "Return summary."},
        ],
        "edges": [{"source": "node1", "target": "node2"}],
    }
    _WORKFLOW_CONFIGS: dict[str, dict[str, Any]] = {
        "node1": {
            "variables": [
                {
                    "variable": "url",
                    "label": "URL",
                    "type": "text-input",
                    "required": True,
                    "max_length": 256,
                    "options": [],
                }
            ]
        },
        "node2": {"outputs": [{"variable": "summary", "value_selector": ["node1", "url"]}]},
    }

    def _generate(self, planner: dict[str, Any], configs: dict[str, dict[str, Any]], mode: str):
        model = _ParallelBuilderModel(planner, configs)
        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode=cast(Any, mode),
            instruction="Summarize a URL",
        )
        return result, model

    def test_auto_resolves_from_planner_mode_field(self):
        planner = {**self._WORKFLOW_PLANNER, "mode": "workflow"}

        result, model = self._generate(planner, self._WORKFLOW_CONFIGS, "auto")

        assert result["error"] == ""
        assert result["mode"] == "workflow"
        # exactly one planner call + one builder per node — no classification call
        assert model.planner_calls == 1
        assert model.builder_calls == 2

    def test_auto_without_mode_field_infers_from_terminal_node(self):
        planner = {
            "title": "Greeting Bot",
            "description": "Echo greeting.",
            "nodes": [
                {"id": "node1", "label": "Start", "node_type": "start", "purpose": "Receive query."},
                {"id": "node2", "label": "Reply", "node_type": "answer", "purpose": "Reply to user."},
            ],
            "edges": [{"source": "node1", "target": "node2"}],
        }
        configs: dict[str, dict[str, Any]] = {"node1": {"variables": []}, "node2": {"answer": "Hi!"}}

        result, _ = self._generate(planner, configs, "auto")

        assert result["error"] == ""
        assert result["mode"] == "advanced-chat"

    def test_auto_ignores_invalid_planner_mode_value(self):
        planner = {**self._WORKFLOW_PLANNER, "mode": "chatbot-3000"}

        result, _ = self._generate(planner, self._WORKFLOW_CONFIGS, "auto")

        assert result["error"] == ""
        assert result["mode"] == "workflow"

    def test_explicit_mode_wins_over_contradictory_planner_mode(self):
        planner = {**self._WORKFLOW_PLANNER, "mode": "advanced-chat"}

        result, _ = self._generate(planner, self._WORKFLOW_CONFIGS, "workflow")

        assert result["error"] == ""
        assert result["mode"] == "workflow"

    def test_auto_planner_failure_stamps_conversational_default(self):
        model_instance = MagicMock()
        model_instance.invoke_llm.return_value = _llm_result("not json at all")

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="auto",
            instruction="x",
        )

        assert result["error"]
        assert result["mode"] == "advanced-chat"

    def test_auto_with_no_terminal_node_defaults_to_conversational(self):
        from core.workflow.generator.planner import resolve_generation_mode as _resolve_generation_mode

        plan = cast(Any, {"title": "x", "description": "x", "nodes": [{"node_type": "llm"}]})
        assert _resolve_generation_mode("auto", plan) == "advanced-chat"

    def test_auto_prompt_and_plan_event_carry_resolved_mode(self):
        planner = {**self._WORKFLOW_PLANNER, "mode": "workflow"}
        model = _ParallelBuilderModel(planner, self._WORKFLOW_CONFIGS)

        events = list(
            WorkflowGenerator.generate_workflow_graph_stream(
                model_instance=model,
                model_parameters={},
                provider="openai",
                model_name="gpt-4o",
                model_mode="chat",
                mode="auto",
                instruction="Summarize a URL",
            )
        )

        plan_events = [payload for name, payload in events if name == "plan"]
        assert len(plan_events) == 1
        assert plan_events[0]["mode"] == "workflow"
        planner_prompt = str(model.planner_prompt_messages[-1].content)
        assert "auto (choose workflow or advanced-chat)" in planner_prompt


class TestPlannerSchemaValidation:
    """Planner responses missing the topology contract are rejected with a stage error."""

    _NODES = [{"id": "node1", "label": "Start", "node_type": "start", "purpose": "x"}]

    def test_defaults_omitted_resource_requests_to_empty_list(self):
        parsed = {"nodes": self._NODES, "edges": [{"source": "node1", "target": "node1"}]}

        plan = validate_planner_schema(parsed)

        assert plan["resource_requests"] == []

    def test_non_list_nodes_value_is_rejected(self):
        with pytest.raises(ValueError, match="missing 'nodes' array"):
            validate_planner_schema({"nodes": "start,llm,end"})

    def test_node_entry_without_node_type_is_rejected(self):
        with pytest.raises(ValueError, match="malformed node entry"):
            validate_planner_schema({"nodes": [{"id": "node1", "label": "Start"}]})

    def test_missing_edges_array_is_rejected(self):
        with pytest.raises(ValueError, match="missing non-empty 'edges' array"):
            validate_planner_schema({"nodes": self._NODES, "edges": []})

    def test_malformed_edge_entry_is_rejected(self):
        with pytest.raises(ValueError, match="malformed edge entry"):
            validate_planner_schema({"nodes": self._NODES, "edges": ["node1->node2"]})

    def test_edge_with_non_string_endpoint_is_rejected(self):
        with pytest.raises(ValueError, match="edge missing source or target"):
            validate_planner_schema({"nodes": self._NODES, "edges": [{"source": "node1", "target": 2}]})

    def test_start_input_with_non_string_variable_is_rejected(self):
        parsed = {
            "nodes": self._NODES,
            "edges": [{"source": "node1", "target": "node1"}],
            "start_inputs": [{"variable": 123, "label": "Bad", "type": "text-input"}],
        }

        with pytest.raises(ValueError, match="start_inputs"):
            validate_planner_schema(parsed)

    def test_malformed_start_input_returns_schema_error_envelope(self):
        planner = {
            "nodes": [
                {"id": "node1", "label": "Start", "node_type": "start", "purpose": "x"},
                {"id": "node2", "label": "End", "node_type": "end", "purpose": "x"},
            ],
            "edges": [{"source": "node1", "target": "node2"}],
            "start_inputs": [{"variable": 123, "label": "Bad", "type": "text-input"}],
        }
        model = _ParallelBuilderModel(planner, {})

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert result["errors"][0]["code"] == "INVALID_SCHEMA"
        assert result["graph"]["nodes"] == []


class TestPlannerRecoversReasoningWrappedJson:
    """A planner reply wrapped in <think> must still produce a plan."""

    def test_reasoning_wrapped_planner_reply_succeeds_on_first_attempt(self):
        planner = {
            "title": "x",
            "description": "x",
            "nodes": [
                {"id": "node1", "label": "Start", "node_type": "start", "purpose": "x"},
                {"id": "node2", "label": "End", "node_type": "end", "purpose": "x"},
            ],
            "edges": [{"source": "node1", "target": "node2"}],
        }
        builder = json.dumps({"config": {}})

        class _ReasoningModel:
            def __init__(self) -> None:
                self.planner_calls = 0

            def invoke_llm(self, *, prompt_messages, model_parameters, stream):
                if "workflow planner" in str(prompt_messages[0].content).lower():
                    self.planner_calls += 1
                    text = f"<think>用户要一个两节点流程 {{草稿}}</think>{json.dumps(planner)}"
                    return _stream_text(text) if stream else _llm_result(text)
                return _stream_text(builder) if stream else _llm_result(builder)

        model_instance = _ReasoningModel()
        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert model_instance.planner_calls == 1
        assert not any(error["code"] == "INVALID_JSON" for error in result["errors"])


class TestPlannerUsesTheModelCeiling:
    """The planner output budget must leave room for its input context."""

    def test_planner_budget_comes_from_the_model_schema(self):
        planner = {
            "title": "x",
            "description": "x",
            "nodes": [
                {"id": "node1", "label": "Start", "node_type": "start", "purpose": "x"},
                {"id": "node2", "label": "End", "node_type": "end", "purpose": "x"},
            ],
            "edges": [{"source": "node1", "target": "node2"}],
        }
        builder = json.dumps({"config": {}})
        planner_budgets: list[int] = []

        class _CeilingModel:
            def get_model_schema(self):
                return SimpleNamespace(
                    parameter_rules=[SimpleNamespace(name="max_tokens", max=32000)],
                    model_properties={ModelPropertyKey.CONTEXT_SIZE: 128000},
                )

            def get_llm_num_tokens(self, prompt_messages):
                return sum(len(str(message.content or "")) for message in prompt_messages) // 4

            def invoke_llm(self, *, prompt_messages, model_parameters, stream):
                if "workflow planner" in str(prompt_messages[0].content).lower():
                    planner_budgets.append(model_parameters["max_tokens"])
                    return _stream_text(json.dumps(planner)) if stream else _llm_result(json.dumps(planner))
                return _stream_text(builder) if stream else _llm_result(builder)

        WorkflowGenerator.generate_workflow_graph(
            model_instance=_CeilingModel(),
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert planner_budgets == [8192]


class TestWorkflowGeneratorAppMetadata:
    """
    Planner-supplied ``app_name`` / ``icon`` flow through to the result so
    the frontend's ``applyToNewApp`` can use a meaningful product name and
    emoji instead of the canned ``deriveAppName`` + 🤖 fallback.
    """

    def _planner_with_metadata(self) -> str:
        return json.dumps(
            {
                "title": "URL Summarizer",
                "description": "Fetch a URL and summarize it.",
                "app_name": "URL Summarizer",
                "icon": "📰",
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "Take URL."},
                    {"label": "End", "node_type": "end", "purpose": "Return summary."},
                ],
            }
        )

    def _planner_without_metadata(self) -> str:
        return json.dumps(
            {
                "title": "Untitled",
                "description": "...",
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "x"},
                    {"label": "End", "node_type": "end", "purpose": "x"},
                ],
            }
        )

    def _minimal_builder(self) -> str:
        return json.dumps(
            {
                "nodes": [
                    {
                        "id": "node1",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "start", "title": "Start"},
                    },
                    {
                        "id": "node2",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "end", "title": "End"},
                    },
                ],
                "edges": [
                    {"id": "x", "source": "node1", "target": "node2", "type": "custom"},
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )

    def test_surfaces_planner_app_name_and_icon(self):
        # When the planner emits ``app_name`` + ``icon``, the runner must
        # forward them verbatim. The frontend uses them to name the new App
        # and pick its display icon.
        model_instance = _GraphFixtureModel(self._planner_with_metadata(), self._minimal_builder())

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Summarize a URL",
        )

        assert result["error"] == ""
        assert result["app_name"] == "URL Summarizer"
        assert result["icon"] == "📰"

    def test_defaults_to_empty_strings_when_planner_omits_metadata(self):
        # Planner outputs that drop the optional fields must not break the
        # pipeline — both fields default to "" so the
        # frontend can run its own ``deriveAppName`` + 🤖 fallback.
        model_instance = _GraphFixtureModel(self._planner_without_metadata(), self._minimal_builder())

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert result["error"] == ""
        assert result["app_name"] == ""
        assert result["icon"] == ""

    def test_metadata_is_stripped_of_surrounding_whitespace(self):
        # Some LLMs return ``"app_name": "  URL Summarizer  "`` — the runner
        # must strip both ends so the frontend doesn't have to.
        planner = json.dumps(
            {
                "title": "x",
                "description": "x",
                "app_name": "   URL Summarizer   ",
                "icon": "  📰  ",
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "x"},
                    {"label": "End", "node_type": "end", "purpose": "x"},
                ],
            }
        )
        model_instance = _GraphFixtureModel(planner, self._minimal_builder())

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert result["app_name"] == "URL Summarizer"
        assert result["icon"] == "📰"
