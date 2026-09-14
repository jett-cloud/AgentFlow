"""Pure, side-effect-free operations on a candidate ``MinimalGraphDict``.

Every function returns a new graph and never mutates its input, so the loop can
keep the pre-call graph for diffing and rollback. These functions deliberately
emit the *minimal* graph shape (no edge ids, no ReactFlow node ``type``, no
positions): ``graph_postprocessor.postprocess_graph`` is the single normaliser
that fills those in, exactly as it does for ``node_builder.assemble_graph``. That
shape is what ``MinimalGraphDict`` describes, so nothing here has to cast an
incomplete node to the fully populated ``GraphNodeDict``.

The model-facing projection is ``render_compact_graph`` (id/type/title/parent,
edges, exposed outputs, and confirmed typed selectors — no full config).
``read_node_view`` is the single-node editing unit. ``upsert_node`` is the internal writer and is not a main-model tool.
``replace_container_subgraph`` swaps one container's descendants atomically
on a deepcopy; it never mutates the input graph.
"""

from copy import deepcopy
from typing import Any

from core.workflow.generator.graph.types import MinimalGraphDict, MinimalGraphEdgeDict, MinimalGraphNodeDict
from core.workflow.generator.types import GraphViewportDict
from core.workflow.generator.variables.declarations import declared_output_type, declared_outputs
from core.workflow.generator.variables.syntax import collect_references
from core.workflow.generator.variables.variable_registry import canonical_registry_type

type MinimalNodeDict = MinimalGraphNodeDict
type MinimalEdgeDict = MinimalGraphEdgeDict


class ContainerReplaceError(ValueError):
    """Raised when a container subgraph cannot be replaced atomically.

    Callers must treat the input graph as unchanged: this module only mutates a
    deepcopy, then raises without returning it.
    """


_DEFAULT_VIEWPORT: GraphViewportDict = {"x": 0.0, "y": 0.0, "zoom": 0.7}
_RESERVED_DATA_KEYS = ("type", "title", "desc", "parentId")
_ITERATION_SCOPED_OUTPUTS = ("item", "index")


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


def replace_container_subgraph(
    graph: MinimalGraphDict,
    *,
    container_id: str,
    replacement_nodes: tuple[MinimalNodeDict, ...],
    replacement_edges: tuple[MinimalEdgeDict, ...],
    exposed_outputs: frozenset[str],
    container_data: dict[str, Any] | None = None,
) -> MinimalGraphDict:
    """Replace one container's descendants on a deepcopy of ``graph``.

    Preserves the container id, top-level UI fields such as ``position``, and
    edges whose endpoint is the container id (external in/out). When
    ``container_data`` is supplied it replaces the complete data payload, so
    config from a prior node type cannot leak into the new container.
    Descendant-to-descendant edges and
    container-to-descendant edges are removed. External nodes, edges, or
    selectors that point at descendants, or at a container output not listed
    in ``exposed_outputs``, raise ``ContainerReplaceError``. The input graph
    identity and content are left unchanged.
    """
    candidate = deepcopy(graph)
    descendant_ids = _collect_descendant_ids(candidate, container_id)
    _reject_external_child_references(candidate, container_id, descendant_ids)
    _remove_container_descendants(candidate, container_id, descendant_ids)
    if container_data is not None:
        container = find_node(candidate, container_id)
        if container is None:
            raise ContainerReplaceError(f"unknown container {container_id!r}")
        container["data"] = deepcopy(container_data)
    _install_replacement(candidate, container_id, replacement_nodes, replacement_edges)
    _validate_external_output_references(candidate, container_id, exposed_outputs)
    return candidate


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
            "outputs": _compact_outputs(node),
        }
        parent = _node_parent(node)
        if parent:
            compact["parent"] = parent
        outputs = compact["outputs"]
        if isinstance(outputs, list) and outputs:
            compact["variables"] = confirmed_variable_views(node, outputs=outputs)
        nodes.append(compact)
    return {"nodes": nodes, "edges": _render_edges(graph)}


def confirmed_variable_views(
    node: MinimalGraphNodeDict,
    *,
    outputs: list[str] | None = None,
) -> list[dict[str, object]]:
    """Return bounded model-facing declarations derived from one committed node."""
    parent = _node_parent(node)
    return [
        {
            "selector": [node["id"], *output.split(".")],
            "type": canonical_registry_type(declared_output_type(dict(node), output) or "unknown"),
            "scope": f"container:{parent}" if parent else "workflow",
            "confirmed": True,
        }
        for output in (outputs if outputs is not None else _compact_outputs(node))
    ]


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


