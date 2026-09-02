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

from core.workflow.generator.agent.types import MinimalGraphDict

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


class FailedNodeTrace(TypedDict):
    """One engine node failure as the model should see it."""

    id: str
    type: str
    error: str


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
) -> FinishAcceptanceReason | None:
    """Return why finish must reject, or ``None`` when the claim may proceed.

    ``runner_present=False`` keeps the legacy hydrate+validate finish path so
    unit tests that never inject a runner stay unchanged.
    """
    if not runner_present:
        return None
    matching = [
        attempt
        for attempt in attempts.values()
        if attempt["revision"] == revision and attempt["graph_hash"] == graph_hash
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
