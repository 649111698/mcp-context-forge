# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_tool_apis_json.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the tool API sources JSON API (contextforge-web-ui frontend).
"""

# Standard
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
from fastapi import HTTPException
from mcpgateway import admin as admin_mod
from mcpgateway.db import ToolApiSource
from mcpgateway.schemas import ToolApiSourceSaveRequest
from mcpgateway.services.tool_api_source_service import ToolApiSourceNotFoundError, ToolApiSourceValidationError


def _make_source(**overrides: Any) -> ToolApiSource:
    """Build an unsaved ToolApiSource row for serialization tests."""
    defaults = {
        "id": "src-1",
        "display_name": "金蝶物料清单",
        "description": "物料清单 API",
        "enabled": True,
        "owner_email": "admin@example.com",
        "source_url": None,
        "fetch_method": "GET",
        "request_body": None,
        "auth_type": "none",
        "auth_header_key": None,
        "auth_credential": None,
        "content": '[{"name": "get_bom", "url": "http://erp.example/bom"}]',
        "last_synced_at": None,
        "last_sync_result": None,
    }
    defaults.update(overrides)
    return ToolApiSource(**defaults)


def _json_request(content_type: str = "application/json") -> MagicMock:
    """Build a minimal request mock whose headers discriminate the API surface."""
    request: MagicMock = MagicMock()
    request.headers = {"content-type": content_type}
    return request


@pytest.fixture
def mock_db():
    """Session mock for direct handler invocation."""
    return MagicMock()


@pytest.fixture
def svc(monkeypatch):
    """Replace the admin module's tool API source service with a mock."""
    mock = MagicMock()
    mock.summarize_content.return_value = {"tool_count": 1, "names": ["get_bom"], "first_url": "http://erp.example/bom"}
    mock.list_sources.return_value = []
    monkeypatch.setattr(admin_mod, "tool_api_source_service", mock)
    return mock


class TestToolApisListJson:
    """GET /admin/tool-apis."""

    async def test_list_returns_items_without_credential(self, svc, mock_db):
        """The list serializes rows and never includes the stored credential."""
        svc.list_sources.return_value = [_make_source(auth_credential="enc-secret")]

        result = await admin_mod.admin_tool_apis_list_json.__wrapped__(request=_json_request(), db=mock_db, user={"email": "admin@example.com"})

        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["id"] == "src-1"
        assert item["has_credential"] is True
        assert "auth_credential" not in item
        assert item["summary"]["tool_count"] == 1


class TestToolApisGetJson:
    """GET /admin/tool-apis/{source_id}."""

    async def test_get_returns_source(self, svc, mock_db):
        """The detail view returns the stored content for editing."""
        svc.get_source.return_value = _make_source()

        result = await admin_mod.admin_tool_apis_get_json.__wrapped__(source_id="src-1", request=_json_request(), db=mock_db, user={"email": "admin@example.com"})

        assert result["content"].startswith('[{"name"')
        svc.get_source.assert_called_once_with(mock_db, "src-1")

    async def test_get_missing_returns_404(self, svc, mock_db):
        """An unknown source id returns 404."""
        svc.get_source.side_effect = ToolApiSourceNotFoundError("missing")

        with pytest.raises(HTTPException) as excinfo:
            await admin_mod.admin_tool_apis_get_json.__wrapped__(source_id="nope", request=_json_request(), db=mock_db, user={"email": "admin@example.com"})
        assert excinfo.value.status_code == 404


