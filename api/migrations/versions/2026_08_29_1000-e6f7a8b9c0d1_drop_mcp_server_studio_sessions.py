"""drop local MCP Server Studio session storage

Revision ID: e6f7a8b9c0d1
Revises: f6a7b8c9d0e1
Create Date: 2026-08-29 10:00:00.000000
"""

from alembic import op

revision = "e6f7a8b9c0d1"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Remove storage used exclusively by the retired local generator."""
    op.execute("DROP TABLE IF EXISTS mcp_server_studio_sessions")


def downgrade() -> None:
    """The retired session data is intentionally not recreated on downgrade."""
    pass
