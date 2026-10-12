"""In-memory acceptance runner for workflow assist.

Default ``simulated`` mode delegates to an executor that rewrites external
nodes and explores bounded branch/action scenarios without calling tenant tools
or LLMs, so usage counts stay 0. ``live`` may invoke real external providers.
Production does not persist WorkflowRun rows.

GraphEngine is optional via ``execute_graph``. Production injects it through
``build_acceptance_runner``. ``executed`` is true only when the executor
actually ran. Core never imports this module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Literal
from uuid import uuid4

from core.workflow.generator.acceptance.evidence import (
    AcceptanceAssertionResult,
    AcceptanceAttempt,
    AcceptanceMode,
    Evidence,
    FailedNodeTrace,
    GraphExecutionTrace,
)
from core.workflow.generator.graph.types import MinimalGraphDict
from services.workflow_assist.acceptance_cases import AcceptanceCase, index_acceptance_cases
from services.workflow_assist.effect_policy import classify_node_effect, execution_policy_errors
from services.workflow_assist.runtime_contract import BusinessAssertion, evaluate_runtime_contract

GraphExecutor = Callable[[MinimalGraphDict, AcceptanceMode, Mapping[str, object]], GraphExecutionTrace]


class WorkflowAssistAcceptanceRunner:
    """AcceptanceRunner adapter. Metered calls are counted only in live mode."""

    tenant_id: str
    app_id: str
    user_id: str
    workflow_id: str
    llm_calls: int
    tool_calls: int
    _live_authorized: bool
    _execute_graph: GraphExecutor | None
    _acceptance_cases: Mapping[str, AcceptanceCase]

    def __init__(
        self,
        *,
        tenant_id: str = "",
        app_id: str = "",
        user_id: str = "",
        workflow_id: str = "",
        execute_graph: GraphExecutor | None = None,
        acceptance_cases: list[AcceptanceCase] | None = None,
        live_authorized: bool = False,
    ) -> None:
        self.tenant_id = tenant_id
        self.app_id = app_id
        self.user_id = user_id
        self.workflow_id = workflow_id
        self.llm_calls = 0
        self.tool_calls = 0
        self._execute_graph = execute_graph
        self._live_authorized = live_authorized
        self._acceptance_cases = index_acceptance_cases(acceptance_cases or [])

    def run(
        self,
        *,
        graph: MinimalGraphDict,
        revision: int,
        graph_hash: str,
        case_ids: list[str],
        mode: AcceptanceMode,
    ) -> list[AcceptanceAttempt]:
        ids = case_ids or ["default"]
        unknown_ids = sorted(set(ids) - set(self._acceptance_cases) - {"default"})
        if unknown_ids:
            raise ValueError(f"Unknown acceptance cases: {unknown_ids!r}")
        attempts: list[AcceptanceAttempt] = []
        for case_id in ids:
            prepared = deepcopy(graph)
            acceptance_case = self._acceptance_cases.get(case_id)
            inputs = acceptance_case["inputs"] if acceptance_case is not None else {}
            business_specs = acceptance_case["assertions"] if acceptance_case is not None else []
            effect_unverified = _unverified_node_ids(prepared)
            failed_nodes: list[FailedNodeTrace] = []
            executed = False
            if mode == "live":
                failed_nodes = execution_policy_errors(prepared, mode, live_authorized=self._live_authorized)
                if not failed_nodes and self._execute_graph is not None:
                    self._count_metered(prepared)
                    failed_nodes = self._execute_graph(prepared, mode, inputs)
                    executed = True
            elif self._execute_graph is not None:
                failed_nodes = self._execute_graph(prepared, mode, inputs)
                executed = True
            executed_ids = (
                sorted(failed_nodes.executed_node_ids) if isinstance(failed_nodes, GraphExecutionTrace) else []
            )
            unexecuted = sorted(
                str(node["id"]) for node in prepared.get("nodes") or [] if node["id"] not in executed_ids
            )
            trace = failed_nodes if isinstance(failed_nodes, GraphExecutionTrace) else GraphExecutionTrace()
            assertions = _evaluate_scenario_contracts(prepared, trace, business_specs)
            runtime_contract_passed = all(item["passed"] for item in assertions if item["kind"] != "business")
            business_results = [item for item in assertions if item["kind"] == "business"]
            business_verified = bool(business_results) and all(item["passed"] for item in business_results)
            case_failed_nodes = list(failed_nodes)
            case_failed_nodes.extend(_assertion_failures(assertions))
            passed = (
                len(case_failed_nodes) == 0
                and runtime_contract_passed
                and all(item["passed"] for item in business_results)
            )
            status: Literal["succeeded", "failed", "simulated"]
            status = "simulated" if mode == "simulated" else ("succeeded" if passed else "failed")
            evidence = [_sandbox_evidence(revision, graph_hash, passed, case_failed_nodes, mode, executed)]
            attempts.append(
                {
                    "attempt_id": f"att-{uuid4().hex[:10]}",
                    "revision": revision,
                    "graph_hash": graph_hash,
                    "case_id": case_id,
                    "passed": passed,
                    "executed": executed,
                    "executed_node_ids": executed_ids,
                    "status": status,
                    "failed_nodes": case_failed_nodes,
                    "evidence": evidence,
                    "trace_summary": _trace_summary(passed, case_failed_nodes, unexecuted, mode, executed),
                    "unverified_nodes": unexecuted,
                    "unexecuted_node_ids": unexecuted,
                    "assertions": assertions,
                    "runtime_contract_passed": runtime_contract_passed,
                    "business_verified": business_verified,
                    "scenario_results": list(getattr(trace, "scenario_results", [])),
                }
            )
        return attempts

    def _count_metered(self, graph: MinimalGraphDict) -> None:
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            data = node.get("data")
            node_type = str(data.get("type") or "") if isinstance(data, dict) else ""
            if classify_node_effect(node) != "metered":
                continue
            if node_type in {"llm", "knowledge-retrieval", "agent"}:
                self.llm_calls += 1
            elif node_type == "tool":
                self.tool_calls += 1


def build_acceptance_runner(
    *,
    tenant_id: str,
    app_id: str,
    user_id: str,
    workflow_id: str = "",
    live_authorized: bool = False,
) -> WorkflowAssistAcceptanceRunner:
    """Production runner with a non-persisting GraphEngine adapter injected."""
    from services.workflow_assist.graph_executor import build_acceptance_graph_executor

    return WorkflowAssistAcceptanceRunner(
        tenant_id=tenant_id,
        app_id=app_id,
        user_id=user_id,
        workflow_id=workflow_id,
        live_authorized=live_authorized,
        execute_graph=build_acceptance_graph_executor(
            tenant_id=tenant_id,
            app_id=app_id,
            user_id=user_id,
            workflow_id=workflow_id,
            live_authorized=live_authorized,
        ),
    )


def _evaluate_scenario_contracts(
    graph: MinimalGraphDict,
    trace: GraphExecutionTrace,
    business_specs: Sequence[BusinessAssertion],
) -> list[AcceptanceAssertionResult]:
    if not trace.scenario_results:
        return evaluate_runtime_contract(graph, trace, business_specs)

    assertions: list[AcceptanceAssertionResult] = []
    for scenario in trace.scenario_results:
        scenario_trace = GraphExecutionTrace()
        scenario_trace.executed_node_ids.update(scenario["executed_node_ids"])
        scenario_trace.node_outputs.update(scenario.get("node_outputs", {}))
        scenario_trace.graph_outputs = dict(scenario["graph_outputs"])
        scenario_assertions = evaluate_runtime_contract(graph, scenario_trace, business_specs)
        scenario_passed = all(item["passed"] for item in scenario_assertions)
        scenario["passed"] = scenario["passed"] and scenario_passed
        for assertion in scenario_assertions:
            assertions.append(
                {
                    **assertion,
                    "path": f"scenarios.{scenario['scenario_id']}.{assertion['path']}",
                }
            )
    return assertions


def _sandbox_evidence(
    revision: int,
    graph_hash: str,
    passed: bool,
    failed_nodes: list[FailedNodeTrace],
    mode: AcceptanceMode,
    executed: bool,
) -> Evidence:
    return {
        "evidence_id": f"ev-{uuid4().hex[:10]}",
        "revision": revision,
        "graph_hash": graph_hash,
        "source": "sandbox",
        "passed": passed,
        "assertion": "graph_execution_succeeded" if executed else "execution_classified_only",
        "observed": {
            "mode": mode,
            "failed_node_count": len(failed_nodes),
            "executed": executed,
        },
    }


def _unverified_node_ids(graph: MinimalGraphDict) -> list[str]:
    ids: list[str] = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if classify_node_effect(node) != "local_execute" and isinstance(node_id, str) and node_id:
            ids.append(node_id)
    return ids


def _assertion_failures(assertions: Sequence[Mapping[str, object]]) -> list[FailedNodeTrace]:
    failures: list[FailedNodeTrace] = []
    for assertion in assertions:
        if assertion.get("passed") is True:
            continue
        path = str(assertion.get("path") or "outputs")
        kind = str(assertion.get("kind") or "output_contract")
        failures.append(
            {
                "id": path.split(".", 1)[0],
                "type": kind,
                "error": f"{path}: expected {assertion.get('expected')!r}, observed {assertion.get('actual')!r}",
                "category": "business" if kind == "business" else "output_contract",
            }
        )
    return failures


def _trace_summary(
    passed: bool,
    failed_nodes: list[FailedNodeTrace],
    unverified: list[str],
    mode: AcceptanceMode,
    executed: bool,
) -> str:
    if not passed:
        first = failed_nodes[0] if failed_nodes else {"id": "?", "error": "failed"}
        return f"{first.get('id')}: {first.get('error')}"
    if unverified:
        return f"{mode}; unverified={','.join(unverified)}; executed={str(executed).lower()}"
    if not executed:
        return "ok; executed=false"
    return "ok"
