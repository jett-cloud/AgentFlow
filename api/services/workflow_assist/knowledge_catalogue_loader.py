"""Tenant-scoped knowledge catalogue loading."""

import logging

from sqlalchemy import select

from extensions.ext_database import db
from models.dataset import Dataset

logger = logging.getLogger(__name__)

from core.workflow.generator.resources.knowledge_catalogue import _MAX_DATASETS, KnowledgeCatalogueEntry


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
