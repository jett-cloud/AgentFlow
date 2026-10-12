"""Persist the latest tool-plugin publish build trace.

Revision ID: 4c8e1a7d2b90
Revises: 3b7e9c2d4f10
"""

import sqlalchemy as sa
from alembic import op

revision = "4c8e1a7d2b90"
down_revision = "3b7e9c2d4f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tool_plugin_studio_sessions") as batch_op:
        batch_op.add_column(sa.Column("last_publish_trace_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tool_plugin_studio_sessions") as batch_op:
        batch_op.drop_column("last_publish_trace_json")
