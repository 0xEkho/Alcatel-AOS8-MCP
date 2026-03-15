"""Tests for MCP prompts."""
import pytest
from mcp.server.fastmcp import FastMCP


@pytest.fixture
def mcp_with_prompts():
    """Create a FastMCP instance with prompts registered."""
    instance = FastMCP("test-server")
    from mcp_server.prompts.example import register_prompts
    register_prompts(instance)
    return instance


async def test_summarize_prompt_exists(mcp_with_prompts):
    """Test that summarize prompt is registered."""
    prompts = await mcp_with_prompts.list_prompts()
    names = [p.name for p in prompts]
    assert "summarize" in names


async def test_summarize_prompt_returns_messages(mcp_with_prompts):
    """Test that summarize prompt returns a user message with the text."""
    result = await mcp_with_prompts.get_prompt("summarize", {"text": "Hello world"})
    assert len(result.messages) == 1
    assert result.messages[0].role == "user"
    assert "Hello world" in result.messages[0].content.text


async def test_summarize_prompt_uses_language(mcp_with_prompts):
    """Test that summarize prompt includes the specified language."""
    result = await mcp_with_prompts.get_prompt(
        "summarize", {"text": "Bonjour", "language": "French"}
    )
    assert "French" in result.messages[0].content.text
