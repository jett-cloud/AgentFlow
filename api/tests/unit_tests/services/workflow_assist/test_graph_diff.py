from services.workflow_assist.graph_diff import assert_local_mutable_respected, diff_graphs


def _g(nodes):
    return {"nodes": nodes, "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}


def test_diff_detects_added_removed_changed():
    base = _g([{"id": "a", "data": {"type": "llm", "x": 1}}, {"id": "b", "data": {"type": "end"}}])
    nxt = _g([{"id": "a", "data": {"type": "llm", "x": 2}}, {"id": "c", "data": {"type": "agent"}}])
    d = diff_graphs(base, nxt)
    assert d["added"] == ["c"]
    assert d["removed"] == ["b"]
    assert d["changed"] == ["a"]


def test_local_mutable_blocks_unlisted_deletion():
    base = _g([{"id": "keep", "data": {"type": "llm"}}, {"id": "edit", "data": {"type": "llm"}}])
    nxt = _g([{"id": "edit", "data": {"type": "llm", "title": "x"}}])
    errors = assert_local_mutable_respected(
        base=base, next=nxt, mutable_node_ids={"edit"}, planned_new_ids=set()
    )
    assert any(e["code"] == "LOCAL_IMMUTABLE_CHANGED" and e["node_id"] == "keep" for e in errors)
