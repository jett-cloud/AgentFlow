"""Compile independent children in dependency layers, then assemble one atomic container."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

from configs import dify_config
from core.workflow.generator.compiler.container_assembly import assemble_container_graph
from core.workflow.generator.compiler.container_children import compile_child_with_mechanical_retry
from core.workflow.generator.compiler.container_scope import (
    _child_output_declarations,
    _layer_index,
    _validate_iterator_selector,
    build_container_registry,
    validate_compiled_container,
)
from core.workflow.generator.compiler.container_selectors import allocate_child_ids
from core.workflow.generator.compiler.container_types import (
    ChildCompileContext,
    CompiledChild,
    CompiledContainer,
    ContainerCompileCacheKey,
    ContainerCompileError,
    ContainerCompileRequest,
)
from core.workflow.generator.compiler.container_values import _SENSITIVE_CACHE_MARKERS
from core.workflow.generator.compiler.intents.container_intent import (
    ContainerChildIntent,
    ContainerEdgeIntent,
)


def compile_container_subgraph(request: ContainerCompileRequest) -> CompiledContainer:
    """Compile children, assemble a temp graph, validate, and return it uncommitted."""
    ref_map = allocate_child_ids(request)
    layers = topological_layers(request.intent.children, request.intent.edges)
    registry = build_container_registry(request, ref_map, layers)
    _validate_iterator_selector(request, registry)
    context = ChildCompileContext(
        container_id=request.container_id,
        ref_map=ref_map,
        registry=registry,
        tool_entries=request.tool_entries,
        knowledge_entries=request.knowledge_entries,
        layer_by_ref=_layer_index(layers),
        in_iteration=request.kind == "iteration",
        builder_client=request.builder_client,
        builder_input=request.builder_input,
        frozen_graph=request.frozen_graph,
    )
    by_ref = {child.ref: child for child in request.intent.children}
    intent_layers = tuple(tuple(by_ref[ref] for ref in layer) for layer in layers)
    snapshot_hash = request.resource_snapshot_hash or resource_snapshot_hash(request)

    def compile_child(child: ContainerChildIntent) -> CompiledChild:
        key = ContainerCompileCacheKey(
            container_id=request.container_id,
            child_ref=child.ref,
            resolved_node_id=ref_map[child.ref],
            intent_hash=_intent_hash(child),
            resource_snapshot_hash=snapshot_hash,
            upstream_signature=_upstream_signature(child, request),
        )
        cache = request.compile_cache
        if cache is not None and key in cache:
            return cache[key]
        compiled = compile_child_with_mechanical_retry(child, context)
        if cache is not None and _safe_to_cache(compiled):
            cache[key] = compiled
        return compiled

    children = compile_topological_layers(
        intent_layers,
        compile_child=compile_child,
        max_workers=_configured_compile_workers(),
    )
    graph = assemble_container_graph(request, children, ref_map, layers, registry)
    validate_compiled_container(graph, request, ref_map)
    return CompiledContainer(graph=graph, base_revision=request.base_revision)


def topological_layers(
    children: Sequence[ContainerChildIntent],
    edges: Sequence[ContainerEdgeIntent],
) -> list[list[str]]:
    """Kahn layers. Independent children share a layer; cycles fail closed."""
    order = [child.ref for child in children]
    incoming: dict[str, int] = dict.fromkeys(order, 0)
    outgoing: dict[str, list[str]] = {ref: [] for ref in order}
    for edge in edges:
        if edge.source not in incoming or edge.target not in incoming:
            raise ContainerCompileError(
                "INVALID_CONTAINER",
                "edge references unknown child ref",
                path="edges",
            )
        outgoing[edge.source].append(edge.target)
        incoming[edge.target] += 1
    remaining = dict(incoming)
    layers: list[list[str]] = []
    while remaining:
        ready = [ref for ref in order if remaining.get(ref) == 0]
        if not ready:
            trapped = [ref for ref, count in remaining.items() if count]
            raise ContainerCompileError(
                "GRAPH_CYCLE",
                f"container children contain a cycle: {', '.join(trapped)}",
                path="edges",
                cause={"error_code": "GRAPH_CYCLE", "error": "internal edges form a cycle", "refs": trapped},
            )
        layers.append(ready)
        for ref in ready:
            del remaining[ref]
            for successor in outgoing[ref]:
                if successor in remaining:
                    remaining[successor] -= 1
    return layers


def _configured_compile_workers() -> int:
    return max(1, int(dify_config.WORKFLOW_GENERATOR_NODE_BUILDER_MAX_WORKERS))


def compile_topological_layers(
    layers: Sequence[Sequence[ContainerChildIntent]],
    *,
    compile_child: Callable[[ContainerChildIntent], CompiledChild],
    max_workers: int,
) -> tuple[CompiledChild, ...]:
    """Compile each Kahn layer with a bounded pool; assemble in original child order."""
    compiled: list[CompiledChild] = []
    for layer in layers:
        if not layer:
            continue
        workers = max(1, min(max_workers, len(layer)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="assist-container-compile") as executor:
            futures = [executor.submit(compile_child, child) for child in layer]
            layer_results: list[CompiledChild] = []
            first_error: BaseException | None = None
            for future in futures:
                try:
                    layer_results.append(future.result())
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
            if first_error is not None:
                raise first_error
        compiled.extend(layer_results)
    return tuple(compiled)


def resource_snapshot_hash(request: ContainerCompileRequest) -> str:
    return _stable_hash(
        {
            "tools": [dict(entry) for entry in request.tool_entries],
            "knowledge": [dict(entry) for entry in request.knowledge_entries],
        }
    )


def _intent_hash(child: ContainerChildIntent) -> str:
    return _stable_hash(child.model_dump(mode="json"))


def _upstream_signature(child: ContainerChildIntent, request: ContainerCompileRequest) -> str:
    by_ref = {item.ref: item for item in request.intent.children}
    parts = []
    for edge in request.intent.edges:
        if edge.target != child.ref or edge.source not in by_ref:
            continue
        declarations = _child_output_declarations(by_ref[edge.source], request.tool_entries)
        parts.append(
            {
                "ref": edge.source,
                "outputs": [(list(selector), value_type) for selector, value_type in declarations],
            }
        )
    return _stable_hash(parts)


def _stable_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _safe_to_cache(compiled: CompiledChild) -> bool:
    blob = json.dumps(compiled.node, default=str).lower()
    return not any(marker in blob for marker in _SENSITIVE_CACHE_MARKERS)
