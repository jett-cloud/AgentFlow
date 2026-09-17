"""Ingress policy for node ids created or replaced by Workflow Assist."""

import re

_SAFE_NODE_ID = re.compile(r"^[A-Za-z0-9_]+$")


def validate_mutation_node_id(value: str) -> str:
    """Return a normalized runtime-safe id or raise before compilation starts."""
    node_id = value.strip()
    if not node_id or _SAFE_NODE_ID.fullmatch(node_id) is None:
        raise ValueError("node id must match [A-Za-z0-9_]+")
    return node_id
