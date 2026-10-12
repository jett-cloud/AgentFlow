"""container values."""

from __future__ import annotations

_BRANCH_TYPES = frozenset({"if-else", "question-classifier"})


_ID_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


_SENSITIVE_CACHE_MARKERS = ("credential", "api_key", "access_token", "password", "secret")
