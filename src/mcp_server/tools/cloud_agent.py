"""
AOS8 Cloud Agent tools.

Covers the OmniVista Cloud Agent activation and device management state.
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

def _parse_cloud_agent_status(output: str) -> dict:
    """Parse ``show cloud-agent status`` output.

    Expected format (key : value lines)::

        Admin State                     : Enabled,
        Activation Server State         : completeOK,
        Device State                    : DeviceManaged,
        Error State                     : None,
        Cloud Group                     : abc123group,
        Activation Server               : activation.cloud.example.com:443,
        NTP Server                      : 198.51.100.20, 198.51.100.21, 10.0.4.1,
        DNS Server                      : 198.51.100.20, 198.51.100.21, 10.0.4.1,
        DNS Domain                      : company.lan,
        VPN Server                      : abc123group.tenant.vpn.cloud.example.com:443,
        OV tenant                       : acme-corp.ov.example.com:443,
        Time to next Call Home (sec)    : 562,
        Call Home Timer Status          : Running,
        Certificate Status              : Consistent
        Thin Client                     : Disabled

    Multi-valued fields (NTP Server, DNS Server) are split on commas into lists.

    Args:
        output: Raw CLI text from ``show cloud-agent status``.

    Returns:
        Dict with all cloud-agent status fields in snake_case.
    """
    # Mapping from raw label (lowercased, stripped) to result key
    _KEY_MAP: dict[str, str] = {
        "admin state": "admin_state",
        "activation server state": "activation_server_state",
        "device state": "device_state",
        "error state": "error_state",
        "cloud group": "cloud_group",
        "activation server": "activation_server",
        "ntp server": "ntp_servers",
        "dns server": "dns_servers",
        "dns domain": "dns_domain",
        "vpn server": "vpn_server",
        "ov tenant": "ov_tenant",
        "time to next call home (sec)": "time_to_next_call_home_sec",
        "call home timer status": "call_home_timer_status",
        "certificate status": "certificate_status",
        "thin client": "thin_client",
    }
    _LIST_KEYS = {"ntp_servers", "dns_servers"}

    result: dict[str, Any] = {}
    try:
        for line in output.splitlines():
            # Each line: "Label   : value[,]"
            m = re.match(r"^(.+?)\s*:\s*(.+?),?\s*$", line)
            if not m:
                continue
            raw_label = m.group(1).strip().lower()
            raw_value = m.group(2).strip().rstrip(",")

            key = _KEY_MAP.get(raw_label)
            if key is None:
                # Fallback: normalise label to snake_case
                key = re.sub(r"[^a-z0-9]+", "_", raw_label).strip("_")

            if key in _LIST_KEYS:
                result[key] = [v.strip() for v in raw_value.split(",") if v.strip()]
            else:
                result[key] = raw_value
    except Exception as exc:  # noqa: BLE001
        return {**result, "parse_error": str(exc)}
    return result


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 Cloud Agent tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_cloud_agent_status(host: str) -> str:
        """Return OmniVista Cloud Agent status for an OmniSwitch.

        Runs ``show cloud-agent status`` and returns the admin state,
        activation and device management states, cloud group, server
        endpoints (activation, VPN, OV tenant), NTP/DNS server lists,
        call-home timer and certificate status.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with cloud-agent status data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show cloud-agent status"
        logger.debug("aos_show_cloud_agent_status: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_cloud_agent_status(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)
