from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from core.workflow.generator.agent.tools.tools import dispatch
from core.workflow.generator.agent.types import ToolCall
from core.workflow.generator.contracts.workflow_contract import workflow_plan_mutation_error
from core.workflow.generator.contracts.workflow_reconciliation import reconcile_workflow_contract
from core.workflow.generator.graph.graph_ops import upsert_node


def _call(plan: dict[str, object], *, expected_revision: int = 0) -> ToolCall:
    return {
        "id": "plan-1",
        "name": "submit_workflow_plan",
        "arguments": {"expected_revision": expected_revision, "plan": plan},
    }


def _complete_plan() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "complete",
        "operation": "rebuild",
        "requirements": [
            {
                "id": "req.answer",
                "source_turn_id": "turn-1",
                "evidence": "Answer the user's question",
                "text": "Answer the user's question",
                "provenance": "explicit_user",
            }
        ],
        "assumptions": [],
        "edit_scope": None,
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "objective": "Collect the question",
                "requirement_ids": ["req.answer"],
                "inputs": [],
                "outputs": [{"name": "query", "type": "string"}],
                "structure_kind": "start",
                "unresolved": [],
            },
            {
                "id": "answer",
                "type": "end",
                "objective": "Return the answer",
                "requirement_ids": ["req.answer"],
                "inputs": [{"source": ["start", "query"], "role": "answer"}],
                "outputs": [{"name": "answer", "type": "string"}],
                "structure_kind": "end",
                "unresolved": [],
            },
        ],
        "edges": [{"source": "start", "target": "answer"}],
        "final_outputs": [{"name": "answer", "source": ["answer", "answer"], "type": "string"}],
        "resources": [],
        "checks": [
            {
                "id": "check.answer",
                "description": "The terminal returns an answer",
                "level": "static",
                "requirement_ids": ["req.answer"],
            }
        ],
        "unresolved": [],
    }


