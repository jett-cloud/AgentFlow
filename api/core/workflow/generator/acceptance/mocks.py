"""Pure graph rewrites that let Workflow Assist execute a candidate without real providers.

``build_mocked_graph`` swaps every external node (see ``effects``) for a code
node that returns fixed outputs, keeping the node id so downstream selectors
still resolve. ``build_node_probe_graph`` keeps start and one target node,
turns the target's ancestors into such fixed-output nodes in one linear chain,
drops descendants and ends at a synthetic end node. Fixture values are checked
against the node's declared outputs; unspecified outputs get typed placeholders.
Nothing here executes code or imports services.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Mapping
from copy import deepcopy
from itertools import product
from typing import Any, TypedDict

from core.workflow.generator.acceptance.effects import classify_node_effect, external_node_ids
from core.workflow.generator.graph.types import MinimalGraphDict, MinimalGraphEdgeDict, MinimalGraphNodeDict
from core.workflow.generator.variables.declarations import declared_output_schema, declared_outputs

PROBE_END_ID = "assist_probe_end"
MOCK_UNSUPPORTED_NODE_TYPES = frozenset({"question-classifier", "human-input"})
_SCENARIO_BRANCH_NODE_TYPES = frozenset({"question-classifier"})
_SCENARIO_PRESERVED_NODE_TYPES = frozenset({"human-input"})
_MAX_VERIFICATION_SCENARIOS = 12
_PROBE_UNSUPPORTED_TYPES = frozenset({"start", "end", "answer", "loop", "iteration"})
_SCOPE_KEYS = ("isInIteration", "isInLoop", "iteration_id", "loop_id")
_FILE_TYPES = frozenset({"file", "files", "file-list", "array[file]", "arrayFile"})
_ARRAY_ITEM_TYPES = {
    "array[string]": "string",
    "arrayString": "string",
    "array[number]": "number",
    "arrayNumber": "number",
    "array[object]": "object",
    "arrayObject": "object",
    "array[boolean]": "boolean",
    "arrayBoolean": "boolean",
}
_SCHEMA_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("http-request", "body"): {"type": "string"},
    ("http-request", "status_code"): {"type": "number"},
    ("document-extractor", "text"): {"type": "string"},
    ("agent", "text"): {"type": "string"},
    ("agent", "files"): {"type": "arrayFile"},
    ("agent", "json"): {"type": "array[object]"},
}
_TOOL_DEFAULT_SCHEMAS: dict[str, dict[str, Any]] = {
    "text": {"type": "string"},
    "files": {"type": "arrayFile"},
    "json": {"type": "array[object]"},
}
_PE_BUILTIN_SCHEMAS: dict[str, dict[str, Any]] = {
    "__is_success": {"type": "number"},
    "__reason": {"type": "string"},
    "__usage": {"type": "object"},
}
_PE_TYPE_ALIASES = {"select": "string", "bool": "boolean"}
_EXCERPT_CHARS = 600
_PLACEHOLDER_DEPTH = 4

Fixtures = dict[str, dict[str, object]]


class SimulatedGraphScenario(TypedDict):
    scenario_id: str
    graph: MinimalGraphDict
    fixtures: Fixtures
    selections: list[dict[str, str]]


class MockGraphError(ValueError):
    """A fixture or probe request the engine must not run; ``code`` is a ToolResult error code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def mock_output_schemas(node: MinimalGraphNodeDict) -> dict[str, dict[str, Any]]:
    """Return ``{output_name: schema}`` a fixture for ``node`` must satisfy."""
    data = node.get("data") or {}
    node_type = _node_type(node)
    if node_type == "parameter-extractor":
        parameter_schemas = {
            str(parameter["name"]): _parameter_schema(parameter)
            for parameter in data.get("parameters") or []
            if isinstance(parameter, dict) and isinstance(parameter.get("name"), str)
        }
        return {**parameter_schemas, **deepcopy(_PE_BUILTIN_SCHEMAS)}
    if node_type == "tool":
        outputs = data.get("outputs")
        if isinstance(outputs, dict) and outputs:
            return {
                str(name): dict(schema) if isinstance(schema, dict) and schema.get("type") else {"type": "any"}
                for name, schema in outputs.items()
            }
        return deepcopy(_TOOL_DEFAULT_SCHEMAS)
    schemas: dict[str, dict[str, Any]] = {}
    for name in declared_outputs(dict(node)):
        schema = declared_output_schema(dict(node), name)
        override = _SCHEMA_OVERRIDES.get((node_type, name))
        schemas[name] = deepcopy(override) if override is not None and schema == {"type": "object"} else schema
    return schemas


