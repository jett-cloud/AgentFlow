"""Pure workflow graph validation, including Agent v2 and local-mode constraints.

This module reports all discovered issues without modifying the draft graph. Local
mode additionally delegates immutable-node enforcement to ``graph_diff``.
"""

from __future__ import annotations

from typing import Any, Literal

from services.workflow_assist.graph_diff import assert_local_mutable_respected
from services.workflow_assist.types import ValidationIssue, ValidationIssueCode, ValidationResult


def _node_type(node: dict[str, Any]) -> object:
    data = node.get("data")
    if isinstance(data, dict) and "type" in data:
        return data["type"]
    return node.get("type")


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(code: ValidationIssueCode, detail: str, node_id: str | None = None) -> ValidationIssue:
    issue: ValidationIssue = {"code": code, "detail": detail}
    if node_id is not None:
        issue["node_id"] = node_id
    return issue


def validate_graph(
    *,
    graph: dict[str, Any],
    mode: Literal["local", "rebuild"],
    base_graph: dict[str, Any] | None,
    mutable_node_ids: set[str],
    planned_new_ids: set[str],
    intent_flags: dict[str, bool],
) -> ValidationResult:
    """Validate universal graph invariants and Agent v2 requirements.

    Args:
        graph: Candidate Dify draft graph.
        mode: ``local`` enforces immutable nodes against ``base_graph``; ``rebuild`` does not.
        base_graph: Graph preceding the local edit, when available.
        mutable_node_ids: User-authorized node ids for local edits.
        planned_new_ids: New node ids permitted during local edits.
        intent_flags: Agent-related intent booleans inferred by the caller.

    Returns:
        Errors and warnings. Validation has no side effects.
    """
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    nodes = [node for node in graph.get("nodes") or [] if isinstance(node, dict)]

    node_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    start_count = 0
    terminal_count = 0
    has_agent_v2_shape_ready = False

    for node in nodes:
        node_id = str(node["id"]) if node.get("id") is not None else None
        if node_id is not None:
            if node_id in node_ids:
                duplicate_ids.add(node_id)
            node_ids.add(node_id)

        node_type = _node_type(node)
        if node_type == "start":
            start_count += 1
        if node_type in {"end", "answer"}:
            terminal_count += 1

        if node_type == "agent":
            data = node.get("data")
            if not isinstance(data, dict):
                continue
            is_v2_shape = str(data.get("version")) == "2" and data.get("agent_node_kind") == "dify_agent"
            has_task = _non_empty_string(data.get("agent_task"))
            if not is_v2_shape:
                errors.append(_issue("AGENT_V2_SHAPE", "Agent node must use Agent v2 dify_agent shape", node_id))
            if not has_task:
                errors.append(_issue("AGENT_TASK_EMPTY", "Agent node must have a non-empty agent_task", node_id))

            agent_binding = data.get("agent_binding")
            needs_inline_binding = agent_binding is None
            if isinstance(agent_binding, dict) and agent_binding.get("binding_type") == "inline_agent":
                needs_inline_binding = True
            has_inline_ids = (
                isinstance(agent_binding, dict)
                and _non_empty_string(agent_binding.get("agent_id"))
                and _non_empty_string(agent_binding.get("current_snapshot_id"))
            )
            if needs_inline_binding and not has_inline_ids:
                errors.append(
                    _issue(
                        "AGENT_BINDING_MISSING",
                        "Inline Agent v2 binding requires agent_id and current_snapshot_id",
                        node_id,
                    )
                )
            has_agent_v2_shape_ready = has_agent_v2_shape_ready or (is_v2_shape and has_task)

    if start_count != 1:
        errors.append(_issue("MISSING_START", "Graph must contain exactly one start node"))
    if terminal_count == 0:
        errors.append(_issue("MISSING_TERMINAL", "Graph must contain at least one end or answer node"))
    for node_id in sorted(duplicate_ids):
        errors.append(_issue("DUPLICATE_NODE_ID", f"Duplicate node id: {node_id}", node_id))

    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        for endpoint in ("source", "target"):
            referenced_node_id = edge.get(endpoint)
            if referenced_node_id is None or str(referenced_node_id) not in node_ids:
                errors.append(
                    _issue(
                        "DANGLING_EDGE",
                        f"Edge references missing {endpoint} node: {referenced_node_id}",
                        str(referenced_node_id) if referenced_node_id is not None else None,
                    )
                )

    wants_agent = intent_flags.get("wants_agent", False)
    if wants_agent and not has_agent_v2_shape_ready:
        errors.append(_issue("AGENT_SHOULD_BE_USED", "Intent requires a valid Agent v2 node"))

    if mode == "local" and base_graph is not None:
        local_errors = assert_local_mutable_respected(
            base=base_graph,
            next=graph,
            mutable_node_ids=mutable_node_ids,
            planned_new_ids=planned_new_ids,
        )
        errors.extend(
            _issue("LOCAL_IMMUTABLE_CHANGED", error["detail"] or "", error["node_id"]) for error in local_errors
        )

    return {"ok": not errors, "errors": errors, "warnings": warnings}
