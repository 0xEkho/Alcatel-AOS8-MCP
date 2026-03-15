"""Tests for MCP resources."""
import pytest
from mcp.server.fastmcp import FastMCP


@pytest.fixture
def mcp_with_resources():
    """Create a FastMCP instance with resources registered."""
    instance = FastMCP("test-server")
    from mcp_server.resources.example import register_resources
    register_resources(instance)
    return instance


async def test_server_info_resource_exists(mcp_with_resources):
    """Test that config://server-info resource is registered."""
    resources = await mcp_with_resources.list_resources()
    uris = [str(r.uri) for r in resources]
    assert "config://server-info" in uris


async def test_getting_started_resource_exists(mcp_with_resources):
    """Test that docs://getting-started resource is registered."""
    resources = await mcp_with_resources.list_resources()
    uris = [str(r.uri) for r in resources]
    assert "docs://getting-started" in uris


async def test_server_info_content(mcp_with_resources):
    """Test that server-info resource returns expected content."""
    result = await mcp_with_resources.read_resource("config://server-info")
    assert len(result) > 0
    # read_resource returns list[ReadResourceContents] with .content attribute
    content = result[0].content
    assert "mcp-server" in content
    assert "1.1.0" in content
