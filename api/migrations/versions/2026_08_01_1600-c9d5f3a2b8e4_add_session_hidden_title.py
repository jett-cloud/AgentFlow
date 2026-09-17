"""add is_hidden and title to tool plugin studio sessions

Revision ID: c9d5f3a2b8e4
Revises: b8c4e2f1a9d3
Create Date: 2026-08-01 16:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "c9d5f3a2b8e4"
down_revision = "b8c4e2f1a9d3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tool_plugin_studio_sessions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_hidden", sa.Boolean(), server_default=sa.text("false"), nullable=False)
        )
        batch_op.add_column(sa.Column("title", sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table("tool_plugin_studio_sessions", schema=None) as batch_op:
        batch_op.drop_column("title")
        batch_op.drop_column("is_hidden")
