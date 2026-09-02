from __future__ import annotations

from operator import itemgetter

import pytest

from evals.workflow_assist.harness import load_cases, run_case


@pytest.mark.parametrize("case", load_cases(), ids=itemgetter("_path"))
def test_scripted_eval_case(case: dict) -> None:
    result = run_case(case)
    expect = case["expect"]
    if expect.get("forbid_done"):
        assert result["terminal"] != "done"
    else:
        assert result["terminal"] == expect["terminal"]
    for node_type in expect.get("node_types_contains") or []:
        assert node_type in result["node_types"]
    for node_id in expect.get("node_ids_contains") or []:
        assert node_id in result["node_ids"]
    for node_id in expect.get("node_ids_excludes") or []:
        assert node_id not in result["node_ids"]
    if "saw_no_evidence" in expect:
        assert result["saw_no_evidence"] is expect["saw_no_evidence"]
    if expect.get("live_blocked"):
        assert result["live_blocked"] is True
    for handle in expect.get("handles_contains") or []:
        assert handle in result["handles"]
    for node_id, parent in (expect.get("parent_of") or {}).items():
        assert result["parents"].get(node_id) == parent
