"""Upgrade/downgrade coverage for Workflow Assist contract persistence."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3] / "migrations/versions/2026_09_13_1000-f7a8b9c0d1e2_workflow_assist_contract.py"
)
_CONTRACT_COLUMNS = {
    "contract_protocol_version",
    "workflow_contract",
    "contract_revision",
    "contract_hash",
    "completion_contract_protocol_version",
    "completion_contract_revision",
    "completion_contract_hash",
    "completion_graph_hash",
    "completion_validation_version",
}
_RUN_CONTRACT_COLUMNS = {"contract_protocol_version", "contract_rollout_stage"}


def _load_migration():
    spec = importlib.util.spec_from_file_location("workflow_assist_contract_migration", _MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load workflow assist contract migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(module: object, engine: sa.Engine, step: str) -> None:
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        original = module.op
        module.op = operations
        try:
            getattr(module, step)()
        finally:
            module.op = original


def _pre_upgrade_engine() -> sa.Engine:
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "workflow_assist_conversations",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
    )
    sa.Table(
        "workflow_assist_runs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.text("INSERT INTO workflow_assist_conversations (id, title) VALUES ('legacy-1', 'Legacy')")
        )
    return engine


def test_upgrade_preserves_legacy_row_with_null_contract_state() -> None:
    engine = _pre_upgrade_engine()
    module = _load_migration()

    _run(module, engine, "upgrade")

    columns = {column["name"]: column for column in sa.inspect(engine).get_columns("workflow_assist_conversations")}
    assert columns.keys() >= _CONTRACT_COLUMNS
    assert all(columns[name]["nullable"] for name in _CONTRACT_COLUMNS)
    run_columns = {column["name"] for column in sa.inspect(engine).get_columns("workflow_assist_runs")}
    assert run_columns >= _RUN_CONTRACT_COLUMNS
    with engine.begin() as connection:
        row = connection.execute(
            sa.text(
                "SELECT contract_protocol_version, contract_revision, workflow_contract "
                "FROM workflow_assist_conversations WHERE id = 'legacy-1'"
            )
        ).one()
    assert tuple(row) == (None, None, None)


def test_downgrade_removes_all_contract_columns() -> None:
    engine = _pre_upgrade_engine()
    module = _load_migration()
    _run(module, engine, "upgrade")

    _run(module, engine, "downgrade")

    columns = {column["name"] for column in sa.inspect(engine).get_columns("workflow_assist_conversations")}
    run_columns = {column["name"] for column in sa.inspect(engine).get_columns("workflow_assist_runs")}
    assert _CONTRACT_COLUMNS.isdisjoint(columns)
    assert _RUN_CONTRACT_COLUMNS.isdisjoint(run_columns)
    assert {"id", "title"} <= columns