def resolve_mock_outputs(
    node: MinimalGraphNodeDict, supplied: Mapping[str, object], *, strict: bool = True
) -> dict[str, object]:
    """Validate ``supplied`` against the node's outputs and fill the rest with typed placeholders.

    ``strict=False`` silently drops invalid values; it is used for outputs observed
    in an earlier run, which may carry runtime-only shapes.
    """
    node_id = str(node.get("id") or "")
    schemas = mock_output_schemas(node)
    open_names = _node_type(node) == "tool"
    resolved: dict[str, object] = {}
    for name, value in supplied.items():
        schema = schemas.get(name)
        if schema is None and not open_names:
            if strict:
                raise MockGraphError(
                    "INVALID_MOCK_OUTPUT", f"{node_id} has no output {name!r}; declared: {sorted(schemas)}"
                )
            continue
        problem: str | None
        if _code_output_type(value) is None:
            problem = f"{node_id}.{name} must be a string, number, boolean, object or an array of one element type"
        else:
            problem = _value_error(schema or {"type": "any"}, value, f"{node_id}.{name}")
        if problem is not None:
            if strict:
                raise MockGraphError("INVALID_MOCK_OUTPUT", problem)
            continue
        resolved[name] = deepcopy(value)
    for name, schema in schemas.items():
        if name not in resolved and str(schema.get("type") or "") not in _FILE_TYPES:
            resolved[name] = _placeholder(schema, 0)
    return resolved


def build_mocked_graph(
    graph: MinimalGraphDict, mocks: Mapping[str, Mapping[str, object]]
) -> tuple[MinimalGraphDict, Fixtures]:
    """Return a copy of ``graph`` whose external nodes return fixtures, plus the applied fixtures."""
    external = set(external_node_ids(graph))
    unknown = sorted(set(mocks) - external)
    if unknown:
        raise MockGraphError(
            "INVALID_MOCK_OUTPUT",
            f"{unknown[0]} is not an external node; only model, tool, HTTP and other external nodes take mocks",
        )
    nodes: list[MinimalGraphNodeDict] = []
    applied: Fixtures = {}
    for node in graph["nodes"]:
        if node["id"] not in external:
            nodes.append(deepcopy(node))
            continue
        node_type = _node_type(node)
        if node_type in MOCK_UNSUPPORTED_NODE_TYPES:
            raise MockGraphError(
                "MOCK_UNSUPPORTED_NODE",
                f"{node['id']} ({node_type}) routes by its own branch handles and cannot be mocked; "
                "test its downstream nodes with run_node or run live",
            )
        outputs = resolve_mock_outputs(node, mocks.get(node["id"]) or {})
        applied[node["id"]] = outputs
        nodes.append(_fixed_output_node(node, outputs))
    mocked: MinimalGraphDict = {
        "nodes": nodes,
        "edges": deepcopy(graph["edges"]),
        "viewport": deepcopy(graph["viewport"]),
    }
    return mocked, applied


