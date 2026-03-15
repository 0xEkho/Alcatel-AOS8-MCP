"""
AOS8 DHCP relay tools.

Covers DHCP relay global configuration and relay statistics.
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


def _parse_show_ip_dhcp_relay(output: str) -> dict:
    """Parse ``show ip dhcp relay`` output.

    Expected format (key = value pairs)::

        IP DHCP Relay :
          DHCP Relay Admin Status                            =  Enable,
          Forward Delay(seconds)                             =  0,
          Max number of hops                                 =  16,
          Relay Agent Information                            =  Disabled,
          DHCP Relay Opt82 Format                            =  Base MAC,
          DHCP Relay Opt82 String                            =  00:11:22:33:44:55,
          PXE support                                        =  Disabled,
          Relay Mode                                         =  Global,

    Args:
        output: Raw CLI text from ``show ip dhcp relay``.

    Returns:
        Dict with DHCP relay configuration fields.
    """
    data: dict[str, Any] = {}

    _KEY_MAP = {
        "dhcp relay admin status": "admin_status",
        "forward delay(seconds)": "forward_delay_s",
        "max number of hops": "max_hops",
        "relay agent information": "relay_agent_info",
        "dhcp relay opt82 format": "opt82_format",
        "dhcp relay opt82 string": "opt82_string",
        "pxe support": "pxe_support",
        "relay mode": "relay_mode",
    }

    try:
        for line in output.splitlines():
            stripped = line.strip().rstrip(",")
            m = re.match(r"^(.+?)\s*=\s*(.+)$", stripped)
            if not m:
                continue
            raw_key = m.group(1).strip().lower()
            value = m.group(2).strip()
            key = _KEY_MAP.get(
                raw_key,
                re.sub(r"[^a-z0-9]+", "_", raw_key).strip("_"),
            )
            # Coerce numeric strings
            if re.match(r"^\d+$", value):
                data[key] = int(value)
            else:
                data[key] = value

    except Exception as exc:  # noqa: BLE001
        data["parse_error"] = str(exc)

    return data


def _parse_show_ip_dhcp_relay_statistics(output: str) -> dict:
    """Parse ``show ip dhcp relay statistics`` output.

    Expected format::

        Global Statistics :
            Reception From Client :
              Total Count =          0, Delta =          0
            Forw Delay Violation :
              Total Count =          0, Delta =          0

    Each section heading followed by a ``Total Count = N, Delta = N``
    line is captured as one statistics entry.

    Args:
        output: Raw CLI text from ``show ip dhcp relay statistics``.

    Returns:
        Dict with ``statistics`` list, each item having ``category``,
        ``total_count`` and ``delta``.
    """
    statistics: list[dict[str, Any]] = []
    current_category: str | None = None

    try:
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            # Section header lines end with ":"  e.g. "Reception From Client :"
            m_header = re.match(r"^([A-Za-z].+?)\s*:$", stripped)
            if m_header:
                candidate = m_header.group(1).strip()
                # Skip top-level "Global Statistics" header
                if candidate.lower() != "global statistics":
                    current_category = candidate
                continue

            # Data line: "Total Count =   0, Delta =   0"
            m_data = re.match(
                r"^Total\s+Count\s*=\s*(\d+),\s*Delta\s*=\s*(\d+)",
                stripped,
                re.IGNORECASE,
            )
            if m_data and current_category is not None:
                statistics.append(
                    {
                        "category": current_category,
                        "total_count": int(m_data.group(1)),
                        "delta": int(m_data.group(2)),
                    }
                )
                current_category = None

    except Exception as exc:  # noqa: BLE001
        return {"statistics": statistics, "parse_error": str(exc)}

    return {"statistics": statistics}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 DHCP relay tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_ip_dhcp_relay(host: str) -> str:
        """Return DHCP relay global configuration for an OmniSwitch.

        Runs ``show ip dhcp relay`` and returns administrative status,
        forward delay, maximum hops, relay agent information flag,
        option-82 format and string, PXE support status and relay mode.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with DHCP relay configuration, or
            ``"ERROR: ..."`` string on failure.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show ip dhcp relay"
        logger.debug("aos_show_ip_dhcp_relay: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_ip_dhcp_relay(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_ip_dhcp_relay_statistics(host: str) -> str:
        """Return DHCP relay statistics for an OmniSwitch.

        Runs ``show ip dhcp relay statistics`` and returns packet
        counters (total count and delta since last clear) for each
        statistics category such as client reception, forward-delay
        violations, relay drops, etc.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with ``statistics`` list, or ``"ERROR: ..."``
            string on failure.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show ip dhcp relay statistics"
        logger.debug("aos_show_ip_dhcp_relay_statistics: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_ip_dhcp_relay_statistics(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)
