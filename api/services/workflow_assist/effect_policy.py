"""Acceptance execution policy; node classification lives in the generator core."""

from __future__ import annotations

from core.workflow.generator.acceptance.effects import EffectClass, classify_effect, classify_node_effect
from core.workflow.generator.acceptance.evidence import AcceptanceMode, FailedNodeTrace
from core.workflow.generator.graph.types import MinimalGraphDict

__all__ = ["EffectClass", "classify_effect", "classify_node_effect", "execution_policy_errors"]


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
