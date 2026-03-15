"""
Example MCP Resources.

Resources are application-driven data sources that provide context to LLMs.
They are identified by URIs and can contain text or binary data.

Best practices:
- Use clear, meaningful URIs (e.g., config://app, file:///path/to/file)
- Include MIME types for binary resources
- Resources should be read-only and stable
"""
import logging
import os

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_resources(mcp: FastMCP) -> None:
    """Register all resources on the MCP server instance.

    Args:
        mcp: The FastMCP server instance to register resources on.
    """

    @mcp.resource("config://server-info")
    def server_info() -> str:
        """Provide basic server configuration information.

        Returns key metadata about this MCP server instance.
        """
        name = os.getenv("MCP_SERVER_NAME", "mcp-server")
        version = os.getenv("MCP_SERVER_VERSION", "1.1.0")
        return (
            f"Server: {name}\n"
            f"Version: {version}\n"
            "Transport: stdio\n"
            "Description: MCP Template Server\n"
        )

    @mcp.resource("docs://getting-started")
    def getting_started() -> str:
        """Getting started guide for using this MCP server.

        Returns a markdown-formatted guide.
        """
        return """# Getting Started

This MCP server exposes the following primitives:

## Tools
- `echo` — Echo a message back (test connectivity)
- `fetch_url` — Fetch content from a URL

## Resources
- `config://server-info` — Server metadata
- `docs://getting-started` — This document

## Prompts
- `summarize` — Summarize a block of text
"""
