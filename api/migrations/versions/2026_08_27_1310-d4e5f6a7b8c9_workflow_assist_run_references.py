"""add workflow assist run references

Revision ID: d4e5f6a7b8c9
Revises: c8e2a4b6d0f1
Create Date: 2026-08-27 13:10:00.000000
"""

import sqlalchemy as sa
from alembic import op

import models

revision = "d4e5f6a7b8c9"
down_revision = "c8e2a4b6d0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_assist_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("references", models.types.AdjustedJSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workflow_assist_runs", schema=None) as batch_op:
        batch_op.drop_column("references")
