# -*- coding: utf-8 -*-
# Copyright (c) 2026 IBM Corp. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# pylint: disable=no-name-in-module

"""Location: ./mcpgateway/services/tool_api_source_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tool API Source Service.

Manages saved MCP API tool definitions ("tool API sources") and keeps the
tool catalog in sync with them. A source stores the raw tool JSON (a single
tool definition or an array of definitions). Syncing a source upserts tools
by name: a tool whose name already exists is overwritten with the stored
definition (including its URL), otherwise a new tool is registered. This
avoids re-pasting tool JSON into the import dialog every time it changes.
"""

# Standard
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

# Third-Party
import orjson
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import ToolApiSource
from mcpgateway.schemas import ToolCreate, ToolUpdate
from mcpgateway.services.tool_service import tool_service, ToolError

logger = logging.getLogger(__name__)

# Fields copied from stored JSON into ToolCreate/ToolUpdate. Ownership and
# scope fields (team_id, owner_email, visibility, id) are deliberately absent:
# authorization derives from the syncing user, never from stored payloads.
_CREATE_FIELDS = frozenset(
    {
        "name",
        "displayName",
        "title",
        "url",
        "description",
        "integration_type",
        "request_type",
        "headers",
        "input_schema",
        "output_schema",
        "annotations",
        "extension_metadata",
        "jsonpath_filter",
        "auth",
        "auth_headers",
        "tags",
        "deprecated",
        "base_url",
        "path_template",
        "query_mapping",
        "header_mapping",
        "timeout_ms",
        "expose_passthrough",
        "allowlist",
        "plugin_chain_pre",
        "plugin_chain_post",
    }
)


class ToolApiSourceValidationError(Exception):
    """Raised when a tool API source payload fails validation.

    Examples:
        >>> error = ToolApiSourceValidationError("bad json")
        >>> str(error)
        'bad json'
    """


class ToolApiSourceNotFoundError(Exception):
    """Raised when a tool API source cannot be found by id."""


