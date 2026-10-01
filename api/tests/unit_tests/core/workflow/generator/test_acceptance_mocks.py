import pytest

from core.workflow.generator.acceptance.mocks import (
    PROBE_END_ID,
    MockGraphError,
    build_mocked_graph,
    build_node_probe_graph,
    describe_mock_target,
)
from core.workflow.generator.graph.graph_ops import connect, empty_graph, upsert_node
from tests.unit_tests.core.workflow.generator.node_fixtures import node_config

_SENTIMENT_SCHEMA = {
    "type": "object",
    "properties": {"sentiment": {"type": "string", "enum": ["positive", "negative"]}},
}


def _graph():
    graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="开始",
        desc="",
        config={"variables": [{"variable": "review", "type": "paragraph", "label": "review", "required": True}]},
    )
    graph = upsert_node(
        graph,
        node_id="llm",
        node_type="llm",
        title="分析",
        desc="",
        config=node_config(
            "llm", {"structured_output_enabled": True, "structured_output": {"schema": _SENTIMENT_SCHEMA}}
        ),
    )
    graph = upsert_node(
        graph,
        node_id="code",
        node_type="code",
        title="格式化",
        desc="",
        config=node_config(
            "code",
            {
                "variables": [{"variable": "t", "value_selector": ["llm", "text"]}],
                "outputs": {"result": {"type": "string", "children": None}},
            },
        ),
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={"outputs": []})
    graph = connect(graph, source="start", target="llm")
    graph = connect(graph, source="llm", target="code")
    return connect(graph, source="code", target="end")


def _run_fixture(code: str) -> object:
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 -- executes the generated fixture source under test
    return namespace["main"]()


def test_mocked_graph_replaces_external_nodes_with_fixed_output_code() -> None:
    original = _graph()
    mocked, applied = build_mocked_graph(
        original, {"llm": {"text": "差评", "structured_output": {"sentiment": "negative"}}}
    )

    llm = next(node for node in mocked["nodes"] if node["id"] == "llm")
    assert llm["data"]["type"] == "code"
    assert llm["data"]["outputs"]["structured_output"] == {"type": "object", "children": None}
    assert applied["llm"]["text"] == "差评"
    assert applied["llm"]["structured_output"] == {"sentiment": "negative"}
    assert applied["llm"]["reasoning_content"] == "mock"
    assert _run_fixture(llm["data"]["code"]) == applied["llm"]
    local = next(node for node in mocked["nodes"] if node["id"] == "code")
    assert local["data"]["code"] == "def main():\n    return {}"
    assert mocked["edges"] == original["edges"]


def test_placeholders_pick_the_first_enum_value() -> None:
    _, applied = build_mocked_graph(_graph(), {})
    assert applied["llm"]["structured_output"] == {"sentiment": "positive"}
    assert applied["llm"]["usage"] == {}


def test_mock_values_are_checked_against_declared_outputs() -> None:
    with pytest.raises(MockGraphError) as caught:
        build_mocked_graph(_graph(), {"llm": {"structured_output": {"sentiment": "neutral"}}})
    assert caught.value.code == "INVALID_MOCK_OUTPUT"
    assert "sentiment" in caught.value.detail
    with pytest.raises(MockGraphError, match="no output"):
        build_mocked_graph(_graph(), {"llm": {"answer": "x"}})
    with pytest.raises(MockGraphError, match="not an external node"):
        build_mocked_graph(_graph(), {"code": {"result": "x"}})
    with pytest.raises(MockGraphError, match="one element type"):
        build_mocked_graph(_graph(), {"llm": {"text": ["a", 1]}})


def test_question_classifier_cannot_be_mocked() -> None:
    graph = upsert_node(
        _graph(),
        node_id="qc",
        node_type="question-classifier",
        title="分类",
        desc="",
        config={"classes": [{"id": "1", "name": "A"}], "query_variable_selector": ["start", "review"]},
    )
    with pytest.raises(MockGraphError) as caught:
        build_mocked_graph(connect(graph, source="start", target="qc"), {})
    assert caught.value.code == "MOCK_UNSUPPORTED_NODE"


def test_probe_graph_keeps_start_fixes_ancestors_and_drops_descendants() -> None:
    probe, applied = build_node_probe_graph(
        _graph(), "code", upstream_outputs={"llm": {"text": "好评"}}, observed_outputs={}
    )

    assert [node["id"] for node in probe["nodes"]] == ["start", "llm", "code", PROBE_END_ID]
    assert next(node for node in probe["nodes"] if node["id"] == "llm")["data"]["type"] == "code"
    assert next(node for node in probe["nodes"] if node["id"] == "code")["data"]["outputs"] == {
        "result": {"type": "string", "children": None}
    }
    assert applied["llm"]["text"] == "好评"
    assert [(edge["source"], edge["target"]) for edge in probe["edges"]] == [
        ("start", "llm"),
        ("llm", "code"),
        ("code", PROBE_END_ID),
    ]


def test_probe_graph_reuses_valid_observed_outputs() -> None:
    _, applied = build_node_probe_graph(
        _graph(), "code", upstream_outputs={}, observed_outputs={"llm": {"text": "真实输出", "usage": "bad"}}
    )
    assert applied["llm"]["text"] == "真实输出"
    assert applied["llm"]["usage"] == {}


def test_probe_graph_rejects_unsupported_targets_and_foreign_fixtures() -> None:
    with pytest.raises(MockGraphError, match="not upstream"):
        build_node_probe_graph(_graph(), "llm", upstream_outputs={"code": {"result": "x"}}, observed_outputs={})
    with pytest.raises(MockGraphError) as caught:
        build_node_probe_graph(_graph(), "start", upstream_outputs={}, observed_outputs={})
    assert caught.value.code == "NODE_PROBE_UNSUPPORTED"
    with pytest.raises(MockGraphError) as missing:
        build_node_probe_graph(_graph(), "ghost", upstream_outputs={}, observed_outputs={})
    assert missing.value.code == "NODE_NOT_FOUND"


def test_describe_mock_target_reports_schema_consumers_and_branch_conditions() -> None:
    graph = upsert_node(
        _graph(),
        node_id="branch",
        node_type="if-else",
        title="判断",
        desc="",
        config={
            "cases": [
                {
                    "case_id": "true",
                    "logical_operator": "and",
                    "conditions": [
                        {
                            "variable_selector": ["llm", "structured_output", "sentiment"],
                            "comparison_operator": "is",
                            "value": "negative",
                            "varType": "string",
                        }
                    ],
                }
            ]
        },
    )

    target = describe_mock_target(graph, "llm")

    assert target["external"] is True
    assert target["mockable"] is True
    assert target["output_schema"]["structured_output"]["properties"] == _SENTIMENT_SCHEMA["properties"]
    assert target["instruction_excerpt"] == "处理输入。"
    consumers = {item["node_id"]: item for item in target["consumers"]}
    assert consumers["code"]["uses"] == ["text"]
    assert consumers["branch"]["conditions"] == [
        {
            "case_id": "true",
            "selector": ["llm", "structured_output", "sentiment"],
            "operator": "is",
            "value": "negative",
        }
    ]
