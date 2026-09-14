"""Credential-free Agent model identities captured for one Assist run.

The catalogue is an authorization snapshot, not a model configuration payload.
It deliberately excludes credentials, endpoints, quotas, and provider settings.
"""

from collections.abc import Sequence
from typing import TypedDict


class AgentModelCatalogueEntry(TypedDict):
    """One active, non-deprecated LLM available to the current tenant."""

    provider: str
    name: str
    model_type: str
    features: tuple[str, ...]


def resolve_agent_model(
    entries: Sequence[AgentModelCatalogueEntry],
    *,
    provider: str,
    name: str,
) -> AgentModelCatalogueEntry | None:
    """Resolve an exact provider/model identity from an immutable snapshot."""
    return next(
        (entry for entry in entries if entry["provider"] == provider and entry["name"] == name),
        None,
    )
