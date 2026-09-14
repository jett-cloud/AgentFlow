"""Deterministic generation matrix using real graph assembly and contract reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.workflow.generator.contracts.workflow_contract import canonical_workflow_contract_hash
from core.workflow.generator.contracts.workflow_reconciliation import reconcile_workflow_contract
from core.workflow.generator.validation.graph_validator import validate_graph
from core.workflow.generator.compiler.node_builder import assemble_graph
from core.workflow.generator.variables.syntax import collect_references
from services.workflow_assist.acceptance_cases import AcceptanceCase
from services.workflow_assist.runtime_contract import BusinessAssertion

_MODEL = {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {}}
_LLM = {
    "model": _MODEL,
    "prompt_template": [{"role": "user", "text": "{{#start.query#}}"}],
    "context": {"enabled": False, "variable_selector": []},
}


@dataclass(frozen=True)
class GenerationScenario:
    name: str
    mode: Literal["workflow", "advanced-chat"]
    nodes: tuple[tuple[str, str, str | None], ...]
    configs: dict[str, dict[str, object]]
    operation: Literal["rebuild", "edit"] = "rebuild"


SCENARIOS: tuple[GenerationScenario, ...] = (
    GenerationScenario("simple_llm", "workflow", (("llm", "llm", None),), {"llm": _LLM}),
    GenerationScenario(
        "rag",
        "workflow",
        (("rag", "knowledge-retrieval", None),),
        {
            "rag": {
                "dataset_ids": ["dataset-1"],
                "query_variable_selector": ["start", "query"],
                "query_attachment_selector": [],
                "retrieval_mode": "multiple",
                "multiple_retrieval_config": {"top_k": 4, "score_threshold": None, "reranking_enable": False},
            }
        },
    ),
    GenerationScenario(
        "tool_to_llm",
        "workflow",
        (("tool", "tool", None), ("llm", "llm", None)),
        {
            "tool": {
                "provider_id": "builtin/search",
                "provider_type": "builtin",
                "provider_name": "Search",
                "tool_name": "search",
                "tool_label": "Search",
                "tool_configurations": {},
                "tool_parameters": {},
            },
            "llm": _LLM,
        },
    ),
    GenerationScenario(
        "agent_knowledge",
        "workflow",
        (("agent", "agent", None),),
        {
            "agent": {
                "version": "2",
                "agent_node_kind": "dify_agent",
                "agent_task": "Answer with knowledge",
                "agent_binding": {"binding_type": "inline_agent"},
                "model": _MODEL,
                "knowledge": {
                    "sets": [
                        {
                            "id": "knowledge-1",
                            "name": "Docs",
                            "datasets": [{"id": "dataset-1"}],
                            "query": {"mode": "generated_query"},
                            "retrieval": {"mode": "multiple", "top_k": 4, "reranking_enable": False},
                        }
                    ]
                },
            }
        },
    ),
    GenerationScenario(
        "condition_branch",
        "workflow",
        (("branch", "if-else", None),),
        {
            "branch": {
                "cases": [
                    {
                        "case_id": "true",
                        "logical_operator": "and",
                        "conditions": [
                            {
                                "variable_selector": ["start", "query"],
                                "comparison_operator": "empty",
                                "value": None,
                            }
                        ],
                    }
                ]
            }
        },
    ),
    GenerationScenario(
        "iteration_nested_field",
        "workflow",
        (("iteration", "iteration", None), ("nested", "template-transform", "iteration")),
        {
            "iteration": {"iterator_selector": ["start", "items"], "output_selector": ["nested", "output"]},
            "nested": {
                "template": "{{ item.name }}",
                "variables": [{"variable": "item", "value_selector": ["iteration", "item"]}],
            },
        },
    ),
    GenerationScenario(
        "loop_accumulation",
        "workflow",
        (("loop", "loop", None), ("increment", "assigner", "loop")),
        {
            "loop": {
                "loop_count": 3,
                "break_conditions": [],
                "logical_operator": "and",
                "loop_variables": [
                    {"id": "count", "label": "count", "value": "0", "value_type": "constant", "var_type": "number"}
                ],
            },
            "increment": {
                "version": "2",
                "items": [
                    {
                        "input_type": "constant",
                        "operation": "+=",
                        "value": 1,
                        "variable_selector": ["loop", "count"],
                        "write_mode": "over-write",
                    }
                ],
            },
        },
    ),
    GenerationScenario(
        "code_dynamic_output",
        "workflow",
        (("code", "code", None),),
        {
            "code": {
                "variables": [],
                "code_language": "python3",
                "code": "def main():\n    return {'result': 1}\n",
                "outputs": {"result": {"type": "number", "children": None}},
            }
        },
    ),
    GenerationScenario(
        "local_edit",
        "workflow",
        (("edited", "template-transform", None),),
        {
            "edited": {
                "template": "{{ query }}",
                "variables": [{"variable": "query", "value_selector": ["start", "query"]}],
            }
        },
        "edit",
    ),
    GenerationScenario("multi_turn_requirement_change", "workflow", (("llm", "llm", None),), {"llm": _LLM}),
    GenerationScenario("advanced_chat", "advanced-chat", (("llm", "llm", None),), {"llm": _LLM}),
)


def _not_empty_answer() -> BusinessAssertion:
    return {"path": ["answer"], "operator": "not_empty", "expected": True}


# These are evaluator-owned inputs and assertions. Provider output is checked
# against them; the generating model never authors or edits this registry.
BUSINESS_CASES: dict[str, tuple[AcceptanceCase, AcceptanceCase]] = {
    "simple_llm": (
        {"case_id": "normal", "inputs": {"query": "Summarize: alpha"}, "assertions": [_not_empty_answer()]},
        {"case_id": "failure", "inputs": {"query": ""}, "assertions": [_not_empty_answer()]},
    ),
    "rag": (
        {"case_id": "normal", "inputs": {"query": "What is the refund policy?"}, "assertions": [_not_empty_answer()]},
        {"case_id": "failure", "inputs": {"query": "unknown-document-topic"}, "assertions": [_not_empty_answer()]},
    ),
    "tool_to_llm": (
        {"case_id": "normal", "inputs": {"query": "weather in Shanghai"}, "assertions": [_not_empty_answer()]},
        {"case_id": "failure", "inputs": {"query": "unsupported://location"}, "assertions": [_not_empty_answer()]},
    ),
    "agent_knowledge": (
        {"case_id": "normal", "inputs": {"query": "Answer from docs"}, "assertions": [_not_empty_answer()]},
        {"case_id": "failure", "inputs": {"query": "Answer outside docs"}, "assertions": [_not_empty_answer()]},
    ),
    "condition_branch": (
        {"case_id": "normal", "inputs": {"query": ""}, "assertions": [_not_empty_answer()]},
        {"case_id": "failure", "inputs": {"query": "take-other-branch"}, "assertions": [_not_empty_answer()]},
    ),
    "iteration_nested_field": (
        {
            "case_id": "normal",
            "inputs": {"items": [{"name": "alpha"}]},
            "assertions": [_not_empty_answer()],
        },
        {"case_id": "failure", "inputs": {"items": [{}]}, "assertions": [_not_empty_answer()]},
    ),
    "loop_accumulation": (
        {"case_id": "normal", "inputs": {"query": "3"}, "assertions": [_not_empty_answer()]},
        {"case_id": "failure", "inputs": {"query": "not-a-number"}, "assertions": [_not_empty_answer()]},
    ),
    "code_dynamic_output": (
        {"case_id": "normal", "inputs": {"query": "1"}, "assertions": [_not_empty_answer()]},
        {"case_id": "failure", "inputs": {"query": "invalid"}, "assertions": [_not_empty_answer()]},
    ),
    "local_edit": (
        {"case_id": "normal", "inputs": {"query": "preserve bindings"}, "assertions": [_not_empty_answer()]},
        {"case_id": "failure", "inputs": {"query": ""}, "assertions": [_not_empty_answer()]},
    ),
    "multi_turn_requirement_change": (
        {"case_id": "normal", "inputs": {"query": "new requirement"}, "assertions": [_not_empty_answer()]},
        {"case_id": "failure", "inputs": {"query": "old requirement"}, "assertions": [_not_empty_answer()]},
    ),
    "advanced_chat": (
        {"case_id": "normal", "inputs": {"query": "hello"}, "assertions": [_not_empty_answer()]},
        {"case_id": "failure", "inputs": {"query": ""}, "assertions": [_not_empty_answer()]},
    ),
}


def evaluate_scenario(scenario: GenerationScenario, *, valid: bool) -> dict[str, object]:
    """Assemble one candidate and compare it with a server-hashed complete contract."""
    terminal_id = "answer" if scenario.mode == "advanced-chat" else "end"
    terminal_type = terminal_id
    plan_nodes = [{"id": "start", "label": "Start", "node_type": "start", "purpose": "Collect input"}]
    plan_nodes.extend(
        {
            "id": node_id,
            "label": node_id,
            "node_type": node_type,
            "purpose": scenario.name,
            **({"parent": parent} if parent else {}),
        }
        for node_id, node_type, parent in scenario.nodes
    )
    plan_nodes.append(
        {"id": terminal_id, "label": terminal_id, "node_type": terminal_type, "purpose": "Return output"}
    )
    top_level = [node_id for node_id, _node_type, parent in scenario.nodes if parent is None]
    chain = ["start", *top_level, terminal_id]
    plan_edges = [{"source": source, "target": target} for source, target in zip(chain, chain[1:])]
    if scenario.name == "condition_branch":
        plan_edges[-1]["source_handle"] = "true"
    configs = {
        "start": {
            "variables": [
                {"variable": "query", "label": "query", "type": "text-input"},
                {"variable": "items", "label": "items", "type": "file-list"},
            ]
        },
        terminal_id: (
            {"answer": "{{#start.query#}}"}
            if terminal_type == "answer"
            else {"outputs": [{"variable": "answer", "value_selector": ["start", "query"], "value_type": "string"}]}
        ),
        **scenario.configs,
    }
    graph = assemble_graph(plan_nodes=plan_nodes, plan_edges=plan_edges, configs_by_id=configs, existing_by_id={})
    validation_errors = validate_graph(graph=graph, mode=scenario.mode)
    requirements = [
        {
            "id": "req.current",
            "source_turn_id": "turn-2" if scenario.name == "multi_turn_requirement_change" else "turn-1",
            "evidence": scenario.name,
            "text": scenario.name,
            "provenance": "explicit_user",
            "supersedes": ["req.original"] if scenario.name == "multi_turn_requirement_change" else [],
        }
    ]
    requirement_ids = ["req.current"]
    contract_nodes = []
    for raw_node in graph.get("nodes") or []:
        node_id = str(raw_node.get("id") or "")
        node_type = str((raw_node.get("data") or {}).get("type") or "")
        outputs = []
        inputs = [
            {"source": [source, *output.split(".")], "role": output}
            for source, output in collect_references(raw_node.get("data") or {})
        ]
        if node_id == "start":
            outputs = [{"name": "query", "type": "string"}]
        elif node_id == terminal_id:
            outputs = [{"name": "answer", "type": "string"}]
        contract_nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "objective": scenario.name,
                "requirement_ids": requirement_ids,
                "inputs": inputs,
                "outputs": outputs,
                "structure_kind": node_type if node_type in {"start", "end", "answer", "iteration", "loop"} else None,
                "unresolved": [],
            }
        )
    if not valid:
        subject = next(node for node in contract_nodes if node["id"] not in {"start", terminal_id})
        subject["type"] = "code" if subject["type"] != "code" else "llm"
    resources, installed_tools, installed_datasets, installed_models = _resources(graph)
    operation = scenario.operation
    base_hash = "b" * 64 if operation == "edit" else None
    body: dict[str, object] = {
        "schema_version": 1,
        "status": "complete",
        "operation": operation,
        "requirements": requirements,
        "assumptions": [],
        "edit_scope": (
            {
                "candidate_base_hash": base_hash,
                "allowed_node_ids": [node["id"] for node in contract_nodes],
                "affected_downstream_ids": [],
            }
            if operation == "edit"
            else None
        ),
        "nodes": contract_nodes,
        "edges": [
            {
                "source": str(edge.get("source") or ""),
                "target": str(edge.get("target") or ""),
                "source_handle": edge.get("sourceHandle"),
            }
            for edge in graph.get("edges") or []
        ],
        "final_outputs": [{"name": "answer", "source": [terminal_id, "answer"], "type": "string"}],
        "resources": resources,
        "checks": [
            {
                "id": "check.current",
                "description": scenario.name,
                "level": "static",
                "requirement_ids": requirement_ids,
            }
        ],
        "unresolved": [],
    }
    contract_hash = canonical_workflow_contract_hash(body, revision=1)
    contract = {**body, "protocol_version": 1, "revision": 1, "contract_hash": contract_hash}
    report = reconcile_workflow_contract(
        contract=contract,
        graph=graph,
        mode=scenario.mode,
        candidate_base_hash=base_hash,
        installed_tools=installed_tools,
        installed_dataset_ids=installed_datasets,
        installed_models=installed_models,
    )
    return {
        "scenario": scenario.name,
        "valid_fixture": valid,
        "passed": report["passed"] and not validation_errors,
        "report": report,
        "graph": graph,
        "validation_errors": validation_errors,
    }


def _resources(
    graph: dict[str, object],
) -> tuple[list[dict[str, object]], set[tuple[str, str]], set[str], set[tuple[str, str]]]:
    resources: list[dict[str, object]] = []
    tools: set[tuple[str, str]] = set()
    datasets: set[str] = set()
    models: set[tuple[str, str]] = set()
    for node in graph.get("nodes") or []:  # type: ignore[union-attr]
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        data = node.get("data") or {}
        if not isinstance(data, dict):
            continue
        model = data.get("model")
        if isinstance(model, dict) and model.get("provider") and model.get("name"):
            key = (str(model["provider"]), str(model["name"]))
            models.add(key)
            resources.append(
                {
                    "kind": "model",
                    "provider": key[0],
                    "name": key[1],
                    "mode": str(model.get("mode") or "chat"),
                    "consumer_id": node_id,
                    "verified": True,
                    "unresolved_reason": None,
                }
            )
        if data.get("type") == "tool" and data.get("provider_id") and data.get("tool_name"):
            key = (str(data["provider_id"]), str(data["tool_name"]))
            tools.add(key)
            resources.append(
                {
                    "kind": "tool",
                    "provider_name": key[0],
                    "tool_name": key[1],
                    "consumer_id": node_id,
                    "verified": True,
                    "unresolved_reason": None,
                }
            )
        ids = list(data.get("dataset_ids") or [])
        knowledge = data.get("knowledge") or {}
        if isinstance(knowledge, dict):
            for item in knowledge.get("sets") or []:
                if isinstance(item, dict):
                    ids.extend(dataset.get("id") for dataset in item.get("datasets") or [] if isinstance(dataset, dict))
        for dataset_id in {str(item) for item in ids if item}:
            datasets.add(dataset_id)
            resources.append(
                {
                    "kind": "dataset",
                    "dataset_id": dataset_id,
                    "consumer_id": node_id,
                    "verified": True,
                    "unresolved_reason": None,
                }
            )
    return resources, tools, datasets, models
