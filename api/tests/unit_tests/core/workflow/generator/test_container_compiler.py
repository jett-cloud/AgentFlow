import pytest

from core.workflow.generator.compiler.container_compiler import topological_layers
from core.workflow.generator.compiler.container_scope import IterationCompilePolicy, build_container_registry
from core.workflow.generator.compiler.container_selectors import allocate_child_ids, rewrite_selectors
from core.workflow.generator.compiler.container_types import ContainerCompileRequest
from core.workflow.generator.compiler.intents.container_intent import (
    ContainerEdgeIntent,
    StandardContainerChildIntent,
    ToolContainerChildIntent,
    parse_iteration_build_intent,
    parse_loop_build_intent,
)
from core.workflow.generator.variables.variable_registry import VariableResolutionError


def _tool_child(ref: str) -> dict[str, object]:
    return {
        "kind": "tool",
        "ref": ref,
        "intent": {
            "binding": {"provider_name": "image/provider", "tool_name": "generate"},
            "arguments": {"prompt": {"kind": "constant", "value": "draw"}},
        },
    }


def _request(*, children: list[object], existing_ids: dict[str, str] | None = None) -> ContainerCompileRequest:
    intent = parse_loop_build_intent(
        {
            "loop_count": 3,
            "loop_variables": [{"label": "acc", "var_type": "string", "value_type": "constant", "value": ""}],
            "children": children,
            "edges": [{"source": "fetch", "target": "write"}] if len(children) >= 2 else [],
            "break_conditions": [
                {"id": "c1", "variable_selector": ["acc"], "comparison_operator": "is", "value": "done"}
            ],
            "outputs": [{"name": "acc", "type": "string"}],
        }
    )
    return ContainerCompileRequest(
        kind="loop",
        container_id="loop1",
        intent=intent,
        frozen_graph={"nodes": [], "edges": [], "viewport": {"x": 0.0, "y": 0.0, "zoom": 0.7}},
        base_revision=0,
        existing_child_ids=existing_ids or {},
        tool_entries=(),
        knowledge_entries=(),
        installed_tools=None,
        generation_mode="workflow",
    )


def test_allocate_child_ids_uses_container_ref_and_reuses_stored_ids() -> None:
    request = _request(
        children=[_tool_child("fetch"), _tool_child("write")],
        existing_ids={"fetch": "loop1_old_fetch"},
    )

    ref_map = allocate_child_ids(request)

    assert ref_map["fetch"] == "loop1_old_fetch"
    assert ref_map["write"] == "loop1_write"


def test_topological_layers_put_independent_children_together() -> None:
    children = [
        ToolContainerChildIntent.model_validate(_tool_child("a")),
        ToolContainerChildIntent.model_validate(_tool_child("b")),
        StandardContainerChildIntent.model_validate(
            {
                "kind": "standard",
                "ref": "join",
                "node_type": "assigner",
                "intent": {"objective": "Join", "inputs": [{"source": ["a", "text"], "role": "acc"}]},
            }
        ),
    ]
    edges = [
        ContainerEdgeIntent(source="a", target="join"),
        ContainerEdgeIntent(source="b", target="join"),
    ]

    layers = topological_layers(children, edges)

    assert layers[0] == ["a", "b"] or set(layers[0]) == {"a", "b"}
    assert layers[1] == ["join"]


def test_rewrite_selectors_maps_child_refs_and_bare_loop_labels() -> None:
    rewritten = rewrite_selectors(
        [
            ["fetch", "text"],
            ["acc"],
            ["start", "query"],
        ],
        ref_map={"fetch": "loop1_fetch"},
        container_id="loop1",
        loop_variable_labels=frozenset({"acc"}),
    )

    assert rewritten == [
        ["loop1_fetch", "text"],
        ["loop1", "acc"],
        ["start", "query"],
    ]


def _iteration_request(
    *, children: list[object], existing_ids: dict[str, str] | None = None
) -> ContainerCompileRequest:
    intent = parse_iteration_build_intent(
        {
            "iterator_selector": ["start", "images"],
            "iterator_input_type": "array[file]",
            "output_selector": [
                str(children[0]["ref"]) if children and isinstance(children[0], dict) else "fetch",
                "file",
            ],
            "children": children,
            "edges": [],
            "outputs": [{"name": "output", "type": "array[file]"}],
            "is_parallel": True,
            "parallel_nums": 4,
        }
    )
    return ContainerCompileRequest(
        kind="iteration",
        container_id="iter1",
        intent=intent,
        frozen_graph={"nodes": [], "edges": [], "viewport": {"x": 0.0, "y": 0.0, "zoom": 0.7}},
        base_revision=0,
        existing_child_ids=existing_ids or {},
        tool_entries=(),
        knowledge_entries=(),
        installed_tools=None,
        generation_mode="workflow",
    )


def test_iteration_allocate_child_ids_uses_container_ref() -> None:
    request = _iteration_request(
        children=[_tool_child("fetch"), _tool_child("write")],
        existing_ids={"fetch": "iter1_old_fetch"},
    )

    ref_map = allocate_child_ids(request)

    assert ref_map["fetch"] == "iter1_old_fetch"
    assert ref_map["write"] == "iter1_write"