def test_submit_first_complete_plan_advances_only_contract_revision(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    graph_before = deepcopy(tool_context.state.graph)
    graph_revision_before = tool_context.state.candidate_revision

    result = dispatch(_call(_complete_plan()), tool_context)

    assert result["ok"] is True
    assert result["changed"] is False
    assert result["content"] == {
        "schema_version": 1,
        "revision": 1,
        "status": "complete",
        "operation": "rebuild",
        "contract_hash": tool_context.state.contract_hash,
    }
    assert isinstance(tool_context.state.contract_hash, str)
    assert len(tool_context.state.contract_hash) == 64
    assert tool_context.state.contract_revision == 1
    assert tool_context.state.workflow_contract is not None
    assert tool_context.state.workflow_contract["revision"] == 1
    assert tool_context.state.graph == graph_before
    assert tool_context.state.candidate_revision == graph_revision_before


def test_submit_plan_rejects_stale_revision_without_changing_contract(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    first = dispatch(_call(_complete_plan()), tool_context)
    assert first["ok"] is True
    before = deepcopy(tool_context.state.workflow_contract)

    result = dispatch(_call(_complete_plan(), expected_revision=0), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "CONTRACT_REVISION_CONFLICT"
    assert result["cause"] == {"expected_revision": 0, "current_revision": 1}
    assert tool_context.state.workflow_contract == before
    assert tool_context.state.contract_revision == 1


def test_explicit_requirement_evidence_must_exist_in_its_user_turn(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Build an invoice summarizer"}
    plan = _complete_plan()
    plan["requirements"][0]["source_turn_id"] = "turn-1"  # type: ignore[index]
    plan["requirements"][0]["evidence"] = "Send invoices by email"  # type: ignore[index]

    result = dispatch(_call(plan), tool_context)

    assert result["error_code"] == "INVALID_REQUIREMENT_EVIDENCE"
    assert result["cause"] == {"requirement_ids": ["req.answer"]}


def test_plan_revision_cannot_silently_drop_explicit_user_requirement(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    first = dispatch(_call(_complete_plan()), tool_context)
    assert first["ok"] is True
    revised = _complete_plan()
    revised["status"] = "draft"
    revised["requirements"] = []
    for node in revised["nodes"]:  # type: ignore[union-attr]
        node["requirement_ids"] = []
    revised["checks"] = []

    result = dispatch(_call(revised, expected_revision=1), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "EXPLICIT_REQUIREMENT_DROPPED"
    assert result["cause"] == {"requirement_ids": ["req.answer"]}
    assert tool_context.state.contract_revision == 1


def test_complete_plan_requires_every_requirement_in_a_node_and_check(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question and keep it concise"}
    plan = _complete_plan()
    plan["requirements"].append(  # type: ignore[union-attr]
        {
            "id": "req.concise",
            "source_turn_id": "turn-1",
            "evidence": "keep it concise",
            "text": "Keep the answer concise",
            "provenance": "explicit_user",
        }
    )

    result = dispatch(_call(plan), tool_context)

    assert result["error_code"] == "INVALID_WORKFLOW_PLAN"
    assert "referenced by at least one node and check" in result["error"]


def test_explicit_requirement_change_requires_a_new_explicit_user_turn(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {
        "turn-1": "Please answer the user's question",
        "turn-2": "Return a revised answer",
    }
    assert dispatch(_call(_complete_plan()), tool_context)["ok"] is True
    revised = _complete_plan()
    revised["status"] = "draft"
    revised["requirements"] = [
        {
            "id": "req.revised",
            "source_turn_id": "turn-2",
            "evidence": "Return a revised answer",
            "text": "Return a revised answer",
            "provenance": "model_interpretation",
            "supersedes": ["req.answer"],
        }
    ]
    for node in revised["nodes"]:  # type: ignore[union-attr]
        node["requirement_ids"] = ["req.revised"]
    revised["checks"] = []

    model_rewrite = dispatch(_call(revised, expected_revision=1), tool_context)
    revised["requirements"][0]["provenance"] = "explicit_user"  # type: ignore[index]
    explicit_rewrite = dispatch(_call(revised, expected_revision=1), tool_context)

    assert model_rewrite["error_code"] == "EXPLICIT_REQUIREMENT_DROPPED"
    assert explicit_rewrite["ok"] is True


def test_new_contract_run_requires_plan_before_graph_mutation(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1

    result = dispatch(
        {"id": "delete-1", "name": "delete_node", "arguments": {"node_id": "old"}},
        tool_context,
    )

    assert result["error_code"] == "WORKFLOW_PLAN_REQUIRED"
    assert tool_context.state.candidate_revision == 0


def test_submitted_plan_blocks_undeclared_node_build_and_edge(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    assert dispatch(_call(_complete_plan()), tool_context)["ok"] is True

    undeclared_node = dispatch(
        {
            "id": "build-1",
            "name": "build_node",
            "arguments": {
                "mode": "create",
                "id": "extra",
                "type": "template-transform",
                "title": "Extra",
                "intent": {"objective": "Unplanned work"},
            },
        },
        tool_context,
    )
    undeclared_edge = dispatch(
        {"id": "connect-1", "name": "connect", "arguments": {"source": "answer", "target": "start"}},
        tool_context,
    )

    assert undeclared_node["error_code"] == "PLAN_MUTATION_NOT_DECLARED"
    assert undeclared_node["cause"] == {"node_ids": ["extra"]}
    assert undeclared_edge["error_code"] == "PLAN_MUTATION_NOT_DECLARED"
    assert undeclared_edge["cause"] == {"edge": {"source": "answer", "target": "start", "source_handle": None}}


def test_build_node_must_match_planned_type_and_intent(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    assert dispatch(_call(_complete_plan()), tool_context)["ok"] is True

    result = dispatch(
        {
            "id": "build-1",
            "name": "build_node",
            "arguments": {
                "mode": "create",
                "id": "answer",
                "type": "code",
                "title": "Answer",
                "intent": {
                    "objective": "Run arbitrary code",
                    "inputs": [],
                    "outputs": [{"name": "result", "type": "string"}],
                },
            },
        },
        tool_context,
    )

    assert result["error_code"] == "PLAN_MUTATION_MISMATCH"
    assert {issue["field"] for issue in result["cause"]["issues"]} >= {"type", "objective", "inputs", "outputs"}


def test_specialized_builder_must_match_planned_resource_binding(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    tool_context.env = replace(
        tool_context.env,
        tools_available=True,
        installed_tools={("builtin/time", "current_time"), ("builtin/weather", "forecast")},
    )
    plan = _complete_plan()
    plan["nodes"][1]["type"] = "tool"  # type: ignore[index]
    plan["nodes"][1]["structure_kind"] = None  # type: ignore[index]
    plan["resources"] = [
        {
            "kind": "tool",
            "provider_name": "builtin/time",
            "tool_name": "current_time",
            "consumer_id": "answer",
        }
    ]
    assert dispatch(_call(plan), tool_context)["ok"] is True

    result = dispatch(
        {
            "id": "build-tool",
            "name": "build_tool_node",
            "arguments": {
                "mode": "create",
                "id": "answer",
                "title": "Answer",
                "tool": {"provider_name": "builtin/weather", "tool_name": "forecast"},
                "arguments": {},
            },
        },
        tool_context,
    )

    assert result["error_code"] == "PLAN_MUTATION_MISMATCH"
    assert result["cause"]["issues"] == [
        {
            "field": "resources.tools",
            "expected": [("builtin/time", "current_time")],
            "actual": [("builtin/weather", "forecast")],
        }
    ]


def test_llm_builder_must_match_planned_model_binding(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    plan = _complete_plan()
    plan["nodes"][1].update(  # type: ignore[index]
        {
            "type": "llm",
            "objective": "Return the answer",
            "outputs": [{"name": "text", "type": "string"}],
            "structure_kind": "llm",
        }
    )
    plan["final_outputs"] = [{"name": "answer", "source": ["answer", "text"], "type": "string"}]
    plan["resources"] = [
        {"kind": "model", "provider": "openai", "name": "gpt-4o", "mode": "chat", "consumer_id": "answer"}
    ]
    assert dispatch(_call(plan), tool_context)["ok"] is True
    result = dispatch(
        {
            "id": "build-llm",
            "name": "build_node",
            "arguments": {
                "mode": "create",
                "id": "answer",
                "type": "llm",
                "title": "Answer",
                "intent": {
                    "objective": "Return the answer",
                    "inputs": [{"source": ["start", "query"], "role": "answer"}],
                    "outputs": [{"name": "text", "type": "string"}],
                    "structure": {
                        "kind": "llm",
                        "model": {"provider": "openai", "name": "gpt-4.1", "mode": "chat"},
                        "prompt": [{"role": "user", "text": "Answer"}],
                    },
                },
            },
        },
        tool_context,
    )

    assert result["error_code"] == "PLAN_MUTATION_MISMATCH"
    assert result["cause"]["issues"] == [
        {
            "field": "resources.models",
            "expected": [("openai", "gpt-4o", "chat")],
            "actual": [("openai", "gpt-4.1", "chat")],
        }
    ]


def test_node_update_may_omit_structure_to_preserve_planned_model(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    plan = _complete_plan()
    plan["nodes"][1].update(  # type: ignore[index]
        {
            "type": "llm",
            "objective": "Return the answer",
            "outputs": [{"name": "text", "type": "string"}],
            "structure_kind": "llm",
        }
    )
    plan["final_outputs"] = [{"name": "answer", "source": ["answer", "text"], "type": "string"}]
    plan["resources"] = [
        {"kind": "model", "provider": "openai", "name": "gpt-4o", "mode": "chat", "consumer_id": "answer"}
    ]
    assert dispatch(_call(plan), tool_context)["ok"] is True
    tool_context.state.graph = upsert_node(
        tool_context.state.graph,
        node_id="answer",
        node_type="llm",
        title="Answer",
        desc="",
        config={},
    )

    result = workflow_plan_mutation_error(
        {
            "id": "update-llm",
            "name": "build_node",
            "arguments": {
                "mode": "update",
                "id": "answer",
                "intent": {
                    "objective": "Return the answer",
                    "inputs": [{"source": ["start", "query"], "role": "answer"}],
                    "outputs": [{"name": "text", "type": "string"}],
                },
            },
        },
        tool_context,
    )

    assert result is None


def test_agent_update_may_omit_knowledge_to_preserve_planned_datasets(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    tool_context.env = replace(
        tool_context.env,
        knowledge_available=True,
        installed_dataset_ids={"dataset-1"},
    )
    plan = _complete_plan()
    plan["nodes"][1].update(  # type: ignore[index]
        {
            "type": "agent",
            "objective": "Return the answer",
            "outputs": [{"name": "text", "type": "string"}],
            "structure_kind": None,
        }
    )
    plan["final_outputs"] = [{"name": "answer", "source": ["answer", "text"], "type": "string"}]
    plan["resources"] = [
        {"kind": "dataset", "dataset_id": "dataset-1", "consumer_id": "answer"},
        {"kind": "model", "provider": "openai", "name": "gpt-4o", "mode": "chat", "consumer_id": "answer"},
    ]
    assert dispatch(_call(plan), tool_context)["ok"] is True

    result = workflow_plan_mutation_error(
        {
            "id": "update-agent",
            "name": "build_agent_node",
            "arguments": {
                "mode": "update",
                "id": "answer",
                "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
                "instruction": "Return the answer",
                "inputs": [{"source": ["start", "query"], "role": "answer"}],
                "outputs": [{"name": "text", "type": "string"}],
                "tools": [],
                "mcp_tools": [],
            },
        },
        tool_context,
    )

    assert result is None


def test_draft_plan_blocks_only_unresolved_planned_node(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    plan = _complete_plan()
    plan["status"] = "draft"
    plan["unresolved"] = ["answer model is not selected"]
    plan["nodes"][1]["unresolved"] = ["model"]  # type: ignore[index]
    submitted = dispatch(_call(plan), tool_context)
    assert submitted["ok"] is True

    result = dispatch(
        {
            "id": "build-1",
            "name": "build_node",
            "arguments": {
                "mode": "create",
                "id": "answer",
                "type": "llm",
                "title": "Answer",
                "intent": {"objective": "Answer"},
            },
        },
        tool_context,
    )

    assert result["error_code"] == "PLAN_NODE_UNRESOLVED"
    assert result["cause"] == {"node_id": "answer", "unresolved": ["model"]}


def test_edit_plan_prevents_mutating_node_outside_declared_scope(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    tool_context.state.candidate_base_hash = "b" * 64
    tool_context.state.graph = upsert_node(
        tool_context.state.graph,
        node_id="unrelated",
        node_type="template-transform",
        title="Keep me",
        desc="",
        config={"template": "unchanged", "variables": []},
    )
    plan = _complete_plan()
    plan["status"] = "draft"
    plan["operation"] = "edit"
    plan["edit_scope"] = {
        "candidate_base_hash": "b" * 64,
        "allowed_node_ids": ["answer"],
        "affected_downstream_ids": [],
    }
    submitted = dispatch(_call(plan), tool_context)
    assert submitted["ok"] is True

    result = dispatch(
        {"id": "delete-1", "name": "delete_node", "arguments": {"node_id": "unrelated"}},
        tool_context,
    )

    assert result["error_code"] == "PLAN_EDIT_SCOPE_VIOLATION"
    assert result["cause"] == {"node_ids": ["unrelated"], "allowed_node_ids": ["answer"]}
    assert tool_context.state.graph["nodes"][0]["id"] == "unrelated"


def test_new_conversation_rollout_does_not_enable_edit_contracts(tool_context) -> None:
    tool_context.env = replace(tool_context.env, contract_rollout_stage="new_conversations")
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    tool_context.state.candidate_base_hash = "b" * 64
    plan = _complete_plan()
    plan["operation"] = "edit"
    plan["edit_scope"] = {
        "candidate_base_hash": "b" * 64,
        "allowed_node_ids": ["answer"],
        "affected_downstream_ids": [],
    }

    result = dispatch(_call(plan), tool_context)

    assert result["error_code"] == "CONTRACT_EDIT_ROLLOUT_DISABLED"


def test_submitting_plan_invalidates_prior_acceptance_evidence(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    tool_context.state.attempts["old"] = {"attempt_id": "old", "passed": True}  # type: ignore[typeddict-item]

    result = dispatch(_call(_complete_plan()), tool_context)

    assert result["ok"] is True
    assert tool_context.state.attempts == {}


def test_resource_verification_is_derived_from_run_catalogues(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    tool_context.env = replace(
        tool_context.env,
        knowledge_available=True,
        installed_dataset_ids={"dataset-1"},
        tools_available=True,
        installed_tools={("builtin/time", "current_time")},
    )
    plan = _complete_plan()
    plan["resources"] = [
        {"kind": "dataset", "dataset_id": "dataset-1", "consumer_id": "answer"},
        {
            "kind": "tool",
            "provider_name": "builtin/time",
            "tool_name": "current_time",
            "consumer_id": "answer",
        },
        {"kind": "model", "provider": "openai", "name": "gpt-4o", "mode": "chat", "consumer_id": "answer"},
    ]

    result = dispatch(_call(plan), tool_context)

    assert result["ok"] is True
    contract = tool_context.state.workflow_contract
    assert contract is not None
    assert all(resource["verified"] is True for resource in contract["resources"])  # type: ignore[union-attr]


def test_complete_plan_rejects_unknown_resource_and_model_cannot_claim_verified(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    tool_context.env = replace(tool_context.env, knowledge_available=True, installed_dataset_ids=set())
    plan = _complete_plan()
    plan["resources"] = [{"kind": "dataset", "dataset_id": "invented", "consumer_id": "answer"}]

    unknown = dispatch(_call(plan), tool_context)
    plan["resources"][0]["verified"] = True  # type: ignore[index]
    self_verified = dispatch(_call(plan), tool_context)

    assert unknown["error_code"] == "PLAN_RESOURCE_UNRESOLVED"
    assert unknown["cause"] == {"resources": ["dataset:invented"]}
    assert self_verified["error_code"] == "INVALID_WORKFLOW_PLAN"


def test_finish_requires_complete_plan_for_new_contract_protocol(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1

    missing = dispatch(
        {"id": "finish-1", "name": "finish", "arguments": {"summary": "done"}},
        tool_context,
    )

    assert missing["error_code"] == "WORKFLOW_PLAN_REQUIRED"

    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    draft = _complete_plan()
    draft["status"] = "draft"
    submitted = dispatch(_call(draft), tool_context)
    assert submitted["ok"] is True

    incomplete = dispatch(
        {"id": "finish-2", "name": "finish", "arguments": {"summary": "done"}},
        tool_context,
    )

    assert incomplete["error_code"] == "WORKFLOW_PLAN_INCOMPLETE"
    assert incomplete["cause"] == {"contract_revision": 1, "status": "draft"}


def test_finish_rejects_candidate_that_does_not_match_complete_contract(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    assert dispatch(_call(_complete_plan()), tool_context)["ok"] is True
    tool_context.state.graph = upsert_node(
        tool_context.state.graph,
        node_id="start",
        node_type="start",
        title="Start",
        desc="",
        config={
            "variables": [
                {
                    "variable": "query",
                    "label": "Question",
                    "type": "paragraph",
                    "required": True,
                    "max_length": 4096,
                    "options": [],
                }
            ]
        },
    )

    result = dispatch(
        {"id": "finish-1", "name": "finish", "arguments": {"summary": "Done"}},
        tool_context,
    )

    assert result["ok"] is False
    assert result["content"]["contract_report"]["passed"] is False
    checks = result["content"]["contract_report"]["checks"]
    assert any(check["id"] == "node:answer" and check["status"] == "missing" for check in checks)
    assert any(check["id"] == "check:check.answer" and check["status"] == "conflict" for check in checks)


def test_finish_accepts_matching_contract_but_keeps_business_check_unverified(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    plan = _complete_plan()
    plan["checks"][0]["level"] = "business"  # type: ignore[index]
    assert dispatch(_call(plan), tool_context)["ok"] is True
    graph = upsert_node(
        tool_context.state.graph,
        node_id="start",
        node_type="start",
        title="Start",
        desc="",
        config={
            "variables": [
                {
                    "variable": "query",
                    "label": "Question",
                    "type": "paragraph",
                    "required": True,
                    "max_length": 4096,
                    "options": [],
                }
            ]
        },
    )
    graph = upsert_node(
        graph,
        node_id="answer",
        node_type="end",
        title="End",
        desc="",
        config={"outputs": [{"variable": "answer", "value_selector": ["start", "query"], "value_type": "string"}]},
    )
    tool_context.state.graph = {
        **graph,
        "edges": [{"source": "start", "target": "answer"}],
    }

    result = dispatch(
        {"id": "finish-1", "name": "finish", "arguments": {"summary": "Done"}},
        tool_context,
    )

    assert result["ok"] is True, result
    report = result["content"]["contract_report"]
    assert report["passed"] is True
    assert any(check["id"] == "check:check.answer" and check["status"] == "unverified" for check in report["checks"])


def test_reconciliation_resolves_nested_final_selector_from_its_top_level_output(tool_context) -> None:
    tool_context.state.contract_protocol_version = 1
    tool_context.state.user_turn_evidence = {"turn-1": "Please answer the user's question"}
    plan = _complete_plan()
    plan["nodes"][1]["outputs"] = [{"name": "answer", "type": "object"}]  # type: ignore[index]
    plan["final_outputs"] = [{"name": "text", "source": ["answer", "answer", "text"], "type": "string"}]
    assert dispatch(_call(plan), tool_context)["ok"] is True
    contract = tool_context.state.workflow_contract
    assert contract is not None
    graph = {
        "nodes": [
            {
                "id": "start",
                "data": {"type": "start", "variables": [{"variable": "query", "type": "paragraph"}]},
            },
            {
                "id": "answer",
                "data": {
                    "type": "end",
                    "outputs": [
                        {
                            "variable": "answer",
                            "value_selector": ["start", "query"],
                            "value_type": "object",
                        }
                    ],
                },
            },
        ],
        "edges": [{"source": "start", "target": "answer"}],
    }

    report = reconcile_workflow_contract(contract=contract, graph=graph, mode="workflow")

    final_check = next(check for check in report["checks"] if check["id"] == "final_output:text")
    assert final_check["status"] == "satisfied"
