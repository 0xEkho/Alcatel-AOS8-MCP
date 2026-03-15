"""
AOS8 VLAN tools.

Covers VLAN database listing and VLAN port membership.
"""
import json
import logging
import re
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_show_vlan(output: str) -> dict:
    """Parse 'show vlan' output into a structured dict.

    Expected table format (columns separated by whitespace)::

        vlan    type   admin   oper    ip    mtu   name
        1       std    Ena     Dis     Dis   1500  NE PAS UTILISER

    Args:
        output: Raw CLI text from ``show vlan``.

    Returns:
        Dict with ``vlans`` list and ``total_count`` integer.
    """
    vlans: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            stripped = line.strip()
            # Data lines start with a VLAN ID (number)
            m = re.match(
                r"^(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\d+)\s+(.*)",
                stripped,
            )
            if not m:
                continue
            vlans.append(
                {
                    "vlan_id": int(m.group(1)),
                    "type": m.group(2),
                    "admin": m.group(3),
                    "oper": m.group(4),
                    "ip": m.group(5),
                    "mtu": int(m.group(6)),
                    "name": m.group(7).strip() or None,
                }
            )
    except Exception as exc:  # noqa: BLE001
        return {"vlans": vlans, "total_count": len(vlans), "parse_error": str(exc)}
    return {"vlans": vlans, "total_count": len(vlans)}


def _parse_show_vlan_members(output: str) -> dict:
    """Parse 'show vlan members' output into a structured dict.

    Expected table format::

        vlan       port         type         status
          1        1/1/1        untagged     inactive

    Args:
        output: Raw CLI text from ``show vlan members``.

    Returns:
        Dict with ``members`` list and ``total_count`` integer.
    """
    members: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            stripped = line.strip()
            m = re.match(
                r"^(\d+)\s+(\S+)\s+(\S+)\s+(\S+)",
                stripped,
            )
            if not m:
                continue
            members.append(
                {
                    "vlan_id": int(m.group(1)),
                    "port": m.group(2),
                    "type": m.group(3),
                    "status": m.group(4),
                }
            )
    except Exception as exc:  # noqa: BLE001
        return {
            "members": members,
            "total_count": len(members),
            "parse_error": str(exc),
        }
    return {"members": members, "total_count": len(members)}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 VLAN tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_vlan(host: str) -> str:
        """Return the VLAN database for an AOS8 OmniSwitch.

        Runs ``show vlan`` and returns VLAN ID, type, admin/oper/IP
        status, MTU and name for every configured VLAN.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with VLAN list and total count, or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_vlan: host=%s", host)
        output = await execute_command(host, "show vlan")
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_vlan(output)
        return json.dumps({"host": host, "command": "show vlan", **data}, indent=2)

    @mcp.tool()
    async def aos_show_vlan_members(host: str) -> str:
        """Return VLAN port membership for all VLANs on an OmniSwitch.

        Runs ``show vlan members`` and returns VLAN ID, port, membership
        type (tagged/untagged) and forwarding status for every association.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with VLAN membership list or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_vlan_members: host=%s", host)
        output = await execute_command(host, "show vlan members")
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_vlan_members(output)
        return json.dumps(
            {"host": host, "command": "show vlan members", **data}, indent=2
        )
