"""Shared helpers for generated loop and iteration container nodes."""

from typing import Any

from graphon.enums import BuiltinNodeTypes

CONTAINER_NODE_TYPES = frozenset({BuiltinNodeTypes.ITERATION, BuiltinNodeTypes.LOOP})


def resolve_container_start_node_id(*, node_id: str, data: dict[str, Any]) -> str:
    """Return a configured container entry id or its deterministic default."""

    configured = data.get("start_node_id")
    if isinstance(configured, str) and configured:
        return configured
    return f"{node_id}start"


def expected_container_start_node_type(container_type: str) -> str:
    """Return the synthetic entry node type required by a container type."""

    if container_type == BuiltinNodeTypes.ITERATION:
        return BuiltinNodeTypes.ITERATION_START
    if container_type == BuiltinNodeTypes.LOOP:
        return BuiltinNodeTypes.LOOP_START
    raise ValueError(f"Unsupported container node type: {container_type}")
