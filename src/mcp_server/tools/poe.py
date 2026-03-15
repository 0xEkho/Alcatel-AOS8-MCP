"""
AOS8 Power over Ethernet (PoE / LanPower) tools.

Covers PoE slot status and per-port detailed configuration (READ-ONLY).

Note on AOS8 command correctness
---------------------------------
* ``show lanpower slot 1/1``       — chassis/slot format (NOT ``show lanpower slot 1``)
* ``show lanpower slot 1/1 port``  — per-port admin details

WRITE operations
----------------
``aos_poe_restart`` has been **intentionally removed** from this module.
Any PoE reboot request must go through ``aos_poe_reboot_request``
(module ``poe_approval``) which enforces human validation via Teams.
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


def _parse_show_lanpower_slot(slot: str, output: str) -> dict:
    """Parse ``show lanpower slot <chassis/slot>`` output.

    Expected format::

        Port   Maximum(mW) Actual Used(mW)   Status    Priority   On/Off   Class   Type
        --------+-----------+---------------+-----------+---------+--------+-------+----------
         1/1/1      30000            0       Searching      Low      ON        *
         1/1/7      30000         3900       Delivering     Low      ON        2     T

    Args:
        slot: Slot identifier used in the command (e.g. ``"1/1"``).
        output: Raw CLI text from the command.

    Returns:
        Dict with ``slot``, ``ports`` list, ``total_delivering`` and
        ``total_actual_mw``.
    """
    ports: list[dict[str, Any]] = []

    try:
        for line in output.splitlines():
            stripped = line.strip()
            if (
                not stripped
                or stripped.lower().startswith("port")
                or stripped.startswith("-")
                or re.match(r"^[- +]+$", stripped)
            ):
                continue

            # Data line: port  max_mw  actual_mw  status  priority  on_off  [class]  [type]
            m = re.match(
                r"^(\S+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(ON|OFF)\s*(\S+)?\s*(\S+)?\s*$",
                stripped,
                re.IGNORECASE,
            )
            if m:
                ports.append(
                    {
                        "port": m.group(1),
                        "max_mw": int(m.group(2)),
                        "actual_mw": int(m.group(3)),
                        "status": m.group(4),
                        "priority": m.group(5),
                        "on_off": m.group(6).upper(),
                        "class": m.group(7) or "",
                        "type": m.group(8) or "",
                    }
                )

    except Exception as exc:  # noqa: BLE001
        return {
            "slot": slot,
            "ports": ports,
            "total_delivering": 0,
            "total_actual_mw": 0,
            "parse_error": str(exc),
        }

    total_delivering = sum(1 for p in ports if p["status"].lower() == "delivering")
    total_actual_mw = sum(p["actual_mw"] for p in ports)

    return {
        "slot": slot,
        "ports": ports,
        "total_delivering": total_delivering,
        "total_actual_mw": total_actual_mw,
    }


def _parse_show_lanpower_slot_port(slot: str, output: str) -> dict:
    """Parse ``show lanpower slot <chassis/slot> port`` output.

    Expected format::

        Chas/       Admin      4-Pair      Power   power-over Capacitor   802.3bt   Priority    Trust   Type
         Slot/Port   Status                           -HDMI    Detection
           1/1/1    enabled    disabled     30000    disabled   disabled     NA         low     disabled

    Args:
        slot: Slot identifier used in the command (e.g. ``"1/1"``).
        output: Raw CLI text from the command.

    Returns:
        Dict with ``slot`` and ``ports`` list.
    """
    ports: list[dict[str, Any]] = []

    try:
        for line in output.splitlines():
            stripped = line.strip()
            if (
                not stripped
                or stripped.lower().startswith("chas")
                or stripped.lower().startswith("slot")
                or stripped.startswith("-")
            ):
                continue

            # Data line: port  admin  4pair  power  hdmi  capacitor  bt  priority  trust  [type]
            m = re.match(
                r"^(\S+)\s+(\S+)\s+(\S+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(\S+))?\s*$",
                stripped,
            )
            if m:
                ports.append(
                    {
                        "port": m.group(1),
                        "admin_status": m.group(2),
                        "four_pair": m.group(3),
                        "max_power_mw": int(m.group(4)),
                        "power_over_hdmi": m.group(5),
                        "capacitor_detection": m.group(6),
                        "bt_802_3": m.group(7),
                        "priority": m.group(8),
                        "trust": m.group(9),
                        "type": m.group(10) or "",
                    }
                )

    except Exception as exc:  # noqa: BLE001
        return {"slot": slot, "ports": ports, "parse_error": str(exc)}

    return {"slot": slot, "ports": ports}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 PoE / LanPower tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_lanpower_slot(host: str, slot: str) -> str:
        """Return PoE status for all ports on an OmniSwitch slot.

        Runs ``show lanpower slot <chassis/slot>`` (e.g. ``1/1``) and
        returns maximum power budget, actual power drawn, PoE status,
        priority, on/off state, class and type for every port on the
        slot.  Also includes summary totals for delivering ports and
        total power consumed.

        Args:
            host: IP address or hostname of the OmniSwitch.
            slot: Chassis/slot identifier in ``chassis/slot`` format,
                e.g. ``"1/1"``.

        Returns:
            JSON string with ``slot``, ``ports`` list,
            ``total_delivering`` and ``total_actual_mw``, or
            ``"ERROR: ..."`` string on failure.
        """
        from mcp_server.ssh.client import execute_command

        cmd = f"show lanpower slot {slot}"
        logger.debug("aos_show_lanpower_slot: host=%s slot=%s", host, slot)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_lanpower_slot(slot, output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_lanpower_slot_port(host: str, slot: str) -> str:
        """Return detailed per-port PoE configuration for an OmniSwitch slot.

        Runs ``show lanpower slot <chassis/slot> port`` and returns
        administrative status, 4-pair, power budget, power-over-HDMI,
        capacitor detection, 802.3bt, priority and trust settings for
        every port on the slot.

        Args:
            host: IP address or hostname of the OmniSwitch.
            slot: Chassis/slot identifier in ``chassis/slot`` format,
                e.g. ``"1/1"``.

        Returns:
            JSON string with ``slot`` and ``ports`` list, or
            ``"ERROR: ..."`` string on failure.
        """
        from mcp_server.ssh.client import execute_command

        cmd = f"show lanpower slot {slot} port"
        logger.debug("aos_show_lanpower_slot_port: host=%s slot=%s", host, slot)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_lanpower_slot_port(slot, output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)
