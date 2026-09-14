import pytest

from core.workflow.generator.agent.types import AgentMessage, AgentSession
from services.workflow_assist.turn_references import (
    UnknownTurnReferenceError,
    append_hard_bound_resources,
    bind_session_references,
    bind_turn_references,
    normalize_turn_references,
)


def test_normalize_drops_malformed_items_and_rejects_oversize_lists() -> None:
    assert normalize_turn_references(None) is None
    assert normalize_turn_references([{"kind": "node"}, {"kind": "nope", "id": "x"}]) is None
    kept = normalize_turn_references(
        [
            {"kind": "node", "id": "n1", "label": "知识库检索"},
            {"kind": "node", "id": "n1", "label": "dup"},
            {
                "kind": "tool",
                "id": "time/current_time",
                "label": "当前时间",
                "provider": "time",
                "tool_name": "current_time",
            },
            "bad",
        ]
    )
    assert kept == [
        {"kind": "node", "id": "n1", "label": "知识库检索"},
        {
            "kind": "tool",
            "id": "time/current_time",
            "label": "当前时间",
            "provider": "time",
            "tool_name": "current_time",
        },
    ]
    with pytest.raises(ValueError, match="exceeds 8"):
        normalize_turn_references([{"kind": "node", "id": f"n{index}"} for index in range(9)])


def test_normalize_keeps_plugin_provider_ids_that_contain_slashes() -> None:
    """Plugin provider ids are org/plugin/provider; the tool name is after the last slash."""
    kept = normalize_turn_references(
        [
            {
                "kind": "tool",
                "id": "ghy/doubao-image/doubao-image/image_generate",
                "label": "图片生成",
            }
        ]
    )
    assert kept == [
        {
            "kind": "tool",
            "id": "ghy/doubao-image/doubao-image/image_generate",
            "label": "图片生成",
            "provider": "ghy/doubao-image/doubao-image",
            "tool_name": "image_generate",
        }
    ]


def test_bind_accepts_plugin_tool_keys_from_assist_mentions() -> None:
    bound = bind_turn_references(
        [
            {
                "kind": "tool",
                "id": "ghy/doubao-image/doubao-image/image_generate",
                "label": "图片生成",
                "provider": "ghy/doubao-image/doubao-image",
                "tool_name": "image_generate",
            }
        ],
        canvas_graph={"nodes": []},
        installed_tools={("ghy/doubao-image/doubao-image", "image_generate")},
        installed_datasets=set(),
    )
    assert bound is not None
    assert bound[0]["provider"] == "ghy/doubao-image/doubao-image"
    assert bound[0]["tool_name"] == "image_generate"


def test_bind_rejects_unknown_canvas_and_catalogue_ids() -> None:
    refs = [{"kind": "node", "id": "missing", "label": "Gone"}]
    with pytest.raises(UnknownTurnReferenceError, match="missing"):
        bind_turn_references(
            refs,
            canvas_graph={"nodes": [{"id": "n1"}]},
            installed_tools=set(),
            installed_datasets=set(),
        )

    bound = bind_turn_references(
        [
            {"kind": "node", "id": "n1", "label": "知识库检索"},
            {
                "kind": "tool",
                "id": "time/current_time",
                "label": "当前时间",
                "provider": "time",
                "tool_name": "current_time",
            },
            {"kind": "dataset", "id": "ds-1", "label": "产品文档"},
        ],
        canvas_graph={"nodes": [{"id": "n1"}]},
        installed_tools={("time", "current_time")},
        installed_datasets={"ds-1"},
    )
    assert bound is not None
    assert [item["id"] for item in bound] == ["n1", "time/current_time", "ds-1"]


def test_hard_bind_prompt_forbids_search_and_fills_session_lists() -> None:
    session = AgentSession(
        messages=[
            AgentMessage(sequence=1, event_type="message", role="user", status="completed", payload={"text": "x"}),
        ],
        candidate_graph={"nodes": [], "edges": [], "viewport": {"x": 0.0, "y": 0.0, "zoom": 1.0}},
        candidate_revision=0,
        candidate_base_hash=None,
        compacted_until_sequence=None,
        compacted_state=None,
        generation_mode="workflow",
        last_validation=None,
    )
    references = [
        {"kind": "node", "id": "n1", "label": "知识库检索"},
        {
            "kind": "tool",
            "id": "time/current_time",
            "label": "当前时间",
            "provider": "time",
            "tool_name": "current_time",
        },
        {"kind": "dataset", "id": "ds-1", "label": "产品文档"},
    ]
    bind_session_references(session, references)
    assert [item["id"] for item in session.referenced_nodes] == ["n1"]
    assert [item["id"] for item in session.referenced_tools] == ["time/current_time"]
    assert [item["id"] for item in session.referenced_datasets] == ["ds-1"]
    text = append_hard_bound_resources("connect them", references)
    assert "Bound user references (HARD)" in text
    assert "time/current_time" in text
    assert "ds-1" in text
    assert "search_tools" in text
    assert "ask_user" in text
