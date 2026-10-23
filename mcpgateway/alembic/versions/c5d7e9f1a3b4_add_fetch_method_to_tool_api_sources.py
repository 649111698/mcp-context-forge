# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/c5d7e9f1a3b4_add_fetch_method_to_tool_api_sources.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Add fetch_method/request_body to tool_api_sources (POST support)

Revision ID: c5d7e9f1a3b4
Revises: b4c6d8e0f2a3
Create Date: 2026-08-27 11:00:00.000000
"""

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c5d7e9f1a3b4"
down_revision = "b4c6d8e0f2a3"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade():
    """Add fetch_method/request_body columns (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tool_api_sources" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("tool_api_sources")}
    if "fetch_method" not in columns:
        op.add_column("tool_api_sources", sa.Column("fetch_method", sa.String(length=10), nullable=False, server_default="GET"))
    if "request_body" not in columns:
        op.add_column("tool_api_sources", sa.Column("request_body", sa.Text(), nullable=True))


def downgrade():
    """Drop fetch_method/request_body columns (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tool_api_sources" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("tool_api_sources")}
    for column in ("request_body", "fetch_method"):
        if column in columns:
            op.drop_column("tool_api_sources", column)
