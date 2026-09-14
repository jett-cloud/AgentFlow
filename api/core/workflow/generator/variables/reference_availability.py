"""Execution availability of declared references, separate from name resolution."""

from core.workflow.generator.types import GraphDict, WorkflowGenerateErrorDict
from core.workflow.generator.variables.variable_references import VariableReferences


def collect_reference_availability_errors(graph: GraphDict) -> list[WorkflowGenerateErrorDict]:
    nodes = {n["id"]: n for n in graph["nodes"]}
    successors: dict[str, set[str]] = {key: set() for key in nodes}
    predecessors: dict[str, set[str]] = {key: set() for key in nodes}
    for edge in graph.get("edges", []):
        source, target = edge["source"], edge["target"]
        if source in nodes and target in nodes:
            successors[source].add(target)
            predecessors[target].add(source)

    def walk(start: str, adjacency: dict[str, set[str]]) -> set[str]:
        pending = list(adjacency.get(start, set()))
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current not in seen:
                seen.add(current)
                pending.extend(adjacency.get(current, set()))
        return seen

    upstream = {key: walk(key, predecessors) for key in nodes}
    branches: list[list[set[str]]] = []
    for key, node in nodes.items():
        if node["data"].get("type") not in {"if-else", "question-classifier"}:
            continue
        handles: dict[str, set[str]] = {}
        for edge in graph.get("edges", []):
            if edge["source"] == key and edge["target"] in nodes:
                target = edge["target"]
                handles.setdefault(str(edge.get("sourceHandle") or "source"), set()).update(
                    {target} | walk(target, successors)
                )
        if len(handles) > 1:
            branches.append(list(handles.values()))

    errors: list[WorkflowGenerateErrorDict] = []
    for key, node in nodes.items():
        data = node["data"]
        refs: set[tuple[str, str]] = set()
        VariableReferences._collect_refs_in_data(data, refs)
        loop_break_refs: set[tuple[str, str]] = set()
        if data.get("type") == "loop":
            for condition in data.get("break_conditions") or []:
                if isinstance(condition, dict):
                    VariableReferences._collect_refs_in_data(condition, loop_break_refs)
        containers: set[str] = set()
        parent = node.get("parentId") or data.get("parentId")
        while isinstance(parent, str) and parent in nodes and parent not in containers:
            containers.add(parent)
            parent_node = nodes[parent]
            parent = parent_node.get("parentId") or parent_node["data"].get("parentId")
        available = set(upstream[key])
        for container in containers:
            available.update(upstream[container])
        for source, output in sorted(refs):
            if source not in nodes:
                continue  # Existing validator owns unknown and namespace names.
            # Loop break conditions are evaluated after each body pass, when
            # the loop node's own declared variables already exist.
            if source == key and (source, output) in loop_break_refs:
                continue
            if source in containers and output.split(".")[0] in {"item", "index"}:
                continue
            if source in containers and nodes[source]["data"].get("type") == "loop":
                continue
            # Containers collect results after their children have executed.
            source_parent = nodes[source].get("parentId") or nodes[source]["data"].get("parentId")
            if source_parent == key and data.get("type") in {"iteration", "loop"}:
                continue
            reason = "source has not executed before this node"
            invalid = source == key or source not in available
            if not invalid and data.get("type") != "variable-aggregator":
                for alternatives in branches:
                    if any(key in reachable and source not in reachable for reachable in alternatives) and any(
                        source in reachable for reachable in alternatives
                    ):
                        invalid = True
                        reason = "source is absent on an alternative branch"
                        break
            if invalid:
                errors.append(
                    {
                        "code": "REFERENCE_NOT_AVAILABLE",
                        "node_id": key,
                        "detail": f"Node {key!r} reference {{{{#{source}.{output}#}}}}: {reason}",
                    }
                )
    return errors
