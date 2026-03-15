"""
AOS8 NTP tools.

Covers NTP client status and NTP key listing.

Note on AOS8 command correctness
---------------------------------
* ``show ntp client`` — correct (provides current time, sync status,
  stratum, etc.)  The user-friendly tool is named ``aos_show_ntp_status``
  but the underlying command is ``show ntp client``.
* ``show ntp server`` — **INVALID** on AOS8; do not use.
* ``show ntp keys``   — correct.
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


def _parse_show_ntp_client(output: str) -> dict:
    """Parse ``show ntp client`` output.

    Expected format (key: value pairs, comma-terminated)::

        Current time:                   Fri, Mar 13 2026 16:21:58.811 (CET),
        Last NTP update:                Fri, Mar 13 2026 16:07:39.358 (CET),
        Server reference:               10.0.4.1,
        Client mode:                    enabled,
        Clock status:                   synchronized,
        Stratum:                        5,
        Source IP:                      10.1.0.1,
        VRF Name:                       default

    All key/value pairs are parsed dynamically and normalised into
    snake_case keys.

    Args:
        output: Raw CLI text from ``show ntp client``.

    Returns:
        Dict with all parsed NTP client fields.
    """
    data: dict[str, Any] = {}

    _KEY_MAP = {
        "current time": "current_time",
        "last ntp update": "last_ntp_update",
        "server reference": "server_reference",
        "client mode": "client_mode",
        "clock status": "clock_status",
        "stratum": "stratum",
        "source ip": "source_ip",
        "vrf name": "vrf_name",
    }

    try:
        for line in output.splitlines():
            stripped = line.strip().rstrip(",")
            m = re.match(r"^(.+?)\s*:\s*(.+)$", stripped)
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


def _parse_show_ntp_keys(output: str) -> dict:
    """Parse ``show ntp keys`` output.

    Expected format (may be empty)::

        Key       Status
        -------+------------
        (no data lines when no keys configured)

    Args:
        output: Raw CLI text from ``show ntp keys``.

    Returns:
        Dict with ``keys`` list and ``total_count``.
    """
    keys: list[dict[str, Any]] = []

    try:
        for line in output.splitlines():
            stripped = line.strip()
            if (
                not stripped
                or stripped.lower().startswith("key")
                or stripped.startswith("-")
                or re.match(r"^[- +]+$", stripped)
            ):
                continue

            # Data line: key_id  status
            m = re.match(r"^(\S+)\s+(\S+)\s*$", stripped)
            if m:
                keys.append({"key": m.group(1), "status": m.group(2)})

    except Exception as exc:  # noqa: BLE001
        return {"keys": keys, "total_count": len(keys), "parse_error": str(exc)}

    return {"keys": keys, "total_count": len(keys)}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 NTP tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_ntp_status(host: str) -> str:
        """Return NTP synchronisation status for an OmniSwitch.

        Runs ``show ntp client`` (the correct AOS8 command — NOT
        ``show ntp server`` which is invalid on AOS8) and returns
        current time, last NTP update timestamp, server reference IP,
        client mode, clock synchronisation status, stratum level, source
        IP and VRF name.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with NTP client fields, or ``"ERROR: ..."``
            string on failure.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show ntp client"
        logger.debug("aos_show_ntp_status: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_ntp_client(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_ntp_keys(host: str) -> str:
        """Return the NTP authentication keys configured on an OmniSwitch.

        Runs ``show ntp keys`` and returns the key ID and status for
        every configured NTP authentication key.  Returns an empty
        ``keys`` list when no keys are configured.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with ``keys`` list and ``total_count``, or
            ``"ERROR: ..."`` string on failure.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show ntp keys"
        logger.debug("aos_show_ntp_keys: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_ntp_keys(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)
