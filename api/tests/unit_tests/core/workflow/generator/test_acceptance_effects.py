from core.workflow.generator.acceptance.effects import classify_effect, classify_node_effect, external_node_ids
from services.workflow_assist import effect_policy


def test_classification_keeps_existing_policy_boundaries() -> None:
    assert classify_effect("code") == "local_execute"
    assert classify_effect("llm") == "metered"
    assert classify_effect("knowledge-retrieval") == "metered"
    assert classify_effect("tool") == "simulate_always"
    assert classify_effect("http-request") == "simulate_always"
    assert classify_effect("future-plugin") == "simulate_always"
    assert classify_node_effect({"id": "a", "data": {"type": "agent", "dify_tools": [{"tool_name": "x"}]}}) == (
        "simulate_always"
    )
    assert classify_node_effect("not-a-node") == "simulate_always"


def test_external_node_ids_lists_every_node_that_is_not_free() -> None:
    graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start"}},
            {"id": "llm", "data": {"type": "llm"}},
            {"id": "http", "data": {"type": "http-request"}},
            {"id": "end", "data": {"type": "end"}},
        ],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
    assert external_node_ids(graph) == ["llm", "http"]


def test_service_policy_reexports_core_classification() -> None:
    assert effect_policy.classify_node_effect is classify_node_effect
    assert effect_policy.classify_effect is classify_effect
