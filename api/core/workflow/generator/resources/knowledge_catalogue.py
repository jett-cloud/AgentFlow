"""Knowledge catalogue values and prompt formatting."""

import logging
from typing import TypedDict

logger = logging.getLogger(__name__)


_MAX_DATASETS = 40


class KnowledgeCatalogueEntry(TypedDict):
    id: str
    name: str
    description: str


def installed_dataset_keys(entries: list[KnowledgeCatalogueEntry]) -> set[str]:
    """
    Return the set of dataset ids available for the tenant. The validator in
    ``runner.py`` consults this set so a planner / builder that hallucinates a
    dataset id fails loudly at generation time instead of producing a
    runtime-broken graph.

    Mirrors ``tool_catalogue.installed_tool_keys`` — structured data travels
    alongside the formatted text so the validator never needs to recover ids
    from the prompt string via regex.
    """
    return {e["id"] for e in entries}


def format_knowledge_catalogue(entries: list[KnowledgeCatalogueEntry]) -> str:
    """Render knowledge bases as compact lines for planner-prompt injection."""
    if not entries:
        return ""
    lines = []
    for entry in entries:
        name = entry["name"].replace("\n", " ").strip()
        desc = entry["description"].replace("\n", " ").strip()
        if len(desc) > 120:
            desc = desc[:117] + "..."
        lines.append(f"- id={entry['id']} name={name} — {desc}")
    return "\n".join(lines)