def build_simulated_graph_scenarios(
    graph: MinimalGraphDict,
    mocks: Mapping[str, Mapping[str, object]],
    *,
    max_scenarios: int = _MAX_VERIFICATION_SCENARIOS,
) -> list[SimulatedGraphScenario]:
    """Build bounded simulated graphs while preserving Human Input pause semantics.

    Ordinary external nodes become fixed-output Code nodes. Every Question
    Classifier class becomes a branch scenario by retaining only the matching
    outgoing edge. Human Input nodes remain real so the service executor can
    pause, clone the runtime snapshot and resume once per configured action.
    """

    by_id = {node["id"]: node for node in graph.get("nodes") or []}
    external = set(external_node_ids(graph))
    mockable = {
        node_id
        for node_id in external
        if _node_type(by_id[node_id]) not in _SCENARIO_BRANCH_NODE_TYPES | _SCENARIO_PRESERVED_NODE_TYPES
    }
    unknown = sorted(set(mocks) - mockable)
    if unknown:
        raise MockGraphError(
            "INVALID_MOCK_OUTPUT",
            f"{unknown[0]} does not accept a direct fixture in scenario verification",
        )

    branch_options: list[tuple[str, list[dict[str, str]]]] = []
    for node in graph.get("nodes") or []:
        if _node_type(node) != "question-classifier":
            continue
        classes = [
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "label": str(item.get("label") or ""),
            }
            for item in (node.get("data") or {}).get("classes") or []
            if isinstance(item, Mapping) and item.get("id")
        ]
        if not classes:
            raise MockGraphError("MOCK_UNSUPPORTED_NODE", f"{node['id']} has no classifier branches")
        branch_options.append((node["id"], classes))

    combinations = list(product(*(options for _, options in branch_options))) if branch_options else [()]
    if len(combinations) > max_scenarios:
        raise MockGraphError(
            "MOCK_UNSUPPORTED_NODE",
            f"Classifier branch scenarios exceed the verification limit of {max_scenarios}",
        )

    scenarios: list[SimulatedGraphScenario] = []
    for index, combination in enumerate(combinations, start=1):
        selected = {node_id: option for (node_id, _), option in zip(branch_options, combination)}
        nodes: list[MinimalGraphNodeDict] = []
        applied: Fixtures = {}
        selections: list[dict[str, str]] = []
        for node in graph.get("nodes") or []:
            node_id = node["id"]
            node_type = _node_type(node)
            if node_type == "question-classifier":
                option = selected[node_id]
                outputs: dict[str, object] = {
                    "class_name": option["name"],
                    "class_label": option["label"],
                    "class_id": option["id"],
                    "usage": {},
                }
                applied[node_id] = outputs
                nodes.append(_fixed_output_node(node, outputs))
                selections.append({"node_id": node_id, "kind": "classifier", "value": option["id"]})
            elif node_id in mockable:
                outputs = resolve_mock_outputs(node, mocks.get(node_id) or {})
                applied[node_id] = outputs
                nodes.append(_fixed_output_node(node, outputs))
            else:
                nodes.append(deepcopy(node))

        edges: list[MinimalGraphEdgeDict] = []
        for raw_edge in graph.get("edges") or []:
            edge = deepcopy(raw_edge)
            option = selected.get(edge["source"])
            if option is not None:
                if str(edge.get("sourceHandle") or "source") != option["id"]:
                    continue
                edge.pop("sourceHandle", None)
            edges.append(edge)
        scenarios.append(
            {
                "scenario_id": f"branch-{index}",
                "graph": {"nodes": nodes, "edges": edges, "viewport": deepcopy(graph.get("viewport") or {})},
                "fixtures": applied,
                "selections": selections,
            }
        )
    return scenarios


def build_node_probe_graph(
    graph: MinimalGraphDict,
    node_id: str,
    *,
    upstream_outputs: Mapping[str, Mapping[str, object]],
    observed_outputs: Mapping[str, Mapping[str, object]],
) -> tuple[MinimalGraphDict, Fixtures]:
    """Build ``start -> fixed ancestors -> target -> probe end`` for a single-node run."""
    by_id = {node["id"]: node for node in graph["nodes"]}
    target = by_id.get(node_id)
    if target is None:
        raise MockGraphError("NODE_NOT_FOUND", f"Unknown node {node_id!r}")
    data = target.get("data") or {}
    if target.get("parentId") or data.get("isInIteration") or data.get("isInLoop"):
        raise MockGraphError(
            "NODE_PROBE_UNSUPPORTED", f"{node_id} is inside a loop or iteration; use run_workflow instead"
        )
    if _node_type(target) in _PROBE_UNSUPPORTED_TYPES:
        raise MockGraphError(
            "NODE_PROBE_UNSUPPORTED", f"{node_id} ({_node_type(target)}) cannot run alone; use run_workflow instead"
        )
    start = next((node for node in graph["nodes"] if _node_type(node) == "start"), None)
    if start is None:
        raise MockGraphError("NODE_PROBE_UNSUPPORTED", "The candidate has no start node")
    top_level = [node["id"] for node in graph["nodes"] if not node.get("parentId")]
    top_level_ids = set(top_level)
    edges = [edge for edge in graph["edges"] if edge["source"] in top_level_ids and edge["target"] in top_level_ids]
    ancestors = _ancestors(edges, node_id)
    unknown = sorted(set(upstream_outputs) - ancestors)
    if unknown:
        raise MockGraphError("INVALID_MOCK_OUTPUT", f"{unknown[0]} is not upstream of {node_id}")
    chain = [
        candidate
        for candidate in _topological_order(top_level, edges)
        if candidate in ancestors and candidate != start["id"]
    ]
    nodes: list[MinimalGraphNodeDict] = [deepcopy(start)]
    applied: Fixtures = {}
    for ancestor_id in chain:
        ancestor = by_id[ancestor_id]
        supplied = upstream_outputs.get(ancestor_id)
        if supplied is not None:
            outputs = resolve_mock_outputs(ancestor, supplied)
        else:
            outputs = resolve_mock_outputs(ancestor, observed_outputs.get(ancestor_id) or {}, strict=False)
        applied[ancestor_id] = outputs
        nodes.append(_fixed_output_node(ancestor, outputs))
    nodes.append(deepcopy(target))
    nodes.append({"id": PROBE_END_ID, "data": {"type": "end", "title": "Probe end", "desc": "", "outputs": []}})
    order = [start["id"], *chain, node_id]
    probe_edges: list[MinimalGraphEdgeDict] = [
        {"source": source, "target": target_id} for source, target_id in zip(order, order[1:])
    ]
    handles = sorted(
        {str(edge.get("sourceHandle") or "source") for edge in graph["edges"] if edge["source"] == node_id}
    ) or ["source"]
    for handle in handles:
        edge: MinimalGraphEdgeDict = {"source": node_id, "target": PROBE_END_ID}
        if handle != "source":
            edge["sourceHandle"] = handle
        probe_edges.append(edge)
    probe: MinimalGraphDict = {"nodes": nodes, "edges": probe_edges, "viewport": deepcopy(graph["viewport"])}
    return probe, applied


