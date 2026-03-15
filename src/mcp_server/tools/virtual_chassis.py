"""
AOS8 Virtual Chassis tools.

Covers VC topology, consistency check and VF-link status.

Note: ``show virtual-chassis members`` is **not** a valid AOS8 command
and is intentionally omitted.
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

def _parse_vc_topology(output: str) -> dict:
    """Parse ``show virtual-chassis topology`` output.

    Expected format::

        Local Chassis: 1
         Oper                                   Config   Oper
         Chas  Role         Status              Chas ID  Pri   Group  MAC-Address
        -----+------------+-------------------+--------+-----+------+------------------
         1     Master       Running             1        100   195    00:11:22:33:44:55

    Args:
        output: Raw CLI text from ``show virtual-chassis topology``.

    Returns:
        Dict with ``local_chassis`` (int or None) and ``chassis`` list.
    """
    local_chassis: int | None = None
    chassis: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            stripped = line.strip()

            # Local Chassis: 1
            m_lc = re.match(r"^Local\s+Chassis\s*:\s*(\d+)", stripped, re.IGNORECASE)
            if m_lc:
                local_chassis = int(m_lc.group(1))
                continue

            # Skip header / separator lines
            if (
                not stripped
                or stripped.startswith("Legend")
                or stripped.startswith("Oper")
                or stripped.startswith("Chas")
                or re.match(r"^[-+\s]+$", stripped)
            ):
                continue

            # Data line:
            # " 1     Master       Running             1        100   195    00:11:22:33:44:55"
            m = re.match(
                r"^(\d+)\s+(\S+)\s+(\S+(?:\s+\S+)*?)\s{2,}(\d+)\s+(\d+)\s+(\d+)\s+([0-9a-fA-F:]{17})\s*$",
                stripped,
            )
            if m:
                chassis.append(
                    {
                        "chas_id": int(m.group(1)),
                        "role": m.group(2),
                        "status": m.group(3).strip(),
                        "config_chas_id": int(m.group(4)),
                        "priority": int(m.group(5)),
                        "group": int(m.group(6)),
                        "mac_address": m.group(7).lower(),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return {
            "local_chassis": local_chassis,
            "chassis": chassis,
            "parse_error": str(exc),
        }
    return {"local_chassis": local_chassis, "chassis": chassis}


def _parse_vc_consistency(output: str) -> dict:
    """Parse ``show virtual-chassis consistency`` output.

    Expected format::

           Config           Oper                   Oper     Config
           Chas             Chas    Chas   Hello   Control  Control
     Chas* ID     Status    Type*   Group* Interv  Vlan*    Vlan     License*
    ------+------+---------+-------+------+-------+--------+--------+----------
     1     1      OK        OS6860  195    15      4094     4094     A

    Args:
        output: Raw CLI text from ``show virtual-chassis consistency``.

    Returns:
        Dict with ``chassis`` list.
    """
    chassis: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            stripped = line.strip()

            # Skip header / separator / legend lines
            if (
                not stripped
                or stripped.startswith("Legend")
                or stripped.startswith("Config")
                or stripped.startswith("Chas")
                or stripped.startswith("Oper")
                or re.match(r"^[-+\s]+$", stripped)
            ):
                continue

            # Data line:
            # " 1     1      OK        OS6860  195    15      4094     4094     A"
            m = re.match(
                r"^(\d+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s*$",
                stripped,
            )
            if m:
                chassis.append(
                    {
                        "chas_id": int(m.group(1)),
                        "config_chas_id": int(m.group(2)),
                        "status": m.group(3),
                        "chas_type": m.group(4),
                        "group": int(m.group(5)),
                        "hello_interval": int(m.group(6)),
                        "control_vlan_oper": int(m.group(7)),
                        "control_vlan_config": int(m.group(8)),
                        "license": m.group(9),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return {"chassis": chassis, "parse_error": str(exc)}
    return {"chassis": chassis}


def _parse_vc_vf_link(output: str) -> dict:
    """Parse ``show virtual-chassis vf-link`` output.

    Returns an empty ``vf_links`` list when no VF-Links are configured
    (header-only or blank output).

    Args:
        output: Raw CLI text from ``show virtual-chassis vf-link``.

    Returns:
        Dict with ``vf_links`` list and ``total_count`` integer.
    """
    vf_links: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            stripped = line.strip()
            if (
                not stripped
                or re.match(r"^[-+\s]+$", stripped)
                or re.match(r"^(VF[- ]?Link|Chassis|Port|Slot)", stripped, re.IGNORECASE)
            ):
                continue
            # Generic data line parsing — adapt columns when real output is available
            parts = stripped.split()
            if len(parts) >= 2:
                vf_links.append({"raw": stripped})
    except Exception as exc:  # noqa: BLE001
        return {"vf_links": vf_links, "total_count": len(vf_links), "parse_error": str(exc)}
    return {"vf_links": vf_links, "total_count": len(vf_links)}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 Virtual Chassis tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_vc_topology(host: str) -> str:
        """Return Virtual Chassis topology for an OmniSwitch.

        Runs ``show virtual-chassis topology`` and returns the local chassis
        identifier and the list of chassis with their role, operational status,
        priority, group and MAC address.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with VC topology data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show virtual-chassis topology"
        logger.debug("aos_show_vc_topology: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_vc_topology(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_vc_consistency(host: str) -> str:
        """Return Virtual Chassis consistency information for an OmniSwitch.

        Runs ``show virtual-chassis consistency`` and returns per-chassis
        consistency details including chassis type, group, hello interval,
        control VLAN and license status.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with VC consistency data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show virtual-chassis consistency"
        logger.debug("aos_show_vc_consistency: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_vc_consistency(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_vc_vf_link(host: str) -> str:
        """Return Virtual Chassis VF-Link status for an OmniSwitch.

        Runs ``show virtual-chassis vf-link`` and returns the list of
        configured VF-Links.  Returns an empty list when no VF-Links are
        configured (single-chassis or no VF-Links defined).

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with VF-Link data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show virtual-chassis vf-link"
        logger.debug("aos_show_vc_vf_link: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_vc_vf_link(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)
