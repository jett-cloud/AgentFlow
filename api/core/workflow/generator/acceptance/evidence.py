"""Revision-bound sandbox evidence for the workflow agent finish gate.

The model never constructs these records. ``AcceptanceRunner`` (injected on
``ToolContext``) and the structural validator are the only writers. Hashing
ignores layout and viewport so a postprocess layout bump cannot stale a
passing attempt that did not change topology.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Literal, NotRequired, Protocol, TypedDict

from core.workflow.generator.graph.types import MinimalGraphDict

AcceptanceMode = Literal["simulated", "live"]
AcceptanceStatus = Literal["succeeded", "failed", "simulated"]
EvidenceSource = Literal["validator", "sandbox"]
FinishAcceptanceReason = Literal["NO_EVIDENCE", "STALE_EVIDENCE", "ASSERTION_FAILED"]

_LAYOUT_NODE_KEYS = frozenset({"position", "width", "height", "selected", "dragging", "measured"})


class Evidence(TypedDict):
    """One assertion bound to a candidate revision and graph hash."""

    evidence_id: str
    revision: int
    graph_hash: str
    source: EvidenceSource
    passed: bool
    assertion: str
    observed: dict[str, object]
    contract_revision: NotRequired[int]
    contract_hash: NotRequired[str]
    app_mode: NotRequired[str]
    candidate_base_hash: NotRequired[str | None]
    run_id: NotRequired[str]
    epoch: NotRequired[int]
    validation_version: NotRequired[int]


class FailedNodeTrace(TypedDict):
    """One engine node failure as the model should see it."""

    id: str
    type: str
    error: str
    category: NotRequired[Literal["credential", "network", "quota", "policy", "runtime", "output_contract", "business"]]


class AcceptanceAssertionResult(TypedDict):
    """One server-evaluated runtime or business assertion."""

    kind: Literal["output_present", "output_type", "business"]
    path: str
    passed: bool
    expected: object
    actual: object


class AcceptanceAttempt(TypedDict):
    """One sandbox case run against a frozen candidate."""

    attempt_id: str
    revision: int
    graph_hash: str
    case_id: str
    passed: bool
    status: AcceptanceStatus
    failed_nodes: list[FailedNodeTrace]
    evidence: list[Evidence]
    trace_summary: str
    unverified_nodes: NotRequired[list[str]]
    executed: NotRequired[bool]
    executed_node_ids: NotRequired[list[str]]
    unexecuted_node_ids: NotRequired[list[str]]
    assertions: NotRequired[list[AcceptanceAssertionResult]]
    runtime_contract_passed: NotRequired[bool]
    business_verified: NotRequired[bool]
    contract_revision: NotRequired[int]
    contract_hash: NotRequired[str]
    app_mode: NotRequired[str]
    candidate_base_hash: NotRequired[str | None]
    run_id: NotRequired[str]
    epoch: NotRequired[int]
    validation_version: NotRequired[int]


class GraphExecutionTrace(list[FailedNodeTrace]):  # noqa: FURB189 -- preserve JSON list serialization at tool boundaries
    """List-compatible failures plus observed execution coverage."""

    executed_node_ids: set[str]
    node_outputs: dict[str, dict[str, object]]
    graph_outputs: dict[str, object]

    def __init__(self) -> None:
        super().__init__()
        self.executed_node_ids: set[str] = set()
        self.node_outputs = {}
        self.graph_outputs = {}


class AcceptanceRunner(Protocol):
    """Executes acceptance cases. Core must not import the service adapter."""

    def run(
        self,
        *,
        graph: MinimalGraphDict,
        revision: int,
        graph_hash: str,
        case_ids: list[str],
        mode: AcceptanceMode,
    ) -> list[AcceptanceAttempt]: ...


def canonical_graph_hash(graph: MinimalGraphDict | Mapping[str, object]) -> str:
    """SHA256 of topology: node ids/data and edges, excluding layout fields."""

    nodes_raw = graph.get("nodes") if isinstance(graph, Mapping) else None
    edges_raw = graph.get("edges") if isinstance(graph, Mapping) else None
    nodes = (
        [_canonical_node(node) for node in nodes_raw if isinstance(node, dict)] if isinstance(nodes_raw, list) else []
    )
    edges = (
        [_canonical_edge(edge) for edge in edges_raw if isinstance(edge, dict)] if isinstance(edges_raw, list) else []
    )
    payload = {
        "nodes": sorted(nodes, key=lambda item: str(item["id"])),
        "edges": sorted(edges, key=_edge_sort_key),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def finish_acceptance_reason(
    *,
    attempts: Mapping[str, AcceptanceAttempt],
    revision: int,
    graph_hash: str,
    runner_present: bool,
    required_case_ids: tuple[str, ...] = ("default",),
    contract_revision: int | None = None,
    contract_hash: str | None = None,
    app_mode: str | None = None,
    candidate_base_hash: str | None = None,
    validation_version: int | None = None,
) -> FinishAcceptanceReason | None:
    """Return why finish must reject, or ``None`` when the claim may proceed.

    ``runner_present=False`` keeps the legacy hydrate+validate finish path so
    unit tests that never inject a runner stay unchanged. Simulated attempts
    that classified metered nodes without running GraphEngine remain finishable.
    A live ``succeeded`` attempt with ``executed=false`` is treated as missing
    evidence.
    """
    if not runner_present:
        return None
    matching = [
        attempt
        for attempt in attempts.values()
        if attempt["revision"] == revision
        and attempt["graph_hash"] == graph_hash
        and (contract_revision is None or attempt.get("contract_revision") == contract_revision)
        and (contract_hash is None or attempt.get("contract_hash") == contract_hash)
        and (app_mode is None or attempt.get("app_mode") == app_mode)
        and (candidate_base_hash is None or attempt.get("candidate_base_hash") == candidate_base_hash)
        and (validation_version is None or attempt.get("validation_version") == validation_version)
    ]
    if not matching:
        if attempts:
            return "STALE_EVIDENCE"
        return "NO_EVIDENCE"
    latest_by_case: dict[str, AcceptanceAttempt] = {}
    for attempt in matching:
        latest_by_case[attempt["case_id"]] = attempt
    if not set(required_case_ids) <= set(latest_by_case):
        return "NO_EVIDENCE"
    if any(not latest_by_case[case_id]["passed"] for case_id in required_case_ids):
        return "ASSERTION_FAILED"
    if any(
        latest_by_case[case_id].get("status") == "succeeded" and latest_by_case[case_id].get("executed") is False
        for case_id in required_case_ids
    ):
        # Live "succeeded" without GraphEngine is not evidence. Simulated
        # classification of metered graphs stays finishable (status=simulated).
        return "NO_EVIDENCE"
    return None


def _canonical_node(node: Mapping[str, object]) -> dict[str, object]:
    data = node.get("data")
    clean_data = (
        {key: value for key, value in data.items() if key not in _LAYOUT_NODE_KEYS} if isinstance(data, dict) else {}
    )
    out: dict[str, object] = {"id": str(node.get("id") or ""), "data": clean_data}
    parent = node.get("parentId")
    if isinstance(parent, str) and parent:
        out["parentId"] = parent
    return out


def _canonical_edge(edge: Mapping[str, object]) -> dict[str, object]:
    out: dict[str, object] = {
        "source": str(edge.get("source") or ""),
        "target": str(edge.get("target") or ""),
    }
    handle = edge.get("sourceHandle") or edge.get("source_handle")
    if isinstance(handle, str) and handle:
        out["sourceHandle"] = handle
    return out


def _edge_sort_key(edge: Mapping[str, object]) -> tuple[str, str, str]:
    return (str(edge.get("source") or ""), str(edge.get("target") or ""), str(edge.get("sourceHandle") or ""))
