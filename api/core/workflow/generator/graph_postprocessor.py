"""Deterministic normalization for generated workflow graphs."""

import logging
from typing import Any, cast

from core.workflow.generator.types import GraphDict, GraphViewportDict, WorkflowGenerationMode
from core.workflow.generator.variable_references import VariableReferences
from graphon.enums import BuiltinNodeTypes

logger = logging.getLogger(__name__)

_NODE_X_OFFSET = 80
_NODE_X_GAP = 80
_NODE_Y = 280
_NODE_Y_GAP = 60
_DEFAULT_VIEWPORT: GraphViewportDict = {"x": 0.0, "y": 0.0, "zoom": 0.7}
_DEFAULT_NODE_WIDTH = 244
_DEFAULT_NODE_HEIGHT = 100
_DEFAULT_CONTAINER_WIDTH = 808
_DEFAULT_CONTAINER_HEIGHT = 204
_CONTAINER_CHILD_ORIGIN_X = 24.0
_CONTAINER_CHILD_ORIGIN_Y = 68.0
_CONTAINER_PADDING = 24
_CONTAINER_MIN_WIDTH = 320
_CONTAINER_MIN_HEIGHT = 200
_CONTAINER_TYPES = frozenset({BuiltinNodeTypes.ITERATION, BuiltinNodeTypes.LOOP})
_START_TYPES = frozenset({"iteration-start", "loop-start"})
_FILE_VARIABLE_TYPES = frozenset({"file", "file-list"})
_DEFAULT_ALLOWED_FILE_TYPES = ("document", "image", "audio", "video")
_DEFAULT_FILE_UPLOAD_METHODS = ("local_file", "remote_url")


