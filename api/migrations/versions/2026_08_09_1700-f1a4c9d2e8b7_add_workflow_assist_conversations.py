"""add workflow assist conversations

Revision ID: f1a4c9d2e8b7
Revises: e7f6a5b4c3d2
Create Date: 2026-08-09 17:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

import models


revision = "f1a4c9d2e8b7"
down_revision = "e7f6a5b4c3d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_assist_conversations",
        sa.Column("id", models.types.StringUUID(), nullable=False),
        sa.Column("tenant_id", models.types.StringUUID(), nullable=False),
        sa.Column("app_id", models.types.StringUUID(), nullable=False),
        sa.Column("account_id", models.types.StringUUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False, server_default="New workflow chat"),
        sa.Column("draft_hash", sa.String(length=255), nullable=True),
        sa.Column("state", models.types.AdjustedJSON(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("id", name="workflow_assist_conversation_pkey"),
    )
    op.create_index(
        "workflow_assist_conversation_owner_updated_idx",
        "workflow_assist_conversations",
        ["tenant_id", "app_id", "account_id", "is_deleted", "updated_at"],
    )
    op.create_table(
        "workflow_assist_messages",
        sa.Column("id", models.types.StringUUID(), nullable=False),
        sa.Column("tenant_id", models.types.StringUUID(), nullable=False),
        sa.Column("app_id", models.types.StringUUID(), nullable=False),
        sa.Column("account_id", models.types.StringUUID(), nullable=False),
        sa.Column("conversation_id", models.types.StringUUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("payload", models.types.AdjustedJSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("id", name="workflow_assist_message_pkey"),
        sa.UniqueConstraint("conversation_id", "sequence", name="workflow_assist_message_conversation_sequence_unique"),
    )
    op.create_index(
        "workflow_assist_message_conversation_sequence_idx",
        "workflow_assist_messages",
        ["conversation_id", "sequence"],
    )
    op.create_index(
        "workflow_assist_message_owner_idx",
        "workflow_assist_messages",
        ["tenant_id", "app_id", "account_id"],
    )


def downgrade() -> None:
    op.drop_index("workflow_assist_message_owner_idx", table_name="workflow_assist_messages")
    op.drop_index("workflow_assist_message_conversation_sequence_idx", table_name="workflow_assist_messages")
    op.drop_table("workflow_assist_messages")
    op.drop_index("workflow_assist_conversation_owner_updated_idx", table_name="workflow_assist_conversations")
    op.drop_table("workflow_assist_conversations")
