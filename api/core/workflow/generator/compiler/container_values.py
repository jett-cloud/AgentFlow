"""container values."""

from __future__ import annotations

_BRANCH_TYPES = frozenset({"if-else", "question-classifier"})


_ID_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


_MECHANICAL_ATTEMPTS = 2


_NEVER_MECHANICAL_RETRY = frozenset(
    {
        "UNKNOWN_TOOL_OUTPUT",
        "UNKNOWN_OUTPUT",
        "VARIABLE_TYPE_MISMATCH",
        "PRIVATE_CONTAINER_REFERENCE",
        "UNKNOWN_TOOL",
        "UNKNOWN_DATASET",
        "GRAPH_CYCLE",
        "EXTERNAL_REFERENCE_BROKEN",
        "REFERENCE_NOT_AVAILABLE",
        "INVALID_CONTAINER",
        "UNSUPPORTED_NODE_TYPE",
        "CAPABILITY_UNAVAILABLE",
        "NESTED_CONTAINER_UNSUPPORTED",
    }
)


_SENSITIVE_CACHE_MARKERS = ("credential", "api_key", "access_token", "password", "secret")