class GraphPostprocessor:
    @classmethod
    def _postprocess_graph(cls, *, graph: GraphDict, mode: WorkflowGenerationMode) -> GraphDict:
        """Fill safe defaults and apply only deterministic graph repairs."""

        # Internally treat nodes/edges as untyped dicts — TypedDicts forbid the
        # arbitrary-key setdefault writes we need here, but the caller only sees
        # the final structurally-valid ``GraphDict`` shape.
        nodes: list[dict[str, Any]] = list(cast(list[dict[str, Any]], graph.get("nodes", [])))
        edges: list[dict[str, Any]] = list(cast(list[dict[str, Any]], graph.get("edges", [])))

        # Defensive ID remap: Dify's run-time placeholder regex only accepts
        # ``[a-zA-Z0-9_]`` in the node-id slot, so anything the LLM emits with
        # hyphens, dots, or spaces (``node-1``, ``node.2``, etc.) would break
        # every placeholder pointing at it. Sanitize every id + every
        # cross-reference (edges' ``source`` / ``target``, ``parentId``,
        # ``start_node_id`` / ``iteration_id`` / ``loop_id`` on data, and the
        # ``{{#…#}}`` and ``["node-id", "var"]`` references) BEFORE the rest
        # of the postprocess pass touches them.
        VariableReferences._sanitize_node_ids(nodes=nodes, edges=edges)

        # An LLM context accepts one selector. If the builder wires multiple
        # retrieval nodes straight into an LLM but selects only one result,
        # insert a template-transform fan-in that renders every result into
        # one string and point the context at that output.
        VariableReferences._insert_multi_retrieval_context_templates(nodes=nodes, edges=edges)

        # Assist upserts loop/iteration children without the synthetic start
        # node cmd+k's assembler inserts. The canvas still draws a house icon,
        # but nothing connects it to the first body node unless we add both
        # the start node and the entry edge before layout sees the subgraph.
        cls._ensure_container_starts(nodes=nodes, edges=edges)

        # Container children keep staggered relative coordinates when the
        # builder already laid them out (cmd+k). Missing or piled positions
        # get the same longest-path layering as the top-level canvas, then
        # the parent is sized from the child bounding box. Innermost
        # containers are laid out first so nested widths feed the outer pass.
        cls._layout_container_subgraphs(nodes=nodes, edges=edges)
        cls._layout_top_level_nodes(nodes=nodes, edges=edges)
        for node in nodes:
            cls._fill_node_defaults(node)
            if node.get("parentId"):
                # Inner node — keep whatever relative layout produced; only fill
                # the absolutely-required defaults so the canvas can render it.
                node.setdefault("zIndex", 1002)
                node.setdefault("extent", "parent")
            # Inner nodes keep their relative position; top-level nodes were
            # positioned by the layered layout. The setdefault only fires for
            # a node the layout pass couldn't see.
            node.setdefault("position", {"x": 0.0, "y": 0.0})
            node.setdefault("positionAbsolute", dict(node["position"]))
            node.setdefault("width", _DEFAULT_NODE_WIDTH)
            node.setdefault("height", _DEFAULT_NODE_HEIGHT)
            node.setdefault("sourcePosition", "right")
            node.setdefault("targetPosition", "left")

        # ``parentId`` → set of inner-node ids, so edges between siblings can be
        # marked ``isInIteration`` / ``isInLoop`` with the right container id.
        inner_node_to_parent: dict[str, str] = {
            n["id"]: n["parentId"] for n in nodes if n.get("parentId") and n.get("id")
        }
        # Map parent id → its container node-type so we can pick the right flag.
        parent_type: dict[str, str] = {}
        for n in nodes:
            if n.get("id") in inner_node_to_parent.values():
                parent_type[n["id"]] = n.get("data", {}).get("type", "")

        # Branch nodes (if-else / question-classifier) emit one handle per
        # case; an edge leaving them on the default "source" handle dangles
        # off a handle that doesn't exist on the canvas. Repair the
        # unambiguous cases before edge ids are computed from the handles.
        cls._repair_branch_edge_handles(nodes=nodes, edges=edges)

        # Dedupe edges (LLMs sometimes emit the same edge twice).
        seen: set[tuple[str, str, str, str]] = set()
        deduped_edges = []
        for edge in edges:
            cls._fill_edge_defaults(edge)
            key = (
                edge.get("source", ""),
                edge.get("sourceHandle", "source"),
                edge.get("target", ""),
                edge.get("targetHandle", "target"),
            )
            if key in seen:
                continue
            seen.add(key)
            edge["id"] = f"{key[0]}-{key[1]}-{key[2]}-{key[3]}"
            deduped_edges.append(edge)

        # Build source/target → node_type lookup so we can fill edge.data.{sourceType,targetType}
        # which Dify's edge renderer needs.
        type_by_id = {node.get("id", ""): node.get("data", {}).get("type", "") for node in nodes}
        for edge in deduped_edges:
            edge.setdefault("data", {})
            edge["data"].setdefault("sourceType", type_by_id.get(edge.get("source", ""), ""))
            edge["data"].setdefault("targetType", type_by_id.get(edge.get("target", ""), ""))

            # An edge is "inside" a container iff both endpoints share the same
            # parent. Set isInIteration / isInLoop + iteration_id / loop_id +
            # zIndex so the canvas renders it inside the subgraph rather than
            # at the top level. Edges connecting a container to the outside
            # world keep the defaults (isInIteration=False, isInLoop=False).
            src_parent = inner_node_to_parent.get(edge.get("source", ""))
            tgt_parent = inner_node_to_parent.get(edge.get("target", ""))
            in_iter = bool(src_parent and src_parent == tgt_parent and parent_type.get(src_parent) == "iteration")
            in_loop = bool(src_parent and src_parent == tgt_parent and parent_type.get(src_parent) == "loop")
            edge["data"].setdefault("isInIteration", in_iter)
            edge["data"].setdefault("isInLoop", in_loop)
            if in_iter:
                edge["data"].setdefault("iteration_id", src_parent)
                edge.setdefault("zIndex", 1002)
            if in_loop:
                edge["data"].setdefault("loop_id", src_parent)
                edge.setdefault("zIndex", 1002)

        viewport = graph.get("viewport") or _DEFAULT_VIEWPORT
        # Coerce to floats in case the LLM emitted strings.
        viewport = {
            "x": float(viewport.get("x", 0.0)),
            "y": float(viewport.get("y", 0.0)),
            "zoom": float(viewport.get("zoom", 0.7)),
        }

        # Variable-reference walker: every ``{#node-id.var#}`` and every
        # ``["node-id", "var"]`` selector must point at a variable the source
        # node actually exposes — otherwise the workflow's variable resolver
        # fails at run time with "variable not found". The dominant failure
        # mode is a prompt that references ``{#start.url#}`` when the start
        # node has ``variables: []``, so we auto-inject missing start-node
        # variables. We also repair a mistaken output name when its source
        # exposes exactly one valid output; ambiguous references still fail
        # closed in the structural validator.
        VariableReferences._normalize_sys_query_references(nodes=nodes, mode=mode)
        VariableReferences._reconcile_variable_references(nodes=nodes, mode=mode)

        # Schema backstop: a "file" / "file-list" start variable MUST carry a
        # non-empty ``allowed_file_types`` or Studio refuses to load the draft
        # ("supported file types is required"). The builder is now told to set
        # it, but we fill safe defaults for any variable that still lacks it so
        # the generated workflow always loads and runs.
        cls._normalize_start_file_variables(nodes=nodes)

        return cast(GraphDict, {"nodes": nodes, "edges": deduped_edges, "viewport": viewport})

    @classmethod
    def _repair_branch_edge_handles(cls, *, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        """
        Re-home edges that leave a branch node on the default "source" handle.

        if-else exposes one source handle per ``case_id`` plus the implicit
        "false" (ELSE) handle; question-classifier exposes one per class id.
        The builder prompt documents this, but LLMs still emit the default
        handle, which renders as an edge hanging off a handle that doesn't
        exist and the branch silently never runs.

        Repair only when unambiguous: default-handle edges are assigned to the
        node's UNUSED branch handles in declaration order, and only when there
        are at least as many unused handles as edges to fix. Anything
        ambiguous is left alone — a wrong guess that swaps the IF and ELSE
        arms is worse than a visible dangling edge.
        """
        for node in nodes:
            data = node.get("data") or {}
            node_type = data.get("type")
            if node_type == BuiltinNodeTypes.IF_ELSE:
                branch_handles = [
                    str(case["case_id"])
                    for case in (data.get("cases") or [])
                    if isinstance(case, dict) and case.get("case_id")
                ]
                # ELSE is implicit — it has a handle even though no case
                # declares it.
                branch_handles.append("false")
            elif node_type == BuiltinNodeTypes.QUESTION_CLASSIFIER:
                branch_handles = [
                    str(klass["id"])
                    for klass in (data.get("classes") or [])
                    if isinstance(klass, dict) and klass.get("id")
                ]
            elif node_type == BuiltinNodeTypes.HUMAN_INPUT:
                branch_handles = [
                    str(action["id"])
                    for action in (data.get("user_actions") or [])
                    if isinstance(action, dict) and action.get("id")
                ]
            else:
                continue

            node_id = node.get("id")
            outgoing = [e for e in edges if e.get("source") == node_id]
            taken = {e.get("sourceHandle") for e in outgoing if e.get("sourceHandle") in branch_handles}
            unused = [h for h in branch_handles if h not in taken]
            defaulted = [e for e in outgoing if e.get("sourceHandle") in (None, "", "source")]
            if not defaulted or len(defaulted) > len(unused):
                continue
            for edge, handle in zip(defaulted, unused):
                edge["sourceHandle"] = handle
                logger.info(
                    "Workflow generator: re-homed default-handle edge %s -> %s onto branch handle %r",
                    node_id,
                    edge.get("target"),
                    handle,
                )

    @classmethod
    def _ensure_container_starts(cls, *, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        by_id = {n["id"]: n for n in nodes if isinstance(n.get("id"), str) and n.get("id")}
        extras: list[dict[str, Any]] = []
        for container in list(nodes):
            node_id = container.get("id")
            data = container.setdefault("data", {})
            node_type = data.get("type")
            if node_type not in _CONTAINER_TYPES or not isinstance(node_id, str) or not node_id:
                continue
            is_iteration = node_type == BuiltinNodeTypes.ITERATION
            configured = data.get("start_node_id")
            start_id = configured if isinstance(configured, str) and configured else f"{node_id}start"
            existing = by_id.get(start_id)
            if existing is None or (existing.get("data") or {}).get("type") not in _START_TYPES:
                start = cls._synthetic_start_node(container_id=node_id, start_id=start_id, is_iteration=is_iteration)
                extras.append(start)
                by_id[start_id] = start
            else:
                start = existing
                start["parentId"] = node_id
            data["start_node_id"] = start_id

            body_ids = [
                child["id"]
                for child in (*nodes, *extras)
                if child.get("parentId") == node_id
                and isinstance(child.get("id"), str)
                and child.get("id")
                and (child.get("data") or {}).get("type") not in _START_TYPES
            ]
            if not body_ids:
                continue
            if any(edge.get("source") == start_id and edge.get("target") in body_ids for edge in edges):
                continue
            entry = cls._container_entry_target(body_ids=body_ids, start_id=start_id, edges=edges)
            if entry:
                edges.append({"source": start_id, "target": entry})
            body_nodes = [by_id[body_id] for body_id in body_ids if body_id in by_id]
            if not cls._children_need_auto_layout(body_nodes):
                start.setdefault("position", {"x": _CONTAINER_CHILD_ORIGIN_X, "y": _CONTAINER_CHILD_ORIGIN_Y})
        nodes.extend(extras)

    @classmethod
    def _synthetic_start_node(cls, *, container_id: str, start_id: str, is_iteration: bool) -> dict[str, Any]:
        marker = "isInIteration" if is_iteration else "isInLoop"
        return {
            "id": start_id,
            "type": "custom-iteration-start" if is_iteration else "custom-loop-start",
            "parentId": container_id,
            "extent": "parent",
            "draggable": False,
            "selectable": False,
            "zIndex": 1002,
            "data": {
                "type": "iteration-start" if is_iteration else "loop-start",
                "title": "",
                "desc": "",
                "selected": False,
                marker: True,
            },
        }

    @classmethod
    def _container_entry_target(
        cls, *, body_ids: list[str], start_id: str, edges: list[dict[str, Any]]
    ) -> str | None:
        body = set(body_ids)
        incoming: set[str] = set()
        for edge in edges:
            target = edge.get("target")
            source = edge.get("source")
            if target not in body:
                continue
            if source in body or source == start_id:
                incoming.add(str(target))
        for body_id in body_ids:
            if body_id not in incoming:
                return body_id
        return body_ids[0] if body_ids else None

    @classmethod
    def _layout_top_level_nodes(cls, *, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        """Lay out top-level nodes by graph topology instead of array order."""
        top_level = [n for n in nodes if not n.get("parentId") and isinstance(n.get("id"), str) and n.get("id")]
        cls._layout_layered_nodes(
            nodes=top_level,
            edges=edges,
            origin_x=float(_NODE_X_OFFSET),
            origin_y=float(_NODE_Y),
        )

    @classmethod
    def _layout_container_subgraphs(cls, *, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        by_id = {n["id"]: n for n in nodes if isinstance(n.get("id"), str) and n.get("id")}
        containers = [
            node
            for node in nodes
            if isinstance(node.get("id"), str)
            and node.get("id")
            and (node.get("data") or {}).get("type") in _CONTAINER_TYPES
        ]
        containers.sort(key=lambda node: cls._container_depth(node, by_id), reverse=True)
        for container in containers:
            children = [node for node in nodes if node.get("parentId") == container["id"] and node.get("id")]
            if cls._children_need_auto_layout(children):
                child_ids = {child["id"] for child in children}
                inner_edges = [
                    edge
                    for edge in edges
                    if edge.get("source") in child_ids and edge.get("target") in child_ids
                ]
                cls._layout_layered_nodes(
                    nodes=children,
                    edges=inner_edges,
                    origin_x=_CONTAINER_CHILD_ORIGIN_X,
                    origin_y=_CONTAINER_CHILD_ORIGIN_Y,
                )
            cls._size_container_from_children(container, children)

    @classmethod
    def _container_depth(cls, node: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> int:
        depth = 0
        current = node
        seen: set[str] = set()
        while True:
            parent_id = current.get("parentId")
            node_id = current.get("id")
            if not isinstance(parent_id, str) or not parent_id or not isinstance(node_id, str) or node_id in seen:
                return depth
            seen.add(node_id)
            parent = by_id.get(parent_id)
            if parent is None:
                return depth
            depth += 1
            current = parent

    @classmethod
    def _children_need_auto_layout(cls, children: list[dict[str, Any]]) -> bool:
        points: list[tuple[float, float]] = []
        for child in children:
            position = child.get("position")
            if not isinstance(position, dict):
                return True
            x, y = position.get("x"), position.get("y")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                return True
            points.append((float(x), float(y)))
        if not points:
            return False
        unique = set(points)
        if len(unique) > 1:
            return False
        only = next(iter(unique))
        return only == (0.0, 0.0) or len(children) > 1

    @classmethod
    def _size_container_from_children(cls, container: dict[str, Any], children: list[dict[str, Any]]) -> None:
        if not children:
            return
        max_right = 0.0
        max_bottom = 0.0
        for child in children:
            position = child.get("position") if isinstance(child.get("position"), dict) else {}
            x = position.get("x") if isinstance(position.get("x"), (int, float)) else 0.0
            y = position.get("y") if isinstance(position.get("y"), (int, float)) else 0.0
            max_right = max(max_right, float(x) + cls._node_width(child))
            max_bottom = max(max_bottom, float(y) + cls._node_height(child))
        container["width"] = max(float(_CONTAINER_MIN_WIDTH), max_right + _CONTAINER_PADDING)
        container["height"] = max(float(_CONTAINER_MIN_HEIGHT), max_bottom + _CONTAINER_PADDING)

    @classmethod
    def _layout_layered_nodes(
        cls,
        *,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        origin_x: float,
        origin_y: float,
    ) -> None:
        """
        Lay out ``nodes`` by longest-path depth.

        x = longest-path depth from the entry layer, y = lane within the
        layer — so an if-else's two arms render as two parallel rows instead
        of overlapping on one line, and a builder that emits nodes out of
        execution order still gets a left-to-right canvas. Longest-path (not
        BFS) layering keeps a join node (variable-aggregator, end) to the
        right of its deepest branch.

        Cycle-safe: Kahn's algorithm simply never reaches nodes on a cycle,
        and those get parked one layer past the deepest laid-out node in
        declaration order — the cycle itself is flagged by the structural
        validator afterwards.
        """
        id_set = {n["id"] for n in nodes if isinstance(n.get("id"), str) and n.get("id")}
        if not id_set:
            return

        succs: dict[str, list[str]] = {node_id: [] for node_id in id_set}
        indegree: dict[str, int] = dict.fromkeys(id_set, 0)
        seen_pairs: set[tuple[str, str]] = set()
        for edge in edges:
            src, tgt = edge.get("source"), edge.get("target")
            if not isinstance(src, str) or not isinstance(tgt, str):
                continue
            if src not in id_set or tgt not in id_set or src == tgt or (src, tgt) in seen_pairs:
                continue
            seen_pairs.add((src, tgt))
            succs[src].append(tgt)
            indegree[tgt] += 1

        depth: dict[str, int] = {}
        queue = [n["id"] for n in nodes if n.get("id") in id_set and indegree[n["id"]] == 0]
        for node_id in queue:
            depth[node_id] = 0
        while queue:
            cur = queue.pop(0)
            for nxt in succs[cur]:
                depth[nxt] = max(depth.get(nxt, 0), depth[cur] + 1)
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)

        overflow_depth = (max(depth.values()) + 1) if depth else 0
        layers: dict[int, list[dict[str, Any]]] = {}
        for node in nodes:
            if node.get("id") not in id_set:
                continue
            layers.setdefault(depth.get(node["id"], overflow_depth), []).append(node)

        x_by_depth: dict[int, float] = {}
        next_x = float(origin_x)
        for layer_depth in sorted(layers):
            layer = layers[layer_depth]
            x_by_depth[layer_depth] = next_x
            next_x += max(cls._node_width(node) for node in layer) + _NODE_X_GAP

        for layer_depth, layer in layers.items():
            next_y = float(origin_y)
            for node in layer:
                node["position"] = {"x": x_by_depth[layer_depth], "y": next_y}
                next_y += cls._node_height(node) + _NODE_Y_GAP

    @classmethod
    def _node_width(cls, node: dict[str, Any]) -> float:
        width = node.get("width")
        if isinstance(width, (int, float)) and width > 0:
            return float(width)
        node_type = (node.get("data") or {}).get("type")
        if node_type in _CONTAINER_TYPES:
            return float(_DEFAULT_CONTAINER_WIDTH)
        return float(_DEFAULT_NODE_WIDTH)

    @classmethod
    def _node_height(cls, node: dict[str, Any]) -> float:
        height = node.get("height")
        if isinstance(height, (int, float)) and height > 0:
            return float(height)
        node_type = (node.get("data") or {}).get("type")
        if node_type in _CONTAINER_TYPES:
            return float(_DEFAULT_CONTAINER_HEIGHT)
        return float(_DEFAULT_NODE_HEIGHT)

    @classmethod
    def _normalize_start_file_variables(cls, *, nodes: list[dict[str, Any]]) -> None:
        """
        Fill the required upload config on every file / file-list start variable.

        A start variable of type ``file`` / ``file-list`` is invalid without a
        non-empty ``allowed_file_types`` — Studio rejects the draft with
        "supported file types is required" (see the front-end validator in
        ``config-var/config-modal/utils.ts``) and the workflow never runs. The
        builder prompt now documents these fields, but LLMs still drop them, so
        we backfill safe defaults here:

          * a start variable a ``document-extractor`` consumes but that wasn't
            declared as a file type → promoted to ``file`` (or ``file-list``
            when the extractor's ``is_array_file`` is set), defaulting its
            allowed types to ``["document"]`` (what extraction needs);
          * empty / missing ``allowed_file_types`` → every standard file type;
          * ``custom`` present without ``allowed_file_extensions`` → drop
            ``custom`` (it would otherwise require a non-empty extension list);
          * empty / missing ``allowed_file_upload_methods`` → local + remote;
          * ensure ``allowed_file_extensions`` is at least an empty list.

        Idempotent: a variable that already declares valid file config is left
        untouched.
        """
        start_node = next(
            (n for n in nodes if (n.get("data") or {}).get("type") == BuiltinNodeTypes.START),
            None,
        )
        if start_node is None:
            return
        variables = (start_node.get("data") or {}).get("variables")
        if not isinstance(variables, list):
            return

        # Start variables a document-extractor reads → whether it wants an
        # array (file-list). These MUST be file inputs even if the builder
        # mistyped them (e.g. declared "paragraph"), or the extractor fails at
        # run time. ``["document"]`` is the right default for text extraction.
        extractor_file_vars = cls._document_extractor_start_vars(nodes=nodes, start_id=start_node.get("id", ""))

        for var in variables:
            if not isinstance(var, dict):
                continue
            name = var.get("variable")
            if name in extractor_file_vars and var.get("type") not in _FILE_VARIABLE_TYPES:
                var["type"] = "file-list" if extractor_file_vars[name] else "file"
                var.setdefault("allowed_file_types", ["document"])
            if var.get("type") not in _FILE_VARIABLE_TYPES:
                continue
            allowed_types = var.get("allowed_file_types")
            if not isinstance(allowed_types, list) or not allowed_types:
                allowed_types = list(_DEFAULT_ALLOWED_FILE_TYPES)
                var["allowed_file_types"] = allowed_types
            # ``custom`` demands a non-empty extension list; without one, drop it
            # so the variable doesn't trip the "file extensions required" check.
            extensions = var.get("allowed_file_extensions")
            has_extensions = isinstance(extensions, list) and bool(extensions)
            if "custom" in allowed_types and not has_extensions:
                pruned = [t for t in allowed_types if t != "custom"]
                var["allowed_file_types"] = pruned or list(_DEFAULT_ALLOWED_FILE_TYPES)
            methods = var.get("allowed_file_upload_methods")
            if not isinstance(methods, list) or not methods:
                var["allowed_file_upload_methods"] = list(_DEFAULT_FILE_UPLOAD_METHODS)
            if not isinstance(var.get("allowed_file_extensions"), list):
                var["allowed_file_extensions"] = []

    @classmethod
    def _document_extractor_start_vars(cls, *, nodes: list[dict[str, Any]], start_id: str) -> dict[str, bool]:
        """
        Map start-variable name → ``is_array_file`` for every start variable a
        ``document-extractor`` node reads via its ``variable_selector``.

        When two extractors read the same variable we keep ``True`` (file-list)
        if any of them wants an array, since a file-list also satisfies a
        single-file read.
        """
        out: dict[str, bool] = {}
        if not start_id:
            return out
        for node in nodes:
            data = node.get("data") or {}
            if data.get("type") != BuiltinNodeTypes.DOCUMENT_EXTRACTOR:
                continue
            selector = data.get("variable_selector")
            if isinstance(selector, list) and len(selector) == 2 and selector[0] == start_id:
                var_name = selector[1]
                out[var_name] = out.get(var_name, False) or bool(data.get("is_array_file"))
        return out

    @classmethod
    def _fill_node_defaults(cls, node: dict[str, Any]) -> None:
        """Ensure every node has the wrapper-level fields the Studio canvas needs."""
        node.setdefault("type", "custom")
        data = node.setdefault("data", {})
        data.setdefault("title", node.get("id", "Node"))
        data.setdefault("desc", "")
        data.setdefault("selected", False)

    @classmethod
    def _fill_edge_defaults(cls, edge: dict[str, Any]) -> None:
        edge.setdefault("type", "custom")
        edge.setdefault("sourceHandle", "source")
        edge.setdefault("targetHandle", "target")


def postprocess_graph(*, graph: GraphDict, mode: WorkflowGenerationMode) -> GraphDict:
    return GraphPostprocessor._postprocess_graph(graph=graph, mode=mode)
