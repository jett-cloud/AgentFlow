from __future__ import annotations

from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[3] / "migrations" / "versions"
PARENT_REVISION = "b7d9e3f5a1c4"


def _followup_migration() -> tuple[Path, str]:
    matches: list[tuple[Path, str]] = []
    for path in VERSIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if f'down_revision = "{PARENT_REVISION}"' in text or f"down_revision = '{PARENT_REVISION}'" in text:
            matches.append((path, text))
    assert matches, f"missing follow-up migration after {PARENT_REVISION}"
    assert len(matches) == 1, f"expected one follow-up after {PARENT_REVISION}, found {len(matches)}"
    return matches[0]


def test_followup_casts_active_run_id_to_uuid_with_using() -> None:
    _path, text = _followup_migration()
    assert '"active_run_id"' in text
    assert "postgresql_using" in text
    assert "NULLIF(active_run_id, '')::uuid" in text
    assert "latest_run_id" not in text
