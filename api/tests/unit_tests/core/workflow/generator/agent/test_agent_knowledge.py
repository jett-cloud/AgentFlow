from __future__ import annotations

from copy import deepcopy

from core.workflow.generator.compiler.agent_knowledge import (
    apply_agent_knowledge_intent,
    collect_agent_knowledge_dataset_ids,
    compile_agent_knowledge,
)
from core.workflow.generator.compiler.intents.node_intent import AgentKnowledgeIntent

CATALOGUE = [
    {"id": "ds-a", "name": "Alpha", "description": "Alpha docs"},
    {"id": "ds-b", "name": "Beta", "description": "Beta docs"},
]


def _intent(dataset_ids: list[str], *, name: str = "Product docs") -> AgentKnowledgeIntent:
    return AgentKnowledgeIntent.model_validate(
        {
            "operation": "replace",
            "sets": [{"name": name, "dataset_ids": dataset_ids}],
        }
    )


def test_compile_agent_knowledge_uses_catalogue_metadata_and_stable_ids() -> None:
    first = compile_agent_knowledge(_intent(["ds-b", "ds-a"]), CATALOGUE)
    second = compile_agent_knowledge(_intent(["ds-a", "ds-b"]), CATALOGUE)

    assert first == second
    knowledge_set = first["sets"][0]
    assert knowledge_set["id"].startswith("ks_")
    assert knowledge_set["name"] == "Product docs"
    assert knowledge_set["description"] is None
    assert knowledge_set["datasets"] == [
        {"id": "ds-a", "name": "Alpha", "description": "Alpha docs"},
        {"id": "ds-b", "name": "Beta", "description": "Beta docs"},
    ]
    assert knowledge_set["query"] == {"mode": "generated_query", "value": None}
    assert knowledge_set["retrieval"] == {
        "mode": "multiple",
        "top_k": 4,
        "score_threshold": None,
        "reranking_mode": "reranking_model",
        "reranking_enable": False,
        "reranking_model": None,
        "weights": None,
        "model": None,
    }
    assert knowledge_set["metadata_filtering"] == {
        "mode": "disabled",
        "model_config": None,
        "conditions": None,
    }


def test_compile_agent_knowledge_deduplicates_implicit_catalogue_names() -> None:
    catalogue = [
        {"id": "ds-a", "name": "Docs", "description": "Alpha"},
        {"id": "ds-b", "name": "Docs", "description": "Beta"},
    ]
    intent = AgentKnowledgeIntent.model_validate(
        {
            "operation": "replace",
            "sets": [{"dataset_ids": ["ds-a"]}, {"dataset_ids": ["ds-b"]}],
        }
    )

    compiled = compile_agent_knowledge(intent, catalogue)

    assert [item["name"] for item in compiled["sets"]] == ["Docs", "Docs (2)"]


def test_compile_agent_knowledge_preserves_explicit_name_when_implicit_name_collides() -> None:
    catalogue = [
        {"id": "ds-a", "name": "Docs", "description": "Alpha"},
        {"id": "ds-b", "name": "Other", "description": "Beta"},
    ]
    intent = AgentKnowledgeIntent.model_validate(
        {
            "operation": "replace",
            "sets": [
                {"dataset_ids": ["ds-a"]},
                {"name": "Docs", "dataset_ids": ["ds-b"]},
            ],
        }
    )

    compiled = compile_agent_knowledge(intent, catalogue)

    assert [item["name"] for item in compiled["sets"]] == ["Docs (2)", "Docs"]


def test_collect_agent_knowledge_dataset_ids_normalizes_and_deduplicates() -> None:
    data = {
        "type": "agent",
        "knowledge": {
            "sets": [
                {"datasets": [{"id": " ds-a "}, {"id": ""}, {"id": 7}]},
                {"datasets": [{"id": "ds-a"}, {"id": "ds-b"}]},
            ]
        },
    }

    assert collect_agent_knowledge_dataset_ids(data) == ["ds-a", "ds-b"]


def test_apply_agent_knowledge_intent_preserves_only_update_omission() -> None:
    old_knowledge = compile_agent_knowledge(_intent(["ds-a"]), CATALOGUE)
    updated = {"knowledge": {"sets": []}, "agent_task": "new task"}

    apply_agent_knowledge_intent(
        mode="update",
        config=updated,
        old_config={"knowledge": old_knowledge},
        intent=None,
        catalogue_entries=CATALOGUE,
    )

    assert updated["knowledge"] == old_knowledge
    created = {"knowledge": deepcopy(old_knowledge)}
    apply_agent_knowledge_intent(
        mode="create",
        config=created,
        old_config={},
        intent=None,
        catalogue_entries=CATALOGUE,
    )
    assert "knowledge" not in created


def test_apply_agent_knowledge_intent_clear_is_explicit() -> None:
    config = {"knowledge": compile_agent_knowledge(_intent(["ds-a"]), CATALOGUE)}

    apply_agent_knowledge_intent(
        mode="update",
        config=config,
        old_config=deepcopy(config),
        intent=AgentKnowledgeIntent.model_validate({"operation": "clear"}),
        catalogue_entries=CATALOGUE,
    )

    assert config["knowledge"] == {"sets": []}


def test_compile_agent_node_config_embeds_knowledge_and_returns_manifest() -> None:
    from core.workflow.generator.compiler.agent_node_compiler import compile_agent_node_config
    from core.workflow.generator.compiler.intents.agent_intent import AgentNodeBuildIntent
    from core.workflow.generator.variables.variable_registry import VariableReferrer, VariableRegistry

    intent = AgentNodeBuildIntent.model_validate(
        {
            "model": {"provider": "openai", "name": "gpt-4o"},
            "instruction": "Answer with docs",
            "inputs": [],
            "outputs": [],
            "knowledge": {"operation": "replace", "sets": [{"name": "Product docs", "dataset_ids": ["ds-a"]}]},
        }
    )
    registry = VariableRegistry(
        (),
        referrers=(VariableReferrer(node_id="agent_1", layer=1, ancestor_container_ids=()),),
        known_node_ids=frozenset({"agent_1"}),
    )

    config, manifest = compile_agent_node_config(
        intent=intent,
        tool_entries=[],
        knowledge_entries=CATALOGUE,
        variable_registry=registry,
        referrer_id="agent_1",
        mode="create",
        old_config={},
    )

    assert config["knowledge"]["sets"][0]["datasets"][0]["id"] == "ds-a"
    assert "knowledge-retrieval" not in config
    assert manifest.dataset_ids == ("ds-a",)
    assert manifest.binding_id == "agent_1"
    assert manifest.tool_keys == ()
