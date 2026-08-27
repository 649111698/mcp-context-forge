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
import httpx
import orjson
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import ToolApiSource
from mcpgateway.schemas import ToolCreate, ToolUpdate
from mcpgateway.services.tool_service import tool_service, ToolError
from mcpgateway.utils.services_auth import decode_auth, encode_auth

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 15.0
_VALID_AUTH_TYPES = frozenset({"none", "bearer", "basic", "header"})

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
    """CRUD + sync service for saved MCP API tool definitions.

    Two modes per source:
    - remote (``source_url`` set): tool JSON is fetched from the URL on every
      sync, using the stored simple auth (none / bearer / basic / header).
      The last successful payload is kept in ``content`` as a snapshot.
    - manual (``source_url`` empty): the stored ``content`` JSON is used.
    """

    def validate_source_url(self, source_url: Optional[str]) -> Optional[str]:
        """Validate a remote source URL.

        Args:
            source_url: User-provided URL, or None/blank for manual mode.

        Returns:
            The normalized URL, or None when no URL was given.

        Raises:
            ToolApiSourceValidationError: If the URL is not http(s).

        Examples:
            >>> svc = ToolApiSourceService()
            >>> svc.validate_source_url(None) is None
            True
            >>> svc.validate_source_url("  ") is None
            True
            >>> svc.validate_source_url("https://x.example/tools.json")
            'https://x.example/tools.json'
            >>> try:
            ...     svc.validate_source_url("ftp://x/tools.json")
            ... except ToolApiSourceValidationError as e:
            ...     "http" in str(e)
            True
        """
        if not source_url or not source_url.strip():
            return None
        url = source_url.strip()
        if not url.lower().startswith(("http://", "https://")):
            raise ToolApiSourceValidationError("Source URL must start with http:// or https://")
        return url

    def _encode_credential(self, auth_type: str, auth_header_key: Optional[str], credential: Optional[str]) -> Optional[str]:
        """Encrypt a fetch credential for at-rest storage.

        Args:
            auth_type: One of none/bearer/basic/header.
            auth_header_key: Custom header name (header mode).
            credential: Secret value (token, "user:password", or header value).

        Returns:
            Encrypted auth blob, or None when nothing to store.

        Examples:
            >>> svc = ToolApiSourceService()
            >>> svc._encode_credential("none", None, "ignored") is None
            True
            >>> blob = svc._encode_credential("bearer", None, "tok")
            >>> blob and "tok" not in blob
            True
        """
        if auth_type == "none" or not credential:
            return None
        return encode_auth({"credential": credential, "header_key": auth_header_key})

    def _build_fetch_headers(self, source: ToolApiSource) -> Dict[str, str]:
        """Build request headers with the stored auth for a remote fetch.

        Args:
            source: Source row with auth_type/auth_credential.

        Returns:
            Headers dict (possibly empty for auth_type none).

        Examples:
            >>> svc = ToolApiSourceService()
            >>> class S:  # minimal fake row
            ...     auth_type = "none"; auth_credential = None; auth_header_key = None
            >>> svc._build_fetch_headers(S())
            {}
        """
        if not source.auth_credential or source.auth_type in (None, "", "none"):
            return {}
        try:
            data = decode_auth(source.auth_credential)
            credential = data.get("credential", "")
            header_key = data.get("header_key") or source.auth_header_key
        except Exception as ex:  # pylint: disable=broad-exception-caught
            raise ToolApiSourceValidationError(f"Failed to decrypt stored credential: {ex}") from ex

        if source.auth_type == "bearer":
            return {"Authorization": f"Bearer {credential}"}
        if source.auth_type == "basic":
            import base64  # pylint: disable=import-outside-toplevel

            b64 = base64.b64encode(credential.encode("utf-8")).decode("ascii")
            return {"Authorization": f"Basic {b64}"}
        if source.auth_type == "header":
            if not header_key:
                raise ToolApiSourceValidationError("Custom header auth requires a header name")
            return {header_key: credential}
        return {}

    async def fetch_content(self, source: ToolApiSource) -> str:
        """Fetch tool JSON from a remote source URL using stored auth.

        Args:
            source: Source row with a source_url configured.

        Returns:
            The response body text.

        Raises:
            ToolApiSourceValidationError: On connection errors, non-2xx
                responses or auth misconfiguration.

        Examples:
            >>> import asyncio
            >>> svc = ToolApiSourceService()
            >>> class S:
            ...     source_url = None; auth_type = "none"
            ...     auth_credential = None; auth_header_key = None
            >>> try:
            ...     asyncio.run(svc.fetch_content(S()))
            ... except ToolApiSourceValidationError as e:
            ...     "no source URL" in str(e)
            True
        """
        if not source.source_url:
            raise ToolApiSourceValidationError("Source has no source URL")
        headers = self._build_fetch_headers(source)
        method = (source.fetch_method or "GET").upper()
        json_body = self._parse_request_body(method, source.request_body)
        return await self._fetch_url(source.source_url, headers, method=method, json_body=json_body)

    async def fetch_url_content(
        self, source_url: str, auth_type: str = "none", auth_credential: Optional[str] = None, auth_header_key: Optional[str] = None, fetch_method: str = "GET", request_body: Optional[str] = None
    ) -> str:
        """Fetch tool JSON from a URL with raw (unencrypted) credentials.

        Used for save-time validation before anything is persisted.

        Args:
            source_url: URL to fetch.
            auth_type: none/bearer/basic/header.
            auth_credential: Raw secret value.
            auth_header_key: Custom header name for header auth.
            fetch_method: "GET" or "POST".
            request_body: JSON body text for POST.

        Returns:
            The response body text.

        Raises:
            ToolApiSourceValidationError: On connection errors or non-2xx.
        """
        headers: Dict[str, str] = {}
        if auth_type == "bearer" and auth_credential:
            headers["Authorization"] = f"Bearer {auth_credential}"
        elif auth_type == "basic" and auth_credential:
            import base64  # pylint: disable=import-outside-toplevel

            headers["Authorization"] = "Basic " + base64.b64encode(auth_credential.encode("utf-8")).decode("ascii")
        elif auth_type == "header" and auth_credential:
            if not auth_header_key:
                raise ToolApiSourceValidationError("Custom header auth requires a header name")
            headers[auth_header_key] = auth_credential
        method = (fetch_method or "GET").upper()
        json_body = self._parse_request_body(method, request_body)
        return await self._fetch_url(source_url, headers, method=method, json_body=json_body)

    @staticmethod
    def _parse_request_body(method: str, request_body: Optional[str]) -> Optional[Dict[str, Any]]:
        """Validate the stored POST body for a remote fetch.

        Args:
            method: Fetch method (GET/POST).
            request_body: Raw JSON body text (POST only).

        Returns:
            Parsed body dict, or None for GET / empty body.

        Raises:
            ToolApiSourceValidationError: If the method is invalid or the
                body is not a JSON object.

        Examples:
            >>> ToolApiSourceService._parse_request_body("GET", '{"a": 1}') is None
            True
            >>> ToolApiSourceService._parse_request_body("POST", '{"a": 1}')
            {'a': 1}
            >>> try:
            ...     ToolApiSourceService._parse_request_body("POST", '[1]')
            ... except ToolApiSourceValidationError as e:
            ...     "JSON object" in str(e)
            True
        """
        if method not in ("GET", "POST"):
            raise ToolApiSourceValidationError(f"Invalid fetch method: {method}")
        if method == "GET" or not request_body or not request_body.strip():
            return None
        try:
            body = orjson.loads(request_body)
        except orjson.JSONDecodeError as ex:
            raise ToolApiSourceValidationError(f"Request body is not valid JSON: {ex}") from ex
        if not isinstance(body, dict):
            raise ToolApiSourceValidationError("Request body must be a JSON object")
        return body

    @staticmethod
    def _check_error_envelope(text: str) -> None:
        """Detect APIs that report failures inside an HTTP-200 body.

        Some APIs (e.g. Kingdee) answer 200 with ``{"success": false,
        "errorCode": ..., "message": ...}``. Surface that message instead of
        letting it fail later as unparseable tool JSON.

        Args:
            text: Response body text.

        Raises:
            ToolApiSourceValidationError: When the body is an error envelope.

        Examples:
            >>> ToolApiSourceService._check_error_envelope('[{"name": "t"}]')
            >>> ToolApiSourceService._check_error_envelope('{"success": true}')
            >>> try:
            ...     ToolApiSourceService._check_error_envelope('{"success": false, "message": "no access"}')
            ... except ToolApiSourceValidationError as e:
            ...     str(e)
            'no access'
        """
        try:
            payload = orjson.loads(text)
        except orjson.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        is_error = payload.get("success") is False or (payload.get("errorCode") and payload.get("status") is False)
        if is_error:
            raise ToolApiSourceValidationError(str(payload.get("message") or payload.get("error_desc") or f"Upstream error: {payload.get('errorCode')}"))

    @staticmethod
    async def _fetch_url(source_url: str, headers: Dict[str, str], method: str = "GET", json_body: Optional[Dict[str, Any]] = None) -> str:
        """Fetch a URL expecting JSON, mapping failures to validation errors.

        Args:
            source_url: URL to fetch.
            headers: Request headers (auth already applied).
            method: HTTP method, GET or POST.
            json_body: Parsed JSON object for POST bodies.

        Returns:
            Response body text.

        Raises:
            ToolApiSourceValidationError: On transport errors or bad status.
        """
        headers = dict(headers)
        headers.setdefault("Accept", "application/json")
        try:
            async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True) as client:
                if method == "POST":
                    response = await client.post(source_url, headers=headers, json=json_body or {})
                else:
                    response = await client.get(source_url, headers=headers)
        except httpx.HTTPError as ex:
            raise ToolApiSourceValidationError(f"Failed to fetch {source_url}: {ex}") from ex
        if response.status_code in (401, 403):
            raise ToolApiSourceValidationError(f"Fetch returned {response.status_code} — check the auth settings")
        if response.status_code != 200:
            raise ToolApiSourceValidationError(f"Fetch returned HTTP {response.status_code}")
        ToolApiSourceService._check_error_envelope(response.text)
        return response.text

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

    def create_source(
        self,
        db: Session,
        display_name: Optional[str],
        description: Optional[str],
        content: str,
        enabled: bool,
        owner_email: Optional[str] = None,
        source_url: Optional[str] = None,
        auth_type: str = "none",
        auth_header_key: Optional[str] = None,
        auth_credential: Optional[str] = None,
        fetch_method: str = "GET",
        request_body: Optional[str] = None,
    ) -> ToolApiSource:
        """Validate and save a new tool API source.

        Args:
            db: Database session.
            display_name: Optional label; derived from the JSON when blank.
            description: Optional free-text note.
            content: Raw tool JSON text (manual JSON, or a first snapshot).
            enabled: Whether ``sync_all`` includes this source.
            owner_email: Creator email.
            source_url: Remote URL to fetch tool JSON from (None = manual).
            auth_type: Fetch auth: none/bearer/basic/header.
            auth_header_key: Custom header name for header auth.
            auth_credential: Secret for the chosen auth type (stored encrypted).
            fetch_method: HTTP method for the remote fetch (GET/POST).
            request_body: JSON object body for POST fetches.

        Returns:
            The created ToolApiSource row.

        Raises:
            ToolApiSourceValidationError: If the URL or tool JSON is invalid.
        """
        source_url = self.validate_source_url(source_url)
        if auth_type not in _VALID_AUTH_TYPES:
            raise ToolApiSourceValidationError(f"Invalid auth type: {auth_type}")
        if source_url:
            self._parse_request_body(fetch_method, request_body)
        self.parse_content(content)

        source = ToolApiSource(
            display_name=(display_name or "").strip() or self.derive_display_name(content),
            description=(description or "").strip() or None,
            content=content.strip(),
            enabled=enabled,
            owner_email=owner_email,
            source_url=source_url,
            fetch_method=fetch_method.upper(),
            request_body=(request_body or "").strip() or None,
            auth_type=auth_type,
            auth_header_key=(auth_header_key or "").strip() or None if auth_type == "header" else None,
            auth_credential=self._encode_credential(auth_type, auth_header_key, auth_credential),
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        logger.info("Created tool API source %s (%s)", source.id, source.display_name)
        return source

    def update_source(
        self,
        db: Session,
        source_id: str,
        display_name: Optional[str],
        description: Optional[str],
        content: str,
        enabled: bool,
        source_url: Optional[str] = None,
        auth_type: str = "none",
        auth_header_key: Optional[str] = None,
        auth_credential: Optional[str] = None,
        credential_provided: bool = False,
        fetch_method: str = "GET",
        request_body: Optional[str] = None,
    ) -> ToolApiSource:
        """Update an existing tool API source.

        Args:
            db: Database session.
            source_id: Source id.
            display_name: Optional label; derived from the JSON when blank.
            description: Optional free-text note.
            content: Raw tool JSON text (manual JSON, or last snapshot).
            enabled: Whether ``sync_all`` includes this source.
            source_url: Remote URL to fetch from (None/blank = manual mode).
            auth_type: Fetch auth: none/bearer/basic/header.
            auth_header_key: Custom header name for header auth.
            auth_credential: New secret (only applied when provided).
            credential_provided: Whether the form submitted a credential;
                False keeps the previously stored secret.
            fetch_method: HTTP method for the remote fetch (GET/POST).
            request_body: JSON object body for POST fetches.

        Returns:
            The updated ToolApiSource row.

        Raises:
            ToolApiSourceNotFoundError: If the source does not exist.
            ToolApiSourceValidationError: If the URL or tool JSON is invalid.
        """
        source = self.get_source(db, source_id)
        source_url = self.validate_source_url(source_url)
        if auth_type not in _VALID_AUTH_TYPES:
            raise ToolApiSourceValidationError(f"Invalid auth type: {auth_type}")
        self.parse_content(content)
        source.display_name = (display_name or "").strip() or self.derive_display_name(content)
        source.description = (description or "").strip() or None
        source.content = content.strip()
        source.enabled = enabled
        if source_url:
            self._parse_request_body(fetch_method, request_body)
        source.source_url = source_url
        source.fetch_method = fetch_method.upper()
        source.request_body = (request_body or "").strip() or None
        source.auth_type = auth_type
        source.auth_header_key = (auth_header_key or "").strip() or None if auth_type == "header" else None
        if credential_provided:
            source.auth_credential = self._encode_credential(auth_type, auth_header_key, auth_credential)
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

        Remote sources (``source_url`` set) are re-fetched first; the fresh
        payload replaces the stored snapshot and is applied. For each tool
        definition: a local (non-gateway) tool with the same name is
        overwritten with the definition; otherwise the tool is registered.
        Gateway-managed tools are skipped because gateways own their tool
        definitions.

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

        if source.source_url:
            try:
                fetched = (await self.fetch_content(source)).strip()
                items = self.parse_content(fetched)
                source.content = fetched
                db.commit()
            except ToolApiSourceValidationError as ex:
                summary = f"Fetch failed: {ex}"
                source.last_synced_at = datetime.now(timezone.utc)
                source.last_sync_result = summary
                db.commit()
                logger.warning("Tool API source '%s' fetch failed: %s", source.display_name, ex)
                return {"created": 0, "updated": 0, "skipped": 0, "failed": 1, "errors": [summary], "summary": summary}
        else:
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
