"""Pure workflow graph validation, including Assist product-layer overlays.

This module reports all discovered issues without modifying the draft graph.
Core node and topology checks live in ``GraphValidator``. Assist only adds
``wants_agent`` intent and local-mode immutable-node enforcement.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from core.workflow.generator.types import GraphDict, WorkflowGenerationMode
from core.workflow.generator.validation.graph_validator import validate_graph as validate_core_graph
from services.workflow_assist.graph_diff import assert_local_mutable_respected
from services.workflow_assist.types import ValidationIssue, ValidationResult
from services.workflow_assist.validation_context import WorkflowValidationContext


def generation_mode_from_app_mode(mode: object) -> WorkflowGenerationMode:
    """Map an app mode value onto the generator's workflow/advanced-chat split."""
    return "advanced-chat" if str(mode) == "advanced-chat" else "workflow"


def _node_type(node: dict[str, Any]) -> object:
    data = node.get("data")
    if isinstance(data, dict) and "type" in data:
        return data["type"]
    return node.get("type")


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(code: str, detail: str, node_id: str | None = None) -> ValidationIssue:
    issue: ValidationIssue = {"code": code, "detail": detail}
    if node_id is not None:
        issue["node_id"] = node_id
    return issue


def _has_ready_agent_v2(nodes: list[dict[str, Any]]) -> bool:
    for node in nodes:
        if _node_type(node) != "agent":
            continue
        data = node.get("data")
        if not isinstance(data, dict):
            continue
        if str(data.get("version")) != "2" or data.get("agent_node_kind") != "dify_agent":
            continue
        if _non_empty_string(data.get("agent_task")):
            return True
    return False


def validate_graph(
    *,
    graph: dict[str, Any],
    mode: Literal["local", "rebuild"],
    generation_mode: WorkflowGenerationMode,
    base_graph: dict[str, Any] | None,
    mutable_node_ids: set[str],
    planned_new_ids: set[str],
    intent_flags: dict[str, bool],
    validation_context: WorkflowValidationContext | None = None,
) -> ValidationResult:
    """Validate core graph invariants, then Assist-only product constraints.

    Args:
        graph: Candidate Dify draft graph.
        mode: ``local`` enforces immutable nodes against ``base_graph``; ``rebuild`` does not.
        generation_mode: App mode used by ``GraphValidator`` (``workflow`` or ``advanced-chat``).
        base_graph: Graph preceding the local edit, when available.
        mutable_node_ids: User-authorized node ids for local edits.
        planned_new_ids: New node ids permitted during local edits.
        intent_flags: Agent-related intent booleans inferred by the caller.

    Returns:
        Errors and warnings. Validation has no side effects.
    """
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    for item in validate_core_graph(graph=cast(GraphDict, graph), mode=generation_mode, **(validation_context or {})):
        node_id = item.get("node_id")
        errors.append(_issue(str(item["code"]), item["detail"], node_id or None))

    raw_nodes = graph.get("nodes")
    if not isinstance(raw_nodes, list) or not all(isinstance(node, dict) for node in raw_nodes):
        return {"ok": False, "errors": errors, "warnings": warnings}
    nodes = raw_nodes

    wants_agent = intent_flags.get("wants_agent", False)
    if wants_agent and not _has_ready_agent_v2(nodes):
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
