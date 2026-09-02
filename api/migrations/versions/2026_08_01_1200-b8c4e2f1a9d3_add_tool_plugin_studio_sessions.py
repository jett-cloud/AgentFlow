"""add tool plugin studio sessions

Revision ID: b8c4e2f1a9d3
Revises: 7a1c2d9e4b60
Create Date: 2026-08-01 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

import models

revision = "b8c4e2f1a9d3"
down_revision = "7a1c2d9e4b60"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tool_plugin_studio_sessions",
        sa.Column("id", models.types.StringUUID(), nullable=False),
        sa.Column("tenant_id", models.types.StringUUID(), nullable=False),
        sa.Column("account_id", models.types.StringUUID(), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False, server_default="creating"),
        sa.Column("plugin_locked_at", sa.DateTime(), nullable=True),
        sa.Column("author", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("plugin_name", sa.String(length=255), nullable=False),
        sa.Column("active_tool_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("tool_names_json", models.types.LongText(), nullable=False, server_default="[]"),
        sa.Column("files_json", models.types.LongText(), nullable=False, server_default="{}"),
        sa.Column("messages_json", models.types.LongText(), nullable=False, server_default="[]"),
        sa.Column("preview_json", models.types.LongText(), nullable=True),
        sa.Column("model_provider", sa.String(length=255), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("plugin_unique_identifier", sa.String(length=512), nullable=True),
        sa.Column("installation_id", sa.String(length=255), nullable=True),
        sa.Column("plugin_status", sa.String(length=32), nullable=False, server_default="idle"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="tool_plugin_studio_session_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "account_id",
            "plugin_name",
            name="unique_tool_plugin_studio_session_plugin",
        ),
    )
    op.create_index(
        "tool_plugin_studio_session_tenant_account_updated_idx",
        "tool_plugin_studio_sessions",
        ["tenant_id", "account_id", "updated_at"],
    )


def downgrade():
    op.drop_index(
        "tool_plugin_studio_session_tenant_account_updated_idx",
        table_name="tool_plugin_studio_sessions",
    )
    op.drop_table("tool_plugin_studio_sessions")