def test_iteration_layers_stay_topological_when_parallel_is_enabled() -> None:
    children = [
        ToolContainerChildIntent.model_validate(_tool_child("a")),
        ToolContainerChildIntent.model_validate(_tool_child("b")),
        StandardContainerChildIntent.model_validate(
            {
                "kind": "standard",
                "ref": "join",
                "node_type": "assigner",
                "intent": {"objective": "Join", "inputs": [{"source": ["a", "text"], "role": "acc"}]},
            }
        ),
    ]
    edges = [
        ContainerEdgeIntent(source="a", target="join"),
        ContainerEdgeIntent(source="b", target="join"),
    ]
    request = _iteration_request(children=[_tool_child("a"), _tool_child("b")])

    layers = topological_layers(children, edges)

    assert request.intent.is_parallel is True
    assert layers[0] == ["a", "b"] or set(layers[0]) == {"a", "b"}
    assert layers[1] == ["join"]


def test_iteration_policy_seeds_private_item_and_index() -> None:
    intent = parse_iteration_build_intent(
        {
            "iterator_selector": ["start", "images"],
            "iterator_input_type": "array[file]",
            "output_selector": ["worker", "file"],
            "children": [_tool_child("worker")],
        }
    )
    policy = IterationCompilePolicy(container_id="iter1")

    seeded = {item.selector: item for item in policy.seed_scope(intent)}

    assert seeded[("iter1", "item")].value_type == "file"
    assert seeded[("iter1", "index")].value_type == "number"
    assert seeded[("iter1", "item")].owner_container_id == "iter1"
    assert seeded[("iter1", "index")].owner_container_id == "iter1"


def test_iteration_registry_exposes_declared_object_item_children() -> None:
    child = StandardContainerChildIntent.model_validate(
        {
            "kind": "standard",
            "ref": "reader",
            "node_type": "template-transform",
            "intent": {
                "objective": "Read question",
                "inputs": [{"source": ["iter1", "item", "question"], "role": "question"}],
                "outputs": [{"name": "output", "type": "string"}],
            },
        }
    )
    intent = parse_iteration_build_intent(
        {
            "iterator_selector": ["parse", "cases"],
            "iterator_input_type": "array[object]",
            "output_selector": ["reader", "output"],
            "children": [child.model_dump(mode="python")],
            "outputs": [{"name": "output", "type": "array[string]"}],
        }
    )
    request = ContainerCompileRequest(
        kind="iteration",
        container_id="iter1",
        intent=intent,
        frozen_graph={
            "nodes": [
                {
                    "id": "parse",
                    "data": {
                        "type": "code",
                        "outputs": {
                            "cases": {
                                "type": "array[object]",
                                "children": {"question": {"type": "string", "children": None}},
                            }
                        },
                    },
                }
            ],
            "edges": [],
            "viewport": {"x": 0.0, "y": 0.0, "zoom": 1.0},
        },
        base_revision=0,
        existing_child_ids={},
        tool_entries=(),
        knowledge_entries=(),
        installed_tools=None,
        generation_mode="workflow",
    )

    registry = build_container_registry(request, {"reader": "iter1_reader"}, [["reader"]])

    declaration = registry.resolve(
        ("iter1", "item", "question"),
        referrer_id="iter1_reader",
        expected_type="string",
    )
    assert declaration.value_type == "string"


def test_iteration_registry_rejects_undeclared_object_item_child() -> None:
    request = _iteration_request(children=[_tool_child("worker")])
    request = ContainerCompileRequest(
        **{
            **request.__dict__,
            "intent": parse_iteration_build_intent(
                {
                    "iterator_selector": ["start", "images"],
                    "iterator_input_type": "array[file]",
                    "output_selector": ["worker", "file"],
                    "children": [_tool_child("worker")],
                    "outputs": [{"name": "output", "type": "array[file]"}],
                }
            ),
        }
    )
    registry = build_container_registry(request, {"worker": "iter1_worker"}, [["worker"]])

    with pytest.raises(VariableResolutionError) as exc_info:
        registry.resolve(
            ("iter1", "item", "question"),
            referrer_id="iter1_worker",
            expected_type=None,
        )

    assert exc_info.value.code == "UNKNOWN_OUTPUT"


def test_loop_registry_exposes_declared_object_variable_children() -> None:
    intent = parse_loop_build_intent(
        {
            "loop_count": 3,
            "loop_variables": [
                {
                    "label": "state",
                    "var_type": "object",
                    "value_type": "constant",
                    "value": {"count": 0},
                    "children": {"count": {"type": "number"}},
                }
            ],
            "children": [
                {
                    "kind": "standard",
                    "ref": "reader",
                    "node_type": "template-transform",
                    "intent": {
                        "objective": "Read count",
                        "inputs": [{"source": ["loop1", "state", "count"], "role": "count"}],
                        "outputs": [{"name": "output", "type": "string"}],
                    },
                }
            ],
            "outputs": [{"name": "state", "type": "object"}],
        }
    )
    request = ContainerCompileRequest(
        kind="loop",
        container_id="loop1",
        intent=intent,
        frozen_graph={"nodes": [], "edges": [], "viewport": {"x": 0.0, "y": 0.0, "zoom": 1.0}},
        base_revision=0,
        existing_child_ids={},
        tool_entries=(),
        knowledge_entries=(),
        installed_tools=None,
        generation_mode="workflow",
    )

    registry = build_container_registry(request, {"reader": "loop1_reader"}, [["reader"]])

    declaration = registry.resolve(
        ("loop1", "state", "count"),
        referrer_id="loop1_reader",
        expected_type="number",
    )
    assert declaration.value_type == "number"


def test_rewrite_selectors_maps_iteration_child_refs() -> None:
    rewritten = rewrite_selectors(
        [
            ["fetch", "file"],
            ["start", "images"],
        ],
        ref_map={"fetch": "iter1_fetch"},
        container_id="iter1",
        loop_variable_labels=frozenset(),
    )

    assert rewritten == [
        ["iter1_fetch", "file"],
        ["start", "images"],
    ]
