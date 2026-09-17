from __future__ import annotations

import json
from typing import Any


def _nodes_by_id(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for node in graph.get("nodes") or []:
        if isinstance(node, dict) and node.get("id") is not None:
            out[str(node["id"])] = node
    return out


def diff_graphs(base: dict[str, Any], next: dict[str, Any]) -> dict[str, list[str]]:
    base_m = _nodes_by_id(base)
    next_m = _nodes_by_id(next)
    added = [i for i in next_m if i not in base_m]
    removed = [i for i in base_m if i not in next_m]
    changed: list[str] = []
    for i, node in next_m.items():
        prev = base_m.get(i)
        if prev is None:
            continue
        if json.dumps(prev.get("data"), sort_keys=True, default=str) != json.dumps(
            node.get("data"), sort_keys=True, default=str
        ):
            changed.append(i)
    return {"added": added, "removed": removed, "changed": changed}


def assert_local_mutable_respected(
    *,
    base: dict[str, Any],
    next: dict[str, Any],
    mutable_node_ids: set[str],
    planned_new_ids: set[str],
) -> list[dict[str, str | None]]:
    allowed = set(mutable_node_ids) | set(planned_new_ids)
    d = diff_graphs(base, next)
    errors: list[dict[str, str | None]] = []
    for nid in d["removed"] + d["changed"]:
        if nid not in allowed:
            errors.append(
                {
                    "code": "LOCAL_IMMUTABLE_CHANGED",
                    "detail": f"Node {nid} is outside mutable_node_ids",
                    "node_id": nid,
                }
            )
    return errors
