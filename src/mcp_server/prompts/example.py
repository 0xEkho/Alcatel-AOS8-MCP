"""
Example MCP Prompts.

Prompts are user-controlled reusable templates that structure LLM interactions.
They support arguments for customization and are typically triggered via
slash commands in the host application.

Best practices:
- Prompts should be focused and reusable across different contexts
- Validate arguments and provide clear descriptions
- Use embedded resources when referencing server-managed content
"""
import logging

from mcp.server.fastmcp import FastMCP
from mcp.types import GetPromptResult, PromptMessage, TextContent

logger = logging.getLogger(__name__)


def register_prompts(mcp: FastMCP) -> None:
    """Register all prompts on the MCP server instance.

    Args:
        mcp: The FastMCP server instance to register prompts on.
    """

    @mcp.prompt()
    def summarize(text: str, language: str = "English") -> GetPromptResult:
        """Generate a prompt asking the LLM to summarize provided text.

        Args:
            text: The text to summarize.
            language: The language to write the summary in (default: English).
        """
        logger.info("summarize prompt requested, language=%s", language)
        return GetPromptResult(
            description=f"Summarize the provided text in {language}",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=(
                            f"Please provide a concise summary of the following text in {language}.\n\n"
                            f"Text to summarize:\n{text}"
                        ),
                    ),
                )
            ],
        )
