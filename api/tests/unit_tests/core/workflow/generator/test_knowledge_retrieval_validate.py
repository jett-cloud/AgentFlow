"""Tests for knowledge-retrieval catalogue constraints in the generator."""

from core.workflow.generator.graph_validator import GraphValidator
from core.workflow.generator.node_builder import _MODEL_NODE_TYPES
from graphon.enums import BuiltinNodeTypes


def test_knowledge_retrieval_unknown_dataset_id_errors() -> None:
    errors = GraphValidator._collect_unknown_dataset_ids(
        nodes=[
            {
                "id": "knowledge",
                "data": {
                    "type": BuiltinNodeTypes.KNOWLEDGE_RETRIEVAL,
                    "dataset_ids": ["real", "missing"],
                },
            }
        ],
        installed_dataset_ids={"real"},
    )

    assert len(errors) == 1
    assert errors[0]["code"] == "UNKNOWN_DATASET"
    assert errors[0]["node_id"] == "knowledge"
    assert "missing" in errors[0]["detail"]


def test_agent_included_in_model_injection_types() -> None:
    assert BuiltinNodeTypes.AGENT in _MODEL_NODE_TYPES
