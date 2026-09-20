"""Resolve container variable scope and validate a compiled subgraph before commit."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from core.workflow.generator.compiler.container_selectors import _rewrite_selector
from core.workflow.generator.compiler.container_types import ContainerCompileError, ContainerCompileRequest
from core.workflow.generator.compiler.container_values import _BRANCH_TYPES
from core.workflow.generator.compiler.intents.container_intent import (
    ContainerChildIntent,
    ContainerEdgeIntent,
    IterationBuildIntent,
    LoopBuildIntent,
    StandardContainerChildIntent,
    ToolContainerChildIntent,
)
from core.workflow.generator.graph.types import MinimalGraphDict
from core.workflow.generator.resources.tool_catalogue import ToolCatalogueEntry, find_tool_entry
from core.workflow.generator.types import GraphDict
from core.workflow.generator.validation.graph_validator import validate_graph
from core.workflow.generator.variables.variable_references import VariableReferences
from core.workflow.generator.variables.variable_registry import (
    VariableDeclaration,
    VariableReferrer,
    VariableRegistry,
    VariableResolutionError,
)
from core.workflow.generator.variables.variable_types import (
    aggregate_type,
    array_item_type,
)
from core.workflow.generator.variables.variable_types import (
    canonical_value_type as _canonical_value_type,
)


def _resolution_cause(exc: VariableResolutionError, registry: VariableRegistry) -> dict[str, object]:
    cause: dict[str, object] = {
        "error_code": exc.code,
        "error": exc.detail,
        "selector": list(exc.selector),
    }
    if exc.code in {"UNKNOWN_OUTPUT", "UNKNOWN_TOOL_OUTPUT"} and exc.selector:
        cause["available_outputs"] = list(registry.outputs_for(exc.selector[0]))
    return cause


def iteration_scope_declarations(container_id: str, item_type: str) -> tuple[VariableDeclaration, ...]:
    return (
        VariableDeclaration(
            selector=(container_id, "item"),
            value_type=item_type,
            owner_container_id=container_id,
            producer_layer=0,
            guaranteed=True,
        ),
        VariableDeclaration(
            selector=(container_id, "index"),
            value_type="number",
            owner_container_id=container_id,
            producer_layer=0,
            guaranteed=True,
        ),
    )


class IterationCompilePolicy:
    """Iteration-specific scope and public output aggregation."""

    container_id: str

    def __init__(self, container_id: str) -> None:
        self.container_id = container_id

    def seed_scope(self, intent: IterationBuildIntent) -> tuple[VariableDeclaration, ...]:
        item_type = array_item_type(intent.iterator_input_type)
        return iteration_scope_declarations(self.container_id, item_type)

    def validate_terminal_output(self, selector: tuple[str, ...], registry: VariableRegistry) -> str:
        try:
            declaration = registry.resolve(selector, referrer_id=self.container_id, expected_type=None)
        except VariableResolutionError as exc:
            raise ContainerCompileError(
                exc.code, exc.detail, path="output_selector", cause=_resolution_cause(exc, registry)
            ) from exc
        try:
            return aggregate_type(declaration.value_type)
        except ValueError as exc:
            raise ContainerCompileError("INVALID_NODE_CONFIG", str(exc), path="output_selector") from exc


def validate_compiled_container(
    graph: MinimalGraphDict,
    request: ContainerCompileRequest,
    ref_map: Mapping[str, str],
) -> None:
    baseline_errors = validate_graph(
        graph=cast(GraphDict, request.frozen_graph),
        mode=request.generation_mode,
        installed_tools=request.installed_tools,
        tool_entries=list(request.tool_entries) if request.tool_entries else None,
    )
    baseline_error_keys = {_validation_error_key(item) for item in baseline_errors}
    errors = [
        item
        for item in validate_graph(
            graph=cast(GraphDict, graph),
            mode=request.generation_mode,
            installed_tools=request.installed_tools,
            tool_entries=list(request.tool_entries) if request.tool_entries else None,
        )
        if _validation_error_key(item) not in baseline_error_keys
        and not _is_staged_container_attachment_error(item, request)
    ]
    if errors:
        first = errors[0]
        node_id = str(first.get("node_id") or "")
        child_ref = _ref_for_id(node_id, ref_map)
        raise ContainerCompileError(
            str(first["code"]),
            str(first["detail"]),
            path=f"children.{child_ref}" if child_ref else (f"nodes.{node_id}" if node_id else "graph"),
            child_ref=child_ref,
            cause={"error_code": str(first["code"]), "error": str(first["detail"]), "node_id": node_id},
        )
    if request.kind == "loop":
        _validate_loop_exit(graph, request, ref_map)


def _validation_error_key(error: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(error.get("code") or ""),
        str(error.get("node_id") or ""),
        str(error.get("detail") or ""),
    )


def _is_staged_container_attachment_error(
    error: Mapping[str, Any], request: ContainerCompileRequest
) -> bool:
    """Ignore errors resolved by connecting a newly committed container.

    Node builders commit nodes before separate ``connect`` calls wire the final
    workflow. A newly assembled top-level container follows the same staged
    protocol, so reachability and upstream-availability checks cannot pass
    until after the atomic container commit. Explicit ``validate_graph`` and
    ``finish`` still enforce both invariants once graph construction is complete.
    """
    code = str(error.get("code") or "")
    if str(error.get("node_id") or "") != request.container_id:
        return False
    detail = str(error.get("detail") or "")
    return code == "REFERENCE_NOT_AVAILABLE" or (
        code == "INVALID_SCHEMA" and " is not reachable from start node " in detail
    )


def build_container_registry(
    request: ContainerCompileRequest,
    ref_map: Mapping[str, str],
    layers: Sequence[Sequence[str]],
) -> VariableRegistry:
    layer_by_ref = _layer_index(layers)
    declarations: list[VariableDeclaration] = []
    known: set[str] = {request.container_id, *ref_map, *ref_map.values()}
    descendant_ids = _current_descendant_ids(request.frozen_graph, request.container_id)
    for node in request.frozen_graph["nodes"]:
        node_id = str(node.get("id") or "")
        if not node_id or node_id in descendant_ids or node_id == request.container_id:
            continue
        known.add(node_id)
        declarations.extend(_declarations_for_existing(node, tool_entries=request.tool_entries))
    declarations.extend(_seed_container_scope(request))
    declarations.extend(_iteration_item_child_declarations(request))
    by_ref = {child.ref: child for child in request.intent.children}
    for ref, node_id in ref_map.items():
        producer_layer = layer_by_ref[ref] + 1
        for selector, value_type in _child_output_declarations(by_ref[ref], request.tool_entries):
            path = selector[1:]
            for owner in (ref, node_id):
                declarations.append(
                    VariableDeclaration(
                        selector=(owner, *path) if path else (owner,),
                        value_type=value_type,
                        owner_container_id=request.container_id,
                        producer_layer=producer_layer,
                        guaranteed=True,
                    )
                )
    referrers = [
        VariableReferrer(
            node_id=node_id,
            layer=layer_by_ref[ref] + 1,
            ancestor_container_ids=(request.container_id,),
        )
        for ref, node_id in ref_map.items()
    ]
    referrers.append(
        VariableReferrer(
            node_id=request.container_id,
            layer=max(layer_by_ref.values(), default=0) + 2,
            ancestor_container_ids=(),
            allows_self_variables=True,
        )
    )
    return VariableRegistry(declarations, referrers=referrers, known_node_ids=frozenset(known))


def _validate_loop_exit(
    graph: MinimalGraphDict,
    request: ContainerCompileRequest,
    ref_map: Mapping[str, str],
) -> None:
    intent = request.intent
    if not isinstance(intent, LoopBuildIntent):
        return
    labels = {item.label for item in intent.loop_variables}
    dominated = _dominated_child_refs(intent.children, intent.edges)
    id_to_ref = {node_id: ref for ref, node_id in ref_map.items()}
    by_id = {str(node["id"]): node for node in graph["nodes"]}
    for index, condition in enumerate(intent.break_conditions):
        selector = _rewrite_selector(
            list(condition.variable_selector),
            ref_map=ref_map,
            container_id=request.container_id,
            loop_variable_labels=frozenset(labels),
        )
        source = selector[0]
        output = selector[1] if len(selector) > 1 else ""
        if source == request.container_id and output in labels:
            continue
        source_node = by_id.get(source)
        if source_node is not None and source_node.get("parentId") != request.container_id:
            continue
        child_ref = id_to_ref.get(source)
        if child_ref is None or child_ref not in dominated:
            raise ContainerCompileError(
                "REFERENCE_NOT_AVAILABLE",
                "break condition reads a result that is not produced on every path",
                path=f"break_conditions.{index}",
                child_ref=child_ref,
                cause={
                    "error_code": "REFERENCE_NOT_AVAILABLE",
                    "error": "exit condition is not path-dominated",
                    "selector": selector,
                },
            )


def _dominated_child_refs(
    children: Sequence[ContainerChildIntent],
    edges: Sequence[ContainerEdgeIntent],
) -> set[str]:
    refs = [child.ref for child in children]
    if not refs:
        return set()
    branch_refs = {
        child.ref
        for child in children
        if isinstance(child, StandardContainerChildIntent) and child.node_type in _BRANCH_TYPES
    }
    outgoing: dict[str, dict[str, list[str]]] = {ref: {} for ref in refs}
    incoming: dict[str, int] = dict.fromkeys(refs, 0)
    for edge in edges:
        handle = edge.source_handle or ("true" if edge.source in branch_refs else "")
        outgoing[edge.source].setdefault(handle, []).append(edge.target)
        incoming[edge.target] += 1
    entries = [ref for ref in refs if incoming[ref] == 0]
    paths: list[set[str]] = []

    def walk(current: str, seen: set[str]) -> None:
        next_seen = set(seen)
        next_seen.add(current)
        groups = outgoing[current]
        if current in branch_refs:
            handles = set(groups) | {"true", "false"}
            for handle in handles:
                targets = groups.get(handle, [])
                if not targets:
                    paths.append(next_seen)
                    continue
                for target in targets:
                    if target not in next_seen:
                        walk(target, next_seen)
            return
        successors = [target for bucket in groups.values() for target in bucket]
        if not successors:
            paths.append(next_seen)
            return
        for target in successors:
            if target not in next_seen:
                walk(target, next_seen)

    for entry in entries:
        walk(entry, set())
    if not paths:
        return set(refs)
    dominated = set(paths[0])
    for path in paths[1:]:
        dominated &= path
    return dominated


def _child_output_declarations(
    child: ContainerChildIntent,
    tool_entries: Sequence[ToolCatalogueEntry],
) -> list[tuple[tuple[str, ...], str]]:
    if isinstance(child, ToolContainerChildIntent):
        entry = find_tool_entry(
            list(tool_entries),
            provider_name=child.intent.binding.provider_name,
            tool_name=child.intent.binding.tool_name,
        )
        outputs = entry.get("outputs") if entry is not None else None
        if outputs:
            return [((child.ref, spec["name"]), spec["type"]) for spec in outputs]
        names = entry.get("output_names") if entry is not None else None
        if names:
            raise ContainerCompileError(
                "TOOL_OUTPUT_SCHEMA_UNAVAILABLE",
                "tool output names are known but their types are unavailable",
                path=f"children.{child.ref}",
                child_ref=child.ref,
            )
        return []
    declarations: list[tuple[tuple[str, ...], str]] = []
    for item in child.intent.outputs:
        declarations.append(((child.ref, item.name), item.type or "string"))
        if item.type == "object":
            declarations.extend(
                _intent_child_output_declarations(
                    prefix=(child.ref, item.name),
                    children=item.children,
                )
            )
    return declarations


def _intent_child_output_declarations(
    *,
    prefix: tuple[str, ...],
    children: Mapping[str, Any] | None,
) -> list[tuple[tuple[str, ...], str]]:
    declarations: list[tuple[tuple[str, ...], str]] = []
    for name, child in (children or {}).items():
        child_selector = (*prefix, name)
        declarations.append((child_selector, child.type))
        if child.type == "object":
            declarations.extend(
                _intent_child_output_declarations(prefix=child_selector, children=child.children)
            )
    return declarations


def _declarations_for_existing(
    node: Mapping[str, Any],
    *,
    tool_entries: Sequence[ToolCatalogueEntry],
) -> list[VariableDeclaration]:
    node_id = str(node.get("id") or "")
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    node_type = str((data or {}).get("type") or "")
    if node_type == "iteration":
        return _iteration_existing_declarations(node_id, data or {})
    declarations: list[VariableDeclaration] = []
    if node_type == "tool":
        provider = str((data or {}).get("provider_id") or (data or {}).get("provider_name") or "")
        tool_name = str((data or {}).get("tool_name") or "")
        entry = find_tool_entry(list(tool_entries), provider_name=provider, tool_name=tool_name)
        outputs = entry.get("outputs") if entry is not None else None
        if outputs:
            for spec in outputs:
                declarations.append(
                    VariableDeclaration(
                        selector=(node_id, spec["name"]),
                        value_type=spec["type"],
                        owner_container_id=None,
                        producer_layer=0,
                        guaranteed=True,
                    )
                )
        return declarations
    for name in VariableReferences._declared_outputs(dict(node)):
        schema = VariableReferences._declared_output_schema(dict(node), name)
        raw_type = str(schema.get("type") or "string")
        declarations.append(
            VariableDeclaration(
                selector=(node_id, name),
                value_type=_canonical_value_type(raw_type),
                owner_container_id=None,
                producer_layer=0,
                guaranteed=True,
            )
        )
        declarations.extend(
            _schema_child_declarations(
                prefix=(node_id, name),
                schema=schema,
                owner_container_id=None,
                producer_layer=0,
            )
        )
    return declarations


def _schema_child_declarations(
    *,
    prefix: tuple[str, ...],
    schema: Mapping[str, Any],
    owner_container_id: str | None,
    producer_layer: int,
) -> list[VariableDeclaration]:
    if _canonical_value_type(str(schema.get("type") or "object")).startswith("array"):
        return []
    properties = schema.get("properties")
    if properties is None:
        properties = schema.get("children")
    if not isinstance(properties, Mapping):
        return []
    declarations: list[VariableDeclaration] = []
    for name, raw_child in properties.items():
        if not isinstance(name, str) or not isinstance(raw_child, Mapping):
            continue
        child_schema = dict(raw_child)
        value_type = _canonical_value_type(str(child_schema.get("type") or "object"))
        selector = (*prefix, name)
        declarations.append(
            VariableDeclaration(
                selector=selector,
                value_type=value_type,
                owner_container_id=owner_container_id,
                producer_layer=producer_layer,
                guaranteed=True,
            )
        )
        declarations.extend(
            _schema_child_declarations(
                prefix=selector,
                schema=child_schema,
                owner_container_id=owner_container_id,
                producer_layer=producer_layer,
            )
        )
    return declarations


def _iteration_item_child_declarations(request: ContainerCompileRequest) -> list[VariableDeclaration]:
    intent = request.intent
    if not isinstance(intent, IterationBuildIntent):
        return []
    source_id = intent.iterator_selector[0]
    source = next((node for node in request.frozen_graph["nodes"] if node.get("id") == source_id), None)
    if source is None:
        return []
    schema = VariableReferences._schema_for_variable(
        dict(source),
        ".".join(intent.iterator_selector[1:]),
        {str(node["id"]): dict(node) for node in request.frozen_graph["nodes"] if node.get("id")},
    )
    item_schema = VariableReferences._element_schema(schema)
    return _schema_child_declarations(
        prefix=(request.container_id, "item"),
        schema=item_schema,
        owner_container_id=request.container_id,
        producer_layer=0,
    )


def _validate_declared_outputs(
    request: ContainerCompileRequest,
    registry: VariableRegistry | None,
    ref_map: Mapping[str, str],
    labels: frozenset[str],
) -> frozenset[str]:
    """Validate model-declared outputs against the container's runtime contract."""
    intent = request.intent
    declared_names = [item.name for item in intent.outputs]
    if isinstance(intent, LoopBuildIntent):
        actual = [(item.label, item.var_type) for item in intent.loop_variables]
        if declared_names != [name for name, _value_type in actual]:
            raise ContainerCompileError(
                "INVALID_CONTAINER_OUTPUT",
                "Loop outputs must exactly match loop variable labels",
                path="outputs",
            )
        declared_types = [item.type for item in intent.outputs]
        actual_types = [value_type for _name, value_type in actual]
        if declared_types != actual_types:
            raise ContainerCompileError(
                "VARIABLE_TYPE_MISMATCH",
                "Loop output types must exactly match loop variable types",
                path="outputs",
            )
        return frozenset(name for name, _value_type in actual)

    if declared_names != ["output"]:
        raise ContainerCompileError(
            "INVALID_CONTAINER_OUTPUT",
            "Iteration must declare exactly one output named 'output'",
            path="outputs",
        )
    if registry is None:
        raise ContainerCompileError(
            "INVALID_CONTAINER", "iteration output validation requires a registry", path="outputs"
        )
    output_ref = intent.output_selector[0]
    if output_ref not in _dominated_child_refs(intent.children, intent.edges):
        raise ContainerCompileError(
            "REFERENCE_NOT_AVAILABLE",
            "iteration output is not produced on every branch",
            path="output_selector",
            child_ref=output_ref,
            cause={
                "error_code": "REFERENCE_NOT_AVAILABLE",
                "error": "iteration output is not path-dominated",
                "selector": list(intent.output_selector),
            },
        )
    output_selector = _rewrite_selector(
        list(intent.output_selector),
        ref_map=ref_map,
        container_id=request.container_id,
        loop_variable_labels=labels,
    )
    actual_type = IterationCompilePolicy(request.container_id).validate_terminal_output(
        tuple(output_selector),
        registry,
    )
    if intent.outputs[0].type != actual_type:
        raise ContainerCompileError(
            "VARIABLE_TYPE_MISMATCH",
            f"Iteration output expects {actual_type!r}, got {intent.outputs[0].type!r}",
            path="outputs.0.type",
        )
    return frozenset({"output"})


