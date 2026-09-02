"""Shared result shapes for workflow assist orchestration validations."""

from typing import Literal, NotRequired, TypedDict

ValidationIssueCode = Literal[
    "MISSING_START",
    "MISSING_TERMINAL",
    "DUPLICATE_NODE_ID",
    "DANGLING_EDGE",
    "LOCAL_IMMUTABLE_CHANGED",
    "AGENT_V2_SHAPE",
    "AGENT_TASK_EMPTY",
    "AGENT_BINDING_MISSING",
    "AGENT_SHOULD_BE_USED",
]


class ValidationIssue(TypedDict):
    """A single graph validation finding."""

    code: ValidationIssueCode
    detail: str
    node_id: NotRequired[str | None]


class ValidationResult(TypedDict):
    """Validation findings grouped by severity."""

    ok: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
