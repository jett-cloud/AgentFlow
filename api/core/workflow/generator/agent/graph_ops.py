"""Pure, side-effect-free operations on a candidate ``MinimalGraphDict``.

Every function returns a new graph and never mutates its input, so the loop can
keep the pre-call graph for diffing and rollback. These functions deliberately
emit the *minimal* graph shape (no edge ids, no ReactFlow node ``type``, no
positions): ``graph_postprocessor.postprocess_graph`` is the single normaliser
that fills those in, exactly as it does for ``node_builder.assemble_graph``. That
shape is what ``MinimalGraphDict`` describes, so nothing here has to cast an
incomplete node to the fully populated ``GraphNodeDict``.

The model-facing projection is ``render_compact_graph`` (id/type/title/parent,
edges, exposed outputs — no full config). ``read_node_view`` is the single-node
editing unit. ``upsert_node`` is the internal writer and is not a main-model tool.
"""

from copy import deepcopy
from typing import Any

from core.workflow.generator.agent.types import MinimalGraphDict, MinimalGraphEdgeDict, MinimalGraphNodeDict
from core.workflow.generator.types import GraphViewportDict
from core.workflow.generator.variable_references import declared_outputs

_DEFAULT_VIEWPORT: GraphViewportDict = {"x": 0.0, "y": 0.0, "zoom": 0.7}
_RESERVED_DATA_KEYS = ("type", "title", "desc", "parentId")


def empty_graph() -> MinimalGraphDict:
    """Return a graph with no nodes and the generator's default viewport."""
    return {"nodes": [], "edges": [], "viewport": deepcopy(_DEFAULT_VIEWPORT)}


def find_node(graph: MinimalGraphDict, node_id: str) -> MinimalGraphNodeDict | None:
    """Return the node with ``node_id``, or ``None`` when it is absent.

    The returned node aliases ``graph`` — it is not a copy — so treat it as
    read-only. Mutating it edits the caller's graph in place and defeats the
    purity every other function here preserves; go through ``upsert_node`` to
    change a node. Aliasing is deliberate: callers want identity checks and the
    common use is "does this node exist", where a copy would be wasted work.
    """
    for node in graph["nodes"]:
        if node["id"] == node_id:
            return node
    return None


def upsert_node(
    graph: MinimalGraphDict,
    *,
    node_id: str,
    node_type: str,
    title: str,
    desc: str,
    config: dict[str, Any],
    parent: str | None = None,
) -> MinimalGraphDict:
    """Insert or replace one node, preserving insertion order for existing ids.

    ``parent`` is the container id. ``None`` / ``""`` means a top-level node;
    the wrapper ``parentId`` is omitted rather than stored as null so omission
    and "move to top" stay distinguishable from an actual parent id.
    ``config`` is deep-copied so later caller mutations cannot alias into the graph.
    """
    config = deepcopy(config)
    payload = {key: value for key, value in config.items() if key not in _RESERVED_DATA_KEYS}
    data: dict[str, Any] = {"type": node_type, "title": title, "desc": desc, **payload}
    node: MinimalGraphNodeDict = {"id": node_id, "data": data}
    if parent:
        node["parentId"] = parent
    nodes = [deepcopy(existing) for existing in graph["nodes"]]
    for index, existing in enumerate(nodes):
        if existing["id"] == node_id:
            nodes[index] = node
            break
    else:
        nodes.append(node)
    return {"nodes": nodes, "edges": deepcopy(graph["edges"]), "viewport": deepcopy(graph["viewport"])}


def delete_node(graph: MinimalGraphDict, node_id: str) -> MinimalGraphDict:
    """Remove one node together with every edge touching it."""
    nodes = [deepcopy(node) for node in graph["nodes"] if node["id"] != node_id]
    edges = [deepcopy(edge) for edge in graph["edges"] if edge["source"] != node_id and edge["target"] != node_id]
    return {"nodes": nodes, "edges": edges, "viewport": deepcopy(graph["viewport"])}


