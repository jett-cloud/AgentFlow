"""Read-only validation entry point for generated graphs."""

from typing import Any, cast

from core.workflow.generator.compiler.tool_parameter_normalize import collect_missing_required_tool_parameters
from core.workflow.generator.resources.tool_catalogue import ToolCatalogueEntry, tool_schema_lookups
from core.workflow.generator.types import (
    GraphDict,
    WorkflowGenerateErrorCode,
    WorkflowGenerateErrorDict,
    WorkflowGenerationMode,
)
from core.workflow.generator.validation.graph_branches import (
    _collect_branch_edge_errors,
    _collect_error_strategy_edge_errors,
    _collect_http_request_edge_errors,
    _collect_human_input_edge_errors,
    _collect_response_node_errors,
    _collect_tool_edge_errors,
)
from core.workflow.generator.validation.graph_containers import _ancestor_ids, _collect_container_errors
from core.workflow.generator.validation.graph_resources import (
    _collect_unknown_dataset_ids,
    _collect_unknown_dify_tools,
    _collect_unknown_tool_parameters,
    _collect_unknown_tools,
)
from core.workflow.generator.validation.graph_topology import (
    _collect_dangling_id_refs,
    _collect_edge_cycle_errors,
    _collect_terminal_bypass_errors,
    _collect_unreachable_node_errors,
)
from core.workflow.generator.validation.graph_validation_values import _CONTAINER_TYPES, _ID_FIELDS, _err
from core.workflow.generator.validation.node_config_validator import (
    collect_generated_node_completeness_errors,
    collect_node_config_errors,
)
from core.workflow.generator.variables.reference_availability import collect_reference_availability_errors
from core.workflow.generator.variables.variable_references import VariableReferences
from core.workflow.generator.variables.variable_types import is_array_type
from graphon.enums import BuiltinNodeTypes


