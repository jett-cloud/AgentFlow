"""add workflow assist resumable runs

Revision ID: b7d9e3f5a1c4
Revises: a8d4f6c2b1e9
Create Date: 2026-08-25 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

import models

revision = "b7d9e3f5a1c4"
down_revision = "a8d4f6c2b1e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_assist_conversations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("latest_run_id", models.types.StringUUID(), nullable=True))
        batch_op.add_column(sa.Column("completion_run_id", models.types.StringUUID(), nullable=True))
        batch_op.add_column(sa.Column("completion_epoch", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("completion_candidate_revision", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("completion_candidate_base_hash", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(sa.Column("completion_app_mode", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("completion_assertion", sa.String(length=64), nullable=True))

    op.create_table(
        "workflow_assist_runs",
        sa.Column("id", models.types.StringUUID(), nullable=False),
        sa.Column("tenant_id", models.types.StringUUID(), nullable=False),
        sa.Column("app_id", models.types.StringUUID(), nullable=False),
        sa.Column("created_by", models.types.StringUUID(), nullable=False),
        sa.Column("conversation_id", models.types.StringUUID(), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column(
            "input",
            models.types.LimitedLongText(max_bytes=65536, field_name="input"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("model_config", models.types.AdjustedJSON(), nullable=False),
        sa.Column("selected_node", sa.String(length=255), nullable=True),
        sa.Column("next_event_sequence", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("queued_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("termination_reason", sa.String(length=64), nullable=True),
        sa.Column("candidate_revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("id", name="workflow_assist_run_pkey"),
    )
    op.create_index(
        "workflow_assist_run_owner_conversation_epoch_idx",
        "workflow_assist_runs",
        ["tenant_id", "app_id", "created_by", "conversation_id", "epoch"],
    )
    op.create_index(
        "workflow_assist_run_queue_reaper_idx",
        "workflow_assist_runs",
        ["status", "queued_at"],
    )
    op.create_index(
        "workflow_assist_run_heartbeat_reaper_idx",
        "workflow_assist_runs",
        ["status", "heartbeat_at"],
    )

    op.create_table(
        "workflow_assist_run_events",
        sa.Column("id", models.types.StringUUID(), nullable=False),
        sa.Column("tenant_id", models.types.StringUUID(), nullable=False),
        sa.Column("app_id", models.types.StringUUID(), nullable=False),
        sa.Column("created_by", models.types.StringUUID(), nullable=False),
        sa.Column("conversation_id", models.types.StringUUID(), nullable=False),
        sa.Column("run_id", models.types.StringUUID(), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.String(length=255), nullable=False),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column(
            "payload",
            models.types.LimitedAdjustedJSON(max_bytes=262144, field_name="event payload"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("id", name="workflow_assist_run_event_pkey"),
        sa.UniqueConstraint(
            "run_id",
            "sequence",
            name="workflow_assist_run_event_run_sequence_unique",
        ),
        sa.UniqueConstraint(
            "run_id",
            "step_id",
            name="workflow_assist_run_event_run_step_unique",
        ),
    )
    op.create_index(
        "workflow_assist_run_event_owner_timeline_idx",
        "workflow_assist_run_events",
        ["tenant_id", "app_id", "created_by", "conversation_id", "epoch", "sequence"],
    )


def downgrade() -> None:
    op.drop_index(
        "workflow_assist_run_event_owner_timeline_idx",
        table_name="workflow_assist_run_events",
    )
    op.drop_table("workflow_assist_run_events")
    op.drop_index("workflow_assist_run_heartbeat_reaper_idx", table_name="workflow_assist_runs")
    op.drop_index("workflow_assist_run_queue_reaper_idx", table_name="workflow_assist_runs")
    op.drop_index("workflow_assist_run_owner_conversation_epoch_idx", table_name="workflow_assist_runs")
    op.drop_table("workflow_assist_runs")

    with op.batch_alter_table("workflow_assist_conversations", schema=None) as batch_op:
        batch_op.drop_column("completion_assertion")
        batch_op.drop_column("completion_app_mode")
        batch_op.drop_column("completion_candidate_base_hash")
        batch_op.drop_column("completion_candidate_revision")
        batch_op.drop_column("completion_epoch")
        batch_op.drop_column("completion_run_id")
        batch_op.drop_column("latest_run_id")
