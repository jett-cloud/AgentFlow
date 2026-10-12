"""Node verification capabilities used by Workflow Assist scenario planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.workflow.generator.graph.types import MinimalGraphDict

VerificationMode = Literal["local", "live", "mock", "mock_branch", "pause_resume"]


@dataclass(frozen=True)
class NodeVerificationCapability:
    """Server-owned ways one node type may participate in verification."""

    modes: frozenset[VerificationMode]


LOCAL_NODE_TYPES = frozenset(
    {
        "start",
        "end",
        "answer",
        "code",
        "if-else",
        "iteration",
        "iteration-start",
        "loop",
        "loop-start",
        "loop-end",
        "template-transform",
        "assigner",
        "variable-aggregator",
        "list-operator",
    }
)
LIVE_MOCK_NODE_TYPES = frozenset(
    {
        "llm",
        "knowledge-retrieval",
        "tool",
        "agent",
        "http-request",
        "document-extractor",
        "parameter-extractor",
    }
)

NODE_VERIFICATION_CAPABILITIES: dict[str, NodeVerificationCapability] = {
    **{node_type: NodeVerificationCapability(frozenset({"local"})) for node_type in LOCAL_NODE_TYPES},
    **{
        node_type: NodeVerificationCapability(frozenset({"live", "mock"}))
        for node_type in LIVE_MOCK_NODE_TYPES
    },
    "question-classifier": NodeVerificationCapability(frozenset({"live", "mock_branch"})),
    "human-input": NodeVerificationCapability(frozenset({"pause_resume"})),
}


def node_verification_capability(node_type: str) -> NodeVerificationCapability | None:
    """Return the declared verification capability, or ``None`` for unknown types."""

    return NODE_VERIFICATION_CAPABILITIES.get(node_type)


def workflow_verification_blockers(graph: MinimalGraphDict) -> list[dict[str, str]]:
    """Return only nodes for which no verification strategy is registered."""

    blockers: list[dict[str, str]] = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data")
        node_type = str(data.get("type") or "") if isinstance(data, dict) else ""
        if node_verification_capability(node_type) is not None:
            continue
        blockers.append(
            {
                "node_id": str(node.get("id") or ""),
                "type": node_type,
                "reason": "no Workflow Assist verification capability is registered",
            }
        )
    return blockers

