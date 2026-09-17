"""Expose the generator-visible knowledge catalogue for workflow-assist UI."""

from __future__ import annotations

from typing import Any, TypedDict

from core.workflow.generator.resources.knowledge_catalogue import _MAX_DATASETS, KnowledgeCatalogueEntry
from services.workflow_assist.knowledge_catalogue_loader import build_knowledge_catalogue


class AssistKnowledgeCatalogue(TypedDict):
    datasets: list[KnowledgeCatalogueEntry]
    truncated: bool
    max_datasets: int
    total_before_cap: int


def list_assist_knowledge_catalogue(tenant_id: str) -> AssistKnowledgeCatalogue:
    """
    Return the same installed knowledge-base inventory the planner sees.

    Fetches the uncapped catalogue, then applies the generator's
    ``_MAX_DATASETS`` cap so the UI can show ``truncated`` when entries were
    dropped.
    """
    all_datasets = build_knowledge_catalogue(tenant_id, limit=None)
    total_before_cap = len(all_datasets)
    max_datasets = _MAX_DATASETS
    truncated = total_before_cap > max_datasets
    datasets: list[KnowledgeCatalogueEntry] = all_datasets[:max_datasets]
    return AssistKnowledgeCatalogue(
        datasets=datasets,
        truncated=truncated,
        max_datasets=max_datasets,
        total_before_cap=total_before_cap,
    )


def list_assist_knowledge_catalogue_as_dict(tenant_id: str) -> dict[str, Any]:
    """JSON-serializable form of :func:`list_assist_knowledge_catalogue`."""
    return dict(list_assist_knowledge_catalogue(tenant_id))
