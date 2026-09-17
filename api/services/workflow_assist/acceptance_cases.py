"""Server-owned acceptance fixtures for Workflow Assist candidate execution.

The model may select case IDs, but it cannot define their inputs or assertions.
Callers build the registry from trusted application/eval configuration and pass
it to :class:`WorkflowAssistAcceptanceRunner`.
"""

from __future__ import annotations

from typing import TypedDict

from services.workflow_assist.runtime_contract import BusinessAssertion


class AcceptanceCase(TypedDict):
    """One trusted business example with Start inputs and expected outputs."""

    case_id: str
    inputs: dict[str, object]
    assertions: list[BusinessAssertion]


def index_acceptance_cases(cases: list[AcceptanceCase]) -> dict[str, AcceptanceCase]:
    """Validate case IDs and return a detached lookup for one runner."""
    indexed: dict[str, AcceptanceCase] = {}
    for case in cases:
        case_id = case["case_id"].strip()
        if not case_id or case_id in indexed:
            raise ValueError("Acceptance case IDs must be non-empty and unique")
        indexed[case_id] = {
            "case_id": case_id,
            "inputs": dict(case["inputs"]),
            "assertions": list(case["assertions"]),
        }
    return indexed