class TestToolApisCreateJson:
    """POST /admin/tool-apis."""

    async def test_create_manual_content(self, svc, mock_db):
        """A manual create passes the payload through and returns the row."""
        svc.create_source.return_value = _make_source()
        payload = ToolApiSourceSaveRequest(display_name="金蝶物料清单", content='[{"name": "get_bom", "url": "http://erp.example/bom"}]')

        result = await admin_mod.admin_tool_apis_create_json.__wrapped__(payload=payload, request=_json_request(), db=mock_db, user={"email": "admin@example.com", "is_admin": True})

        svc.create_source.assert_called_once()
        kwargs = svc.create_source.call_args.kwargs
        assert kwargs["owner_email"] == "admin@example.com"
        assert kwargs["content"].startswith('[{"name"')
        assert result["id"] == "src-1"

    async def test_create_requires_content_or_url(self, svc, mock_db):
        """Neither content nor source_url is a 422, not a server error."""
        payload = ToolApiSourceSaveRequest()

        with pytest.raises(HTTPException) as excinfo:
            await admin_mod.admin_tool_apis_create_json.__wrapped__(payload=payload, request=_json_request(), db=mock_db, user={"email": "admin@example.com"})
        assert excinfo.value.status_code == 422

    async def test_create_remote_fetches_snapshot(self, svc, mock_db):
        """A remote create fetches the URL, validates, and stores the snapshot."""
        svc.fetch_url_content = AsyncMock(return_value=' [{"name": "remote", "url": "http://up/api"}] ')
        svc.create_source.return_value = _make_source(content='{"name": "remote", "url": "http://up/api"}')
        payload = ToolApiSourceSaveRequest(source_url="http://up.example/api", content="ignored")

        await admin_mod.admin_tool_apis_create_json.__wrapped__(payload=payload, request=_json_request(), db=mock_db, user={"email": "admin@example.com"})

        svc.fetch_url_content.assert_awaited_once()
        kwargs = svc.create_source.call_args.kwargs
        assert kwargs["content"] == '[{"name": "remote", "url": "http://up/api"}]'

    async def test_create_validation_error_returns_422(self, svc, mock_db):
        """Service validation errors surface as 422 with the message."""
        svc.create_source.side_effect = ToolApiSourceValidationError("JSON 不合法")
        payload = ToolApiSourceSaveRequest(content="not json")

        with pytest.raises(HTTPException) as excinfo:
            await admin_mod.admin_tool_apis_create_json.__wrapped__(payload=payload, request=_json_request(), db=mock_db, user={"email": "admin@example.com"})
        assert excinfo.value.status_code == 422
        assert "JSON" in excinfo.value.detail


class TestToolApisUpdateJson:
    """PUT /admin/tool-apis/{source_id}."""

    async def test_update_blank_credential_keeps_stored(self, svc, mock_db):
        """Omitting auth_credential keeps the stored secret (credential_provided False)."""
        svc.update_source.return_value = _make_source()
        payload = ToolApiSourceSaveRequest(content='[{"name": "get_bom", "url": "http://erp.example/bom"}]')

        await admin_mod.admin_tool_apis_update_json.__wrapped__(source_id="src-1", payload=payload, request=_json_request(), db=mock_db, user={"email": "admin@example.com"})

        kwargs = svc.update_source.call_args.kwargs
        assert kwargs["credential_provided"] is False
        assert kwargs["auth_credential"] is None

    async def test_update_provided_credential_applied(self, svc, mock_db):
        """A submitted credential is marked provided so the service stores it."""
        svc.update_source.return_value = _make_source()
        payload = ToolApiSourceSaveRequest(content='[{"name": "get_bom", "url": "http://erp.example/bom"}]', auth_credential="new-secret")

        await admin_mod.admin_tool_apis_update_json.__wrapped__(source_id="src-1", payload=payload, request=_json_request(), db=mock_db, user={"email": "admin@example.com"})

        assert svc.update_source.call_args.kwargs["credential_provided"] is True

    async def test_update_missing_returns_404(self, svc, mock_db):
        """Updating an unknown source returns 404."""
        svc.update_source.side_effect = ToolApiSourceNotFoundError("missing")
        payload = ToolApiSourceSaveRequest(content="[]")

        with pytest.raises(HTTPException) as excinfo:
            await admin_mod.admin_tool_apis_update_json.__wrapped__(source_id="nope", payload=payload, request=_json_request(), db=mock_db, user={"email": "admin@example.com"})
        assert excinfo.value.status_code == 404


