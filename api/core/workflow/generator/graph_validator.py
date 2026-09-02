"""Read-only structural validation for generated workflow graphs."""

from typing import Any, ClassVar, cast

from core.workflow.generator.types import (
    GraphDict,
    WorkflowGenerateErrorCode,
    WorkflowGenerateErrorDict,
    WorkflowGenerationMode,
)
from core.workflow.generator.variable_references import VariableReferences
from graphon.enums import BuiltinNodeTypes


def _err(code: str, detail: str, node_id: str = "") -> WorkflowGenerateErrorDict:
    out: WorkflowGenerateErrorDict = {"code": code, "detail": detail}
    if node_id:
        out["node_id"] = node_id
    return out


class GraphValidator:
    _CONTAINER_TYPES: ClassVar = frozenset({BuiltinNodeTypes.ITERATION, BuiltinNodeTypes.LOOP})
    _ID_FIELDS: ClassVar = frozenset({"start_node_id", "iteration_id", "loop_id", "parentId"})

    @classmethod
    def _validate_structure(
        cls,
        *,
        graph: GraphDict,
        mode: WorkflowGenerationMode,
        installed_tools: set[tuple[str, str]] | None = None,
        installed_dataset_ids: set[str] | None = None,
    ) -> list[WorkflowGenerateErrorDict]:
        """
        Return a list of structured errors for every violation found.

        Catches:
          * exactly-one ``start`` node + mode-aware terminal (``end`` for
            workflow, ``answer`` for advanced-chat);
          * edges whose endpoints don't exist;
          * top-level nodes that cannot be reached from ``start``;
          * dangling ``parentId`` / ``start_node_id`` / ``iteration_id`` /
            ``loop_id`` references inside node ``data``;
          * container nodes (iteration / loop) without children, children
            whose ``parentId`` points at a non-container, and cycles in the
            parent chain;
          * variable references (``{{#node.var#}}`` / value selectors) that
            point at a node which does NOT declare the variable;
          * tool nodes naming a ``(provider, tool)`` pair the tenant hasn't
            installed.
          * knowledge-retrieval nodes without dataset ids, or naming ids absent
            from the tenant knowledge catalogue.

        Per-node config validation (model spec, prompt template shape, etc.)
        is deferred to ``WorkflowService.sync_draft_workflow``; we only fail
        on structural issues the user must know about so they don't get a
        broken-at-runtime draft.
        """
        errors: list[WorkflowGenerateErrorDict] = []

        nodes_raw = graph.get("nodes", [])
        nodes: list[dict[str, Any]] = list(cast(list[dict[str, Any]], nodes_raw))
        if not nodes:
            errors.append(_err(WorkflowGenerateErrorCode.INVALID_SCHEMA, "Generated graph has no nodes"))
            return errors

        # Duplicate ids make every cross-reference ambiguous (edges, variable
        # placeholders, parentId all resolve to "whichever node wins"), so a
        # graph with them is unusable no matter how the canvas renders it.
        id_counts: dict[str, int] = {}
        for node in nodes:
            node_id = node.get("id", "")
            if node_id:
                id_counts[node_id] = id_counts.get(node_id, 0) + 1
        for node_id, count in id_counts.items():
            if count > 1:
                errors.append(
                    _err(
                        WorkflowGenerateErrorCode.DUPLICATE_NODE_ID,
                        f"Duplicate node id {node_id!r} ({count} nodes share it)",
                        node_id=node_id,
                    )
                )

        types = [node.get("data", {}).get("type", "") for node in nodes]
        starts = [t for t in types if t == BuiltinNodeTypes.START]
        if len(starts) != 1:
            errors.append(
                _err(
                    WorkflowGenerateErrorCode.MISSING_START,
                    f"Workflow must have exactly one 'start' node (found {len(starts)})",
                )
            )

        if mode == "advanced-chat":
            terminal_count = sum(1 for t in types if t == BuiltinNodeTypes.ANSWER)
            terminal_name = "answer"
        else:
            terminal_count = sum(1 for t in types if t == BuiltinNodeTypes.END)
            terminal_name = "end"
        if terminal_count < 1:
            errors.append(
                _err(
                    WorkflowGenerateErrorCode.MISSING_TERMINAL,
                    f"Workflow must end with at least one '{terminal_name}' node",
                )
            )

        # Edges must reference real node ids.
        known_ids: set[str] = {node.get("id", "") for node in nodes if node.get("id")}
        for edge in graph.get("edges", []):
            src = edge.get("source")
            tgt = edge.get("target")
            if src not in known_ids:
                errors.append(_err(WorkflowGenerateErrorCode.DANGLING_EDGE, f"Edge source node not found: {src!r}"))
            if tgt not in known_ids:
                errors.append(_err(WorkflowGenerateErrorCode.DANGLING_EDGE, f"Edge target node not found: {tgt!r}"))

        # Workflow graphs must be DAGs — a directed cycle hangs or errors the
        # run, and nothing downstream of the cycle ever executes. (A "loop"
        # container is the sanctioned way to iterate; its edges are internal.)
        errors.extend(cls._collect_edge_cycle_errors(graph=graph, known_ids=known_ids))
        errors.extend(cls._collect_unreachable_node_errors(nodes=nodes, graph=graph))

        # Dangling node-id references in node ``data`` (parentId, start_node_id, iteration_id, loop_id).
        errors.extend(cls._collect_dangling_id_refs(nodes=nodes, known_ids=known_ids))

        # Container topology.
        errors.extend(cls._collect_container_errors(nodes=nodes))

        # Tool catalogue check — only run if the caller wired in a catalogue.
        if installed_tools is not None:
            errors.extend(cls._collect_unknown_tools(nodes=nodes, installed_tools=installed_tools))

        # Knowledge catalogue check — an absent catalogue means the caller did
        # not provide one, while an empty set means its non-empty prompt had no
        # valid entries and therefore no dataset id is permitted.
        errors.extend(cls._collect_unknown_dataset_ids(nodes=nodes, installed_dataset_ids=installed_dataset_ids))

        # Variable-reference resolution — walks ``{{#node.var#}}`` placeholders
        # and value selectors and flags anything pointing at a node that
        # doesn't declare the variable. Start-node refs are auto-fixed
        # earlier in postprocess, so anything that survives to here is
        # genuinely unresolvable.
        errors.extend(cls._collect_unresolved_refs(nodes=nodes, mode=mode))

        return errors

    @classmethod
    def _collect_edge_cycle_errors(cls, *, graph: GraphDict, known_ids: set[str]) -> list[WorkflowGenerateErrorDict]:
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

    @classmethod
    def _collect_unreachable_node_errors(
        cls, *, nodes: list[dict[str, Any]], graph: GraphDict
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

    @classmethod
    def _collect_dangling_id_refs(
        cls, *, nodes: list[dict[str, Any]], known_ids: set[str]
    ) -> list[WorkflowGenerateErrorDict]:
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
            for field in cls._ID_FIELDS:
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

    @classmethod
    def _collect_container_errors(cls, *, nodes: list[dict[str, Any]]) -> list[WorkflowGenerateErrorDict]:
        """
        Validate iteration / loop topology:

          * every container has at least one executable child whose
            ``parentId`` points at it;
          * every non-container node with a ``parentId`` points at a real
            container, not at a non-container node;
          * no cycles in the parent chain (a node cannot be its own
            ancestor).
        """
        out: list[WorkflowGenerateErrorDict] = []
        by_id: dict[str, dict[str, Any]] = {n.get("id", ""): n for n in nodes if n.get("id")}

        # Containers and the set of node-ids that have a parentId pointing at them.
        container_ids = {n.get("id", "") for n in nodes if n.get("data", {}).get("type") in cls._CONTAINER_TYPES}
        children_by_parent: dict[str, list[str]] = {cid: [] for cid in container_ids}
        for n in nodes:
            parent = (n.get("data") or {}).get("parentId") or n.get("parentId")
            if not isinstance(parent, str) or not parent:
                continue
            if parent in container_ids:
                node_type = (n.get("data") or {}).get("type")
                if node_type not in {"iteration-start", "loop-start"}:
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

    @classmethod
    def _collect_unknown_tools(
        cls,
        *,
        nodes: list[dict[str, Any]],
        installed_tools: set[tuple[str, str]],
    ) -> list[WorkflowGenerateErrorDict]:
        """Flag tool nodes naming a provider / tool pair not in the catalogue."""
        out: list[WorkflowGenerateErrorDict] = []
        for n in nodes:
            data = n.get("data") or {}
            if data.get("type") != BuiltinNodeTypes.TOOL:
                continue
            # The builder is told to put the catalogue's ``provider_name``
            # into BOTH ``provider_id`` and ``provider_name``. Accept either
            # for the lookup so we don't false-fail on the rare case where
            # the LLM only populated one of the two fields.
            provider = str(data.get("provider_id") or data.get("provider_name") or "").strip()
            tool = str(data.get("tool_name") or "").strip()
            if not provider or not tool:
                out.append(
                    _err(
                        WorkflowGenerateErrorCode.UNKNOWN_TOOL,
                        f"Tool node {n.get('id')!r} missing provider / tool name",
                        node_id=n.get("id", ""),
                    )
                )
                continue
            if (provider, tool) not in installed_tools:
                out.append(
                    _err(
                        WorkflowGenerateErrorCode.UNKNOWN_TOOL,
                        f"Tool {provider}/{tool} is not installed for this tenant",
                        node_id=n.get("id", ""),
                    )
                )
        out.extend(cls._collect_unknown_dify_tools(nodes=nodes, installed_tools=installed_tools))
        return out

    @classmethod
    def _collect_unknown_dify_tools(
        cls,
        *,
        nodes: list[dict[str, Any]],
        installed_tools: set[tuple[str, str]],
    ) -> list[WorkflowGenerateErrorDict]:
        """Flag agent nodes whose Soul dify_tools are outside the catalogue."""
        out: list[WorkflowGenerateErrorDict] = []
        providers = {item[0] for item in installed_tools}
        for n in nodes:
            data = n.get("data") or {}
            if data.get("type") != BuiltinNodeTypes.AGENT:
                continue
            dify_tools = data.get("dify_tools")
            if not isinstance(dify_tools, list):
                continue
            for item in dify_tools:
                if not isinstance(item, dict):
                    continue
                provider = str(item.get("provider_id") or item.get("provider_name") or item.get("provider") or "").strip()
                tool_name = item.get("tool_name")
                if not provider:
                    out.append(
                        _err(
                            WorkflowGenerateErrorCode.UNKNOWN_TOOL,
                            f"Agent node {n.get('id')!r} dify_tools entry missing provider",
                            node_id=n.get("id", ""),
                        )
                    )
                    continue
                if tool_name is None or tool_name == "":
                    if provider not in providers:
                        out.append(
                            _err(
                                WorkflowGenerateErrorCode.UNKNOWN_TOOL,
                                f"Tool {provider} is not installed for this tenant",
                                node_id=n.get("id", ""),
                            )
                        )
                    continue
                tool = str(tool_name).strip()
                if (provider, tool) not in installed_tools:
                    out.append(
                        _err(
                            WorkflowGenerateErrorCode.UNKNOWN_TOOL,
                            f"Tool {provider}/{tool} is not installed for this tenant",
                            node_id=n.get("id", ""),
                        )
                    )
        return out

    @classmethod
    def _collect_unknown_dataset_ids(
        cls,
        *,
        nodes: list[dict[str, Any]],
        installed_dataset_ids: set[str] | None,
    ) -> list[WorkflowGenerateErrorDict]:
        """Require valid dataset ids and optionally verify tenant membership."""
        out: list[WorkflowGenerateErrorDict] = []
        for node in nodes:
            data = node.get("data") or {}
            if data.get("type") != BuiltinNodeTypes.KNOWLEDGE_RETRIEVAL:
                continue
            dataset_ids = data.get("dataset_ids")
            if not isinstance(dataset_ids, list) or not dataset_ids:
                out.append(
                    _err(
                        WorkflowGenerateErrorCode.UNKNOWN_DATASET,
                        f"Knowledge-retrieval node {node.get('id')!r} must define a non-empty dataset_ids list",
                        node_id=node.get("id", ""),
                    )
                )
                continue
            invalid_ids = [
                dataset_id for dataset_id in dataset_ids if not isinstance(dataset_id, str) or not dataset_id.strip()
            ]
            if invalid_ids:
                out.append(
                    _err(
                        WorkflowGenerateErrorCode.UNKNOWN_DATASET,
                        f"Knowledge-retrieval node {node.get('id')!r} contains invalid dataset ids",
                        node_id=node.get("id", ""),
                    )
                )
                continue
            if installed_dataset_ids is None:
                continue
            unknown_ids = sorted(dataset_id for dataset_id in dataset_ids if dataset_id not in installed_dataset_ids)
            if unknown_ids:
                out.append(
                    _err(
                        WorkflowGenerateErrorCode.UNKNOWN_DATASET,
                        f"Knowledge-retrieval node {node.get('id')!r} references uninstalled datasets: "
                        f"{', '.join(unknown_ids)}",
                        node_id=node.get("id", ""),
                    )
                )
        return out

    @classmethod
    def _collect_unresolved_refs(
        cls, *, nodes: list[dict[str, Any]], mode: WorkflowGenerationMode
    ) -> list[WorkflowGenerateErrorDict]:
        """
        Walk every variable reference and flag anything pointing at a node
        that doesn't declare it. The postprocess step has already
        auto-injected missing start-node variables and repaired references to
        sole outputs, so by the time this runs only ambiguous or impossible
        references should fail.
        """
        out: list[WorkflowGenerateErrorDict] = []
        by_id: dict[str, dict[str, Any]] = {n.get("id", ""): n for n in nodes if n.get("id")}

        refs: set[tuple[str, str]] = set()
        for node in nodes:
            VariableReferences._collect_refs_in_data(node.get("data") or {}, refs)

        for node_id, var in refs:
            if mode == "advanced-chat" and node_id == "sys":
                continue
            target = by_id.get(node_id)
            if target is None:
                out.append(
                    _err(
                        WorkflowGenerateErrorCode.UNKNOWN_NODE_REFERENCE,
                        f"Reference {{#{node_id}.{var}#}} points at unknown node {node_id!r}",
                        node_id=node_id,
                    )
                )
                continue
            if VariableReferences._declares_variable(target, var):
                continue
            out.append(
                _err(
                    WorkflowGenerateErrorCode.UNRESOLVED_REFERENCE,
                    f"Reference {{#{node_id}.{var}#}} not declared on node {node_id!r}",
                    node_id=node_id,
                )
            )
        return out


def validate_graph(
    *,
    graph: GraphDict,
    mode: WorkflowGenerationMode,
    installed_tools: set[tuple[str, str]] | None = None,
    installed_dataset_ids: set[str] | None = None,
) -> list[WorkflowGenerateErrorDict]:
    return GraphValidator._validate_structure(
        graph=graph,
        mode=mode,
        installed_tools=installed_tools,
        installed_dataset_ids=installed_dataset_ids,
    )
