"""Execution classes for candidate nodes, shared by acceptance and Assist execution tools.

``local_execute`` nodes need no provider credentials and have no external side
effects. ``metered`` nodes consume tenant model or retrieval quota. Everything
else, including tools, HTTP, extractors and unknown plugin types, is
``simulate_always``: the service runs it only under a live grant. Unknown
shapes fail closed.
"""

from typing import Literal

from core.workflow.generator.graph.types import MinimalGraphDict

EffectClass = Literal["local_execute", "metered", "simulate_always"]

LOCAL_EXECUTE_NODE_TYPES = frozenset(
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
_METERED_NODE_TYPES = frozenset({"llm", "knowledge-retrieval", "agent"})


def classify_effect(node_type: str) -> EffectClass:
    """Return the execution class for one node type."""
    if node_type in LOCAL_EXECUTE_NODE_TYPES:
        return "local_execute"
    if node_type in _METERED_NODE_TYPES:
        return "metered"
    return "simulate_always"


def classify_node_effect(node: object) -> EffectClass:
    """Classify one graph node, failing closed for agents that carry tools."""
    if not isinstance(node, dict):
        return "simulate_always"
    data = node.get("data")
    if not isinstance(data, dict):
        return "simulate_always"
    node_type = str(data.get("type") or "")
    if node_type == "agent" and data.get("dify_tools"):
        return "simulate_always"
    return classify_effect(node_type)


def external_node_ids(graph: MinimalGraphDict) -> list[str]:
    """Return ids of nodes that would reach providers or external systems when run for real."""
    return [
        str(node.get("id") or "")
        for node in graph.get("nodes") or []
        if isinstance(node, dict) and classify_node_effect(node) != "local_execute"
    ]
