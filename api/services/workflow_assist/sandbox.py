"""In-memory acceptance runner for workflow assist.

Default ``simulated`` mode classifies nodes and never calls tenant tools or
LLMs, so usage counts stay 0. ``live`` may invoke an injected graph executor
which tests spy on. Production does not persist WorkflowRun rows.

GraphEngine is optional via ``execute_graph``. Simulated graphs that still
contain metered nodes never call it; local-only graphs (start/code/end) do
when an executor is injected. Core never imports this module.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Literal, cast
from uuid import uuid4

from core.workflow.generator.agent.evidence import AcceptanceAttempt, AcceptanceMode, Evidence, FailedNodeTrace
from core.workflow.generator.agent.types import MinimalGraphDict
from core.workflow.generator.graph_postprocessor import postprocess_graph
from core.workflow.generator.types import GraphDict
from services.workflow_assist.effect_policy import classify_effect

GraphExecutor = Callable[[MinimalGraphDict, AcceptanceMode], list[FailedNodeTrace]]


class WorkflowAssistAcceptanceRunner:
    """AcceptanceRunner adapter. Metered calls are counted only in live mode."""

    tenant_id: str
    app_id: str
    user_id: str
    llm_calls: int
    tool_calls: int
    _execute_graph: GraphExecutor | None

    def __init__(
        self,
        *,
        tenant_id: str = "",
        app_id: str = "",
        user_id: str = "",
        execute_graph: GraphExecutor | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.app_id = app_id
        self.user_id = user_id
        self.llm_calls = 0
        self.tool_calls = 0
        self._execute_graph = execute_graph

    def run(
        self,
        *,
        graph: MinimalGraphDict,
        revision: int,
        graph_hash: str,
        case_ids: list[str],
        mode: AcceptanceMode,
    ) -> list[AcceptanceAttempt]:
        prepared = _prepare_graph(graph)
        unverified = _unverified_node_ids(prepared)
        failed_nodes: list[FailedNodeTrace] = []
        if mode == "live":
            self._count_metered(prepared)
            if self._execute_graph is not None:
                failed_nodes = self._execute_graph(prepared, mode)
        elif self._execute_graph is not None and not unverified:
            failed_nodes = self._execute_graph(prepared, mode)
        ids = case_ids or ["default"]
        attempts: list[AcceptanceAttempt] = []
        passed = len(failed_nodes) == 0
        status: Literal["succeeded", "failed", "simulated"]
        if mode == "simulated":
            status = "simulated"
        else:
            status = "succeeded" if passed else "failed"
        evidence = [_sandbox_evidence(revision, graph_hash, passed, failed_nodes, mode)]
        for case_id in ids:
            attempts.append(
                {
                    "attempt_id": f"att-{uuid4().hex[:10]}",
                    "revision": revision,
                    "graph_hash": graph_hash,
                    "case_id": case_id,
                    "passed": passed,
                    "status": status,
                    "failed_nodes": failed_nodes,
                    "evidence": evidence,
                    "trace_summary": _trace_summary(passed, failed_nodes, unverified, mode),
                    "unverified_nodes": unverified,
                }
            )
        return attempts

    def _count_metered(self, graph: MinimalGraphDict) -> None:
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            data = node.get("data")
            node_type = str(data.get("type") or "") if isinstance(data, dict) else ""
            if classify_effect(node_type) != "metered":
                continue
            if node_type in {"llm", "knowledge-retrieval", "agent"}:
                self.llm_calls += 1
            elif node_type == "tool":
                self.tool_calls += 1


def _prepare_graph(graph: MinimalGraphDict) -> MinimalGraphDict:
    """Normalize a copy so engine adapters see canvas defaults, not the candidate."""
    prepared = cast(MinimalGraphDict, deepcopy(graph))
    try:
        return cast(MinimalGraphDict, postprocess_graph(graph=cast(GraphDict, prepared), mode="workflow"))
    except Exception:
        return prepared


def _sandbox_evidence(
    revision: int,
    graph_hash: str,
    passed: bool,
    failed_nodes: list[FailedNodeTrace],
    mode: AcceptanceMode,
) -> Evidence:
    return {
        "evidence_id": f"ev-{uuid4().hex[:10]}",
        "revision": revision,
        "graph_hash": graph_hash,
        "source": "sandbox",
        "passed": passed,
        "assertion": "graph_succeeded_with_output",
        "observed": {
            "mode": mode,
            "failed_node_count": len(failed_nodes),
        },
    }


def _unverified_node_ids(graph: MinimalGraphDict) -> list[str]:
    ids: list[str] = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        data = node.get("data")
        node_type = str(data.get("type") or "") if isinstance(data, dict) else ""
        if classify_effect(node_type) != "local_execute" and isinstance(node_id, str) and node_id:
            ids.append(node_id)
    return ids


def _trace_summary(
    passed: bool,
    failed_nodes: list[FailedNodeTrace],
    unverified: list[str],
    mode: AcceptanceMode,
) -> str:
    if not passed:
        first = failed_nodes[0] if failed_nodes else {"id": "?", "error": "failed"}
        return f"{first.get('id')}: {first.get('error')}"
    if mode == "simulated" and unverified:
        return f"simulated; unverified={','.join(unverified)}"
    return "ok"