def describe_mock_target(graph: MinimalGraphDict, node_id: str) -> dict[str, object]:
    """Facts an Agent needs to write a grounded fixture for one node."""
    node = next((item for item in graph["nodes"] if item["id"] == node_id), None)
    if node is None:
        raise MockGraphError("NODE_NOT_FOUND", f"Unknown node {node_id!r}")
    data = node.get("data") or {}
    node_type = _node_type(node)
    return {
        "node_id": node_id,
        "type": node_type,
        "title": str(data.get("title") or ""),
        "external": classify_node_effect(node) != "local_execute",
        "mockable": node_type not in MOCK_UNSUPPORTED_NODE_TYPES,
        "output_schema": mock_output_schemas(node),
        "placeholder": resolve_mock_outputs(node, {}),
        "instruction_excerpt": _instruction_excerpt(data),
        "consumers": _consumers(graph, node_id),
    }


def _node_type(node: Mapping[str, Any]) -> str:
    data = node.get("data")
    return str(data.get("type") or "") if isinstance(data, dict) else ""


def _parameter_schema(parameter: Mapping[str, Any]) -> dict[str, Any]:
    raw_type = str(parameter.get("type") or "string")
    schema: dict[str, Any] = {"type": _PE_TYPE_ALIASES.get(raw_type, raw_type)}
    options = parameter.get("options")
    if isinstance(options, list):
        values = [option for option in options if isinstance(option, str)]
        if values:
            schema["enum"] = values
    return schema


def _value_error(schema: Mapping[str, Any], value: object, path: str) -> str | None:
    raw_type = str(schema.get("type") or "any")
    enum = schema.get("enum")
    if isinstance(enum, list) and enum and value not in enum:
        return f"{path} must be one of {enum}"
    if raw_type in _FILE_TYPES:
        return f"{path} is a file output and cannot be mocked"
    if raw_type == "string":
        return None if isinstance(value, str) else f"{path} must be a string"
    if raw_type in {"number", "integer"}:
        is_number = isinstance(value, int | float) and not isinstance(value, bool)
        return None if is_number else f"{path} must be a number"
    if raw_type == "boolean":
        return None if isinstance(value, bool) else f"{path} must be a boolean"
    if raw_type == "object":
        if not isinstance(value, dict):
            return f"{path} must be an object"
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for key, child in properties.items():
                if key in value and isinstance(child, dict):
                    problem = _value_error(child, value[key], f"{path}.{key}")
                    if problem is not None:
                        return problem
        return None
    if raw_type.startswith("array"):
        if not isinstance(value, list):
            return f"{path} must be an array"
        item_schema = schema.get("items")
        if not isinstance(item_schema, dict):
            item_type = _ARRAY_ITEM_TYPES.get(raw_type)
            item_schema = {"type": item_type} if item_type else None
        if item_schema is not None:
            for index, element in enumerate(value):
                problem = _value_error(item_schema, element, f"{path}[{index}]")
                if problem is not None:
                    return problem
        return None
    return None


def _code_output_type(value: object) -> str | None:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        kinds = {_code_output_type(item) for item in value}
        if not kinds:
            return "array[object]"
        if len(kinds) == 1:
            kind = next(iter(kinds))
            if kind in {"string", "number", "object", "boolean"}:
                return f"array[{kind}]"
    return None


