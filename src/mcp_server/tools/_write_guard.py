"""
Architectural contract — protection of WRITE operations on AOS8 switches.

WRITE RULE
----------
Any MCP tool that modifies a switch configuration (WRITE) MUST go through
a human approval workflow (Teams or equivalent).

Never expose an MCP tool that directly executes configuration commands
without prior human validation.

Implementation convention
-------------------------
* Legitimate WRITE tools delegate to an approval workflow and mention
  ``_write_guard`` in their docstring.
* Any tool that would bypass this rule must be removed or converted
  to a READ-ONLY tool.

Example of a compliant WRITE tool
----------------------------------
``aos_poe_reboot_request`` (``poe_approval.py``):
  - Creates a pending entry with a 30-minute TTL.
  - Posts a Teams card with Approve / Reject buttons.
  - Only executes the switch command after human validation.

Using ``write_guard``
---------------------
Call :func:`write_guard` at the start of any WRITE tool that does NOT go
through an approval workflow — this allows it to return a standardised error
message instead of silently executing a dangerous command.
"""
import logging

logger = logging.getLogger(__name__)

# Standardised message returned by any unapproved WRITE tool.
_BLOCKED_MSG_TEMPLATE = (
    "⛔ OPERATION BLOCKED — '{tool_name}' is a WRITE operation that cannot "
    "be executed directly.\n"
    "\n"
    "Use the appropriate approval workflow:\n"
    "  • PoE reboot  → aos_poe_reboot_request\n"
    "\n"
    "Any switch configuration change requires prior human validation "
    "(Teams or equivalent)."
)


def write_guard(tool_name: str) -> str:
    """Return a standardised error message for an unapproved WRITE tool.

    To be used in any WRITE tool that does not go through an approval
    workflow, in order to block execution and inform the model of the
    correct path.

    This function never raises an exception — it always returns a string
    (in accordance with MCP best practices: business errors are returned,
    not raised).

    Convention: every compliant WRITE tool must mention ``_write_guard``
    in its docstring to indicate it has been audited.

    Args:
        tool_name: Name of the calling MCP tool (used in the message).

    Returns:
        Human-readable error message explaining the block and indicating
        the approval workflow to use.

    Example::

        @mcp.tool()
        async def some_write_tool(host: str) -> str:
            # This tool does not go through a workflow → block immediately.
            return write_guard("some_write_tool")
    """
    logger.warning(
        "write_guard: direct call attempt to a blocked WRITE tool — '%s'",
        tool_name,
    )
    return _BLOCKED_MSG_TEMPLATE.format(tool_name=tool_name)
