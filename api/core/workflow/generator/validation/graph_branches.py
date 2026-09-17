"""graph branches."""

from typing import Any

from core.workflow.generator.types import (
    WorkflowGenerateErrorCode,
    WorkflowGenerateErrorDict,
    WorkflowGenerationMode,
)
from core.workflow.generator.validation.graph_validation_values import _err
from graphon.enums import BuiltinNodeTypes


def _collect_response_node_errors(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    mode: WorkflowGenerationMode,
) -> list[WorkflowGenerateErrorDict]:
    errors: list[WorkflowGenerateErrorDict] = []
    forbidden_type = BuiltinNodeTypes.END if mode == "advanced-chat" else BuiltinNodeTypes.ANSWER
    for node in nodes:
        node_id = str(node.get("id") or "")
        data = node.get("data") or {}
        node_type = data.get("type") if isinstance(data, dict) else None
        if node_type == forbidden_type:
            errors.append(
                _err(
                    WorkflowGenerateErrorCode.INVALID_NODE_CONFIG,
                    f"Node {node_id!r} type {node_type!r} is not allowed in {mode} mode",
                    node_id=node_id,
                )
            )
        if node_type == BuiltinNodeTypes.END and any(edge.get("source") == node_id for edge in edges):
            errors.append(
                _err(
                    WorkflowGenerateErrorCode.INVALID_NODE_CONFIG,
                    f"End node {node_id!r} must not have outgoing edges",
                    node_id=node_id,
                )
            )
    return errors


def _collect_human_input_edge_errors(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[WorkflowGenerateErrorDict]:
    """Require human-input edges to use declared action ids or ``__timeout``."""

    allowed_by_node: dict[str, set[str]] = {}
    for node in nodes:
        data = node.get("data") or {}
        node_id = node.get("id")
        if data.get("type") != BuiltinNodeTypes.HUMAN_INPUT or not isinstance(node_id, str):
            continue
        action_ids = {
            str(action["id"])
            for action in (data.get("user_actions") or [])
            if isinstance(action, dict) and isinstance(action.get("id"), str) and action["id"]
        }
        allowed_by_node[node_id] = action_ids | {"__timeout"}

    out: list[WorkflowGenerateErrorDict] = []
    for edge in edges:
        source = edge.get("source")
        if not isinstance(source, str) or source not in allowed_by_node:
            continue
        source_handle = edge.get("sourceHandle")
        if source_handle in allowed_by_node[source]:
            continue
        allowed = ", ".join(sorted(allowed_by_node[source]))
        out.append(
            _err(
                WorkflowGenerateErrorCode.INVALID_SCHEMA,
                f"Human-input node {source!r} edge must use a declared action id or __timeout; "
                f"got {source_handle!r} (allowed: {allowed})",
                node_id=source,
            )
        )
    return out


def _collect_error_strategy_edge_errors(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    node_type: str,
    label: str,
) -> list[WorkflowGenerateErrorDict]:
    """Require error-strategy nodes to use only configured output handles."""

    allowed_by_node: dict[str, set[str]] = {}
    for node in nodes:
        data = node.get("data") or {}
        node_id = node.get("id")
        if data.get("type") != node_type or not isinstance(node_id, str):
            continue
        allowed = {"source"}
        strategy = data.get("error_strategy") or data.get("error_handle_mode")
        if strategy in {"fail-branch", "failBranch"}:
            allowed.add("fail-branch")
        allowed_by_node[node_id] = allowed

    out: list[WorkflowGenerateErrorDict] = []
    for edge in edges:
        source = edge.get("source")
        if not isinstance(source, str) or source not in allowed_by_node:
            continue
        source_handle = edge.get("sourceHandle") or "source"
        if source_handle in allowed_by_node[source]:
            continue
        allowed = ", ".join(sorted(allowed_by_node[source]))
        out.append(
            _err(
                WorkflowGenerateErrorCode.INVALID_SCHEMA,
                f"{label} node {source!r} edge uses invalid handle {source_handle!r} (allowed: {allowed})",
                node_id=source,
            )
        )
    return out


def _collect_http_request_edge_errors(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[WorkflowGenerateErrorDict]:
    """Require HTTP request edges to use only configured output handles."""

    return _collect_error_strategy_edge_errors(
        nodes=nodes,
        edges=edges,
        node_type=BuiltinNodeTypes.HTTP_REQUEST,
        label="HTTP request",
    )


def _collect_tool_edge_errors(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[WorkflowGenerateErrorDict]:
    """Require Tool edges to use only configured output handles."""

    return _collect_error_strategy_edge_errors(
        nodes=nodes,
        edges=edges,
        node_type=BuiltinNodeTypes.TOOL,
        label="Tool",
    )


def _collect_branch_edge_errors(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[WorkflowGenerateErrorDict]:
    """Require branch edges to use a Handle declared by their source node."""

    allowed_by_node: dict[str, set[str]] = {}
    branch_kind_by_node: dict[str, str] = {}
    for node in nodes:
        data = node.get("data") or {}
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        if data.get("type") == BuiltinNodeTypes.IF_ELSE:
            case_ids = {
                case_id
                for case in (data.get("cases") or [])
                if isinstance(case, dict)
                and isinstance((case_id := case.get("case_id")), str)
                and case_id
                and case_id != "false"
            }
            allowed_by_node[node_id] = case_ids | {"false"}
            branch_kind_by_node[node_id] = "If-else"
        elif data.get("type") == BuiltinNodeTypes.QUESTION_CLASSIFIER:
            class_ids = {
                class_id
                for class_config in (data.get("classes") or [])
                if isinstance(class_config, dict) and isinstance((class_id := class_config.get("id")), str) and class_id
            }
            allowed_by_node[node_id] = class_ids
            branch_kind_by_node[node_id] = "Question-classifier"

    out: list[WorkflowGenerateErrorDict] = []
    for edge in edges:
        source = edge.get("source")
        if not isinstance(source, str) or source not in allowed_by_node:
            continue
        source_handle = edge.get("sourceHandle")
        if source_handle in allowed_by_node[source]:
            continue
        allowed = ", ".join(sorted(allowed_by_node[source]))
        out.append(
            _err(
                WorkflowGenerateErrorCode.INVALID_SCHEMA,
                f"{branch_kind_by_node[source]} node {source!r} edge must use a declared branch handle; "
                f"got {source_handle!r} (allowed: {allowed})",
                node_id=source,
            )
        )
    return out