def _collect_descendant_ids(graph: MinimalGraphDict, container_id: str) -> set[str]:
    if find_node(graph, container_id) is None:
        raise ContainerReplaceError(f"unknown container {container_id!r}")
    descendants: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in graph["nodes"]:
            node_id = node["id"]
            if node_id == container_id or node_id in descendants:
                continue
            parent = _node_parent(node)
            if parent == container_id or parent in descendants:
                descendants.add(node_id)
                changed = True
    return descendants


def _reject_external_child_references(
    graph: MinimalGraphDict,
    container_id: str,
    descendant_ids: set[str],
) -> None:
    owned = descendant_ids | {container_id}
    for edge in graph["edges"]:
        source, target = edge["source"], edge["target"]
        source_owned = source in descendant_ids
        target_owned = target in descendant_ids
        if source_owned == target_owned:
            continue
        other = target if source_owned else source
        if other != container_id:
            raise ContainerReplaceError("external edge references a container child")
    for node in graph["nodes"]:
        if node["id"] in owned:
            continue
        parent = _node_parent(node)
        if parent in descendant_ids:
            raise ContainerReplaceError("external node parents a container child")
        for source, _output in collect_references(node.get("data")):
            if source in descendant_ids:
                raise ContainerReplaceError("external selector references a container child")


def _remove_container_descendants(
    graph: MinimalGraphDict,
    container_id: str,
    descendant_ids: set[str],
) -> None:
    owned = descendant_ids | {container_id}
    graph["nodes"] = [node for node in graph["nodes"] if node["id"] not in descendant_ids]
    graph["edges"] = [edge for edge in graph["edges"] if not (edge["source"] in owned and edge["target"] in owned)]


def _install_replacement(
    graph: MinimalGraphDict,
    container_id: str,
    replacement_nodes: tuple[MinimalNodeDict, ...],
    replacement_edges: tuple[MinimalEdgeDict, ...],
) -> None:
    remaining_ids = {node["id"] for node in graph["nodes"]}
    incoming_ids: set[str] = set()
    installed: list[MinimalGraphNodeDict] = []
    for node in replacement_nodes:
        node_id = node["id"]
        if node_id == container_id or node_id in remaining_ids or node_id in incoming_ids:
            raise ContainerReplaceError(f"replacement node id collides: {node_id!r}")
        incoming_ids.add(node_id)
        installed.append(deepcopy(node))
    known = remaining_ids | incoming_ids
    installed_edges: list[MinimalGraphEdgeDict] = []
    for edge in replacement_edges:
        if edge["source"] not in known or edge["target"] not in known:
            raise ContainerReplaceError("replacement edge references an unknown node")
        installed_edges.append(deepcopy(edge))
    graph["nodes"].extend(installed)
    graph["edges"].extend(installed_edges)


def _validate_external_output_references(
    graph: MinimalGraphDict,
    container_id: str,
    exposed_outputs: frozenset[str],
) -> None:
    descendant_ids = _collect_descendant_ids(graph, container_id)
    owned = descendant_ids | {container_id}
    for node in graph["nodes"]:
        if node["id"] in owned:
            continue
        for source, output in collect_references(node.get("data")):
            if source != container_id:
                continue
            basename = output.split(".", 1)[0]
            if basename not in exposed_outputs:
                raise ContainerReplaceError("external selector uses a container output that is not exposed")


def _compact_outputs(node: MinimalGraphNodeDict) -> list[str]:
    """Outputs the model may reference on this node id, including iteration scope."""
    outputs = declared_outputs(dict(node))
    node_type = str(node["data"].get("type") or "")
    if node_type != "iteration":
        return outputs
    extra = [name for name in _ITERATION_SCOPED_OUTPUTS if name not in outputs]
    return [*outputs, *extra]


def _render_edges(graph: MinimalGraphDict) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for edge in graph["edges"]:
        rendered: dict[str, Any] = {"source": edge["source"], "target": edge["target"]}
        if edge.get("sourceHandle"):
            rendered["source_handle"] = edge["sourceHandle"]
        edges.append(rendered)
    return edges
