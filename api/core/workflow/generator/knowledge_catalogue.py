"""
Knowledge-base catalogue for the workflow generator planner.

Returns a compact, LLM-readable inventory of a tenant's datasets. The planner
uses exact dataset ids from this list when it plans ``knowledge-retrieval``
nodes. The list is capped to keep the planner prompt bounded; failures degrade
to an empty catalogue so generation remains available.
"""

import logging
from typing import TypedDict

from sqlalchemy import select

from extensions.ext_database import db
from models.dataset import Dataset

logger = logging.getLogger(__name__)


_MAX_DATASETS = 40


class KnowledgeCatalogueEntry(TypedDict):
    id: str
    name: str
    description: str


def build_knowledge_catalogue(
    tenant_id: str,
    *,
    limit: int | None = _MAX_DATASETS,
    raise_on_error: bool = False,
) -> list[KnowledgeCatalogueEntry]:
    """
    Enumerate datasets available to a tenant, ordered by name.

    Failures querying datasets are logged and return an empty catalogue so a
    temporary database problem does not prevent workflow generation. Snapshot
    callers pass ``raise_on_error=True`` when they need to distinguish an
    unavailable catalogue from a successful empty result. Pass ``limit=None``
    to return the complete planner authorization snapshot.
    """
    try:
        stmt = select(Dataset).where(Dataset.tenant_id == tenant_id).order_by(Dataset.name)
        if limit is not None:
            stmt = stmt.limit(limit)
        datasets = db.session.scalars(stmt).all()
    except Exception:
        logger.exception("Workflow generator: failed to list knowledge bases for tenant %s", tenant_id)
        if raise_on_error:
            raise
        return []

    return [
        KnowledgeCatalogueEntry(
            id=str(dataset.id),
            name=dataset.name or "",
            description=dataset.description or "",
        )
        for dataset in datasets
    ]


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
