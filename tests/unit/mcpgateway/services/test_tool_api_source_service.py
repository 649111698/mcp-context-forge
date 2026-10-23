# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_api_source_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the tool API source service (saved MCP API definitions + sync).
"""

# Standard
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import ToolApiSource
from mcpgateway.schemas import ToolCreate, ToolUpdate
from mcpgateway.services.tool_api_source_service import ToolApiSourceNotFoundError, ToolApiSourceService, ToolApiSourceValidationError
from mcpgateway.services.tool_service import ToolError


@pytest.fixture
def service():
    """Create a service instance."""
    return ToolApiSourceService()


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock()


VALID_TOOL_JSON = '{"name": "queryCustomer", "url": "http://kingdee/api", "integration_type": "REST", "request_type": "POST"}'


def make_source(content: str = VALID_TOOL_JSON, enabled: bool = True) -> ToolApiSource:
    """Build an in-memory ToolApiSource row.

    Args:
        content: Stored tool JSON.
        enabled: Whether the source is enabled.

    Returns:
        ToolApiSource instance (not persisted).
    """
    return ToolApiSource(id="src1", display_name="queryCustomer", content=content, enabled=enabled)


# ---------------------------------------------------------------------------
# parse / summarize
# ---------------------------------------------------------------------------


def test_parse_content_single_object(service):
    """A single tool object parses into a one-item list."""
    items = service.parse_content(VALID_TOOL_JSON)
    assert len(items) == 1
    assert items[0]["name"] == "queryCustomer"


def test_parse_content_array(service):
    """An array of tool objects parses into the full list."""
    items = service.parse_content('[{"name": "a", "url": "u1"}, {"name": "b", "url": "u2"}]')
    assert [i["name"] for i in items] == ["a", "b"]


@pytest.mark.parametrize("bad", ["", "   ", "not json", "[]", '{"url": "u"}', '{"name": "x"}', '[{"name": "a", "url": "u"}, {"name": ""}]', '"just a string"'])
def test_parse_content_invalid(service, bad):
    """Malformed or incomplete payloads are rejected."""
    with pytest.raises(ToolApiSourceValidationError):
        service.parse_content(bad)


def test_summarize_content(service):
    """Display metadata is derived from the stored JSON."""
    summary = service.summarize_content('[{"name": "a", "url": "http://x"}, {"name": "b", "url": "http://y"}]')
    assert summary["tool_count"] == 2
    assert summary["first_url"] == "http://x"
    assert summary["names"] == ["a", "b"]


def test_summarize_content_error(service):
    """Broken JSON yields an error summary instead of raising."""
    assert "error" in service.summarize_content("not json")


def test_derive_display_name(service):
    """Display names default to the first tool name with an extra count."""
    assert service.derive_display_name(VALID_TOOL_JSON) == "queryCustomer"
    assert service.derive_display_name('[{"name": "a", "url": "u"}, {"name": "b", "url": "u"}]') == "a (+1)"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_create_source_validates_json(service, mock_db):
    """Invalid JSON is rejected before anything is persisted."""
    with pytest.raises(ToolApiSourceValidationError):
        service.create_source(mock_db, "n", None, "not json", True, "u@x")
    mock_db.add.assert_not_called()


def test_create_source_persists(service, mock_db):
    """A valid source is added and committed with a derived display name."""
    source = service.create_source(mock_db, "", None, VALID_TOOL_JSON, True, "u@x")
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    assert source.display_name == "queryCustomer"
    assert source.owner_email == "u@x"


def test_get_source_missing(service, mock_db):
    """A missing id raises ToolApiSourceNotFoundError."""
    mock_db.execute.return_value.scalars.return_value.one_or_none.return_value = None
    with pytest.raises(ToolApiSourceNotFoundError):
        service.get_source(mock_db, "missing")


def test_delete_source(service, mock_db):
    """Deleting removes the row and keeps the name for the response."""
    mock_db.execute.return_value.scalars.return_value.one_or_none.return_value = make_source()
    assert service.delete_source(mock_db, "src1") == "queryCustomer"
    mock_db.delete.assert_called_once()
    mock_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


def wire_db(mock_db, existing_tool=None, source=None):
    """Wire a mock session so get_source resolves and tool lookup returns a fixture.

    Args:
        mock_db: Mock session to configure.
        existing_tool: Tool row returned by the name lookup (None = not found).
        source: Source row returned by get_source (default: fresh make_source).
    """
    scalars = mock_db.execute.return_value.scalars.return_value
    scalars.one_or_none.return_value = source or make_source()
    scalars.first.return_value = existing_tool


def async_tool_service():
    """Create a mocked tool service with async methods.

    Returns:
        MagicMock whose register_tool/update_tool are AsyncMock.
    """
    # Standard
    from unittest.mock import AsyncMock  # pylint: disable=import-outside-toplevel

    tool_svc = MagicMock()
    tool_svc.register_tool = AsyncMock()
    tool_svc.update_tool = AsyncMock()
    return tool_svc


@pytest.mark.asyncio
async def test_sync_source_creates_new_tool(service, mock_db):
    """Unknown tool names are registered as new tools."""
    wire_db(mock_db, existing_tool=None)
    with patch("mcpgateway.services.tool_api_source_service.tool_service", async_tool_service()) as tool_svc:
        result = await service.sync_source(mock_db, "src1", user_email="admin@example.com")
    assert result["created"] == 1
    assert result["updated"] == 0
    assert result["failed"] == 0
    created: ToolCreate = tool_svc.register_tool.call_args[0][1]
    assert created.name == "queryCustomer"
    assert tool_svc.register_tool.call_args.kwargs.get("created_via") == "tool-api-sync"


@pytest.mark.asyncio
async def test_sync_source_overwrites_existing_tool(service, mock_db):
    """Existing tools with the same name are updated, not duplicated."""
    wire_db(mock_db, existing_tool=SimpleNamespace(id="tool9", gateway_id=None))
    with patch("mcpgateway.services.tool_api_source_service.tool_service", async_tool_service()) as tool_svc:
        result = await service.sync_source(mock_db, "src1")
    assert result["updated"] == 1
    assert result["created"] == 0
    tool_svc.update_tool.assert_called_once()
    updated: ToolUpdate = tool_svc.update_tool.call_args.args[2]
    assert updated.url == "http://kingdee/api"


@pytest.mark.asyncio
async def test_sync_source_item_failure_is_reported(service, mock_db):
    """A failing tool definition does not abort the whole sync."""
    wire_db(mock_db, existing_tool=None)
    with patch("mcpgateway.services.tool_api_source_service.tool_service", async_tool_service()) as tool_svc:
        tool_svc.register_tool.side_effect = ToolError("boom")
        result = await service.sync_source(mock_db, "src1")
    assert result["failed"] == 1
    assert any("boom" in err for err in result["errors"])
    assert "失败 1" in result["summary"]


@pytest.mark.asyncio
async def test_sync_source_skips_gateway_managed_tool(service, mock_db):
    """Gateway-managed tools are skipped, not overwritten."""
    wire_db(mock_db, existing_tool=SimpleNamespace(id="tool9", gateway_id="gw1"))
    with patch("mcpgateway.services.tool_api_source_service.tool_service", async_tool_service()) as tool_svc:
        result = await service.sync_source(mock_db, "src1")
    assert result["skipped"] == 1
    tool_svc.update_tool.assert_not_called()


@pytest.mark.asyncio
async def test_sync_all_skips_disabled_sources(service, mock_db):
    """Disabled sources are excluded from sync-all."""
    with patch.object(service, "list_sources", return_value=[make_source(enabled=False)]), patch("mcpgateway.services.tool_api_source_service.tool_service", async_tool_service()) as tool_svc:
        result = await service.sync_all(mock_db, "admin@example.com")
    tool_svc.register_tool.assert_not_called()
    assert "新建 0" in result["summary"]


# ---------------------------------------------------------------------------
# remote URL mode
# ---------------------------------------------------------------------------


def test_validate_source_url(service):
    """Only http(s) URLs are accepted; blank means manual mode."""
    assert service.validate_source_url(None) is None
    assert service.validate_source_url("  ") is None
    assert service.validate_source_url(" https://x.example/t.json ") == "https://x.example/t.json"
    with pytest.raises(ToolApiSourceValidationError):
        service.validate_source_url("ftp://x/t.json")
    with pytest.raises(ToolApiSourceValidationError):
        service.validate_source_url("file:///etc/passwd")


def test_credential_encrypted_at_rest(service):
    """Stored credential blob is ciphertext, decryptable for fetch headers."""
    blob = service._encode_credential("bearer", None, "secret-token")
    assert blob and "secret-token" not in blob
    source = make_source()
    source.auth_type = "bearer"
    source.auth_credential = blob
    assert service._build_fetch_headers(source) == {"Authorization": "Bearer secret-token"}


def test_credential_basic_and_header(service):
    """Basic auth is base64-encoded; header auth uses the stored key."""
    source = make_source()
    source.auth_type = "basic"
    source.auth_credential = service._encode_credential("basic", None, "user:pass")
    headers = service._build_fetch_headers(source)
    assert headers["Authorization"].startswith("Basic ")

    source.auth_type = "header"
    source.auth_header_key = "X-Api-Key"
    source.auth_credential = service._encode_credential("header", "X-Api-Key", "k1")
    assert service._build_fetch_headers(source) == {"X-Api-Key": "k1"}


def test_credential_none_mode(service):
    """None auth never stores or decrypts anything."""
    assert service._encode_credential("none", None, "x") is None
    assert service._build_fetch_headers(make_source()) == {}


@pytest.mark.asyncio
async def test_fetch_content_requires_url(service):
    """Fetching a manual-mode source is a validation error."""
    with pytest.raises(ToolApiSourceValidationError, match="没有配置拉取 URL"):
        await service.fetch_content(make_source())


@pytest.mark.asyncio
async def test_sync_source_fetches_remote(service, mock_db):
    """Remote sources are re-fetched on sync and the snapshot updated."""
    remote = make_source(content='{"name": "old", "url": "http://old"}')
    remote.source_url = "https://cfg.example/tools.json"
    remote.auth_type = "bearer"
    remote.auth_credential = service._encode_credential("bearer", None, "tok")
    wire_db(mock_db, existing_tool=None, source=remote)

    class FakeResponse:
        status_code = 200
        text = '[{"name": "remoteTool", "url": "http://x/new"}]'

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            assert url == "https://cfg.example/tools.json"
            assert headers.get("Authorization") == "Bearer tok"
            return FakeResponse()

    with patch("mcpgateway.services.tool_api_source_service.httpx.AsyncClient", FakeClient), patch("mcpgateway.services.tool_api_source_service.tool_service", async_tool_service()) as tool_svc:
        result = await service.sync_source(mock_db, "src1")
    assert result["created"] == 1
    created: ToolCreate = tool_svc.register_tool.call_args[0][1]
    assert created.name == "remoteTool"
    assert '"remoteTool"' in remote.content


@pytest.mark.asyncio
async def test_sync_source_fetch_failure_reported(service, mock_db):
    """A failing fetch marks the sync failed without touching tools."""
    remote = make_source()
    remote.source_url = "https://cfg.example/tools.json"
    wire_db(mock_db, existing_tool=None, source=remote)

    class FakeResponse:
        status_code = 401
        text = ""

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return FakeResponse()

    with patch("mcpgateway.services.tool_api_source_service.httpx.AsyncClient", FakeClient), patch("mcpgateway.services.tool_api_source_service.tool_service", async_tool_service()) as tool_svc:
        result = await service.sync_source(mock_db, "src1")
    assert result["failed"] == 1
    assert "401" in result["summary"]
    tool_svc.register_tool.assert_not_called()


def test_create_source_with_url_roundtrip(service, mock_db):
    """URL mode persists URL/auth and validates the snapshot JSON."""
    source = service.create_source(
        mock_db,
        "cfg",
        None,
        '[{"name": "a", "url": "http://x"}]',
        True,
        "u@x",
        source_url="https://cfg.example/tools.json",
        auth_type="bearer",
        auth_credential="tok",
    )
    assert source.source_url == "https://cfg.example/tools.json"
    assert source.auth_type == "bearer"
    assert source.auth_credential and "tok" not in source.auth_credential


# ---------------------------------------------------------------------------
# POST fetch + upstream error envelopes
# ---------------------------------------------------------------------------


def test_parse_request_body_validation(service):
    """POST bodies must be JSON objects; GET ignores the body."""
    assert service._parse_request_body("GET", '{"a": 1}') is None
    assert service._parse_request_body("POST", "") is None
    assert service._parse_request_body("POST", '{"a": 1}') == {"a": 1}
    with pytest.raises(ToolApiSourceValidationError, match="不是合法 JSON"):
        service._parse_request_body("POST", "{oops")
    with pytest.raises(ToolApiSourceValidationError, match="必须是 JSON 对象"):
        service._parse_request_body("POST", "[1]")
    with pytest.raises(ToolApiSourceValidationError, match="无效的请求方法"):
        service._parse_request_body("DELETE", None)


def test_check_error_envelope(service):
    """HTTP-200 error envelopes surface the upstream message."""
    service._check_error_envelope('[{"name": "t"}]')  # tool array passes
    service._check_error_envelope('{"success": true}')  # success passes
    service._check_error_envelope("not json")  # unparseable left to later validation
    with pytest.raises(ToolApiSourceValidationError, match="未经授权"):
        service._check_error_envelope('{"success": false, "errorCode": "401", "message": "未经授权的访问"}')
    with pytest.raises(ToolApiSourceValidationError, match="no access"):
        service._check_error_envelope('{"status": false, "errorCode": "403", "message": "no access"}')


@pytest.mark.asyncio
async def test_fetch_uses_post_and_body(service, mock_db):
    """POST sources send the stored JSON body on every sync."""
    remote = make_source()
    remote.source_url = "https://cfg.example/export"
    remote.fetch_method = "POST"
    remote.request_body = '{"group": "ai"}'
    remote.auth_type = "header"
    remote.auth_header_key = "openApiSign"
    remote.auth_credential = service._encode_credential("header", "openApiSign", "SIGN123")
    wire_db(mock_db, existing_tool=None, source=remote)

    seen = {}

    class FakeResponse:
        status_code = 200
        text = '[{"name": "posted", "url": "http://x"}]'

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            seen["url"], seen["headers"], seen["json"] = url, headers, json
            return FakeResponse()

    with patch("mcpgateway.services.tool_api_source_service.httpx.AsyncClient", FakeClient), patch("mcpgateway.services.tool_api_source_service.tool_service", async_tool_service()):
        result = await service.sync_source(mock_db, "src1")
    assert result["created"] == 1
    assert seen["url"] == "https://cfg.example/export"
    assert seen["headers"]["openApiSign"] == "SIGN123"
    assert seen["json"] == {"group": "ai"}


@pytest.mark.asyncio
async def test_fetch_surfaces_200_error_envelope(service, mock_db):
    """Upstream 200-with-errorCode shows the API message, no tools touched."""
    remote = make_source()
    remote.source_url = "https://cfg.example/export"
    remote.fetch_method = "POST"
    remote.request_body = '{"group": "ai"}'
    wire_db(mock_db, existing_tool=None, source=remote)

    class FakeResponse:
        status_code = 200
        text = '{"success": false, "errorCode": "403", "message": "该第三方应用没有此接口访问权限"}'

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            return FakeResponse()

    with patch("mcpgateway.services.tool_api_source_service.httpx.AsyncClient", FakeClient), patch("mcpgateway.services.tool_api_source_service.tool_service", async_tool_service()) as tool_svc:
        result = await service.sync_source(mock_db, "src1")
    assert result["failed"] == 1
    assert "该第三方应用没有此接口访问权限" in result["summary"]
    tool_svc.register_tool.assert_not_called()