class ToolApiSourceService:
    """CRUD + sync service for saved MCP API tool definitions."""

    def parse_content(self, content: str) -> List[Dict[str, Any]]:
        """Parse and validate stored tool JSON.

        Args:
            content: Raw JSON text - a single tool definition object or an
                array of tool definition objects.

        Returns:
            List of tool definition dictionaries.

        Raises:
            ToolApiSourceValidationError: If the JSON is malformed or any
                definition is missing the required ``name``/``url`` fields.

        Examples:
            >>> svc = ToolApiSourceService()
            >>> svc.parse_content('{"name": "t1", "url": "http://x"}')[0]["name"]
            't1'
            >>> len(svc.parse_content('[{"name": "a", "url": "u"}, {"name": "b", "url": "u"}]'))
            2
        """
        if not content or not content.strip():
            raise ToolApiSourceValidationError("Tool JSON is empty")
        try:
            payload = orjson.loads(content)
        except orjson.JSONDecodeError as ex:
            raise ToolApiSourceValidationError(f"Invalid JSON: {ex}") from ex

        items = payload if isinstance(payload, list) else [payload]
        if not items:
            raise ToolApiSourceValidationError("Tool JSON array is empty")

        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ToolApiSourceValidationError(f"Tool definition #{index + 1} must be a JSON object")
            name = item.get("name")
            if not name or not isinstance(name, str) or not name.strip():
                raise ToolApiSourceValidationError(f"Tool definition #{index + 1} is missing a 'name'")
            if not item.get("url"):
                raise ToolApiSourceValidationError(f"Tool '{name}' is missing a 'url'")
        return items

    def summarize_content(self, content: str) -> Dict[str, Any]:
        """Derive display metadata from stored tool JSON.

        Args:
            content: Raw stored JSON text.

        Returns:
            Dict with ``tool_count``, ``names`` (first few tool names) and
            ``first_url``; on parse failure a dict with ``error`` set.

        Examples:
            >>> svc = ToolApiSourceService()
            >>> summary = svc.summarize_content('{"name": "t1", "url": "http://x"}')
            >>> summary["tool_count"], summary["first_url"]
            (1, 'http://x')
            >>> svc.summarize_content("not json")["error"].startswith("Invalid JSON")
            True
        """
        try:
            items = self.parse_content(content)
        except ToolApiSourceValidationError as ex:
            return {"error": str(ex)}
        return {
            "tool_count": len(items),
            "names": [str(item.get("name", "")) for item in items[:5]],
            "first_url": str(items[0].get("url", "")),
        }

    def derive_display_name(self, content: str) -> str:
        """Derive a default display name from the stored tool JSON.

        Args:
            content: Raw stored JSON text.

        Returns:
            First tool name, suffixed with the extra count for arrays.

        Examples:
            >>> svc = ToolApiSourceService()
            >>> svc.derive_display_name('{"name": "queryCustomer", "url": "http://x"}')
            'queryCustomer'
            >>> svc.derive_display_name('[{"name": "a", "url": "u"}, {"name": "b", "url": "u"}]')
            'a (+1)'
        """
        try:
            items = self.parse_content(content)
        except ToolApiSourceValidationError:
            return "Untitled API"
        first = str(items[0].get("name", "Untitled API"))
        extra = len(items) - 1
        return f"{first} (+{extra})" if extra > 0 else first

    def list_sources(self, db: Session) -> List[ToolApiSource]:
        """List all saved tool API sources, newest first.

        Args:
            db: Database session.

        Returns:
            List of ToolApiSource rows.
        """
        return list(db.execute(select(ToolApiSource).order_by(ToolApiSource.created_at.desc(), ToolApiSource.id.desc())).scalars().all())

    def get_source(self, db: Session, source_id: str) -> ToolApiSource:
        """Fetch a single tool API source.

        Args:
            db: Database session.
            source_id: Source id.

        Returns:
            The ToolApiSource row.

        Raises:
            ToolApiSourceNotFoundError: If no row matches the id.

        Examples:
            >>> svc = ToolApiSourceService()
            >>> try:
            ...     import asyncio
            ...     from unittest.mock import MagicMock
            ...     db = MagicMock()
            ...     db.execute.return_value.scalars.return_value.one_or_none.return_value = None
            ...     asyncio.run(svc.get_source(db, "missing"))
            ... except ToolApiSourceNotFoundError as e:
            ...     "not found" in str(e).lower()
            True
        """
        source = db.execute(select(ToolApiSource).where(ToolApiSource.id == source_id)).scalars().one_or_none()
        if not source:
            raise ToolApiSourceNotFoundError(f"Tool API source not found: {source_id}")
        return source

    def create_source(self, db: Session, display_name: Optional[str], description: Optional[str], content: str, enabled: bool, owner_email: Optional[str]) -> ToolApiSource:
        """Validate and save a new tool API source.

        Args:
            db: Database session.
            display_name: Optional label; derived from the JSON when blank.
            description: Optional free-text note.
            content: Raw tool JSON text.
            enabled: Whether ``sync_all`` includes this source.
            owner_email: Creator email.

        Returns:
            The created ToolApiSource row.

        Raises:
            ToolApiSourceValidationError: If the tool JSON is invalid.
        """
        self.parse_content(content)
        source = ToolApiSource(
            display_name=(display_name or "").strip() or self.derive_display_name(content),
            description=(description or "").strip() or None,
            content=content.strip(),
            enabled=enabled,
            owner_email=owner_email,
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        logger.info("Created tool API source %s (%s)", source.id, source.display_name)
        return source

    def update_source(self, db: Session, source_id: str, display_name: Optional[str], description: Optional[str], content: str, enabled: bool) -> ToolApiSource:
        """Update an existing tool API source.

        Args:
            db: Database session.
            source_id: Source id.
            display_name: Optional label; derived from the JSON when blank.
            description: Optional free-text note.
            content: Raw tool JSON text.
            enabled: Whether ``sync_all`` includes this source.

        Returns:
            The updated ToolApiSource row.

        Raises:
            ToolApiSourceNotFoundError: If the source does not exist.
            ToolApiSourceValidationError: If the tool JSON is invalid.
        """
        source = self.get_source(db, source_id)
        self.parse_content(content)
        source.display_name = (display_name or "").strip() or self.derive_display_name(content)
        source.description = (description or "").strip() or None
        source.content = content.strip()
        source.enabled = enabled
        db.commit()
        db.refresh(source)
        logger.info("Updated tool API source %s (%s)", source.id, source.display_name)
        return source

    def delete_source(self, db: Session, source_id: str) -> str:
        """Delete a tool API source (tools created by syncing are kept).

        Args:
            db: Database session.
            source_id: Source id.

        Returns:
            The display name of the deleted source.

        Raises:
            ToolApiSourceNotFoundError: If the source does not exist.
        """
        source = self.get_source(db, source_id)
        display_name = source.display_name
        db.delete(source)
        db.commit()
        logger.info("Deleted tool API source %s (%s)", source_id, display_name)
        return display_name

    async def sync_source(self, db: Session, source_id: str, user_email: Optional[str] = None) -> Dict[str, Any]:
        """Upsert tools from a saved source, matching existing tools by name.

        For each tool definition in the stored JSON: a local (non-gateway)
        tool with the same name is overwritten with the stored definition;
        otherwise the tool is registered. Gateway-managed tools are skipped
        because gateways own their tool definitions.

        Args:
            db: Database session.
            source_id: Source id.
            user_email: Email of the user running the sync (audit trail).

        Returns:
            Dict with ``created``, ``updated``, ``skipped``, ``failed`` counts,
            ``errors`` list and a human-readable ``summary``.

        Raises:
            ToolApiSourceNotFoundError: If the source does not exist.
            ToolApiSourceValidationError: If the stored JSON no longer parses.
        """
        source = self.get_source(db, source_id)
        items = self.parse_content(source.content)

        created, updated, skipped, failed = 0, 0, 0, 0
        errors: List[str] = []

        for item in items:
            name = str(item.get("name", "")).strip()
            try:
                existing = db.execute(select(DbTool).where(DbTool.original_name == name, DbTool.gateway_id.is_(None)).order_by(DbTool.enabled.desc(), DbTool.created_at.asc())).scalars().first()

                if existing is not None and existing.gateway_id is not None:
                    skipped += 1
                    errors.append(f"Tool '{name}' is managed by a gateway; skipped")
                    continue

                payload = {key: value for key, value in item.items() if key in _CREATE_FIELDS}

                if existing is not None:
                    await tool_service.update_tool(
                        db,
                        existing.id,
                        ToolUpdate(**payload),
                        modified_by=user_email,
                        modified_via="tool-api-sync",
                    )
                    updated += 1
                    logger.info("Tool API sync updated tool '%s' (%s)", name, existing.id)
                else:
                    if "integration_type" not in payload and "request_type" not in payload:
                        payload["integration_type"] = "REST"
                        payload["request_type"] = "GET"
                    await tool_service.register_tool(
                        db,
                        ToolCreate(**payload),
                        created_by=user_email,
                        created_via="tool-api-sync",
                    )
                    created += 1
                    logger.info("Tool API sync created tool '%s'", name)
            except (ValidationError, ToolError) as ex:
                failed += 1
                errors.append(f"Tool '{name}': {ex}")
                logger.warning("Tool API sync failed for tool '%s': %s", name, ex)
            except Exception as ex:  # pylint: disable=broad-exception-caught
                failed += 1
                errors.append(f"Tool '{name}': {ex}")
                logger.error("Tool API sync error for tool '%s': %s", name, ex)

        summary = self._format_summary(created, updated, skipped, failed, errors)
        source.last_synced_at = datetime.now(timezone.utc)
        source.last_sync_result = summary
        db.commit()

        logger.info("Tool API source '%s' synced: %s", source.display_name, summary)
        return {"created": created, "updated": updated, "skipped": skipped, "failed": failed, "errors": errors, "summary": summary}

    async def sync_all(self, db: Session, user_email: Optional[str] = None) -> Dict[str, Any]:
        """Sync every enabled tool API source.

        Args:
            db: Database session.
            user_email: Email of the user running the sync (audit trail).

        Returns:
            Aggregated dict with ``created``, ``updated``, ``skipped``,
            ``failed`` counts, per-source ``results`` and a ``summary``.
        """
        totals = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
        results: List[Dict[str, Any]] = []
        for source in self.list_sources(db):
            if not source.enabled:
                continue
            result = await self.sync_source(db, source.id, user_email=user_email)
            results.append({"display_name": source.display_name, **{key: result[key] for key in ("created", "updated", "skipped", "failed")}})
            for key in totals:
                totals[key] += result[key]

        errors_note = "" if totals["failed"] == 0 else f", {totals['failed']} failed"
        summary = f"Sync all: {totals['created']} created, {totals['updated']} updated, {totals['skipped']} skipped{errors_note} across {len(results)} source(s)"
        return {**totals, "results": results, "summary": summary}

    @staticmethod
    def _format_summary(created: int, updated: int, skipped: int, failed: int, errors: List[str]) -> str:
        """Build the persisted one-line sync result for a source.

        Args:
            created: Tools created.
            updated: Tools updated.
            skipped: Tools skipped.
            failed: Tools failed.
            errors: Per-tool error messages.

        Returns:
            Compact summary text, first error appended when present.

        Examples:
            >>> ToolApiSourceService._format_summary(1, 2, 0, 0, [])
            '1 created, 2 updated, 0 skipped'
            >>> ToolApiSourceService._format_summary(0, 0, 0, 1, ["Tool 'x': boom"])
            "0 created, 0 updated, 0 skipped, 1 failed — Tool 'x': boom"
        """
        base = f"{created} created, {updated} updated, {skipped} skipped"
        if failed:
            first_error = errors[0] if errors else "unknown error"
            return f"{base}, {failed} failed — {first_error}"
        return base


tool_api_source_service = ToolApiSourceService()
