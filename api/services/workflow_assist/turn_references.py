"""Normalize and hard-bind Workflow Assist Turn @ references."""

from __future__ import annotations

from typing import Any

from core.workflow.generator.agent.types import AgentSession

ASSIST_TURN_REFERENCE_LIMIT = 8
_KINDS = frozenset({"node", "tool", "dataset"})


class UnknownTurnReferenceError(ValueError):
    """Raised when a remaining @ reference is not on the canvas or catalogue."""


def normalize_turn_references(raw: object) -> list[dict[str, Any]] | None:
    """Drop malformed items. Raise if the payload is not a list or exceeds 8."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("references must be a list")
    if len(raw) > ASSIST_TURN_REFERENCE_LIMIT:
        raise ValueError("references exceeds 8")
    kept: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        reference = _coerce_reference(item)
        if reference is None:
            continue
        key = (str(reference["kind"]), str(reference["id"]))
        if key in seen:
            continue
        seen.add(key)
        kept.append(reference)
    return kept or None


def bind_turn_references(
    references: list[dict[str, Any]] | None,
    *,
    canvas_graph: dict[str, Any] | None,
    installed_tools: set[tuple[str, str]],
    installed_datasets: set[str],
) -> list[dict[str, Any]] | None:
    """Reject remaining ids that are not on this canvas or this tenant catalogue."""
    if not references:
        return None
    node_ids = _canvas_node_ids(canvas_graph)
    for item in references:
        kind = item["kind"]
        item_id = str(item["id"])
        if kind == "node" and item_id not in node_ids:
            raise UnknownTurnReferenceError(f"unknown referenced node {item_id!r}")
        if kind == "tool":
            key = (str(item.get("provider") or ""), str(item.get("tool_name") or ""))
            if key not in installed_tools:
                raise UnknownTurnReferenceError(f"unknown referenced tool {item_id!r}")
        if kind == "dataset" and item_id not in installed_datasets:
            raise UnknownTurnReferenceError(f"unknown referenced dataset {item_id!r}")
    return references


def bind_session_references(session: AgentSession, references: list[dict[str, Any]] | None) -> None:
    """Fill request-scoped referenced_* lists used by CurrentSituation."""
    session.referenced_nodes = [item for item in references or [] if item.get("kind") == "node"]
    session.referenced_tools = [item for item in references or [] if item.get("kind") == "tool"]
    session.referenced_datasets = [item for item in references or [] if item.get("kind") == "dataset"]


def append_hard_bound_resources(instruction: str, references: list[dict[str, Any]] | None) -> str:
    """Tell the node builder to use @-named tools and datasets exactly."""
    tools = [item for item in references or [] if item.get("kind") == "tool"]
    datasets = [item for item in references or [] if item.get("kind") == "dataset"]
    if not tools and not datasets:
        return instruction
    tool_text = ", ".join(_label(item) for item in tools) or "none"
    dataset_text = ", ".join(_label(item) for item in datasets) or "none"
    return instruction + (
        "\n\n# Bound user references (HARD)\n"
        "The user named these resources with @. Use these exact ids. "
        "Do not call search_tools, search_datasets, or ask_user to disambiguate them.\n"
        f"Tools: {tool_text}\n"
        f"Datasets: {dataset_text}"
    )


def _coerce_reference(item: object) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    kind = item.get("kind")
    item_id = item.get("id")
    if kind not in _KINDS or not isinstance(item_id, str) or not item_id.strip():
        return None
    label = item.get("label")
    reference: dict[str, Any] = {
        "kind": kind,
        "id": item_id.strip(),
        "label": label.strip() if isinstance(label, str) else "",
    }
    if kind == "tool":
        provider = item.get("provider")
        tool_name = item.get("tool_name")
        if not isinstance(provider, str) or not isinstance(tool_name, str) or not provider or not tool_name:
            provider, tool_name = _split_tool_id(reference["id"])
        if not provider or not tool_name:
            return None
        reference["provider"] = provider
        reference["tool_name"] = tool_name
        reference["id"] = f"{provider}/{tool_name}"
    return reference


def _split_tool_id(item_id: str) -> tuple[str, str]:
    """Split ``provider/tool`` on the last slash.

    Plugin providers are ``org/plugin/provider`` (two slashes already).
    ``partition("/")`` would treat ``ghy/doubao-image/doubao-image/image_generate``
    as provider ``ghy``, which then fails catalogue membership.
    """
    if "/" not in item_id:
        return "", ""
    provider, tool_name = item_id.rsplit("/", 1)
    if not provider or not tool_name:
        return "", ""
    return provider, tool_name


def _canvas_node_ids(canvas_graph: dict[str, Any] | None) -> set[str]:
    if not isinstance(canvas_graph, dict):
        return set()
    nodes = canvas_graph.get("nodes")
    if not isinstance(nodes, list):
        return set()
    return {str(node["id"]) for node in nodes if isinstance(node, dict) and node.get("id") is not None}


def _label(item: dict[str, Any]) -> str:
    item_id = str(item.get("id") or "")
    label = str(item.get("label") or "").strip()
    return f"{item_id} ({label})" if label else item_id
