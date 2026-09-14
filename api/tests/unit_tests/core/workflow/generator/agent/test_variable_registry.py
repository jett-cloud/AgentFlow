import pytest

from core.workflow.generator.variables.variable_registry import (
    VariableDeclaration,
    VariableReferrer,
    VariableRegistry,
    VariableResolutionError,
)


def _declaration(
    selector: tuple[str, ...],
    value_type: str,
    *,
    owner_container_id: str | None = None,
    producer_layer: int = 0,
    guaranteed: bool = True,
) -> VariableDeclaration:
    return VariableDeclaration(
        selector=selector,
        value_type=value_type,
        owner_container_id=owner_container_id,
        producer_layer=producer_layer,
        guaranteed=guaranteed,
    )


def _registry() -> VariableRegistry:
    return VariableRegistry(
        declarations=(
            _declaration(("start", "image"), "file", producer_layer=0),
            _declaration(("start", "images"), "array[file]", producer_layer=0),
            _declaration(("tool", "files"), "array[file]", producer_layer=1),
            _declaration(("end", "result"), "string", producer_layer=2),
            _declaration(("loop", "count"), "number", owner_container_id="loop", producer_layer=0),
            _declaration(("iteration", "item"), "file", owner_container_id="iteration", producer_layer=0),
            _declaration(("iteration", "index"), "number", owner_container_id="iteration", producer_layer=0),
            _declaration(("body", "text"), "string", owner_container_id="iteration", producer_layer=1),
            _declaration(("iteration", "output"), "array[file]", producer_layer=0),
        ),
        referrers=(
            VariableReferrer(node_id="start", layer=0, ancestor_container_ids=()),
            VariableReferrer(node_id="tool", layer=1, ancestor_container_ids=()),
            VariableReferrer(node_id="end", layer=2, ancestor_container_ids=()),
            VariableReferrer(node_id="loop", layer=0, ancestor_container_ids=(), allows_self_variables=True),
            VariableReferrer(node_id="iteration", layer=0, ancestor_container_ids=()),
            VariableReferrer(node_id="body", layer=1, ancestor_container_ids=("iteration",)),
            VariableReferrer(node_id="outsider", layer=1, ancestor_container_ids=()),
        ),
        known_node_ids=frozenset({"start", "tool", "end", "loop", "iteration", "body", "outsider"}),
    )


def test_resolve_returns_upstream_file_declaration() -> None:
    registry = _registry()

    resolved = registry.resolve(("start", "image"), referrer_id="tool", expected_type="file")

    assert resolved.selector == ("start", "image")
    assert resolved.value_type == "file"


def test_resolve_rejects_unknown_output_on_known_node() -> None:
    registry = _registry()

    with pytest.raises(VariableResolutionError) as exc_info:
        registry.resolve(("start", "missing"), referrer_id="tool", expected_type=None)

    assert exc_info.value.code == "UNKNOWN_OUTPUT"
    assert exc_info.value.selector == ("start", "missing")


def test_resolve_rejects_unknown_node_reference() -> None:
    registry = _registry()

    with pytest.raises(VariableResolutionError) as exc_info:
        registry.resolve(("ghost", "image"), referrer_id="tool", expected_type="file")

    assert exc_info.value.code == "UNKNOWN_NODE_REFERENCE"
    assert exc_info.value.selector == ("ghost", "image")


def test_resolve_rejects_downstream_reverse_reference() -> None:
    registry = _registry()

    with pytest.raises(VariableResolutionError) as exc_info:
        registry.resolve(("end", "result"), referrer_id="tool", expected_type="string")

    assert exc_info.value.code == "REFERENCE_NOT_AVAILABLE"
    assert exc_info.value.selector == ("end", "result")


def test_resolve_rejects_private_container_child_from_outside() -> None:
    registry = _registry()

    with pytest.raises(VariableResolutionError) as exc_info:
        registry.resolve(("body", "text"), referrer_id="outsider", expected_type="string")

    assert exc_info.value.code == "PRIVATE_CONTAINER_REFERENCE"
    assert exc_info.value.selector == ("body", "text")


def test_resolve_allows_loop_self_variables() -> None:
    registry = _registry()

    resolved = registry.resolve(("loop", "count"), referrer_id="loop", expected_type="number")

    assert resolved.selector == ("loop", "count")
    assert resolved.value_type == "number"


def test_resolve_allows_iteration_item_and_index_for_descendants() -> None:
    registry = _registry()

    item = registry.resolve(("iteration", "item"), referrer_id="body", expected_type="file")
    index = registry.resolve(("iteration", "index"), referrer_id="body", expected_type="number")

    assert item.value_type == "file"
    assert index.value_type == "number"


def test_resolve_rejects_iteration_item_from_outside_container() -> None:
    registry = _registry()

    with pytest.raises(VariableResolutionError) as exc_info:
        registry.resolve(("iteration", "item"), referrer_id="outsider", expected_type="file")

    assert exc_info.value.code == "PRIVATE_CONTAINER_REFERENCE"
    assert exc_info.value.selector == ("iteration", "item")


def test_resolve_rejects_file_and_array_file_mismatch() -> None:
    registry = _registry()

    with pytest.raises(VariableResolutionError) as exc_info:
        registry.resolve(("start", "images"), referrer_id="tool", expected_type="file")

    assert exc_info.value.code == "VARIABLE_TYPE_MISMATCH"
    assert exc_info.value.selector == ("start", "images")
