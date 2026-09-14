from __future__ import annotations

import json
from operator import itemgetter
from pathlib import Path

import pytest

from evals.workflow_assist.benchmark import BUSINESS_CASES, SCENARIOS, evaluate_scenario
from evals.workflow_assist.harness import load_cases, run_case, summarize_results
from evals.workflow_assist.provider_eval import ProviderEvalRequest, run_provider_eval


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


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.name)
@pytest.mark.parametrize("valid", [True, False], ids=["good", "bad"])
def test_fixed_generation_matrix(scenario, valid: bool) -> None:
    result = evaluate_scenario(scenario, valid=valid)

    assert result["passed"] is valid


def test_fixed_generation_matrix_has_every_required_good_and_bad_scenario() -> None:
    assert {scenario.name for scenario in SCENARIOS} == {
        "simple_llm",
        "rag",
        "tool_to_llm",
        "agent_knowledge",
        "condition_branch",
        "iteration_nested_field",
        "loop_accumulation",
        "code_dynamic_output",
        "local_edit",
        "multi_turn_requirement_change",
        "advanced_chat",
    }
    assert len([(scenario.name, valid) for scenario in SCENARIOS for valid in (True, False)]) == 22


def test_every_generation_scenario_has_distinct_normal_and_failure_business_inputs() -> None:
    assert set(BUSINESS_CASES) == {scenario.name for scenario in SCENARIOS}
    for cases in BUSINESS_CASES.values():
        assert [case["case_id"] for case in cases] == ["normal", "failure"]
        assert cases[0]["inputs"] != cases[1]["inputs"]
        assert all(case["assertions"] for case in cases)


def test_eval_metrics_report_distribution_and_zero_illegal_gate_passes() -> None:
    cases = load_cases()
    results = [run_case(case) for case in cases]

    summary = summarize_results(cases, results)

    assert summary["runs"] == len(cases)
    assert summary["illegal_gate_passes"] == 0
    assert len(summary["elapsed_ms"]) == len(cases)
    assert 0 <= summary["first_complete_rate"] <= 1
    assert 0 <= summary["final_complete_within_budget_rate"] <= 1


def test_provider_eval_configuration_is_fixed_and_covers_the_matrix() -> None:
    path = Path(__file__).resolve().parent / "provider_eval_config.json"
    config = json.loads(path.read_text(encoding="utf-8"))

    assert config["runs_per_case"] >= 3
    assert config["model"]["parameters"]["temperature"] == 0
    assert set(config["cases"]) == {scenario.name for scenario in SCENARIOS}
    assert config["budgets"] == {
        "max_model_calls": 32,
        "max_tool_calls": 64,
        "max_total_tokens": 400000,
    }


def test_provider_eval_executes_every_configured_repeat_and_enforces_budgets() -> None:
    requests: list[ProviderEvalRequest] = []

    def run_once(request: ProviderEvalRequest) -> dict[str, object]:
        requests.append(request)
        return {
            "passed": request.run_index != 1,
            "elapsed_ms": request.run_index + 0.5,
            "usage": {
                "model_calls": 2,
                "tool_calls": 1,
                "total_tokens": 401 if request.run_index == 2 else 40,
            },
        }

    report = run_provider_eval(
        run_once,
        config={
            "model": {"provider": "test", "name": "fixed", "mode": "chat", "parameters": {"temperature": 0}},
            "runs_per_case": 3,
            "budgets": {"max_model_calls": 3, "max_tool_calls": 2, "max_total_tokens": 400},
            "cases": ["simple_llm", "rag"],
        },
    )

    assert len(requests) == 6
    assert {request.scenario.name for request in requests} == {"simple_llm", "rag"}
    assert all(request.model["name"] == "fixed" for request in requests)
    assert all([case["case_id"] for case in request.acceptance_cases] == ["normal", "failure"] for request in requests)
    assert report["runs"] == 6
    assert report["pass_rate"] == pytest.approx(4 / 6)
    assert report["budget_violation_count"] == 2
    assert len(report["elapsed_ms"]) == 6
