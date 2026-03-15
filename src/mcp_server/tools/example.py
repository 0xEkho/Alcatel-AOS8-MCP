"""
Example MCP Tools.

Tools are model-controlled executable functions that AI can invoke.
Replace this with your actual tool implementations.

Best practices:
- Use descriptive names and clear docstrings (they become the tool description)
- Validate inputs and return errors in the result (isError=True), don't raise
- Use type hints for automatic schema generation
- Log to stderr, never stdout
"""
import logging

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_tools(mcp: FastMCP) -> None:
    """Register all tools on the MCP server instance.

    Args:
        mcp: The FastMCP server instance to register tools on.
    """

    @mcp.tool()
    async def aos_echo(message: str) -> str:
        """Echo a message back to the caller.

        This is the simplest possible tool — useful for testing connectivity.

        Args:
            message: The message to echo back.
        """
        logger.info("aos_echo called with: %s", message)
        return f"Echo: {message}"

    @mcp.tool()
    async def aos_fetch_url(url: str) -> str:
        """Fetch the content of a URL and return it as text.

        Args:
            url: The URL to fetch (must start with http:// or https://).
        """
        if not url.startswith(("http://", "https://")):
            # Return error in result — do NOT raise an exception
            return "Error: URL must start with http:// or https://"

        logger.info("Fetching URL: %s", url)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.text[:2000]  # Truncate to avoid huge responses
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching %s: %s", url, e)
            return f"Error: HTTP {e.response.status_code} for {url}"
        except Exception as e:
            logger.error("Unexpected error fetching %s: %s", url, e)
            return f"Error: {e}"
