"""
AOS8 Health and monitoring tools.

Covers CPU/memory health, temperature sensors, fan status and MAC
learning table.

Note: AOS8 OmniSwitch does not expose ``show cpu`` or
``show power supplies`` as standalone commands.  CPU and memory
utilisation are available via ``show health`` and power supply data
via dedicated hardware-specific commands not covered here.
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

def _parse_show_health(output: str) -> dict:
    """Parse 'show health' output.

    Expected format::

        CMM                    Current   1 Min    1 Hr   1 Day
        Resources                         Avg      Avg     Avg
        CPU                     78       43      32      31
        Memory                  10       10      10      10

    Args:
        output: Raw CLI text from ``show health``.

    Returns:
        Dict with ``resources`` list.
    """
    resources: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            stripped = line.strip()
            # Data lines: "CPU   78   43   32   31"
            m = re.match(
                r"^([A-Za-z]\S*)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$",
                stripped,
            )
            if m:
                resources.append(
                    {
                        "resource": m.group(1),
                        "current_pct": int(m.group(2)),
                        "avg_1min_pct": int(m.group(3)),
                        "avg_1hr_pct": int(m.group(4)),
                        "avg_1day_pct": int(m.group(5)),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return {"resources": resources, "parse_error": str(exc)}
    return {"resources": resources}


def _parse_show_temp(output: str) -> dict:
    """Parse 'show temp' output.

    Expected format::

        Chassis/Device | Current | Range | Danger | Thresh | Status
         1/CMMA            38      15 to 85   88      85    UNDER THRESHOLD

    Args:
        output: Raw CLI text from ``show temp``.

    Returns:
        Dict with ``sensors`` list.
    """
    sensors: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            stripped = line.strip()
            # Data line: "1/CMMA  38  15 to 85  88  85  UNDER THRESHOLD"
            m = re.match(
                r"^(\S+)\s+(\d+)\s+(\d+)\s+to\s+(\d+)\s+(\d+)\s+(\d+)\s+(.+)$",
                stripped,
            )
            if m:
                sensors.append(
                    {
                        "device": m.group(1),
                        "current_c": int(m.group(2)),
                        "range_min_c": int(m.group(3)),
                        "range_max_c": int(m.group(4)),
                        "danger_c": int(m.group(5)),
                        "thresh_c": int(m.group(6)),
                        "status": m.group(7).strip(),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return {"sensors": sensors, "parse_error": str(exc)}
    return {"sensors": sensors}


def _parse_show_fan(output: str) -> dict:
    """Parse 'show fan' output.

    Expected format::

        Chassis/Tray | Fan | Functional
           1/--         1       YES

    Args:
        output: Raw CLI text from ``show fan``.

    Returns:
        Dict with ``fans`` list.
    """
    fans: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            stripped = line.strip()
            # Data line: "1/--   1   YES"
            m = re.match(r"^(\S+)\s+(\d+)\s+(\S+)\s*$", stripped)
            if not m:
                continue
            # Skip the header line
            if m.group(1).lower() in ("chassis/tray", "---"):
                continue
            fans.append(
                {
                    "chassis_tray": m.group(1),
                    "fan": int(m.group(2)),
                    "functional": m.group(3).upper() == "YES",
                }
            )
    except Exception as exc:  # noqa: BLE001
        return {"fans": fans, "parse_error": str(exc)}
    return {"fans": fans}


def _parse_mac_learning(output: str) -> dict:
    """Parse 'show mac-learning' or 'show mac-learning port <port>' output.

    Expected table format::

        Domain    Vlan/SrvcId[:ID]    Mac Address    Type    Operation    Interface
        VLAN      18   00:aa:bb:cc:dd:01   dynamic   bridging   1/1/25

    Args:
        output: Raw CLI text from ``show mac-learning``.

    Returns:
        Dict with ``entries`` list and ``total_count`` integer.
    """
    entries: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            stripped = line.strip()
            # Skip legend, header and separator lines
            if (
                not stripped
                or stripped.startswith("Legend")
                or stripped.startswith("Mac Address")
                or stripped.startswith("ID =")
                or stripped.startswith("Domain")
                or stripped.startswith("---")
                or stripped.startswith("-")
                or re.match(r"^[- +]+$", stripped)
            ):
                continue
            # Data line:
            # "  VLAN   18   00:aa:bb:cc:dd:01   dynamic   bridging   1/1/25"
            m = re.match(
                r"^(\S+)\s+(\d+)\s+([0-9a-fA-F:]{17})\s+(\S+)\s+(\S+)\s+(\S+)\s*$",
                stripped,
            )
            if m:
                entries.append(
                    {
                        "domain": m.group(1),
                        "vlan_id": int(m.group(2)),
                        "mac_address": m.group(3).lower(),
                        "type": m.group(4),
                        "operation": m.group(5),
                        "interface": m.group(6),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return {
            "entries": entries,
            "total_count": len(entries),
            "parse_error": str(exc),
        }
    return {"entries": entries, "total_count": len(entries)}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 health and monitoring tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_health(host: str) -> str:
        """Return CPU and memory utilisation statistics for an OmniSwitch.

        Runs ``show health`` and returns current, 1-minute, 1-hour and
        1-day average percentages for CPU and memory.

        Note: AOS8 does not provide a standalone ``show cpu`` command;
        this tool is the correct way to retrieve CPU utilisation.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with health resources or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_health: host=%s", host)
        output = await execute_command(host, "show health")
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_health(output)
        return json.dumps(
            {"host": host, "command": "show health", **data}, indent=2
        )

    @mcp.tool()
    async def aos_show_temp(host: str) -> str:
        """Return temperature sensor readings for an OmniSwitch.

        Runs ``show temp`` and returns current temperature, operating
        range, danger threshold and status for each hardware sensor.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with temperature sensor data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_temp: host=%s", host)
        output = await execute_command(host, "show temp")
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_temp(output)
        return json.dumps(
            {"host": host, "command": "show temp", **data}, indent=2
        )

    @mcp.tool()
    async def aos_show_fan(host: str) -> str:
        """Return fan operational status for an OmniSwitch.

        Runs ``show fan`` and returns chassis/tray identifier, fan
        number and functional status for each fan unit.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with fan status list or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_fan: host=%s", host)
        output = await execute_command(host, "show fan")
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_fan(output)
        return json.dumps(
            {"host": host, "command": "show fan", **data}, indent=2
        )

    @mcp.tool()
    async def aos_show_mac_learning(host: str) -> str:
        """Return the full MAC address learning table for an OmniSwitch.

        Runs ``show mac-learning`` (the correct AOS8 command — not
        ``show mac-address-table``) and returns domain, VLAN ID, MAC
        address, entry type, forwarding operation and learned interface
        for every entry.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with MAC learning entries or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_mac_learning: host=%s", host)
        output = await execute_command(host, "show mac-learning")
        if output.startswith("ERROR:"):
            return output
        data = _parse_mac_learning(output)
        return json.dumps(
            {"host": host, "command": "show mac-learning", **data}, indent=2
        )

    @mcp.tool()
    async def aos_show_mac_learning_port(host: str, port: str) -> str:
        """Return MAC addresses learned on a specific OmniSwitch port.

        Runs ``show mac-learning port <port>`` and returns the MAC
        learning entries filtered to the requested interface.

        Args:
            host: IP address or hostname of the OmniSwitch.
            port: Port identifier in ``chassis/slot/port`` format, e.g. ``"1/1/7"``.

        Returns:
            JSON string with MAC learning entries or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = f"show mac-learning port {port}"
        logger.debug("aos_show_mac_learning_port: host=%s port=%s", host, port)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_mac_learning(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)
