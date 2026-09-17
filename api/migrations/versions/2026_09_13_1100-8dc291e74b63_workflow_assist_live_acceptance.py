"""Persist single-use Workflow Assist live execution grants.

Revision ID: 8dc291e74b63
Revises: f7a8b9c0d1e2
"""

import sqlalchemy as sa
from alembic import op

from models.types import AdjustedJSON

revision = "8dc291e74b63"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_assist_runs") as batch_op:
        batch_op.add_column(sa.Column("live_acceptance", AdjustedJSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workflow_assist_runs") as batch_op:
        batch_op.drop_column("live_acceptance")
