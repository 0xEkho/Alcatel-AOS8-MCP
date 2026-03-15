"""Tests for MCP tools."""
import httpx
import pytest
from unittest.mock import AsyncMock, patch
from mcp.server.fastmcp import FastMCP


@pytest.fixture
def mcp_with_tools():
    """Create a fresh FastMCP instance with tools registered."""
    instance = FastMCP("test-server")
    from mcp_server.tools.example import register_tools
    register_tools(instance)
    return instance


async def test_echo_tool_exists(mcp_with_tools):
    """Test that echo tool is registered."""
    tools = {t.name: t for t in await mcp_with_tools.list_tools()}
    assert "aos_echo" in tools


async def test_echo_returns_message(mcp_with_tools):
    """Test that echo tool returns the message prefixed with 'Echo: '."""
    result = await mcp_with_tools.call_tool("aos_echo", {"message": "hello"})
    contents = result[0]  # call_tool returns (list[TextContent], meta)
    assert len(contents) > 0
    assert "hello" in contents[0].text


async def test_fetch_url_rejects_invalid_url(mcp_with_tools):
    """Test that fetch_url returns an error for non-HTTP URLs."""
    result = await mcp_with_tools.call_tool("aos_fetch_url", {"url": "ftp://example.com"})
    contents = result[0]
    assert len(contents) > 0
    assert "Error" in contents[0].text


async def test_fetch_url_handles_http_error(mcp_with_tools):
    """Test that fetch_url handles HTTP errors gracefully."""
    with patch("mcp_server.tools.example.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_client.get = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "404",
                request=httpx.Request("GET", "https://example.com/notfound"),
                response=mock_response,
            )
        )

        result = await mcp_with_tools.call_tool("aos_fetch_url", {"url": "https://example.com/notfound"})
        contents = result[0]
        assert len(contents) > 0
        assert "Error" in contents[0].text
