"""
AOS8 UNP (Unified Network Policy) tools.

Covers UNP port configuration, authenticated users, profile definitions
and statistics.
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

def _parse_unp_port(output: str) -> dict:
    """Parse ``show unp port`` output.

    Expected format::

         Port    Port    Type         802.1x   Mac      Class.   Default
                  Domain              Auth     Auth                     ...
        --------+-------+...
        1/1/1          0 Bridge       Enabled  Enabled  Enabled  -   ...

    Args:
        output: Raw CLI text from ``show unp port``.

    Returns:
        Dict with ``ports`` list and ``total_count`` integer.
    """
    ports: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            stripped = line.strip()
            # Skip headers and separators
            if (
                not stripped
                or stripped.lower().startswith("port")
                or stripped.lower().startswith("domain")
                or re.match(r"^[-+\s]+$", stripped)
            ):
                continue
            # Data line:
            # "1/1/1          0 Bridge       Enabled  Enabled  Enabled  -   -   -  Disabled"
            # Columns: port, domain, type, 802.1x_auth, mac_auth, classification,
            #          default_profile, 802.1x_pass_alt, mac_pass_alt, trust_tag
            m = re.match(
                r"^(\S+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)"
                r"(?:\s+(\S+)\s+(\S+)\s+(\S+))?\s*$",
                stripped,
            )
            if m:
                ports.append(
                    {
                        "port": m.group(1),
                        "domain": int(m.group(2)),
                        "type": m.group(3),
                        "auth_802_1x": m.group(4),
                        "mac_auth": m.group(5),
                        "classification": m.group(6),
                        "default_profile": m.group(7),
                        "trust_tag": m.group(10) if m.group(10) else None,
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return {"ports": ports, "total_count": len(ports), "parse_error": str(exc)}
    return {"ports": ports, "total_count": len(ports)}


def _parse_unp_user(output: str) -> dict:
    """Parse ``show unp user`` output.

    Returns an empty list when no authenticated users are present.

    Args:
        output: Raw CLI text from ``show unp user``.

    Returns:
        Dict with ``users`` list and ``total_count`` integer.
    """
    users: list[dict[str, Any]] = []
    total_count = 0
    try:
        for line in output.splitlines():
            stripped = line.strip()

            # "Total users : 0"
            m_total = re.match(r"^Total\s+users\s*:\s*(\d+)", stripped, re.IGNORECASE)
            if m_total:
                total_count = int(m_total.group(1))
                continue

            # Skip headers and separators
            if (
                not stripped
                or stripped.lower().startswith("port")
                or re.match(r"^[-+\s]+$", stripped)
            ):
                continue

            # Data line: port username mac_addr ip vlan profile type status
            m = re.match(
                r"^(\S+)\s+(\S+)\s+([0-9a-fA-F:]{17})\s+(\S+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$",
                stripped,
            )
            if m:
                users.append(
                    {
                        "port": m.group(1),
                        "username": m.group(2),
                        "mac_address": m.group(3).lower(),
                        "ip_address": m.group(4),
                        "vlan": int(m.group(5)),
                        "profile": m.group(6),
                        "type": m.group(7),
                        "status": m.group(8),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return {"users": users, "total_count": total_count or len(users), "parse_error": str(exc)}
    return {"users": users, "total_count": total_count or len(users)}


def _parse_unp_profile(output: str) -> dict:
    """Parse ``show unp profile`` output.

    Expected block format::

        Profile Name: DEVICE-A
            Qos Policy      = -,
            CP State        = Dis,
            Inact Interval  = 10,
            Mac-Mobility =  Dis
        Profile Name: Wi-Fi
            ...
        Total Profile Count: 12

    Args:
        output: Raw CLI text from ``show unp profile``.

    Returns:
        Dict with ``profiles`` list and ``total_count`` integer.
    """
    _FIELD_MAP: dict[str, str] = {
        "qos policy": "qos_policy",
        "cp state": "cp_state",
        "inact interval": "inact_interval",
        "mac-mobility": "mac_mobility",
        "location policy": "location_policy",
        "saa profile": "saa_profile",
        "bandwidth": "bandwidth",
        "vlan": "vlan",
        "sap profile": "sap_profile",
        "mobile tag": "mobile_tag",
    }

    profiles: list[dict[str, Any]] = []
    total_count = 0
    current: dict[str, Any] | None = None
    try:
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            # "Total Profile Count: 12"
            m_total = re.match(r"^Total\s+Profile\s+Count\s*:\s*(\d+)", stripped, re.IGNORECASE)
            if m_total:
                total_count = int(m_total.group(1))
                continue

            # "Profile Name: DEVICE-A"
            m_name = re.match(r"^Profile\s+Name\s*:\s*(\S+)", stripped, re.IGNORECASE)
            if m_name:
                if current is not None:
                    profiles.append(current)
                current = {"name": m_name.group(1)}
                continue

            if current is None:
                continue

            # Key = value lines: "Qos Policy  = -,"
            m_kv = re.match(r"^(.+?)\s*=\s*(.+?),?\s*$", stripped)
            if not m_kv:
                continue
            raw_key = m_kv.group(1).strip().lower()
            raw_val = m_kv.group(2).strip().rstrip(",").strip()
            key = _FIELD_MAP.get(raw_key)
            if key is None:
                key = re.sub(r"[^a-z0-9]+", "_", raw_key).strip("_")
            current[key] = raw_val

        if current is not None:
            profiles.append(current)
    except Exception as exc:  # noqa: BLE001
        return {
            "profiles": profiles,
            "total_count": total_count or len(profiles),
            "parse_error": str(exc),
        }
    return {"profiles": profiles, "total_count": total_count or len(profiles)}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 UNP tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_unp_port(host: str) -> str:
        """Return UNP port configuration for an OmniSwitch.

        Runs ``show unp port`` and returns per-port UNP configuration
        including port, domain, type, 802.1X / MAC authentication state,
        classification enablement, default profile and trust-tag setting.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with UNP port data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show unp port"
        logger.debug("aos_show_unp_port: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_unp_port(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_unp_user(host: str) -> str:
        """Return currently authenticated UNP users for an OmniSwitch.

        Runs ``show unp user`` and returns the list of users currently
        authenticated via 802.1X or MAC authentication, with their port,
        MAC address, IP address, VLAN, assigned profile, auth type and
        session status.  Returns an empty list when no users are active.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with UNP user data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show unp user"
        logger.debug("aos_show_unp_user: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_unp_user(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_unp_profile(host: str) -> str:
        """Return UNP profile definitions for an OmniSwitch.

        Runs ``show unp profile`` and returns all defined UNP profiles
        with their QoS policy, Captive Portal state, inactivity interval,
        MAC-mobility setting and any other configured attributes.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with UNP profile data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show unp profile"
        logger.debug("aos_show_unp_profile: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_unp_profile(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)
