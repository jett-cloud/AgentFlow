"""Unit tests for the workflow generator knowledge catalogue."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.workflow.generator.resources.knowledge_catalogue import format_knowledge_catalogue
from services.workflow_assist.knowledge_catalogue_loader import build_knowledge_catalogue


def _dataset(index: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"dataset-{index:02d}",
        name=f"Dataset {index:02d}",
        description=f"Description {index}",
    )


class TestKnowledgeCatalogue:
    @patch("services.workflow_assist.knowledge_catalogue_loader.db.session")
    def test_empty_datasets_format_to_empty_string(self, mock_session: MagicMock):
        mock_session.scalars.return_value.all.return_value = []

        entries = build_knowledge_catalogue("tenant-1")

        assert entries == []
        assert format_knowledge_catalogue(entries) == ""

    @patch("services.workflow_assist.knowledge_catalogue_loader.db.session")
    def test_default_limit_applies_sql_limit(self, mock_session: MagicMock):
        mock_session.scalars.return_value.all.return_value = [_dataset(index) for index in range(40)]

        entries = build_knowledge_catalogue("tenant-1")

        assert len(entries) == 40
        stmt = mock_session.scalars.call_args[0][0]
        assert stmt._limit == 40

    @patch("services.workflow_assist.knowledge_catalogue_loader.db.session")
    def test_db_exception_returns_empty_list(self, mock_session: MagicMock):
        mock_session.scalars.side_effect = Exception("database unavailable")

        entries = build_knowledge_catalogue("tenant-1")

        assert entries == []

    @patch("services.workflow_assist.knowledge_catalogue_loader.db.session")
    def test_strict_snapshot_mode_surfaces_database_failure(self, mock_session: MagicMock):
        mock_session.scalars.side_effect = RuntimeError("database unavailable")

        with pytest.raises(RuntimeError, match="database unavailable"):
            build_knowledge_catalogue("tenant-1", limit=None, raise_on_error=True)

    @patch("services.workflow_assist.knowledge_catalogue_loader.db.session")
    def test_none_limit_returns_all_entries(self, mock_session: MagicMock):
        mock_session.scalars.return_value.all.return_value = [_dataset(index) for index in range(41)]

        entries = build_knowledge_catalogue("tenant-1", limit=None)

        assert len(entries) == 41

    def test_format_includes_dataset_id_and_name(self):
        catalogue = format_knowledge_catalogue(
            [{"id": "dataset-1", "name": "Product Docs", "description": "Current product documentation."}]
        )

        assert "id=dataset-1" in catalogue
        assert "name=Product Docs" in catalogue

    def test_format_strips_newlines_from_name_and_description(self):
        catalogue = format_knowledge_catalogue(
            [
                {
                    "id": "dataset-1",
                    "name": "Product\nDocs",
                    "description": "line1\nline2\nline3",
                }
            ]
        )

        assert catalogue == "- id=dataset-1 name=Product Docs — line1 line2 line3"

    def test_format_truncates_long_descriptions(self):
        long_desc = "x" * 200
        catalogue = format_knowledge_catalogue([{"id": "dataset-1", "name": "Product Docs", "description": long_desc}])

        assert catalogue.endswith("...")
        assert len(catalogue.split(" — ", 1)[1]) == 120
