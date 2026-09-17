"""cast workflow assist active_run_id to uuid

Revision ID: c8e2a4b6d0f1
Revises: b7d9e3f5a1c4
Create Date: 2026-08-27 00:35:00.000000
"""

import sqlalchemy as sa
from alembic import op

import models

revision = "c8e2a4b6d0f1"
down_revision = "b7d9e3f5a1c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "workflow_assist_conversations",
        "active_run_id",
        existing_type=sa.String(length=255),
        type_=models.types.StringUUID(),
        existing_nullable=True,
        postgresql_using="NULLIF(active_run_id, '')::uuid",
    )


def downgrade() -> None:
    op.alter_column(
        "workflow_assist_conversations",
        "active_run_id",
        existing_type=models.types.StringUUID(),
        type_=sa.String(length=255),
        existing_nullable=True,
        postgresql_using="active_run_id::text",
    )
