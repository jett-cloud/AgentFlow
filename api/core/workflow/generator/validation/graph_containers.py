"""graph containers."""

from typing import Any

from core.workflow.generator.graph.container_nodes import expected_container_start_node_type
from core.workflow.generator.types import (
    WorkflowGenerateErrorCode,
    WorkflowGenerateErrorDict,
)
from core.workflow.generator.validation.graph_validation_values import _CONTAINER_TYPES, _err
from core.workflow.generator.variables.variable_references import VariableReferences
from graphon.enums import BuiltinNodeTypes


def _collect_container_errors(*, nodes: list[dict[str, Any]]) -> list[WorkflowGenerateErrorDict]:
    """
    Validate iteration / loop topology:

      * every container has at least one executable child whose
        ``parentId`` points at it;
      * every container's ``start_node_id`` points to the matching start
        node type owned by that same container;
      * every non-container node with a ``parentId`` points at a real
        container, not at a non-container node;
      * no cycles in the parent chain (a node cannot be its own
        ancestor).
    """
    out: list[WorkflowGenerateErrorDict] = []
    by_id: dict[str, dict[str, Any]] = {n.get("id", ""): n for n in nodes if n.get("id")}

    # Containers and the set of node-ids that have a parentId pointing at them.
    container_ids = {n.get("id", "") for n in nodes if n.get("data", {}).get("type") in _CONTAINER_TYPES}
    children_by_parent: dict[str, list[str]] = {cid: [] for cid in container_ids}
    for n in nodes:
        parent = (n.get("data") or {}).get("parentId") or n.get("parentId")
        if not isinstance(parent, str) or not parent:
            continue
        if parent in container_ids:
            node_type = (n.get("data") or {}).get("type")
            if node_type == BuiltinNodeTypes.END:
                out.append(
                    _err(
                        WorkflowGenerateErrorCode.INVALID_CONTAINER,
                        f"End node {n.get('id')!r} cannot be placed inside a container",
                        node_id=n.get("id", ""),
                    )
                )
            elif node_type not in {"iteration-start", "loop-start"}:
                children_by_parent.setdefault(parent, []).append(n.get("id", ""))
        elif parent in by_id:
            # Parent exists but isn't a container — that's a topology bug.
            out.append(
                _err(
                    WorkflowGenerateErrorCode.INVALID_CONTAINER,
                    f"Node {n.get('id')!r} parentId {parent!r} is not an iteration or loop node",
                    node_id=n.get("id", ""),
                )
            )
        # parent missing from by_id is already flagged by _collect_dangling_id_refs.

    for cid in container_ids:
        if not children_by_parent.get(cid):
            out.append(
                _err(
                    WorkflowGenerateErrorCode.INVALID_CONTAINER,
                    f"Container node {cid!r} has no child nodes",
                    node_id=cid,
                )
            )
        container = by_id[cid]
        container_data = container.get("data") or {}
        start_id = container_data.get("start_node_id")
        if not isinstance(start_id, str) or not start_id:
            continue
        start = by_id.get(start_id)
        if start is None:
            continue
        expected_type = expected_container_start_node_type(str(container_data.get("type") or ""))
        actual_type = (start.get("data") or {}).get("type")
        if actual_type != expected_type:
            out.append(
                _err(
                    WorkflowGenerateErrorCode.INVALID_CONTAINER,
                    f"Container node {cid!r} requires start node type {expected_type!r}, got {actual_type!r}",
                    node_id=cid,
                )
            )
        start_parent = (start.get("data") or {}).get("parentId") or start.get("parentId")
        if start_parent != cid:
            out.append(
                _err(
                    WorkflowGenerateErrorCode.INVALID_CONTAINER,
                    f"Container node {cid!r} start node {start_id!r} is owned by {start_parent!r}",
                    node_id=cid,
                )
            )
        if container_data.get("type") == BuiltinNodeTypes.ITERATION:
            output_selector = container_data.get("output_selector")
            if VariableReferences._is_selector_list(output_selector):
                source_id = output_selector[0]
                source = by_id.get(source_id)
                wrapper_parent = source.get("parentId") if isinstance(source, dict) else None
                source_type = (source.get("data") or {}).get("type") if isinstance(source, dict) else None
                if source is None or wrapper_parent != cid or source_type in {"iteration-start", "loop-start"}:
                    out.append(
                        _err(
                            WorkflowGenerateErrorCode.INVALID_CONTAINER,
                            (
                                f"Iteration {cid!r} output_selector source {source_id!r} "
                                f"is not a direct child of {cid!r}"
                            ),
                            node_id=cid,
                        )
                    )

    loop_ends_by_parent: dict[str, list[str]] = {}
    for n in nodes:
        if (n.get("data") or {}).get("type") != "loop-end":
            continue
        nid = str(n.get("id") or "")
        wrapper_parent = n.get("parentId")
        parent = by_id.get(wrapper_parent) if isinstance(wrapper_parent, str) else None
        parent_type = (parent.get("data") or {}).get("type") if isinstance(parent, dict) else None
        if parent_type != BuiltinNodeTypes.LOOP:
            out.append(
                _err(
                    WorkflowGenerateErrorCode.INVALID_CONTAINER,
                    f"Loop End {nid!r} is not a direct child of a loop container",
                    node_id=nid,
                )
            )
            continue
        loop_id = (n.get("data") or {}).get("loop_id")
        if loop_id != wrapper_parent:
            out.append(
                _err(
                    WorkflowGenerateErrorCode.INVALID_CONTAINER,
                    (f"Loop End {nid!r} requires data.loop_id {wrapper_parent!r}, got {loop_id!r}"),
                    node_id=nid,
                )
            )
        loop_ends_by_parent.setdefault(str(wrapper_parent), []).append(nid)
    for cid, end_ids in loop_ends_by_parent.items():
        if len(end_ids) > 1:
            out.append(
                _err(
                    WorkflowGenerateErrorCode.INVALID_CONTAINER,
                    f"Loop {cid!r} has multiple Loop End nodes {end_ids!r}",
                    node_id=cid,
                )
            )

    # Cycle detection — for each node, walk up parentId chain and
    # bail if we ever revisit a node we've already seen on the chain.
    for n in nodes:
        seen: set[str] = set()
        cur_id = n.get("id", "")
        cur: dict[str, Any] | None = n
        depth = 0
        while cur is not None and depth < 64:  # generous safety cap
            parent = (cur.get("data") or {}).get("parentId") or cur.get("parentId")
            if not isinstance(parent, str) or not parent:
                break
            if parent == cur_id or parent in seen:
                out.append(
                    _err(
                        WorkflowGenerateErrorCode.INVALID_CONTAINER,
                        f"Cycle detected in parentId chain at node {cur_id!r}",
                        node_id=cur_id,
                    )
                )
                break
            seen.add(parent)
            cur = by_id.get(parent)
            depth += 1
    return out


def _ancestor_ids(node: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> set[str]:
    """Return ``parentId`` ancestors of ``node``, wrapper or data."""
    seen: set[str] = set()
    current: dict[str, Any] | None = node
    depth = 0
    while current is not None and depth < 64:
        parent = (current.get("data") or {}).get("parentId") or current.get("parentId")
        if not isinstance(parent, str) or not parent or parent in seen:
            break
        seen.add(parent)
        current = by_id.get(parent)
        depth += 1
    return seen
