"""
Tools package — aggregates all AOS8 MCP tool modules.

Each sub-module exposes a ``register_tools(mcp)`` function.  The
top-level :func:`register_tools` calls every sub-module in turn so
that ``server.py`` only needs a single import.

WRITE RULE: any tool that modifies a switch configuration MUST go
through an approval workflow (Teams or equivalent).
Never expose an MCP tool that directly executes configuration commands
without prior human validation.
See ``_write_guard.py`` for the complete architectural contract.
"""
from mcp.server.fastmcp import FastMCP

from mcp_server.tools.core import register_tools as _register_core
from mcp_server.tools.health import register_tools as _register_health
from mcp_server.tools.ports import register_tools as _register_ports
from mcp_server.tools.spantree import register_tools as _register_spantree
from mcp_server.tools.vlan import register_tools as _register_vlan


def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 MCP tools on the FastMCP server instance.

    Calls the ``register_tools`` function of every sub-module:
    core, ports, vlan, spantree and health.

    Args:
        mcp: FastMCP server instance to register tools on.
    """
    _register_core(mcp)
    _register_ports(mcp)
    _register_vlan(mcp)
    _register_spantree(mcp)
    _register_health(mcp)
