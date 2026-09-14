"""Shared result shapes for workflow assist orchestration validations."""

from typing import NotRequired, TypedDict

ValidationIssueCode = str


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