def _break_var_type(
    selector: Sequence[str],
    *,
    request: ContainerCompileRequest,
    registry: VariableRegistry,
    index: int,
) -> str:
    try:
        declaration = registry.resolve(
            tuple(selector),
            referrer_id=request.container_id,
            expected_type=None,
        )
    except VariableResolutionError as exc:
        raise ContainerCompileError(
            exc.code,
            exc.detail,
            path=f"break_conditions.{index}",
            cause=_resolution_cause(exc, registry),
        ) from exc
    return _canonical_value_type(declaration.value_type)


def _seed_container_scope(request: ContainerCompileRequest) -> tuple[VariableDeclaration, ...]:
    intent = request.intent
    if isinstance(intent, IterationBuildIntent):
        return IterationCompilePolicy(request.container_id).seed_scope(intent)
    declarations: list[VariableDeclaration] = []
    for variable in intent.loop_variables:
        declarations.append(
            VariableDeclaration(
                selector=(request.container_id, variable.label),
                value_type=variable.var_type,
                owner_container_id=request.container_id,
                producer_layer=0,
                guaranteed=True,
            )
        )
        nested = (
            _intent_child_output_declarations(
                prefix=(request.container_id, variable.label),
                children=variable.children,
            )
            if variable.var_type == "object"
            else []
        )
        for selector, value_type in nested:
            declarations.append(
                VariableDeclaration(
                    selector=selector,
                    value_type=value_type,
                    owner_container_id=request.container_id,
                    producer_layer=0,
                    guaranteed=True,
                )
            )
    return tuple(declarations)


