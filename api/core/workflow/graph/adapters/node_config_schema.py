"""Shared pure NodeData parsing. No node construction or provider lookup."""

from collections.abc import Mapping
from typing import Any

from graphon.entities.base_node_data import BaseNodeData
from graphon.enums import BuiltinNodeTypes
from graphon.nodes.base.node import Node


def validate_resolved_node_data(node_class: type[Node], node_data: BaseNodeData) -> BaseNodeData:
    return node_class.validate_node_data(node_data)


def validate_workflow_node_data(node: Mapping[str, Any]) -> BaseNodeData:
    # Import lazily: bootstrap is owned by workflow, not graphon. Importing
    # implementations registers classes but never constructs their runtimes.
    payload = dict(node["data"])
    payload.setdefault("title", str(node.get("id") or ""))
    if payload.get("type") == "end":
        payload.setdefault("outputs", [])
    shared = BaseNodeData.model_validate(payload)
    if shared.type == BuiltinNodeTypes.HUMAN_INPUT:
        from core.workflow.nodes.human_input.entities import HumanInputNodeData

        return HumanInputNodeData.model_validate(payload)

    from core.workflow.node_factory import get_node_type_classes_mapping

    versions = get_node_type_classes_mapping().get(shared.type)
    if not versions:
        raise ValueError(f"Unsupported node type {shared.type!r}")
    version = str(shared.version)
    node_class = versions.get(version)
    if node_class is None:
        raise ValueError(f"Unsupported version {version!r} for {shared.type!r}")
    return validate_resolved_node_data(node_class, shared)
