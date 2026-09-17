"""graph topology."""

from typing import Any

from core.workflow.generator.types import (
    GraphDict,
    WorkflowGenerateErrorCode,
    WorkflowGenerateErrorDict,
)
from core.workflow.generator.validation.graph_validation_values import _ID_FIELDS, _err
from graphon.enums import BuiltinNodeTypes


def _collect_edge_cycle_errors(*, graph: GraphDict, known_ids: set[str]) -> list[WorkflowGenerateErrorDict]:
    """
    Flag directed cycles among the graph's edges (Kahn's algorithm).

    Self-loops are reported per node; a longer cycle is reported once,
    naming every node Kahn's peeling never reaches (cycle members plus
    anything downstream of them). Edges into unknown ids are ignored
    here — the dangling-edge check already covers those.
    """
    out: list[WorkflowGenerateErrorDict] = []
    succs: dict[str, list[str]] = {node_id: [] for node_id in known_ids}
    indegree: dict[str, int] = dict.fromkeys(known_ids, 0)
    for edge in graph.get("edges", []):
        src, tgt = edge.get("source"), edge.get("target")
        if src not in known_ids or tgt not in known_ids:
            continue
        if src == tgt:
            out.append(
                _err(
                    WorkflowGenerateErrorCode.GRAPH_CYCLE,
                    f"Node {src!r} has an edge pointing at itself",
                    node_id=src,
                )
            )
            continue
        succs[src].append(tgt)
        indegree[tgt] += 1

    queue = [node_id for node_id, deg in indegree.items() if deg == 0]
    visited = 0
    while queue:
        cur = queue.pop()
        visited += 1
        for nxt in succs[cur]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if visited < len(known_ids):
        trapped = sorted(node_id for node_id, deg in indegree.items() if deg > 0)
        out.append(
            _err(
                WorkflowGenerateErrorCode.GRAPH_CYCLE,
                f"Workflow graph contains a cycle; affected nodes: {', '.join(trapped)}",
            )
        )
    return out


def _collect_unreachable_node_errors(
    *, nodes: list[dict[str, Any]], graph: GraphDict
) -> list[WorkflowGenerateErrorDict]:
    """Flag top-level nodes that cannot execute from the workflow start."""
    top_level_nodes: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_id = node.get("id")
        raw_data = node.get("data")
        data = raw_data if isinstance(raw_data, dict) else {}
        if isinstance(node_id, str) and node_id and not node.get("parentId") and not data.get("parentId"):
            top_level_nodes[node_id] = node

    start_ids: list[str] = []
    for node_id, node in top_level_nodes.items():
        start_data = node.get("data")
        if isinstance(start_data, dict) and start_data.get("type") == BuiltinNodeTypes.START:
            start_ids.append(node_id)
    if len(start_ids) != 1:
        return []

    successors: dict[str, list[str]] = {node_id: [] for node_id in top_level_nodes}
    for edge in graph.get("edges", []):
        source = edge.get("source")
        target = edge.get("target")
        if source in successors and target in top_level_nodes:
            successors[source].append(target)

    start_id = start_ids[0]
    reachable: set[str] = set()
    pending = [start_id]
    while pending:
        node_id = pending.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        pending.extend(successors[node_id])

    return [
        _err(
            WorkflowGenerateErrorCode.INVALID_SCHEMA,
            f"Node {node_id!r} is not reachable from start node {start_id!r}",
            node_id=node_id,
        )
        for node_id in sorted(top_level_nodes.keys() - reachable)
    ]


def _collect_terminal_bypass_errors(
    *, nodes: list[dict[str, Any]], graph: GraphDict, mode: str
) -> list[WorkflowGenerateErrorDict]:
    """Reject an unconditional shortcut to a terminal around downstream work.

    A normal node may fan out to parallel work, but a direct terminal edge plus
    another path from the same node to that terminal lets the workflow finish
    along a scaffold/bypass edge. Conditional nodes are excluded because their
    separate handles intentionally represent alternative paths.
    """
    top_level_types: dict[str, str] = {}
    for node in nodes:
        node_id = node.get("id")
        raw_data = node.get("data")
        data = raw_data if isinstance(raw_data, dict) else {}
        if isinstance(node_id, str) and node_id and not node.get("parentId") and not data.get("parentId"):
            top_level_types[node_id] = str(data.get("type") or "")

    terminal_type = BuiltinNodeTypes.ANSWER if mode == "advanced-chat" else BuiltinNodeTypes.END
    terminal_ids = {node_id for node_id, node_type in top_level_types.items() if node_type == terminal_type}
    successors: dict[str, set[str]] = {node_id: set() for node_id in top_level_types}
    for edge in graph.get("edges", []):
        source = edge.get("source")
        target = edge.get("target")
        if source in successors and target in top_level_types:
            successors[source].add(target)

    branch_types = {BuiltinNodeTypes.IF_ELSE, BuiltinNodeTypes.QUESTION_CLASSIFIER}
    errors: list[WorkflowGenerateErrorDict] = []
    for source, targets in successors.items():
        if top_level_types[source] in branch_types:
            continue
        direct_terminals = targets & terminal_ids
        if not direct_terminals:
            continue
        for terminal_id in sorted(direct_terminals):
            pending = [target for target in targets if target != terminal_id]
            seen: set[str] = set()
            while pending:
                current = pending.pop()
                if current == terminal_id:
                    errors.append(
                        _err(
                            WorkflowGenerateErrorCode.INVALID_SCHEMA,
                            (
                                f"Edge {source!r} -> {terminal_id!r} bypasses downstream work "
                                f"on another path to the same terminal"
                            ),
                            node_id=source,
                        )
                    )
                    break
                if current in seen:
                    continue
                seen.add(current)
                pending.extend(successors.get(current, set()))
    return errors


def _collect_dangling_id_refs(*, nodes: list[dict[str, Any]], known_ids: set[str]) -> list[WorkflowGenerateErrorDict]:
    """Flag ``parentId`` / ``start_node_id`` / ``iteration_id`` / ``loop_id`` pointing nowhere.

    ``parentId`` is checked at BOTH the node wrapper and inside ``data``
    because Dify's schema puts it on the wrapper (ReactFlow convention)
    but the LLM occasionally drops it into ``data`` too. Either spot is
    a real signal that we should validate.
    """
    out: list[WorkflowGenerateErrorDict] = []
    for node in nodes:
        node_id = node.get("id", "")
        data = node.get("data") or {}
        for field in _ID_FIELDS:
            ref = data.get(field)
            if isinstance(ref, str) and ref and ref not in known_ids:
                out.append(
                    _err(
                        WorkflowGenerateErrorCode.UNKNOWN_NODE_REFERENCE,
                        f"Node {node_id!r} field {field!r} references unknown node: {ref!r}",
                        node_id=node_id,
                    )
                )
        # Wrapper-level parentId (the ReactFlow canonical location).
        wrapper_parent = node.get("parentId")
        if isinstance(wrapper_parent, str) and wrapper_parent and wrapper_parent not in known_ids:
            out.append(
                _err(
                    WorkflowGenerateErrorCode.UNKNOWN_NODE_REFERENCE,
                    f"Node {node_id!r} parentId references unknown node: {wrapper_parent!r}",
                    node_id=node_id,
                )
            )
    return out