def _validate_iterator_selector(request: ContainerCompileRequest, registry: VariableRegistry) -> None:
    """Require the iterator selector to be an array whose kind matches ``iterator_input_type``.

    ``item`` is still seeded from the claimed type. A mismatch must fail here so the
    agent can correct ``iterator_input_type`` instead of compiling ``item`` against a
    different array Graphon will iterate. ``file-list`` and ``array[file]`` are the
    same kind via ``_canonical_value_type``.
    """
    intent = request.intent
    if not isinstance(intent, IterationBuildIntent):
        return
    try:
        declaration = registry.resolve(
            intent.iterator_selector,
            referrer_id=request.container_id,
            expected_type=None,
        )
    except VariableResolutionError as err:
        raise ContainerCompileError(
            err.code, err.detail, path="iterator_selector", cause=_resolution_cause(err, registry)
        ) from err
    resolved_type = _canonical_value_type(declaration.value_type)
    claimed_type = _canonical_value_type(intent.iterator_input_type)
    try:
        array_item_type(resolved_type)
    except ValueError:
        raise ContainerCompileError(
            "INVALID_NODE_CONFIG",
            f"iterator_selector has type {declaration.value_type!r}; expected an array variable",
            path="iterator_selector",
        ) from None
    if resolved_type != claimed_type:
        raise ContainerCompileError(
            "VARIABLE_TYPE_MISMATCH",
            f"期望 {intent.iterator_input_type}，实际 {declaration.value_type}",
            path="iterator_selector",
        )