class TestToolApisDeleteJson:
    """DELETE /admin/tool-apis/{source_id}."""

    async def test_delete_returns_display_name(self, svc, mock_db):
        """Deleting returns the former display name."""
        svc.delete_source.return_value = "金蝶物料清单"

        result = await admin_mod.admin_tool_apis_delete_json.__wrapped__(source_id="src-1", request=_json_request(), db=mock_db, user={"email": "admin@example.com"})

        assert result == {"deleted": True, "display_name": "金蝶物料清单"}

    async def test_delete_missing_returns_404(self, svc, mock_db):
        """Deleting an unknown source returns 404."""
        svc.delete_source.side_effect = ToolApiSourceNotFoundError("missing")

        with pytest.raises(HTTPException) as excinfo:
            await admin_mod.admin_tool_apis_delete_json.__wrapped__(source_id="nope", request=_json_request(), db=mock_db, user={"email": "admin@example.com"})
        assert excinfo.value.status_code == 404


class TestToolApisSyncJsonBranch:
    """Sync endpoints serve JSON to the web-ui BFF and HTML to HTMX."""

    async def test_sync_json_content_type_returns_dict(self, svc, mock_db):
        """A JSON content-type sync returns the result dict."""
        svc.sync_source = AsyncMock(return_value={"created": 1, "updated": 0, "skipped": 0, "failed": 0, "errors": [], "summary": "新建 1"})

        result = await admin_mod.admin_tool_apis_sync.__wrapped__(source_id="src-1", request=_json_request(), db=mock_db, user={"email": "admin@example.com"})

        assert result["created"] == 1
        svc.sync_source.assert_awaited_once_with(mock_db, "src-1", user_email="admin@example.com")

    async def test_sync_form_content_type_renders_partial(self, svc, mock_db, monkeypatch):
        """A form content-type sync keeps the HTMX partial response."""
        svc.sync_source = AsyncMock(return_value={"created": 0, "updated": 1, "skipped": 0, "failed": 0, "errors": [], "summary": "新建 0，更新 1"})
        rendered = MagicMock(name="html")
        monkeypatch.setattr(admin_mod, "_render_tool_apis_partial", AsyncMock(return_value=rendered))

        result = await admin_mod.admin_tool_apis_sync.__wrapped__(source_id="src-1", request=_json_request("application/x-www-form-urlencoded"), db=mock_db, user={"email": "admin@example.com"})

        assert result is rendered

    async def test_sync_json_missing_returns_404(self, svc, mock_db):
        """A JSON sync of an unknown source returns 404."""
        svc.sync_source = AsyncMock(side_effect=ToolApiSourceNotFoundError("missing"))

        with pytest.raises(HTTPException) as excinfo:
            await admin_mod.admin_tool_apis_sync.__wrapped__(source_id="nope", request=_json_request(), db=mock_db, user={"email": "admin@example.com"})
        assert excinfo.value.status_code == 404

    async def test_sync_all_json_content_type_returns_dict(self, svc, mock_db):
        """A JSON sync-all returns the aggregated result."""
        svc.sync_all = AsyncMock(return_value={"created": 2, "updated": 0, "skipped": 0, "failed": 0, "results": [], "summary": "全部同步"})

        result = await admin_mod.admin_tool_apis_sync_all.__wrapped__(request=_json_request(), db=mock_db, user={"email": "admin@example.com"})

        assert result["created"] == 2


class TestToolApisPermissionDenyPaths:
    """The JSON routes keep the tools.* permission checks (Layer 2)."""

    async def test_list_denied_without_permission(self, svc, mock_db, monkeypatch):
        """A caller without tools.read gets 403 from the route decorator."""
        async def deny(*_args, **_kwargs):
            return False

        monkeypatch.setattr("mcpgateway.middleware.rbac.check_permission_inline", deny)

        with pytest.raises(HTTPException) as excinfo:
            await admin_mod.admin_tool_apis_list_json(request=_json_request(), db=mock_db, user={"email": "viewer@example.com"})
        assert excinfo.value.status_code == 403
        svc.list_sources.assert_not_called()

    async def test_list_denied_without_user(self, svc, mock_db):
        """A missing user context is 401 before any data access."""
        with pytest.raises(HTTPException) as excinfo:
            await admin_mod.admin_tool_apis_list_json(request=_json_request(), db=mock_db, user=None)
        assert excinfo.value.status_code == 401
