"""drop unique constraint on tool plugin studio session plugin_name

Revision ID: e7f6a5b4c3d2
Revises: c9d5f3a2b8e4
Create Date: 2026-08-05 11:05:00.000000

"""

from alembic import op

revision = "e7f6a5b4c3d2"
down_revision = "c9d5f3a2b8e4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tool_plugin_studio_sessions", schema=None) as batch_op:
        batch_op.drop_constraint("unique_tool_plugin_studio_session_plugin", type_="unique")
        batch_op.create_index(
            "tool_plugin_studio_session_tenant_account_plugin_idx",
            ["tenant_id", "account_id", "plugin_name"],
        )


def downgrade():
    with op.batch_alter_table("tool_plugin_studio_sessions", schema=None) as batch_op:
        batch_op.drop_index("tool_plugin_studio_session_tenant_account_plugin_idx")
        batch_op.create_unique_constraint(
            "unique_tool_plugin_studio_session_plugin",
            ["tenant_id", "account_id", "plugin_name"],
        )
