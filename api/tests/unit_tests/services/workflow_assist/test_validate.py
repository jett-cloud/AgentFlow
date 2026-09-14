from services.workflow_assist.validate import validate_graph


def _validate(
    graph: dict,
    *,
    mode: str = "rebuild",
    generation_mode: str = "workflow",
    base_graph: dict | None = None,
    mutable_node_ids: set[str] | None = None,
    planned_new_ids: set[str] | None = None,
    intent_flags: dict | None = None,
):
    return validate_graph(
        graph=graph,
        mode=mode,
        generation_mode=generation_mode,
        base_graph=base_graph,
        mutable_node_ids=mutable_node_ids or set(),
        planned_new_ids=planned_new_ids or set(),
        intent_flags=intent_flags or {},
    )


def _agent_data(**overrides: object) -> dict:
    data: dict = {
        "type": "agent",
        "version": "2",
        "agent_node_kind": "dify_agent",
        "agent_task": "做研究",
        "agent_binding": {"binding_type": "inline_agent"},
        "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
    }
    data.update(overrides)
    return data


def test_agent_missing_version_errors():
    graph = {
        "nodes": [
            {"id": "1", "data": {"type": "start"}},
            {"id": "2", "data": _agent_data(version="1")},
            {"id": "3", "data": {"type": "end"}},
        ],
        "edges": [
            {"id": "e1", "source": "1", "target": "2"},
            {"id": "e2", "source": "2", "target": "3"},
        ],
    }
    result = _validate(graph)
    assert result["ok"] is False
    assert any(error["code"] == "INVALID_AGENT_NODE" for error in result["errors"])


def test_missing_start():
    result = _validate(
        {
            "nodes": [{"id": "end", "data": {"type": "end"}}],
            "edges": [],
        }
    )
    assert result["ok"] is False
    assert any(error["code"] == "MISSING_START" for error in result["errors"])


def test_local_immutable_surfaced():
    base_graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start"}},
            {"id": "locked", "data": {"type": "llm"}},
            {"id": "end", "data": {"type": "end"}},
        ],
        "edges": [],
    }
    graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start"}},
            {"id": "locked", "data": {"type": "llm", "title": "changed"}},
            {"id": "end", "data": {"type": "end"}},
        ],
        "edges": [],
    }
    result = _validate(graph, mode="local", base_graph=base_graph)
    assert result["ok"] is False
    assert any(error["code"] == "LOCAL_IMMUTABLE_CHANGED" for error in result["errors"])


def test_wants_agent_without_agent_node():
    result = _validate(
        {
            "nodes": [
                {"id": "start", "data": {"type": "start"}},
                {"id": "end", "data": {"type": "end"}},
            ],
            "edges": [],
        },
        intent_flags={"wants_agent": True},
    )
    assert result["ok"] is False
    assert any(error["code"] == "AGENT_SHOULD_BE_USED" for error in result["errors"])


def test_inline_agent_without_ids_does_not_report_binding_missing():
    result = _validate(
        {
            "nodes": [
                {"id": "start", "data": {"type": "start"}},
                {"id": "a1", "data": _agent_data()},
                {"id": "end", "data": {"type": "end"}},
            ],
            "edges": [
                {"source": "start", "target": "a1"},
                {"source": "a1", "target": "end"},
            ],
        },
        intent_flags={"wants_agent": True},
    )
    assert not any(error["code"] == "AGENT_SHOULD_BE_USED" for error in result["errors"])
    assert not any(error["code"] == "AGENT_BINDING_MISSING" for error in result["errors"])


def test_http_validate_reports_bare_array_code_output():
    result = _validate(
        {
            "nodes": [
                {"id": "start", "data": {"type": "start"}},
                {
                    "id": "node_parse",
                    "data": {"type": "code", "outputs": {"questions": {"type": "array"}}},
                },
                {"id": "end", "data": {"type": "end"}},
            ],
            "edges": [
                {"source": "start", "target": "node_parse"},
                {"source": "node_parse", "target": "end"},
            ],
        }
    )
    assert result["ok"] is False
    assert any(error["code"] == "INVALID_CODE_OUTPUT" for error in result["errors"])
    assert any("questions" in error["detail"] and "'array'" in error["detail"] for error in result["errors"])


def test_http_validate_reports_missing_end_value_type():
    result = _validate(
        {
            "nodes": [
                {"id": "start", "data": {"type": "start"}},
                {
                    "id": "end",
                    "data": {
                        "type": "end",
                        "outputs": [{"variable": "result", "value_selector": ["start", "query"]}],
                    },
                },
            ],
            "edges": [{"source": "start", "target": "end"}],
        }
    )
    assert result["ok"] is False
    assert any(error["code"] == "INVALID_END_OUTPUT" for error in result["errors"])


def test_wants_vision_alone_does_not_require_agent():
    result = _validate(
        {
            "nodes": [
                {"id": "start", "data": {"type": "start"}},
                {"id": "llm", "data": {"type": "llm"}},
                {"id": "end", "data": {"type": "end"}},
            ],
            "edges": [],
        },
        intent_flags={"wants_vision": True, "wants_agent": False},
    )
    assert not any(error["code"] == "AGENT_SHOULD_BE_USED" for error in result["errors"])
