"""add workflow assist contract state

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-13 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

import models

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable fields so pre-migration conversations remain legacy."""
    with op.batch_alter_table("workflow_assist_conversations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("contract_protocol_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("workflow_contract", models.types.AdjustedJSON(), nullable=True))
        batch_op.add_column(sa.Column("contract_revision", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("contract_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("completion_contract_protocol_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("completion_contract_revision", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("completion_contract_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("completion_graph_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("completion_validation_version", sa.Integer(), nullable=True))
    with op.batch_alter_table("workflow_assist_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("contract_protocol_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("contract_rollout_stage", sa.String(length=32), nullable=True))


def downgrade() -> None:
    """Remove contract state without touching candidate graph history."""
    with op.batch_alter_table("workflow_assist_runs", schema=None) as batch_op:
        batch_op.drop_column("contract_rollout_stage")
        batch_op.drop_column("contract_protocol_version")
    with op.batch_alter_table("workflow_assist_conversations", schema=None) as batch_op:
        batch_op.drop_column("completion_validation_version")
        batch_op.drop_column("completion_graph_hash")
        batch_op.drop_column("completion_contract_hash")
        batch_op.drop_column("completion_contract_revision")
        batch_op.drop_column("completion_contract_protocol_version")
        batch_op.drop_column("contract_hash")
        batch_op.drop_column("contract_revision")
        batch_op.drop_column("workflow_contract")
        batch_op.drop_column("contract_protocol_version")
