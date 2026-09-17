"""Bridge databases that applied the retired MCP Studio migration chain.

Revision ID: f6a7b8c9d0e1
Revises: d4e5f6a7b8c9
Create Date: 2026-08-28 10:00:00.000000

Some development databases reached this revision through two temporary MCP
Studio migrations. The next revision drops that temporary table, so replaying
those schema changes for new databases has no lasting effect. Keeping this
revision as a no-op preserves the recorded version and reconnects both database
histories without stamping past any current schema changes.
"""

revision = "f6a7b8c9d0e1"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
