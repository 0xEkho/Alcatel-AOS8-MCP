"""
AOS8 QoS tools.

Covers the global QoS switch configuration.
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

def _parse_qos_config(output: str) -> dict:
    """Parse ``show qos config`` output.

    Expected format (indented key = value lines under a header)::

        QoS Configuration
          Admin                          = enable,
          Switch Group                   = expanded,
          Trust ports                    = no,
          Phones                         = trusted,
          Log lines                      = 10240,
          Log level                      = 6,
          Log console                    = no,
          Forward log                    = no,
          Stats interval                 = 60,
          User-port filter               = none,
          User-port shutdown             = bpdu,
          Debug                          = info,
          DEI Mapping                    = Disabled,
          DEI Marking                    = Disabled,
          Pending changes                = none

    Field names are normalised to snake_case.  Integer-valued fields are
    cast to ``int``; ``yes/no`` values are left as strings for consistency
    with other AOS8 modules.

    Args:
        output: Raw CLI text from ``show qos config``.

    Returns:
        Dict with all QoS configuration fields.
    """
    _KEY_MAP: dict[str, str] = {
        "admin": "admin",
        "switch group": "switch_group",
        "trust ports": "trust_ports",
        "phones": "phones",
        "log lines": "log_lines",
        "log level": "log_level",
        "log console": "log_console",
        "forward log": "forward_log",
        "stats interval": "stats_interval",
        "user-port filter": "user_port_filter",
        "user-port shutdown": "user_port_shutdown",
        "debug": "debug",
        "dei mapping": "dei_mapping",
        "dei marking": "dei_marking",
        "pending changes": "pending_changes",
    }
    _INT_KEYS = {"log_lines", "log_level", "stats_interval"}

    result: dict[str, Any] = {}
    try:
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped or stripped.lower().startswith("qos configuration"):
                continue

            m = re.match(r"^(.+?)\s*=\s*(.+?),?\s*$", stripped)
            if not m:
                continue
            raw_label = m.group(1).strip().lower()
            raw_value = m.group(2).strip().rstrip(",")

            key = _KEY_MAP.get(raw_label)
            if key is None:
                key = re.sub(r"[^a-z0-9]+", "_", raw_label).strip("_")

            if key in _INT_KEYS:
                try:
                    result[key] = int(raw_value)
                except ValueError:
                    result[key] = raw_value
            else:
                result[key] = raw_value
    except Exception as exc:  # noqa: BLE001
        return {**result, "parse_error": str(exc)}
    return result


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 QoS tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_qos_config(host: str) -> str:
        """Return global QoS configuration for an OmniSwitch.

        Runs ``show qos config`` and returns all global QoS parameters
        including admin state, switch group, trust ports setting, phone
        trust, logging parameters, statistics interval, user-port
        shutdown/filter policy, DEI mapping/marking and pending change
        state.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with QoS configuration data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show qos config"
        logger.debug("aos_show_qos_config: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_qos_config(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)
