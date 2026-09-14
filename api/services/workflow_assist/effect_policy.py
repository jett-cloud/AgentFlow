"""Default execution classes, overridden only by a service-approved live trial scope."""

from __future__ import annotations

from typing import Literal

from core.workflow.generator.acceptance.evidence import AcceptanceMode, FailedNodeTrace
from core.workflow.generator.graph.types import MinimalGraphDict

EffectClass = Literal["local_execute", "metered", "simulate_always"]

_LOCAL_EXECUTE = frozenset(
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
_METERED = frozenset({"llm", "knowledge-retrieval", "tool", "agent"})


def classify_effect(node_type: str) -> EffectClass:
    """Return the execution class for one node type."""
    if node_type in _LOCAL_EXECUTE:
        return "local_execute"
    if node_type in _METERED:
        if node_type == "tool":
            return "simulate_always"
        return "metered"
    return "simulate_always"


def classify_node_effect(node: object) -> EffectClass:
    """Classify one graph node, failing closed for tools with unknown effects."""
    if not isinstance(node, dict):
        return "simulate_always"
    data = node.get("data")
    if not isinstance(data, dict):
        return "simulate_always"
    node_type = str(data.get("type") or "")
    if node_type == "agent" and data.get("dify_tools"):
        return "simulate_always"
    return classify_effect(node_type)


def execution_policy_errors(
    graph: MinimalGraphDict, mode: AcceptanceMode, *, live_authorized: bool = False
) -> list[FailedNodeTrace]:
    """Fail closed before engine construction, including direct executor calls."""
    errors: list[FailedNodeTrace] = []
    for node in graph.get("nodes") or []:
        data = node.get("data") or {}
        node_type = str(data.get("type") or "")
        effect = classify_node_effect(node)
        if (
            mode == "live"
            and live_authorized
            and node_type in {"llm", "knowledge-retrieval", "tool", "agent", "http-request"}
        ):
            continue
        if effect == "simulate_always" or (mode == "simulated" and effect == "metered"):
            errors.append(
                {
                    "id": str(node.get("id") or ""),
                    "type": node_type,
                    "error": f"Execution policy forbids {node_type!r} in {mode} acceptance",
                    "category": "policy",
                }
            )
    return errors
