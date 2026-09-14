"""Select the immutable workflow-contract protocol for newly created conversations."""

from __future__ import annotations

from typing import Literal

WorkflowAssistContractRollout = Literal[
    "disabled",
    "internal_samples",
    "new_conversations",
    "local_edits",
    "default",
]


def protocol_for_new_conversation(stage: WorkflowAssistContractRollout | str) -> int | None:
    """Return protocol 1 only after the public new-conversation rollout starts."""
    if stage in {"new_conversations", "local_edits", "default"}:
        return 1
    return None
