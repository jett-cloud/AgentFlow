"""Add durable asynchronous tool-plugin publish jobs.

Revision ID: 6d9f3b8a1c20
Revises: 4c8e1a7d2b90
"""

import sqlalchemy as sa
from alembic import op

revision = "6d9f3b8a1c20"
down_revision = "4c8e1a7d2b90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_plugin_publish_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("publish_mode", sa.String(length=16), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("encrypted_credentials_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("attempt_id", sa.String(length=36), nullable=True),
        sa.Column("candidate_id", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("trace_json", sa.Text(), nullable=True),
        sa.Column("diagnostic_json", sa.Text(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.current_timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="tool_plugin_publish_job_pkey"),
    )
    op.create_index(
        "tool_plugin_publish_job_session_created_idx",
        "tool_plugin_publish_jobs",
        ["session_id", "created_at"],
    )
    op.create_index(
        "tool_plugin_publish_job_status_lease_idx",
        "tool_plugin_publish_jobs",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("tool_plugin_publish_job_status_lease_idx", table_name="tool_plugin_publish_jobs")
    op.drop_index("tool_plugin_publish_job_session_created_idx", table_name="tool_plugin_publish_jobs")
    op.drop_table("tool_plugin_publish_jobs")