def connect(
    graph: MinimalGraphDict,
    *,
    source: str,
    target: str,
    source_handle: str | None = None,
) -> MinimalGraphDict:
    """Add one edge. ``(source, target, source_handle)`` is the edge identity.

    An empty ``source_handle`` is normalised to "no handle" up front so that the
    identity check and the stored payload agree: LLM-generated arguments routinely
    carry ``"source_handle": ""`` to mean "unconditional edge", and treating that
    as a distinct handle would append a duplicate edge on every retry.
    """
    handle = source_handle or None
    for edge in graph["edges"]:
        same_endpoints = edge["source"] == source and edge["target"] == target
        if same_endpoints and edge.get("sourceHandle") == handle:
            return {
                "nodes": deepcopy(graph["nodes"]),
                "edges": deepcopy(graph["edges"]),
                "viewport": deepcopy(graph["viewport"]),
            }
    new_edge: MinimalGraphEdgeDict = {"source": source, "target": target}
    if handle:
        new_edge["sourceHandle"] = handle
    edges = [deepcopy(existing) for existing in graph["edges"]]
    edges.append(new_edge)
    return {"nodes": deepcopy(graph["nodes"]), "edges": edges, "viewport": deepcopy(graph["viewport"])}


def disconnect(
    graph: MinimalGraphDict,
    *,
    source: str,
    target: str,
    source_handle: str | None = None,
) -> tuple[MinimalGraphDict, int]:
    """Remove matching edges. Returns ``(graph, match_count)``; never mutates ``graph``.

    Edge identity is ``(source, target, source_handle)``. An empty handle is
    "no handle", same as ``connect``. When ``source_handle`` is omitted:

    * 0 matches — original graph, ``match_count=0`` (dispatch: no-op success)
    * 1 match — that edge is deleted
    * more than 1 — original graph, ``match_count>1`` (dispatch: ``AMBIGUOUS_EDGE``)

    With a handle, only that edge is deleted. Dispatch maps the count; this
    function does not raise and does not invent error codes.
    """
    handle = source_handle or None
    match_indexes: list[int] = []
    for index, edge in enumerate(graph["edges"]):
        if edge["source"] != source or edge["target"] != target:
            continue
        if handle is None or edge.get("sourceHandle") == handle:
            match_indexes.append(index)
    match_count = len(match_indexes)
    # Omit-handle ambiguity and "nothing to delete" both leave the graph as-is.
    if match_count == 0 or (handle is None and match_count > 1):
        return _copy_graph(graph), match_count
    skip = set(match_indexes)
    edges = [deepcopy(edge) for index, edge in enumerate(graph["edges"]) if index not in skip]
    return _copy_graph(graph, edges=edges), match_count


def render_compact_graph(graph: MinimalGraphDict) -> dict[str, Any]:
    """Return the model-facing map: topology plus exposed outputs, no full config.

    ``read_node`` is the only way to open one node's editing unit. This view is
    for wiring and variable references.
    """
    nodes: list[dict[str, Any]] = []
    for node in graph["nodes"]:
        data = node["data"]
        compact: dict[str, Any] = {
            "id": node["id"],
            "type": str(data.get("type") or ""),
            "title": str(data.get("title") or ""),
            "outputs": declared_outputs(dict(node)),
        }
        parent = _node_parent(node)
        if parent:
            compact["parent"] = parent
        nodes.append(compact)
    return {"nodes": nodes, "edges": _render_edges(graph)}


def read_node_view(graph: MinimalGraphDict, node_id: str) -> dict[str, Any] | None:
    """Return one node's editing unit (including config, excluding edges)."""
    node = find_node(graph, node_id)
    if node is None:
        return None
    data = deepcopy(node["data"])
    node_type = str(data.pop("type", ""))
    title = str(data.pop("title", ""))
    desc = str(data.pop("desc", ""))
    data.pop("parentId", None)
    view: dict[str, Any] = {"id": node["id"], "type": node_type, "title": title, "desc": desc, "config": data}
    parent = _node_parent(node)
    if parent:
        view["parent"] = parent
    return view


def _copy_graph(
    graph: MinimalGraphDict,
    *,
    nodes: list[MinimalGraphNodeDict] | None = None,
    edges: list[MinimalGraphEdgeDict] | None = None,
) -> MinimalGraphDict:
    return {
        "nodes": deepcopy(graph["nodes"]) if nodes is None else nodes,
        "edges": deepcopy(graph["edges"]) if edges is None else edges,
        "viewport": deepcopy(graph["viewport"]),
    }


def _node_parent(node: MinimalGraphNodeDict) -> str | None:
    parent = node.get("parentId") or node["data"].get("parentId")
    if isinstance(parent, str) and parent:
        return parent
    return None


def _render_edges(graph: MinimalGraphDict) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for edge in graph["edges"]:
        rendered: dict[str, Any] = {"source": edge["source"], "target": edge["target"]}
        if edge.get("sourceHandle"):
            rendered["source_handle"] = edge["sourceHandle"]
        edges.append(rendered)
    return edges