def _placeholder(schema: Mapping[str, Any], depth: int) -> object:
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return deepcopy(enum[0])
    raw_type = str(schema.get("type") or "any")
    if raw_type in {"number", "integer"}:
        return 0
    if raw_type == "boolean":
        return False
    if raw_type == "object":
        properties = schema.get("properties")
        if not isinstance(properties, dict) or depth >= _PLACEHOLDER_DEPTH:
            return {}
        return {
            str(key): _placeholder(child, depth + 1)
            for key, child in properties.items()
            if isinstance(child, dict) and str(child.get("type") or "") not in _FILE_TYPES
        }
    if raw_type.startswith("array"):
        return []
    return "mock"


def _fixed_output_node(node: MinimalGraphNodeDict, outputs: Mapping[str, object]) -> MinimalGraphNodeDict:
    data = node.get("data") or {}
    replaced = deepcopy(node)
    replaced["data"] = {
        **{key: deepcopy(data[key]) for key in _SCOPE_KEYS if key in data},
        "type": "code",
        "title": str(data.get("title") or node["id"]),
        "desc": "Assist mock",
        "code_language": "python3",
        "code": _fixture_code(outputs),
        "variables": [],
        "outputs": {name: {"type": _code_output_type(value), "children": None} for name, value in outputs.items()},
    }
    return replaced


def _fixture_code(outputs: Mapping[str, object]) -> str:
    literal = json.dumps(json.dumps(dict(outputs), ensure_ascii=False), ensure_ascii=False)
    return f"import json\n\n\ndef main() -> dict:\n    return json.loads({literal})\n"


def _ancestors(edges: list[MinimalGraphEdgeDict], node_id: str) -> set[str]:
    parents: dict[str, set[str]] = {}
    for edge in edges:
        parents.setdefault(edge["target"], set()).add(edge["source"])
    seen: set[str] = set()
    queue = deque([node_id])
    while queue:
        for parent in parents.get(queue.popleft(), set()):
            if parent not in seen:
                seen.add(parent)
                queue.append(parent)
    seen.discard(node_id)
    return seen


def _topological_order(node_ids: list[str], edges: list[MinimalGraphEdgeDict]) -> list[str]:
    indegree = dict.fromkeys(node_ids, 0)
    children: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        if edge["source"] in children and edge["target"] in indegree:
            children[edge["source"]].append(edge["target"])
            indegree[edge["target"]] += 1
    ready = [node_id for node_id in node_ids if indegree[node_id] == 0]
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for child in children[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    return order


def _instruction_excerpt(data: Mapping[str, Any]) -> str:
    template = data.get("prompt_template")
    if isinstance(template, list):
        text = "\n".join(str(item.get("text") or "") for item in template if isinstance(item, dict))
    elif isinstance(template, dict):
        text = str(template.get("text") or "")
    else:
        text = str(data.get("instruction") or "")
    return text.strip()[:_EXCERPT_CHARS]


def _consumers(graph: MinimalGraphDict, node_id: str) -> list[dict[str, object]]:
    pattern = re.compile(r"\{\{#" + re.escape(node_id) + r"\.([^#]+)#\}\}")
    consumers: list[dict[str, object]] = []
    for node in graph["nodes"]:
        if node["id"] == node_id:
            continue
        data = node.get("data") or {}
        uses = sorted(_references(data, node_id, pattern))
        if not uses:
            continue
        entry: dict[str, object] = {"node_id": node["id"], "type": _node_type(node), "uses": uses}
        conditions = _branch_conditions(data, node_id)
        if conditions:
            entry["conditions"] = conditions
        consumers.append(entry)
    return consumers


def _references(value: object, node_id: str, pattern: re.Pattern[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        found.update(match.group(1) for match in pattern.finditer(value))
    elif isinstance(value, list):
        if len(value) >= 2 and value[0] == node_id and all(isinstance(part, str) for part in value):
            found.add(".".join(value[1:]))
        else:
            for item in value:
                found |= _references(item, node_id, pattern)
    elif isinstance(value, dict):
        for item in value.values():
            found |= _references(item, node_id, pattern)
    return found


def _branch_conditions(data: Mapping[str, Any], node_id: str) -> list[dict[str, object]]:
    conditions: list[dict[str, object]] = []
    for case in data.get("cases") or []:
        if not isinstance(case, dict):
            continue
        for condition in case.get("conditions") or []:
            if not isinstance(condition, dict):
                continue
            selector = condition.get("variable_selector")
            if isinstance(selector, list) and selector[:1] == [node_id]:
                conditions.append(
                    {
                        "case_id": case.get("case_id"),
                        "selector": selector,
                        "operator": condition.get("comparison_operator"),
                        "value": condition.get("value"),
                    }
                )
    return conditions
