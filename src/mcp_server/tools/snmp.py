"""
AOS8 SNMP tools.

Covers SNMP trap station table, community-map and security configuration.
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

def _parse_snmp_station(output: str) -> dict:
    """Parse ``show snmp station`` output.

    Expected format::

        ipAddress/port                                      status    protocol user
        ---------------------------------------------------+---------+--------+-------
        198.51.100.10/162                                   enable    v2       ?
        198.51.100.30/162                                   enable    v2       ?
        203.0.113.50/162                                    enable    v3       CLOUD_RW

    Args:
        output: Raw CLI text from ``show snmp station``.

    Returns:
        Dict with ``stations`` list and ``total_count`` integer.
    """
    stations: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            stripped = line.strip()
            # Skip headers and separators
            if (
                not stripped
                or stripped.lower().startswith("ipaddress")
                or re.match(r"^[-+\s]+$", stripped)
            ):
                continue
            # Data line: "198.51.100.10/162   enable    v2       ?"
            m = re.match(
                r"^(\d[\d.]+)/(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$",
                stripped,
            )
            if m:
                stations.append(
                    {
                        "ip_address": m.group(1),
                        "port": int(m.group(2)),
                        "status": m.group(3),
                        "protocol": m.group(4),
                        "user": m.group(5),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return {"stations": stations, "total_count": len(stations), "parse_error": str(exc)}
    return {"stations": stations, "total_count": len(stations)}


def _parse_snmp_community_map(output: str) -> dict:
    """Parse ``show snmp community-map`` output.

    Expected format::

        Community mode : enabled

        status        community string                 user name
        --------+--------------------------------+--------------------------------
        enabled  company_RO                       SNMP_RO
        enabled  company_RW                       MGMT_RW

    Args:
        output: Raw CLI text from ``show snmp community-map``.

    Returns:
        Dict with ``community_mode`` string, ``communities`` list and
        ``total_count`` integer.
    """
    community_mode: str = ""
    communities: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            stripped = line.strip()

            # "Community mode : enabled"
            m_mode = re.match(r"^Community\s+mode\s*:\s*(\S+)", stripped, re.IGNORECASE)
            if m_mode:
                community_mode = m_mode.group(1).rstrip(",")
                continue

            # Skip headers and separators
            if (
                not stripped
                or stripped.lower().startswith("status")
                or re.match(r"^[-+\s]+$", stripped)
            ):
                continue

            # Data line: "enabled  company_RO   SNMP_RO"
            m = re.match(r"^(\S+)\s+(\S+)\s+(\S+)\s*$", stripped)
            if m:
                communities.append(
                    {
                        "status": m.group(1),
                        "community_string": m.group(2),
                        "user_name": m.group(3),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return {
            "community_mode": community_mode,
            "communities": communities,
            "total_count": len(communities),
            "parse_error": str(exc),
        }
    return {
        "community_mode": community_mode,
        "communities": communities,
        "total_count": len(communities),
    }


def _parse_snmp_security(output: str) -> dict:
    """Parse ``show snmp security`` output.

    The output is typically sparse (default security only, no explicit entries).
    Returns the raw output for LLM interpretation.

    Args:
        output: Raw CLI text from ``show snmp security``.

    Returns:
        Dict with ``raw`` field containing the unmodified CLI output.
    """
    return {"raw": output.strip()}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 SNMP tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_snmp_station(host: str) -> str:
        """Return SNMP trap station (manager) table for an OmniSwitch.

        Runs ``show snmp station`` and returns the list of configured SNMP
        trap destinations with their IP address, UDP port, status, SNMP
        protocol version and user name.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with SNMP station data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show snmp station"
        logger.debug("aos_show_snmp_station: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_snmp_station(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_snmp_community_map(host: str) -> str:
        """Return SNMP community-to-user mapping table for an OmniSwitch.

        Runs ``show snmp community-map`` and returns the global community
        mode flag and the list of community strings mapped to SNMPv3 user
        names.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with community-map data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show snmp community-map"
        logger.debug("aos_show_snmp_community_map: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_snmp_community_map(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_snmp_security(host: str) -> str:
        """Return SNMP security configuration for an OmniSwitch.

        Runs ``show snmp security`` and returns the raw output.  This
        command typically shows little content when only default SNMP
        security is configured.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with raw SNMP security output or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show snmp security"
        logger.debug("aos_show_snmp_security: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_snmp_security(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)
