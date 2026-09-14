"""Deterministic orchestrator for repeated Workflow Assist provider evaluations.

This module owns the fixed model/case/run/budget matrix. The caller supplies a
provider-backed adapter that executes one real Assist/Builder run; this keeps
credentials and external-response mocking outside the evaluator while ensuring
the checked-in configuration is actually enforced and aggregated.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from evals.workflow_assist.benchmark import BUSINESS_CASES, SCENARIOS, GenerationScenario
from services.workflow_assist.acceptance_cases import AcceptanceCase

CONFIG_PATH = Path(__file__).resolve().parent / "provider_eval_config.json"


@dataclass(frozen=True)
class ProviderEvalRequest:
    """One repeatable provider run with immutable model and budget inputs."""

    scenario: GenerationScenario
    run_index: int
    model: Mapping[str, object]
    budgets: Mapping[str, int]
    acceptance_cases: tuple[AcceptanceCase, AcceptanceCase]


ProviderRun = Callable[[ProviderEvalRequest], Mapping[str, object]]


def load_provider_eval_config(path: Path = CONFIG_PATH) -> dict[str, object]:
    """Load and validate the fixed provider evaluation configuration."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Provider eval config must be an object")
    return payload


def run_provider_eval(
    run_once: ProviderRun,
    *,
    config: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Execute every configured scenario repeatedly and report distributions.

    ``run_once`` must invoke the real Workflow Assist generation path. It may
    mock external tool/provider responses, but its result must report model,
    tool, and token usage so this orchestrator can enforce the fixed budgets.
    """
    resolved = dict(config or load_provider_eval_config())
    runs_per_case = _positive_int(resolved.get("runs_per_case"), "runs_per_case")
    model = _object_mapping(resolved.get("model"), "model")
    budgets = {
        key: _positive_int(value, f"budgets.{key}")
        for key, value in _object_mapping(resolved.get("budgets"), "budgets").items()
    }
    required_budgets = {"max_model_calls", "max_tool_calls", "max_total_tokens"}
    if set(budgets) != required_budgets:
        raise ValueError(f"budgets must contain exactly {sorted(required_budgets)!r}")
    scenario_by_name = {scenario.name: scenario for scenario in SCENARIOS}
    case_names = resolved.get("cases")
    if not isinstance(case_names, list) or not all(isinstance(name, str) for name in case_names):
        raise ValueError("cases must be a list of scenario names")
    unknown = sorted(set(case_names) - set(scenario_by_name))
    if unknown:
        raise ValueError(f"Unknown provider eval scenarios: {unknown!r}")

    records: list[dict[str, object]] = []
    for case_name in case_names:
        scenario = scenario_by_name[case_name]
        for run_index in range(runs_per_case):
            result = dict(
                run_once(
                    ProviderEvalRequest(
                        scenario=scenario,
                        run_index=run_index,
                        model=model,
                        budgets=budgets,
                        acceptance_cases=BUSINESS_CASES[case_name],
                    )
                )
            )
            usage = _usage(result)
            records.append(
                {
                    "scenario": case_name,
                    "run_index": run_index,
                    "passed": result.get("passed") is True,
                    "budget_passed": _within_budget(usage, budgets),
                    "usage": usage,
                    "elapsed_ms": float(result.get("elapsed_ms") or 0.0),
                }
            )
    total = len(records)
    return {
        "runs": total,
        "records": records,
        "pass_rate": sum(record["passed"] is True for record in records) / total if total else 0.0,
        "budget_violation_count": sum(record["budget_passed"] is False for record in records),
        "elapsed_ms": [record["elapsed_ms"] for record in records],
    }


def _object_mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return {str(key): item for key, item in value.items()}


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _usage(result: Mapping[str, object]) -> dict[str, int]:
    raw = _object_mapping(result.get("usage"), "result.usage")
    return {
        "model_calls": _non_negative_int(raw.get("model_calls"), "usage.model_calls"),
        "tool_calls": _non_negative_int(raw.get("tool_calls"), "usage.tool_calls"),
        "total_tokens": _non_negative_int(raw.get("total_tokens"), "usage.total_tokens"),
    }


def _non_negative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _within_budget(usage: Mapping[str, int], budgets: Mapping[str, int]) -> bool:
    return (
        usage["model_calls"] <= budgets["max_model_calls"]
        and usage["tool_calls"] <= budgets["max_tool_calls"]
        and usage["total_tokens"] <= budgets["max_total_tokens"]
    )