def _iteration_existing_declarations(node_id: str, data: Mapping[str, Any]) -> list[VariableDeclaration]:
    input_type = _canonical_value_type(str(data.get("iterator_input_type") or "array"))
    try:
        item_type = array_item_type(input_type)
    except ValueError:
        item_type = "object"
    output_type = _canonical_value_type(str(data.get("output_type") or "array"))
    return [
        *iteration_scope_declarations(node_id, item_type),
        VariableDeclaration(
            selector=(node_id, "output"),
            value_type=output_type,
            owner_container_id=None,
            producer_layer=0,
            guaranteed=True,
        ),
    ]


def _current_descendant_ids(graph: MinimalGraphDict, container_id: str) -> set[str]:
    descendants: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in graph["nodes"]:
            node_id = str(node.get("id") or "")
            if not node_id or node_id in descendants or node_id == container_id:
                continue
            parent = node.get("parentId") or (node.get("data") or {}).get("parentId")
            if parent == container_id or parent in descendants:
                descendants.add(node_id)
                changed = True
    return descendants


def _layer_index(layers: Sequence[Sequence[str]]) -> dict[str, int]:
    return {ref: index for index, layer in enumerate(layers) for ref in layer}


def _ref_for_id(node_id: str, ref_map: Mapping[str, str]) -> str | None:
    for ref, mapped in ref_map.items():
        if mapped == node_id:
            return ref
    return None
