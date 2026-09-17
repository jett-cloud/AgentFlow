"""Pure normalization and matching for user-backed workflow requirements."""


def normalize_requirement_evidence(value: str) -> str:
    """Normalize user text without changing its semantic characters."""
    return " ".join(value.casefold().split())


def evidence_occurs_in_turn(*, evidence: str, user_text: str) -> bool:
    """Return whether non-empty normalized evidence occurs in the user turn."""
    normalized_evidence = normalize_requirement_evidence(evidence)
    normalized_turn = normalize_requirement_evidence(user_text)
    return bool(normalized_evidence and normalized_turn and normalized_evidence in normalized_turn)