def _validate_structure(
    *,
    graph: GraphDict,
    mode: WorkflowGenerationMode,
    installed_tools: set[tuple[str, str]] | None = None,
    installed_dataset_ids: set[str] | None = None,
    environment_variables: set[str] | None = None,
    conversation_variables: set[str] | None = None,
    tool_entries: list[ToolCatalogueEntry] | None = None,
    tool_parameter_names: dict[tuple[str, str], frozenset[str]] | None = None,
    tool_output_names: dict[tuple[str, str], frozenset[str]] | None = None,
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
        point at a node which does NOT declare the variable. Nested
        selectors (``[iter_id, "item", "field"]``) resolve against the
        output basename; iteration ``item`` and ``index`` are legal only
        from descendant nodes; loop exposes ``loop_variables`` labels;
      * tool nodes naming a ``(provider, tool)`` pair the tenant hasn't
        installed.
      * human-input edges whose source handle is neither a declared action
        id nor the reserved ``__timeout`` handle.
      * knowledge-retrieval nodes without dataset ids, or naming ids absent
        from the tenant knowledge catalogue.
      * code-node ``outputs`` names/types and end-node output shape
        (``variable``, ``value_selector``, ``value_type``);
      * Agent v2 node shape (``version=2``, ``dify_agent``, non-empty
        ``agent_task``, model, inline ``binding_type``, declared outputs).
        Binding ids are checked after hydrate, not here.
    """
    errors: list[WorkflowGenerateErrorDict] = []
    if tool_entries is not None:
        tool_parameter_names, tool_output_names = tool_schema_lookups(tool_entries)

    # JSON from model/HTTP boundaries is not guaranteed by TypedDict casts.
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        return [_err(WorkflowGenerateErrorCode.INVALID_SCHEMA, "graph.nodes must be a list")]
    for index, node in enumerate(graph["nodes"]):
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("id"), str)
            or not node["id"].strip()
            or not isinstance(node.get("data"), dict)
            or not isinstance(node["data"].get("type"), str)
        ):
            errors.append(_err(WorkflowGenerateErrorCode.INVALID_SCHEMA, f"nodes[{index}] requires id and typed data"))
    edges = graph.get("edges", [])
    if not isinstance(edges, list):
        errors.append(_err(WorkflowGenerateErrorCode.INVALID_SCHEMA, "graph.edges must be a list"))
    else:
        for index, edge in enumerate(edges):
            if not isinstance(edge, dict) or not all(isinstance(edge.get(k), str) for k in ("source", "target")):
                errors.append(_err(WorkflowGenerateErrorCode.INVALID_SCHEMA, f"edges[{index}] requires source/target"))
    if errors:
        return errors

    config_errors = collect_node_config_errors(graph["nodes"])
    errors.extend(config_errors)
    errors.extend(collect_generated_node_completeness_errors(graph["nodes"]))

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

    errors.extend(_collect_response_node_errors(nodes=nodes, edges=graph.get("edges", []), mode=mode))

    # Workflow graphs must be DAGs — a directed cycle hangs or errors the
    # run, and nothing downstream of the cycle ever executes. (A "loop"
    # container is the sanctioned way to iterate; its edges are internal.)
    errors.extend(_collect_edge_cycle_errors(graph=graph, known_ids=known_ids))
    errors.extend(_collect_unreachable_node_errors(nodes=nodes, graph=graph))
    errors.extend(_collect_terminal_bypass_errors(nodes=nodes, graph=graph, mode=mode))

    # Dangling node-id references in node ``data`` (parentId, start_node_id, iteration_id, loop_id).
    errors.extend(_collect_dangling_id_refs(nodes=nodes, known_ids=known_ids))

    # Container topology.
    errors.extend(_collect_container_errors(nodes=nodes))
    errors.extend(_collect_branch_edge_errors(nodes=nodes, edges=graph.get("edges", [])))
    errors.extend(_collect_human_input_edge_errors(nodes=nodes, edges=graph.get("edges", [])))
    errors.extend(_collect_http_request_edge_errors(nodes=nodes, edges=graph.get("edges", [])))
    errors.extend(_collect_tool_edge_errors(nodes=nodes, edges=graph.get("edges", [])))
    errors.extend(_collect_document_extractor_input_type_errors(nodes=nodes))
    errors.extend(_collect_iteration_iterator_type_errors(nodes=nodes))
    errors.extend(_collect_loop_variable_selector_type_errors(nodes=nodes))

    # Tool catalogue check — only run if the caller wired in a catalogue.
    if installed_tools is not None:
        errors.extend(_collect_unknown_tools(nodes=nodes, installed_tools=installed_tools))

    # Knowledge catalogue check — an absent catalogue means the caller did
    # not provide one, while an empty set means its non-empty prompt had no
    # valid entries and therefore no dataset id is permitted.
    errors.extend(_collect_unknown_dataset_ids(nodes=nodes, installed_dataset_ids=installed_dataset_ids))

    # Variable-reference resolution — walks ``{{#node.var#}}`` placeholders
    # and value selectors and flags anything pointing at a node that
    # doesn't declare the variable. Start-node refs are auto-fixed
    # earlier in postprocess, so anything that survives to here is
    # genuinely unresolvable.
    errors.extend(
        _collect_unresolved_refs(
            nodes=nodes,
            mode=mode,
            environment_variables=environment_variables,
            conversation_variables=conversation_variables,
            tool_output_names=tool_output_names,
        )
    )
    errors.extend(_collect_parameter_extractor_query_errors(nodes=nodes))
    errors.extend(_collect_unknown_tool_parameters(nodes=nodes, tool_parameter_names=tool_parameter_names))
    errors.extend(collect_missing_required_tool_parameters(nodes, tool_entries))
    if not any(e["code"] in {"GRAPH_CYCLE", "DANGLING_EDGE", "INVALID_CONTAINER"} for e in errors):
        errors.extend(collect_reference_availability_errors(graph))

    return errors


def _collect_document_extractor_input_type_errors(*, nodes: list[dict[str, Any]]) -> list[WorkflowGenerateErrorDict]:
    """Reject Document Extractors wired to non-file Start inputs.

    This is a cross-node semantic check, so the Document Extractor's own
    Pydantic schema cannot enforce it. Missing selectors and unknown
    variables remain the responsibility of node-config and unresolved-ref
    validation; this method reports only an existing variable with an
    incompatible type and never mutates the graph.
    """
    start_variables: dict[str, dict[str, dict[str, Any]]] = {}
    for node in nodes:
        data = node.get("data") or {}
        node_id = node.get("id")
        if data.get("type") != BuiltinNodeTypes.START or not isinstance(node_id, str):
            continue
        variables = data.get("variables")
        if not isinstance(variables, list):
            continue
        start_variables[node_id] = {
            variable["variable"]: variable
            for variable in variables
            if isinstance(variable, dict) and isinstance(variable.get("variable"), str)
        }

    errors: list[WorkflowGenerateErrorDict] = []
    for node in nodes:
        data = node.get("data") or {}
        if data.get("type") != BuiltinNodeTypes.DOCUMENT_EXTRACTOR:
            continue
        selector = data.get("variable_selector")
        if not isinstance(selector, list) or len(selector) != 2:
            continue
        source_id, variable_name = selector
        if not isinstance(source_id, str) or not isinstance(variable_name, str):
            continue
        variable = start_variables.get(source_id, {}).get(variable_name)
        if variable is None:
            continue
        variable_type = variable.get("type")
        if variable_type in {"file", "file-list"}:
            continue
        errors.append(
            _err(
                WorkflowGenerateErrorCode.INVALID_NODE_CONFIG,
                f"Document Extractor input {source_id}.{variable_name} has type {variable_type!r}; "
                "expected 'file' or 'file-list'",
                node_id=str(node.get("id") or ""),
            )
        )
    return errors


def _collect_iteration_iterator_type_errors(*, nodes: list[dict[str, Any]]) -> list[WorkflowGenerateErrorDict]:
    """Reject Iteration nodes whose iterator_selector is not an array variable."""
    errors: list[WorkflowGenerateErrorDict] = []
    for node in nodes:
        data = node.get("data") or {}
        if data.get("type") != BuiltinNodeTypes.ITERATION:
            continue
        selector = data.get("iterator_selector")
        input_type = VariableReferences.selector_type(nodes, selector)
        if not input_type or is_array_type(str(input_type)):
            continue
        source = ".".join(str(part) for part in selector) if isinstance(selector, list) else ""
        errors.append(
            _err(
                WorkflowGenerateErrorCode.INVALID_NODE_CONFIG,
                (f"Iteration iterator {source} has type {input_type!r}; expected an array variable"),
                node_id=str(node.get("id") or ""),
            )
        )
    return errors


def _collect_loop_variable_selector_type_errors(*, nodes: list[dict[str, Any]]) -> list[WorkflowGenerateErrorDict]:
    """Reject Loop variable selectors whose resolved type does not match var_type."""
    errors: list[WorkflowGenerateErrorDict] = []
    for node in nodes:
        data = node.get("data") or {}
        if data.get("type") != BuiltinNodeTypes.LOOP:
            continue
        for item in data.get("loop_variables") or []:
            if not isinstance(item, dict) or item.get("value_type") != "variable":
                continue
            selector = item.get("value")
            actual = VariableReferences.selector_type(nodes, selector)
            declared = str(item.get("var_type") or "")
            if not actual or not declared or actual == declared:
                continue
            source = ".".join(str(part) for part in selector) if isinstance(selector, list) else ""
            errors.append(
                _err(
                    WorkflowGenerateErrorCode.INVALID_NODE_CONFIG,
                    f"Loop variable {source} has type {actual!r}; expected {declared!r}",
                    node_id=str(node.get("id") or ""),
                )
            )
    return errors


def _collect_parameter_extractor_query_errors(*, nodes: list[dict[str, Any]]) -> list[WorkflowGenerateErrorDict]:
    """Parameter-extractor ``query`` is one value selector, not a list of them."""
    out: list[WorkflowGenerateErrorDict] = []
    for node in nodes:
        data = node.get("data") or {}
        if data.get("type") != BuiltinNodeTypes.PARAMETER_EXTRACTOR:
            continue
        query = data.get("query")
        if VariableReferences._is_multi_wrapped_selectors(query):
            out.append(
                _err(
                    WorkflowGenerateErrorCode.INVALID_SCHEMA,
                    f"Parameter-extractor node {node.get('id')!r} query must be a single value selector",
                    node_id=str(node.get("id") or ""),
                )
            )
    return out


def _collect_unresolved_refs(
    *,
    nodes: list[dict[str, Any]],
    mode: WorkflowGenerationMode,
    environment_variables: set[str] | None = None,
    conversation_variables: set[str] | None = None,
    tool_output_names: dict[tuple[str, str], frozenset[str]] | None = None,
) -> list[WorkflowGenerateErrorDict]:
    """
    Walk every variable reference and flag anything pointing at a node
    that doesn't declare it, or at a nested-container-private node.
    ``environment_variables`` / ``conversation_variables`` of ``None``
    mean that side failed to load (skip membership). An empty set means
    the draft really has none.
    """
    out: list[WorkflowGenerateErrorDict] = []
    by_id: dict[str, dict[str, Any]] = {n.get("id", ""): n for n in nodes if n.get("id")}
    sys_names = VariableReferences.system_variable_names(mode)

    for node in nodes:
        refs: set[tuple[str, str]] = set()
        VariableReferences._collect_refs_in_data(node.get("data") or {}, refs)
        ancestors = _ancestor_ids(node, by_id)
        raw_referrer_id = node.get("id")
        referrer_id = raw_referrer_id if isinstance(raw_referrer_id, str) else ""
        for node_id, var in refs:
            base = var.split(".", 1)[0]
            if node_id == "sys":
                if base not in sys_names:
                    out.append(
                        _err(
                            WorkflowGenerateErrorCode.UNRESOLVED_REFERENCE,
                            f"Reference {{#{node_id}.{var}#}} not declared on node {node_id!r}",
                            node_id=node_id,
                        )
                    )
                continue
            if node_id == "env":
                if environment_variables is None:
                    continue
                if base not in environment_variables:
                    out.append(
                        _err(
                            WorkflowGenerateErrorCode.UNRESOLVED_REFERENCE,
                            f"Reference {{#{node_id}.{var}#}} not declared on node {node_id!r}",
                            node_id=node_id,
                        )
                    )
                continue
            if node_id == "conversation":
                if conversation_variables is None:
                    continue
                if base not in conversation_variables:
                    out.append(
                        _err(
                            WorkflowGenerateErrorCode.UNRESOLVED_REFERENCE,
                            f"Reference {{#{node_id}.{var}#}} not declared on node {node_id!r}",
                            node_id=node_id,
                        )
                    )
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
            if not _target_visible_to_referrer(referrer_id, target, by_id):
                out.append(
                    _err(
                        WorkflowGenerateErrorCode.UNRESOLVED_REFERENCE,
                        f"Reference {{#{node_id}.{var}#}} not declared on node {node_id!r}",
                        node_id=node_id,
                    )
                )
                continue
            if VariableReferences._declares_variable(
                target,
                var,
                ancestor_ids=ancestors,
                nodes_by_id=by_id,
                tool_output_names=tool_output_names,
            ):
                continue
            out.append(
                _err(
                    WorkflowGenerateErrorCode.UNRESOLVED_REFERENCE,
                    f"Reference {{#{node_id}.{var}#}} not declared on node {node_id!r}",
                    node_id=node_id,
                )
            )
    return out


def _target_visible_to_referrer(
    referrer_id: str,
    target: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
) -> bool:
    """Inner-container nodes are private to that container and its descendants."""
    parent = (target.get("data") or {}).get("parentId") or target.get("parentId")
    if not isinstance(parent, str) or not parent:
        return True
    if referrer_id == parent:
        return True
    referrer = by_id.get(referrer_id)
    if referrer is None:
        return False
    return parent in _ancestor_ids(referrer, by_id)


def validate_graph(
    *,
    graph: GraphDict,
    mode: WorkflowGenerationMode,
    installed_tools: set[tuple[str, str]] | None = None,
    installed_dataset_ids: set[str] | None = None,
    environment_variables: set[str] | None = None,
    conversation_variables: set[str] | None = None,
    tool_entries: list[ToolCatalogueEntry] | None = None,
    tool_parameter_names: dict[tuple[str, str], frozenset[str]] | None = None,
    tool_output_names: dict[tuple[str, str], frozenset[str]] | None = None,
) -> list[WorkflowGenerateErrorDict]:
    return _validate_structure(
        graph=graph,
        mode=mode,
        installed_tools=installed_tools,
        installed_dataset_ids=installed_dataset_ids,
        environment_variables=environment_variables,
        conversation_variables=conversation_variables,
        tool_entries=tool_entries,
        tool_parameter_names=tool_parameter_names,
        tool_output_names=tool_output_names,
    )


class GraphValidator:
    """Compatibility surface for existing callers; rules are implemented in focused modules."""

    _CONTAINER_TYPES = _CONTAINER_TYPES
    _ID_FIELDS = _ID_FIELDS
    _validate_structure = staticmethod(_validate_structure)
    _collect_response_node_errors = staticmethod(_collect_response_node_errors)
    _collect_document_extractor_input_type_errors = staticmethod(_collect_document_extractor_input_type_errors)
    _collect_iteration_iterator_type_errors = staticmethod(_collect_iteration_iterator_type_errors)
    _collect_loop_variable_selector_type_errors = staticmethod(_collect_loop_variable_selector_type_errors)
    _collect_edge_cycle_errors = staticmethod(_collect_edge_cycle_errors)
    _collect_unreachable_node_errors = staticmethod(_collect_unreachable_node_errors)
    _collect_dangling_id_refs = staticmethod(_collect_dangling_id_refs)
    _collect_container_errors = staticmethod(_collect_container_errors)
    _collect_unknown_tools = staticmethod(_collect_unknown_tools)
    _collect_unknown_dify_tools = staticmethod(_collect_unknown_dify_tools)
    _collect_human_input_edge_errors = staticmethod(_collect_human_input_edge_errors)
    _collect_error_strategy_edge_errors = staticmethod(_collect_error_strategy_edge_errors)
    _collect_http_request_edge_errors = staticmethod(_collect_http_request_edge_errors)
    _collect_tool_edge_errors = staticmethod(_collect_tool_edge_errors)
    _collect_branch_edge_errors = staticmethod(_collect_branch_edge_errors)
    _collect_unknown_dataset_ids = staticmethod(_collect_unknown_dataset_ids)
    _collect_parameter_extractor_query_errors = staticmethod(_collect_parameter_extractor_query_errors)
    _collect_unresolved_refs = staticmethod(_collect_unresolved_refs)
    _collect_unknown_tool_parameters = staticmethod(_collect_unknown_tool_parameters)
    _target_visible_to_referrer = staticmethod(_target_visible_to_referrer)
    _ancestor_ids = staticmethod(_ancestor_ids)
