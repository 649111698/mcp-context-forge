# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/a3b5c7d9e1f2_add_tool_api_sources.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add tool_api_sources table for saved MCP API tool definitions

Revision ID: a3b5c7d9e1f2
Revises: 12d4a0c7789c
Create Date: 2026-08-27 10:00:00.000000
"""

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a3b5c7d9e1f2"
down_revision = "12d4a0c7789c"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade():
    """Create tool_api_sources table (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tool_api_sources" in inspector.get_table_names():
        return

    op.create_table(
        "tool_api_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("owner_email", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_result", sa.Text(), nullable=True),
    )


def downgrade():
    """Drop tool_api_sources table (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tool_api_sources" not in inspector.get_table_names():
        return

    op.drop_table("tool_api_sources")
