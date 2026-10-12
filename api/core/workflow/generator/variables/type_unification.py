"""Strict branch type unification for deterministic node compilation."""

from __future__ import annotations

from collections.abc import Iterable

from core.workflow.generator.variables.variable_types import canonical_value_type

_AMBIGUOUS_TYPES = frozenset({"", "any", "array[any]"})


def unify_branch_types(value_types: Iterable[str]) -> str:
    """Return the one canonical branch type or reject an unsafe merge.

    The aggregator must not silently degrade incompatible or unknown branch
    outputs to ``any`` because that postpones an actionable compile-time error
    until workflow execution.
    """

    canonical = tuple(canonical_value_type(value_type.strip()) for value_type in value_types)
    if not canonical:
        raise ValueError("at least one branch type is required")
    ambiguous = sorted({value_type for value_type in canonical if value_type in _AMBIGUOUS_TYPES})
    if ambiguous:
        raise ValueError(f"branch types must be concrete, got {ambiguous!r}")
    unique = sorted(set(canonical))
    if len(unique) != 1:
        raise ValueError(f"branch types are incompatible: {unique!r}")
    return unique[0]


__all__ = ["unify_branch_types"]
