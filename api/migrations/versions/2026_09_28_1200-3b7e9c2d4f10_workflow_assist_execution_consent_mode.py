"""Persist the Workflow Assist execution consent mode per run.

Revision ID: 3b7e9c2d4f10
Revises: 8dc291e74b63
"""

import sqlalchemy as sa
from alembic import op

revision = "3b7e9c2d4f10"
down_revision = "8dc291e74b63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_assist_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "execution_consent_mode",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'always_ask'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("workflow_assist_runs") as batch_op:
        batch_op.drop_column("execution_consent_mode")
