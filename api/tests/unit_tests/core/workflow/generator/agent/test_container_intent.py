import pytest
from pydantic import ValidationError

from core.workflow.generator.compiler.intents.container_intent import (
    IterationBuildIntent,
    LoopBuildIntent,
    parse_iteration_build_intent,
    parse_loop_build_intent,
)


def _standard_child(ref: str = "worker", *, node_type: str = "llm") -> dict[str, object]:
    return {
        "kind": "standard",
        "ref": ref,
        "node_type": node_type,
        "intent": {
            "objective": "Transform the current item",
            "inputs": [{"source": ["start", "query"], "role": "query"}],
            "outputs": [{"name": "text", "type": "string"}],
        },
    }


def _loop_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "loop_count": 10,
        "loop_variables": [
            {"label": "acc", "var_type": "string", "value_type": "constant", "value": ""},
        ],
        "children": [_standard_child()],
        "edges": [],
        "break_conditions": [
            {
                "id": "c1",
                "variable_selector": ["acc"],
                "comparison_operator": "is",
                "value": "done",
            }
        ],
        "outputs": [{"name": "acc", "type": "string"}],
    }
    payload.update(changes)
    return payload


def _iteration_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "iterator_selector": ["start", "items"],
        "iterator_input_type": "array[string]",
        "output_selector": ["worker", "text"],
        "children": [_standard_child()],
        "edges": [],
        "outputs": [{"name": "output", "type": "array[string]"}],
    }
    payload.update(changes)
    return payload


def test_duplicate_child_ref_is_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        parse_loop_build_intent(_loop_payload(children=[_standard_child("worker"), _standard_child("worker")]))


def test_edge_to_unknown_ref_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown"):
        parse_loop_build_intent(_loop_payload(edges=[{"source": "worker", "target": "missing"}]))


def test_loop_variable_missing_initial_value_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_loop_build_intent(
            _loop_payload(
                loop_variables=[{"label": "acc", "var_type": "string", "value_type": "constant"}],
            )
        )


@pytest.mark.parametrize("loop_count", [0, 101, -1, True])
def test_illegal_loop_count_is_rejected(loop_count: object) -> None:
    with pytest.raises(ValidationError, match="loop_count"):
        parse_loop_build_intent(_loop_payload(loop_count=loop_count))


def test_iteration_non_array_input_is_rejected() -> None:
    with pytest.raises(ValidationError, match="array"):
        parse_iteration_build_intent(_iteration_payload(iterator_input_type="string"))


@pytest.mark.parametrize("parallel_nums", [0, 11, 100])
def test_iteration_parallelism_outside_ui_contract_is_rejected(parallel_nums: int) -> None:
    with pytest.raises(ValidationError, match="parallel_nums"):
        parse_iteration_build_intent(_iteration_payload(parallel_nums=parallel_nums))


@pytest.mark.parametrize(
    "output_selector",
    [["text"], ["missing", "text"], ["", "text"], ["worker", ""]],
)
def test_illegal_iteration_output_selector_is_rejected(output_selector: list[str]) -> None:
    with pytest.raises(ValidationError):
        parse_iteration_build_intent(_iteration_payload(output_selector=output_selector))


@pytest.mark.parametrize("node_type", ["loop", "iteration", "loop-start", "iteration-start"])
def test_nested_container_child_is_rejected(node_type: str) -> None:
    with pytest.raises(ValidationError, match="nested"):
        parse_loop_build_intent(_loop_payload(children=[_standard_child(node_type=node_type)]))


@pytest.mark.parametrize("field", ["parentId", "_children", "start_node_id"])
def test_loop_intent_forbids_system_owned_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        parse_loop_build_intent(_loop_payload(**{field: "forbidden"}))


def test_valid_loop_and_iteration_intents_parse() -> None:
    loop = parse_loop_build_intent(_loop_payload())
    iteration = parse_iteration_build_intent(_iteration_payload())

    assert isinstance(loop, LoopBuildIntent)
    assert loop.children[0].ref == "worker"
    assert isinstance(iteration, IterationBuildIntent)
    assert iteration.output_selector == ("worker", "text")
