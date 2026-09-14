"""Assemble compiled children and edges into one temporary atomic container replacement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, cast

from core.workflow.generator.compiler.container_children import _canonical_container_data
from core.workflow.generator.compiler.container_scope import (
    IterationCompilePolicy,
    _break_var_type,
    _validate_declared_outputs,
)
from core.workflow.generator.compiler.container_selectors import _rewrite_labels, _rewrite_selector, _rewrite_value
from core.workflow.generator.compiler.container_types import (
    CompiledChild,
    ContainerCompileError,
    ContainerCompileRequest,
)
from core.workflow.generator.compiler.intents.container_intent import (
    IterationBuildIntent,
    LoopBuildIntent,
)
from core.workflow.generator.graph.container_nodes import resolve_container_start_node_id
from core.workflow.generator.graph.graph_ops import (
    ContainerReplaceError,
    find_node,
    replace_container_subgraph,
    upsert_node,
)
from core.workflow.generator.graph.graph_postprocessor import GraphPostprocessor
from core.workflow.generator.graph.types import MinimalGraphDict, MinimalGraphEdgeDict, MinimalGraphNodeDict
from core.workflow.generator.variables.variable_registry import (
    VariableRegistry,
)
from core.workflow.generator.variables.variable_types import (
    canonical_value_type as _canonical_value_type,
)


def assemble_container_graph(
    request: ContainerCompileRequest,
    children: Sequence[CompiledChild],
    ref_map: Mapping[str, str],
    layers: Sequence[Sequence[str]],
    registry: VariableRegistry | None = None,
) -> MinimalGraphDict:
    labels = _rewrite_labels(request)
    start_id = resolve_container_start_node_id(node_id=request.container_id, data={})
    start = GraphPostprocessor._synthetic_start_node(
        container_id=request.container_id,
        start_id=start_id,
        is_iteration=request.kind == "iteration",
    )
    body: list[MinimalGraphNodeDict] = []
    for compiled in children:
        node = deepcopy(compiled.node)
        node["data"] = _rewrite_value(
            node["data"],
            ref_map=ref_map,
            container_id=request.container_id,
            loop_variable_labels=labels,
        )
        if isinstance(node["data"], dict):
            node["data"]["assist_ref"] = compiled.ref
        body.append(node)
    replacement_nodes = (cast(MinimalGraphNodeDict, start), *body)
    replacement_edges = _assembled_edges(request, ref_map, layers, start_id)
    working = deepcopy(request.frozen_graph)
    if find_node(working, request.container_id) is None:
        working = upsert_node(
            working,
            node_id=request.container_id,
            node_type=request.kind,
            title=request.title or request.container_id,
            desc="",
            config={},
        )
    exposed = _validate_declared_outputs(request, registry, ref_map, labels)
    container = find_node(working, request.container_id)
    if container is None:
        raise ContainerCompileError("NODE_NOT_FOUND", "container missing before assemble", path="id")
    container_data = _canonical_container_data(
        kind=request.kind,
        title=request.title or request.container_id,
        old_data=container["data"],
    )
    try:
        replaced = replace_container_subgraph(
            working,
            container_id=request.container_id,
            replacement_nodes=replacement_nodes,
            replacement_edges=replacement_edges,
            exposed_outputs=exposed,
            container_data=container_data,
        )
    except ContainerReplaceError as exc:
        raise ContainerCompileError(
            "EXTERNAL_REFERENCE_BROKEN",
            str(exc),
            path="outputs",
            cause={"error_code": "EXTERNAL_REFERENCE_BROKEN", "error": str(exc)},
        ) from exc
    if request.kind == "iteration":
        _patch_iteration_config(replaced, request, start_id, labels, ref_map, registry)
    else:
        _patch_loop_config(replaced, request, start_id, labels, ref_map, registry)
    container = find_node(replaced, request.container_id)
    if container is not None:
        kids = [node for node in replaced["nodes"] if node.get("parentId") == request.container_id]
        GraphPostprocessor._size_container_from_children(
            cast(dict[str, Any], container),
            cast(list[dict[str, Any]], kids),
        )
    return replaced


def _assembled_edges(
    request: ContainerCompileRequest,
    ref_map: Mapping[str, str],
    layers: Sequence[Sequence[str]],
    start_id: str,
) -> tuple[MinimalGraphEdgeDict, ...]:
    edges: list[MinimalGraphEdgeDict] = []
    for edge in request.intent.edges:
        payload: MinimalGraphEdgeDict = {"source": ref_map[edge.source], "target": ref_map[edge.target]}
        if edge.source_handle:
            payload["sourceHandle"] = edge.source_handle
        edges.append(payload)
    first_layer = list(layers[0]) if layers else []
    for ref in first_layer:
        edges.append({"source": start_id, "target": ref_map[ref]})
    return tuple(edges)


def _patch_loop_config(
    graph: MinimalGraphDict,
    request: ContainerCompileRequest,
    start_id: str,
    labels: frozenset[str],
    ref_map: Mapping[str, str],
    registry: VariableRegistry | None,
) -> None:
    intent = request.intent
    if not isinstance(intent, LoopBuildIntent):
        raise ContainerCompileError("INVALID_CONTAINER", "loop compile received a non-loop intent", path="id")
    container = find_node(graph, request.container_id)
    if container is None:
        raise ContainerCompileError("NODE_NOT_FOUND", "loop container missing after assemble", path="id")
    if registry is None:
        raise ContainerCompileError("INVALID_CONTAINER", "loop assemble requires a variable registry", path="id")
    data = container["data"]
    data["type"] = "loop"
    if request.title:
        data["title"] = request.title
    data["start_node_id"] = start_id
    data["loop_count"] = intent.loop_count
    data["logical_operator"] = intent.logical_operator
    data["loop_variables"] = [
        {
            "id": item.label,
            "label": item.label,
            "var_type": item.var_type,
            "value_type": item.value_type,
            "value": _rewrite_value(
                item.value,
                ref_map=ref_map,
                container_id=request.container_id,
                loop_variable_labels=labels,
            ),
        }
        for item in intent.loop_variables
    ]
    conditions: list[dict[str, Any]] = []
    for index, item in enumerate(intent.break_conditions):
        selector = _rewrite_selector(
            list(item.variable_selector),
            ref_map=ref_map,
            container_id=request.container_id,
            loop_variable_labels=labels,
        )
        conditions.append(
            {
                "id": item.id,
                "variable_selector": selector,
                "comparison_operator": item.comparison_operator,
                "value": item.value,
                "varType": _break_var_type(
                    selector,
                    request=request,
                    registry=registry,
                    index=index,
                ),
            }
        )
    data["break_conditions"] = conditions
    data.pop("iterator_selector", None)
    data.pop("output_selector", None)
    data.pop("is_parallel", None)
    data.pop("parallel_nums", None)


def _patch_iteration_config(
    graph: MinimalGraphDict,
    request: ContainerCompileRequest,
    start_id: str,
    labels: frozenset[str],
    ref_map: Mapping[str, str],
    registry: VariableRegistry | None,
) -> None:
    intent = request.intent
    if not isinstance(intent, IterationBuildIntent):
        raise ContainerCompileError("INVALID_CONTAINER", "iteration compile received a non-iteration intent", path="id")
    container = find_node(graph, request.container_id)
    if container is None:
        raise ContainerCompileError("NODE_NOT_FOUND", "iteration container missing after assemble", path="id")
    if registry is None:
        raise ContainerCompileError("INVALID_CONTAINER", "iteration assemble requires a variable registry", path="id")
    output_selector = _rewrite_selector(
        list(intent.output_selector),
        ref_map=ref_map,
        container_id=request.container_id,
        loop_variable_labels=labels,
    )
    iterator_selector = _rewrite_selector(
        list(intent.iterator_selector),
        ref_map=ref_map,
        container_id=request.container_id,
        loop_variable_labels=labels,
    )
    output_type = IterationCompilePolicy(request.container_id).validate_terminal_output(
        tuple(output_selector),
        registry,
    )
    data = container["data"]
    data["type"] = "iteration"
    if request.title:
        data["title"] = request.title
    data["start_node_id"] = start_id
    data["iterator_selector"] = iterator_selector
    data["iterator_input_type"] = _canonical_value_type(intent.iterator_input_type)
    data["output_selector"] = output_selector
    data["output_type"] = output_type
    data["is_parallel"] = intent.is_parallel
    data["parallel_nums"] = intent.parallel_nums
    data["error_handle_mode"] = intent.error_handle_mode
    data["flatten_output"] = intent.flatten_output
    data.pop("loop_variables", None)
    data.pop("break_conditions", None)
    data.pop("loop_count", None)
