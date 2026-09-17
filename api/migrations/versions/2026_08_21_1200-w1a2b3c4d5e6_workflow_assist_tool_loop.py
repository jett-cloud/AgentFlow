"""add workflow assist tool-loop session columns

Revision ID: w1a2b3c4d5e6
Revises: f1a4c9d2e8b7
Create Date: 2026-08-21 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

import models


revision = "w1a2b3c4d5e6"
down_revision = "f1a4c9d2e8b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_assist_conversations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("candidate_graph", models.types.AdjustedJSON(), nullable=True))
        batch_op.add_column(sa.Column("candidate_revision", sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch_op.add_column(sa.Column("candidate_base_hash", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("compacted_until_sequence", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("compacted_state", models.types.AdjustedJSON(), nullable=True))
        batch_op.add_column(sa.Column("active_run_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("run_epoch", sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch_op.add_column(sa.Column("last_run_termination_reason", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workflow_assist_conversations", schema=None) as batch_op:
        batch_op.drop_column("last_run_termination_reason")
        batch_op.drop_column("run_epoch")
        batch_op.drop_column("active_run_id")
        batch_op.drop_column("compacted_state")
        batch_op.drop_column("compacted_until_sequence")
        batch_op.drop_column("candidate_base_hash")
        batch_op.drop_column("candidate_revision")
        batch_op.drop_column("candidate_graph")
