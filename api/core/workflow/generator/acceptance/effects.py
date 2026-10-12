"""Execution classes for candidate nodes, shared by acceptance and Assist execution tools.

``local_execute`` nodes need no provider credentials and have no external side
effects. ``metered`` nodes consume tenant model or retrieval quota. Everything
else is ``simulate_always``. Known external, branch-selecting and interactive
nodes are covered by capability-specific verification strategies. Unknown
shapes fail closed.
"""

from typing import Literal

from core.workflow.generator.acceptance.capabilities import LOCAL_NODE_TYPES
from core.workflow.generator.graph.types import MinimalGraphDict

EffectClass = Literal["local_execute", "metered", "simulate_always"]

LOCAL_EXECUTE_NODE_TYPES = LOCAL_NODE_TYPES
_METERED_NODE_TYPES = frozenset({"llm", "knowledge-retrieval", "agent"})
LIVE_EXECUTABLE_NODE_TYPES = frozenset(
    {
        "llm",
        "knowledge-retrieval",
        "tool",
        "agent",
        "http-request",
        "document-extractor",
        "parameter-extractor",
        "question-classifier",
        "human-input",
    }
)


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


def workflow_execution_blockers(graph: MinimalGraphDict) -> list[dict[str, str]]:
    """Return nodes without a registered Workflow Assist verification strategy."""
    from core.workflow.generator.acceptance.capabilities import workflow_verification_blockers

    return workflow_verification_blockers(graph)
