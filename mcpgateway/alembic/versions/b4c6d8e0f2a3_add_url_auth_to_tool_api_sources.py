# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/b4c6d8e0f2a3_add_url_auth_to_tool_api_sources.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add remote-fetch fields (source_url + auth) to tool_api_sources

Revision ID: b4c6d8e0f2a3
Revises: a3b5c7d9e1f2
Create Date: 2026-08-27 10:00:00.000000
"""

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b4c6d8e0f2a3"
down_revision = "a3b5c7d9e1f2"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade():
    """Add source_url/auth columns to tool_api_sources (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tool_api_sources" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("tool_api_sources")}
    if "source_url" not in columns:
        op.add_column("tool_api_sources", sa.Column("source_url", sa.String(length=767), nullable=True))
    if "auth_type" not in columns:
        op.add_column("tool_api_sources", sa.Column("auth_type", sa.String(length=20), nullable=False, server_default="none"))
    if "auth_header_key" not in columns:
        op.add_column("tool_api_sources", sa.Column("auth_header_key", sa.String(length=100), nullable=True))
    if "auth_credential" not in columns:
        op.add_column("tool_api_sources", sa.Column("auth_credential", sa.Text(), nullable=True))


def downgrade():
    """Drop source_url/auth columns from tool_api_sources (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tool_api_sources" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("tool_api_sources")}
    for column in ("auth_credential", "auth_header_key", "auth_type", "source_url"):
        if column in columns:
            op.drop_column("tool_api_sources", column)
