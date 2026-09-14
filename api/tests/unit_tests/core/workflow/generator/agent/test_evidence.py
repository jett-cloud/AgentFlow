from core.workflow.generator.acceptance.evidence import (
    AcceptanceAttempt,
    canonical_graph_hash,
    finish_acceptance_reason,
)
from core.workflow.generator.graph.graph_ops import connect, empty_graph, upsert_node


def _start_end(*, title: str = "开始"):
    graph = upsert_node(
        empty_graph(), node_id="start", node_type="start", title=title, desc="", config={"variables": []}
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    return connect(graph, source="start", target="end")


def _attempt(**overrides: object) -> AcceptanceAttempt:
    attempt: AcceptanceAttempt = {
        "attempt_id": "att-1",
        "revision": 0,
        "graph_hash": canonical_graph_hash(_start_end()),
        "case_id": "default",
        "passed": True,
        "status": "simulated",
        "failed_nodes": [],
        "evidence": [],
        "trace_summary": "ok",
    }
    attempt.update(overrides)  # type: ignore[typeddict-item]
    return attempt


def test_canonical_graph_hash_ignores_layout_and_key_order() -> None:
    left = _start_end()
    right = _start_end()
    right["viewport"] = {"x": 99.0, "y": 1.0, "zoom": 2.0}
    right["nodes"][0]["position"] = {"x": 10, "y": 20}  # type: ignore[typeddict-unknown-key]
    right["nodes"][0]["width"] = 244  # type: ignore[typeddict-unknown-key]
    shuffled_edges = list(reversed(right["edges"]))
    right["edges"] = shuffled_edges
    assert canonical_graph_hash(left) == canonical_graph_hash(right)


def test_canonical_graph_hash_changes_when_topology_changes() -> None:
    base = _start_end()
    renamed = _start_end(title="入口")
    assert canonical_graph_hash(base) != canonical_graph_hash(renamed)


def test_canonical_graph_hash_changes_when_node_type_changes() -> None:
    base = _start_end()
    swapped = upsert_node(base, node_id="end", node_type="llm", title="结束", desc="", config={})
    assert canonical_graph_hash(base) != canonical_graph_hash(swapped)


def test_finish_acceptance_reason_skips_when_runner_missing() -> None:
    assert finish_acceptance_reason(attempts={}, revision=0, graph_hash="abc", runner_present=False) is None


def test_finish_acceptance_reason_no_evidence() -> None:
    assert finish_acceptance_reason(attempts={}, revision=0, graph_hash="abc", runner_present=True) == "NO_EVIDENCE"


def test_finish_acceptance_reason_stale_hash() -> None:
    attempt = _attempt(graph_hash="old")
    reason = finish_acceptance_reason(
        attempts={"att-1": attempt},
        revision=0,
        graph_hash="new",
        runner_present=True,
    )
    assert reason == "STALE_EVIDENCE"


def test_finish_acceptance_reason_stale_revision() -> None:
    attempt = _attempt(revision=1)
    reason = finish_acceptance_reason(
        attempts={"att-1": attempt},
        revision=2,
        graph_hash=attempt["graph_hash"],
        runner_present=True,
    )
    assert reason == "STALE_EVIDENCE"


def test_finish_acceptance_reason_rejects_evidence_from_old_contract_revision() -> None:
    attempt = _attempt(contract_revision=1, contract_hash="a" * 64, validation_version=1)

    reason = finish_acceptance_reason(
        attempts={"att-1": attempt},
        revision=attempt["revision"],
        graph_hash=attempt["graph_hash"],
        runner_present=True,
        contract_revision=2,
        contract_hash="b" * 64,
        validation_version=1,
    )

    assert reason == "STALE_EVIDENCE"


def test_finish_acceptance_reason_assertion_failed() -> None:
    graph_hash = canonical_graph_hash(_start_end())
    attempt = _attempt(passed=False, graph_hash=graph_hash, revision=0)
    reason = finish_acceptance_reason(
        attempts={"att-1": attempt},
        revision=0,
        graph_hash=graph_hash,
        runner_present=True,
    )
    assert reason == "ASSERTION_FAILED"


def test_finish_acceptance_reason_passes_when_current_attempt_ok() -> None:
    graph_hash = canonical_graph_hash(_start_end())
    attempt = _attempt(graph_hash=graph_hash, revision=3)
    assert (
        finish_acceptance_reason(
            attempts={"att-1": attempt},
            revision=3,
            graph_hash=graph_hash,
            runner_present=True,
        )
        is None
    )


def test_finish_acceptance_reason_later_pass_overrides_same_revision_fail() -> None:
    graph_hash = canonical_graph_hash(_start_end())
    failed = _attempt(attempt_id="att-1", passed=False, graph_hash=graph_hash, revision=0)
    passed = _attempt(attempt_id="att-2", passed=True, graph_hash=graph_hash, revision=0)
    assert (
        finish_acceptance_reason(
            attempts={"att-1": failed, "att-2": passed},
            revision=0,
            graph_hash=graph_hash,
            runner_present=True,
        )
        is None
    )


def test_finish_acceptance_reason_rejects_live_success_that_never_ran() -> None:
    graph_hash = canonical_graph_hash(_start_end())
    attempt = _attempt(
        graph_hash=graph_hash,
        revision=0,
        status="succeeded",
        passed=True,
        executed=False,
    )
    assert (
        finish_acceptance_reason(
            attempts={"att-1": attempt},
            revision=0,
            graph_hash=graph_hash,
            runner_present=True,
        )
        == "NO_EVIDENCE"
    )


def test_finish_acceptance_reason_allows_simulated_skip_without_execution() -> None:
    graph_hash = canonical_graph_hash(_start_end())
    attempt = _attempt(
        graph_hash=graph_hash,
        revision=0,
        status="simulated",
        passed=True,
        executed=False,
    )
    assert (
        finish_acceptance_reason(
            attempts={"att-1": attempt},
            revision=0,
            graph_hash=graph_hash,
            runner_present=True,
        )
        is None
    )
