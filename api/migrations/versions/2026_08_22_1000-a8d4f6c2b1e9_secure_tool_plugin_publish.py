"""secure tool plugin studio publishing

Revision ID: a8d4f6c2b1e9
Revises: w1a2b3c4d5e6
Create Date: 2026-08-22 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

import models

revision = "a8d4f6c2b1e9"
down_revision = "w1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tool_plugin_studio_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("revision", sa.Integer(), server_default=sa.text("0"), nullable=False))
        batch_op.add_column(
            sa.Column("published_files_json", models.types.LongText(), server_default="{}", nullable=False)
        )
        batch_op.add_column(sa.Column("last_publish_diagnostic_json", models.types.LongText(), nullable=True))

    op.execute(
        sa.text(
            "UPDATE tool_plugin_studio_sessions "
            "SET published_files_json = files_json "
            "WHERE plugin_status = 'installed' AND installation_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("tool_plugin_studio_sessions", schema=None) as batch_op:
        batch_op.drop_column("last_publish_diagnostic_json")
        batch_op.drop_column("published_files_json")
        batch_op.drop_column("revision")
