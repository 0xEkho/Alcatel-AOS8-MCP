"""
AOS8 Port / Interface tools.

Covers interface status, aliases, error counters, DDM optics, per-port
detail, LLDP neighbours and flood-rate configuration.
"""
import json
import logging
import re
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _null(value: str) -> str | None:
    """Return *None* for dash / empty values.

    Args:
        value: Raw string from CLI output.

    Returns:
        Stripped string or ``None``.
    """
    v = value.strip().rstrip(",") if value else ""
    return None if v in ("-", "--", "") else v


def _int_or_none(value: str) -> int | None:
    """Convert *value* to int or return ``None``.

    Args:
        value: String that may represent an integer.

    Returns:
        Integer or ``None``.
    """
    try:
        return int(value.strip().replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _float_or_none(value: str) -> float | None:
    """Convert a DDM numeric value to float, stripping threshold markers.

    Threshold markers like ``(AL)``, ``(AH)``, ``(WL)``, ``(WH)`` are
    removed before conversion.  ``-inf`` and ``inf`` map to ``None``.

    Args:
        value: Raw numeric string from DDM output.

    Returns:
        Float or ``None``.
    """
    v = re.sub(r"\([A-Z]+\)", "", value).strip()
    if not v or v in ("-", "-inf", "inf", "N/A"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_interfaces_status(output: str) -> dict:
    """Parse 'show interfaces status' output.

    Args:
        output: Raw CLI text.

    Returns:
        Dict with ``ports`` list.
    """
    ports: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            m = re.match(
                r"^\s+(\d+/\d+/\d+)\s+"
                r"(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+"
                r"(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)",
                line,
            )
            if not m:
                continue
            ports.append(
                {
                    "port": m.group(1),
                    "admin_status": _null(m.group(2)),
                    "auto_nego": _null(m.group(3)),
                    "detected_speed_mbps": _null(m.group(4)),
                    "detected_duplex": _null(m.group(5)),
                    "configured_speed": _null(m.group(8)),
                    "link_trap": _null(m.group(12)),
                    "eee": _null(m.group(13)),
                }
            )
    except Exception as exc:  # noqa: BLE001
        return {"ports": ports, "parse_error": str(exc)}
    return {"ports": ports}


def _parse_interfaces_alias(output: str) -> dict:
    """Parse 'show interfaces alias' output.

    Args:
        output: Raw CLI text.

    Returns:
        Dict with ``ports`` list.
    """
    ports: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            # port  admin  link  wtr  wts  "alias"
            m = re.match(
                r"^\s+(\d+/\d+/\d+)\s+(\S+)\s+(\S+)\s+\S+\s+\S+\s+\"([^\"]*)\"",
                line,
            )
            if not m:
                continue
            ports.append(
                {
                    "port": m.group(1),
                    "admin_status": m.group(2),
                    "link_status": m.group(3),
                    "alias": m.group(4) if m.group(4) else None,
                }
            )
    except Exception as exc:  # noqa: BLE001
        return {"ports": ports, "parse_error": str(exc)}
    return {"ports": ports}


def _parse_interfaces_counters_errors(output: str) -> dict:
    """Parse 'show interfaces counters errors' output.

    Only ports present in the output are included (AOS8 only shows
    ports that are up or have error counts).

    Args:
        output: Raw CLI text.

    Returns:
        Dict with ``ports`` list.
    """
    ports: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    try:
        for line in output.splitlines():
            # Port header line: "1/1/7   ,"
            m = re.match(r"^(\d+/\d+/\d+)\s*,\s*$", line.strip())
            if m:
                if current is not None:
                    ports.append(current)
                current = {
                    "port": m.group(1),
                    "if_in_errors": None,
                    "undersize_pkts": None,
                    "oversize_pkts": None,
                }
                continue
            if current is None:
                continue
            m_err = re.search(r"IfInErrors\s*=\s*(\d+)", line)
            if m_err:
                current["if_in_errors"] = int(m_err.group(1))
            m_under = re.search(r"Undersize pkts\s*=\s*(\d+)", line)
            if m_under:
                current["undersize_pkts"] = int(m_under.group(1))
            m_over = re.search(r"Oversize pkts\s*=\s*(\d+)", line)
            if m_over:
                current["oversize_pkts"] = int(m_over.group(1))
        if current is not None:
            ports.append(current)
    except Exception as exc:  # noqa: BLE001
        return {"ports": ports, "parse_error": str(exc)}
    return {"ports": ports}


def _parse_interfaces_ddm(output: str) -> dict:
    """Parse 'show interfaces ddm' output.

    Each port entry has five threshold rows (Actual, A-High, W-High,
    W-Low, A-Low) with temperature, voltage, TX bias, output power and
    input power columns.

    Args:
        output: Raw CLI text.

    Returns:
        Dict with ``ports`` list.
    """
    ports: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    _THRESH_ORDER = ["actual", "alarm_high", "warning_high", "warning_low", "alarm_low"]
    _THRESH_LABELS = {
        "actual": "actual",
        "a-high": "alarm_high",
        "w-high": "warning_high",
        "w-low": "warning_low",
        "a-low": "alarm_low",
    }
    _thresh_idx: int = 0

    def _row_fields(cols: list[str]) -> dict[str, Any]:
        return {
            "temp_c": _float_or_none(cols[0]) if len(cols) > 0 else None,
            "voltage_v": _float_or_none(cols[1]) if len(cols) > 1 else None,
            "tx_bias_ma": _float_or_none(cols[2]) if len(cols) > 2 else None,
            "output_dbm": _float_or_none(cols[3]) if len(cols) > 3 else None,
            "input_dbm": _float_or_none(cols[4]) if len(cols) > 4 else None,
        }

    try:
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("Chas") or stripped.startswith("Slot") \
                    or stripped.startswith("Port") or stripped.startswith("---") \
                    or stripped.startswith("WL") or stripped.startswith("WH") \
                    or stripped.startswith("AL") or stripped.startswith("AH") \
                    or stripped.startswith("NS") or stripped.startswith("Calibration"):
                continue

            # New port line: " 1/1/25    Actual    33.0 ..."
            m_port = re.match(
                r"^\s+(\d+/\d+/\d+)\s+(Actual|A-High|W-High|W-Low|A-Low)\s+(.*)",
                line,
                re.IGNORECASE,
            )
            if m_port:
                if current is not None:
                    ports.append(current)
                current = {
                    "port": m_port.group(1),
                    "temp_c": None,
                    "voltage_v": None,
                    "tx_bias_ma": None,
                    "output_dbm": None,
                    "input_dbm": None,
                    "thresholds": {},
                }
                _thresh_idx = 0
                thresh_key = _THRESH_LABELS.get(m_port.group(2).lower(), "actual")
                cols = m_port.group(3).split()
                row = _row_fields(cols)
                if thresh_key == "actual":
                    current["temp_c"] = row["temp_c"]
                    current["voltage_v"] = row["voltage_v"]
                    current["tx_bias_ma"] = row["tx_bias_ma"]
                    current["output_dbm"] = row["output_dbm"]
                    current["input_dbm"] = row["input_dbm"]
                else:
                    current["thresholds"][thresh_key] = row
                continue

            # Continuation threshold row: "           A-High    90.0 ..."
            if current is not None:
                m_thresh = re.match(
                    r"^\s+(A-High|W-High|W-Low|A-Low)\s+(.*)",
                    line,
                    re.IGNORECASE,
                )
                if m_thresh:
                    thresh_key = _THRESH_LABELS.get(m_thresh.group(1).lower(), "unknown")
                    cols = m_thresh.group(2).split()
                    current["thresholds"][thresh_key] = _row_fields(cols)

        if current is not None:
            ports.append(current)
    except Exception as exc:  # noqa: BLE001
        return {"ports": ports, "parse_error": str(exc)}
    return {"ports": ports}


def _parse_interfaces_port(output: str) -> dict:
    """Parse 'show interfaces port <port>' output.

    Args:
        output: Raw CLI text.

    Returns:
        Dict with per-port counters and attributes.
    """
    result: dict[str, Any] = {
        "port": None,
        "operational_status": None,
        "port_down_reason": None,
        "last_time_link_changed": None,
        "number_of_status_change": None,
        "type": None,
        "interface_type": None,
        "mac_address": None,
        "bandwidth_mbps": None,
        "duplex": None,
        "autonegotiation": None,
        "long_frame_size_bytes": None,
        "rx_bytes": None,
        "rx_unicast_frames": None,
        "rx_broadcast_frames": None,
        "rx_mcast_frames": None,
        "rx_undersize_frames": None,
        "rx_oversize_frames": None,
        "rx_lost_frames": None,
        "rx_error_frames": None,
        "rx_crc_error_frames": None,
        "rx_alignment_errors": None,
        "tx_bytes": None,
        "tx_unicast_frames": None,
        "tx_broadcast_frames": None,
        "tx_mcast_frames": None,
        "tx_lost_frames": None,
        "tx_collided_frames": None,
        "tx_error_frames": None,
        "tx_collisions": None,
        "tx_late_collisions": None,
        "tx_exc_collisions": None,
    }

    def _search(pattern: str) -> str | None:
        m = re.search(pattern, output, re.IGNORECASE)
        return m.group(1).strip().rstrip(",").strip() if m else None

    def _int_search(pattern: str) -> int | None:
        val = _search(pattern)
        return _int_or_none(val) if val is not None else None

    try:
        result["port"] = _search(r"Chassis/Slot/Port\s*:\s*(\S+)")
        result["operational_status"] = _search(r"Operational Status\s*:\s*(\S+)")
        result["port_down_reason"] = _search(r"Port-Down/Violation Reason\s*:\s*([^,\n]+)")
        result["last_time_link_changed"] = _search(
            r"Last Time Link Changed\s*:\s*([^,\n]+)"
        )
        result["number_of_status_change"] = _int_search(
            r"Number of Status Change\s*:\s*(\d+)"
        )
        result["type"] = _search(r"^\s+Type\s*:\s*([^,\n]+)")
        result["interface_type"] = _search(r"Interface Type\s*:\s*([^,\n]+)")
        result["mac_address"] = _search(r"MAC address\s*:\s*([0-9a-fA-F:]+)")
        bw = _search(r"BandWidth \(Megabits\)\s*:\s*(\S+)")
        result["bandwidth_mbps"] = _null(bw) if bw else None
        result["duplex"] = _search(r"Duplex\s*:\s*([^,\n\t]+)")
        result["autonegotiation"] = _search(r"Autonegotiation\s*:\s*([^,\n]+)")
        result["long_frame_size_bytes"] = _int_search(
            r"Long Frame Size\(Bytes\)\s*:\s*(\d+)"
        )
        # Rx counters
        result["rx_bytes"] = _int_search(r"Bytes Received\s*:\s*(\d+)")
        result["rx_unicast_frames"] = _int_search(
            r"Bytes Received.*?Unicast Frames\s*:\s*(\d+)"
        )
        result["rx_broadcast_frames"] = _int_search(
            r"Broadcast Frames\s*:\s*(\d+),\s*M-cast"
        )
        result["rx_mcast_frames"] = _int_search(
            r"M-cast Frames\s*:\s*(\d+),\s*UnderSize"
        )
        result["rx_undersize_frames"] = _int_search(r"UnderSize Frames\s*:\s*(\d+)")
        result["rx_oversize_frames"] = _int_search(r"OverSize Frames\s*:\s*(\d+)")
        result["rx_lost_frames"] = _int_search(r"Lost Frames\s*:\s*(\d+),\s*Error")
        result["rx_error_frames"] = _int_search(r"Error Frames\s*:\s*(\d+),\s*CRC")
        result["rx_crc_error_frames"] = _int_search(r"CRC Error Frames\s*:\s*(\d+)")
        result["rx_alignment_errors"] = _int_search(r"Alignments Err\s*:\s*(\d+)")
        # Tx counters
        result["tx_bytes"] = _int_search(r"Bytes Xmitted\s*:\s*(\d+)")
        result["tx_unicast_frames"] = _int_search(
            r"Bytes Xmitted.*?Unicast Frames\s*:\s*(\d+)"
        )
        result["tx_broadcast_frames"] = _int_search(
            r"Broadcast Frames\s*:\s*(\d+),\s*M-cast Frames\s*:\s*(\d+),\s*UnderSize"
        )
        result["tx_mcast_frames"] = _int_search(
            r"M-cast Frames\s*:\s*(\d+),\s*UnderSize Frames\s*:\s*(\d+),\s*OverSize"
        )
        result["tx_lost_frames"] = _int_search(
            r"Lost Frames\s*:\s*(\d+),\s*Collided"
        )
        result["tx_collided_frames"] = _int_search(r"Collided Frames\s*:\s*(\d+)")
        result["tx_error_frames"] = _int_search(
            r"Error Frames\s*:\s*(\d+),\s*Collisions\s*:"
        )
        result["tx_collisions"] = _int_search(
            r"Collisions\s*:\s*(\d+),\s*Late"
        )
        result["tx_late_collisions"] = _int_search(r"Late collisions\s*:\s*(\d+)")
        result["tx_exc_collisions"] = _int_search(r"Exc-Collisions\s*:\s*(\d+)")
    except Exception as exc:  # noqa: BLE001
        result["parse_error"] = str(exc)
    return result


def _parse_lldp_remote_system(output: str) -> dict:
    """Parse 'show lldp remote-system' output.

    Handles multiple local ports, multiple neighbours per port and
    multi-line system descriptions (e.g. Cisco IOS).

    Args:
        output: Raw CLI text.

    Returns:
        Dict with ``neighbors`` list.
    """
    neighbors: list[dict[str, Any]] = []
    current_port: str | None = None
    current_nbr: dict[str, Any] | None = None
    prev_field: str | None = None

    _FIELD_MAP = {
        "Remote ID": "remote_id",
        "Port Description": "port_description",
        "System Name": "system_name",
        "System Description": "system_description",
        "Capabilities Enabled": "capabilities_enabled",
        "Management IP Address": "management_ip",
    }

    def _save_nbr() -> None:
        nonlocal current_nbr
        if current_nbr is not None:
            neighbors.append(current_nbr)
        current_nbr = None

    try:
        for line in output.splitlines():
            # New local port section
            m = re.match(
                r"Remote LLDP\s+\S+\s+Agents\s+on\s+Local\s+Port\s+(\S+):",
                line,
            )
            if m:
                _save_nbr()
                current_port = m.group(1).rstrip(":")
                prev_field = None
                continue

            # New neighbour: "    Chassis XX, Port YY:"
            m = re.match(r"^\s+Chassis\s+(.+?),\s+Port\s+(.+?):\s*$", line)
            if m:
                _save_nbr()
                current_nbr = {
                    "local_port": current_port,
                    "chassis_id": m.group(1).strip(),
                    "remote_port": m.group(2).strip(),
                    "remote_id": None,
                    "port_description": None,
                    "system_name": None,
                    "system_description": None,
                    "capabilities_enabled": None,
                    "management_ip": None,
                }
                prev_field = None
                continue

            if current_nbr is None:
                continue

            # Key = value line (LLDP uses '=' as separator)
            m = re.match(r"^\s+(.+?)\s+=\s+(.+)", line)
            if m:
                key = m.group(1).strip()
                val = m.group(2).strip().rstrip(",").strip()
                if key in _FIELD_MAP:
                    field = _FIELD_MAP[key]
                    current_nbr[field] = val
                    prev_field = field
                else:
                    prev_field = None
                continue

            # Continuation of multi-line value (e.g. Cisco System Description)
            stripped = line.strip()
            if stripped and prev_field == "system_description":
                current_nbr["system_description"] = (
                    (current_nbr["system_description"] or "") + " " + stripped.rstrip(",")
                ).strip()

        _save_nbr()
    except Exception as exc:  # noqa: BLE001
        return {"neighbors": neighbors, "parse_error": str(exc)}
    return {"neighbors": neighbors}


def _parse_interfaces_flood_rate(output: str) -> dict:
    """Parse 'show interfaces flood-rate' output.

    Args:
        output: Raw CLI text.

    Returns:
        Dict with ``ports`` list.
    """
    ports: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            # port  bcast_val  bcast_type  bcast_status  ucast_val ...
            m = re.match(
                r"^\s+(\d+/\d+/\d+)\s+"
                r"(\d+)\s+(\S+)\s+(\S+)\s+"
                r"(\d+)\s+(\S+)\s+(\S+)\s+"
                r"(\d+)\s+(\S+)\s+(\S+)",
                line,
            )
            if not m:
                continue
            ports.append(
                {
                    "port": m.group(1),
                    "bcast_value": int(m.group(2)),
                    "bcast_type": m.group(3),
                    "bcast_status": m.group(4),
                    "ucast_value": int(m.group(5)),
                    "ucast_type": m.group(6),
                    "ucast_status": m.group(7),
                    "mcast_value": int(m.group(8)),
                    "mcast_type": m.group(9),
                    "mcast_status": m.group(10),
                }
            )
    except Exception as exc:  # noqa: BLE001
        return {"ports": ports, "parse_error": str(exc)}
    return {"ports": ports}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 port/interface tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_interfaces_status(host: str) -> str:
        """Return physical interface status for all ports of an OmniSwitch.

        Runs ``show interfaces status`` and returns admin status, auto
        negotiation, detected and configured speed, duplex, link-trap
        and EEE settings for every port.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with interface status list or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_interfaces_status: host=%s", host)
        output = await execute_command(host, "show interfaces status")
        if output.startswith("ERROR:"):
            return output
        data = _parse_interfaces_status(output)
        return json.dumps(
            {"host": host, "command": "show interfaces status", **data}, indent=2
        )

    @mcp.tool()
    async def aos_show_interfaces_alias(host: str) -> str:
        """Return port aliases and link state for all interfaces.

        Runs ``show interfaces alias`` and returns admin status, link
        status and alias string for each port.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with alias list or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_interfaces_alias: host=%s", host)
        output = await execute_command(host, "show interfaces alias")
        if output.startswith("ERROR:"):
            return output
        data = _parse_interfaces_alias(output)
        return json.dumps(
            {"host": host, "command": "show interfaces alias", **data}, indent=2
        )

    @mcp.tool()
    async def aos_show_interfaces_counters_errors(host: str) -> str:
        """Return error counters for active/error interfaces.

        Runs ``show interfaces counters errors`` and returns IfInErrors,
        undersize and oversize packet counts.  Only ports with entries
        (up or with errors) are included.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with error counter list or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_interfaces_counters_errors: host=%s", host)
        output = await execute_command(host, "show interfaces counters errors")
        if output.startswith("ERROR:"):
            return output
        data = _parse_interfaces_counters_errors(output)
        return json.dumps(
            {
                "host": host,
                "command": "show interfaces counters errors",
                **data,
            },
            indent=2,
        )

    @mcp.tool()
    async def aos_show_interfaces_ddm(host: str) -> str:
        """Return Digital Diagnostic Monitoring data for SFP/SFP+ transceivers.

        Runs ``show interfaces ddm`` and returns actual and threshold
        values for temperature, voltage, TX bias, output power and
        input power for each optical port.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with DDM data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_interfaces_ddm: host=%s", host)
        output = await execute_command(host, "show interfaces ddm")
        if output.startswith("ERROR:"):
            return output
        data = _parse_interfaces_ddm(output)
        return json.dumps(
            {"host": host, "command": "show interfaces ddm", **data}, indent=2
        )

    @mcp.tool()
    async def aos_show_interfaces_port(host: str, port: str) -> str:
        """Return detailed statistics for a single OmniSwitch interface.

        Runs ``show interfaces port <port>`` and returns operational
        status, counters (Rx/Tx bytes, unicast, broadcast, multicast,
        errors, collisions …) and physical attributes.

        Args:
            host: IP address or hostname of the OmniSwitch.
            port: Port identifier in ``chassis/slot/port`` format, e.g. ``"1/1/1"``.

        Returns:
            JSON string with port details or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = f"show interfaces port {port}"
        logger.debug("aos_show_interfaces_port: host=%s port=%s", host, port)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_interfaces_port(output)
        return json.dumps(
            {"host": host, "command": cmd, **data}, indent=2
        )

    @mcp.tool()
    async def aos_show_interfaces_flood_rate(host: str) -> str:
        """Return broadcast, unicast and multicast flood-rate limits for all ports.

        Runs ``show interfaces flood-rate`` and returns configured
        flood-rate values, types (mbps/%) and enable/disable status for
        broadcast, unknown-unicast and multicast traffic per port.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with flood-rate configuration or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_interfaces_flood_rate: host=%s", host)
        output = await execute_command(host, "show interfaces flood-rate")
        if output.startswith("ERROR:"):
            return output
        data = _parse_interfaces_flood_rate(output)
        return json.dumps(
            {"host": host, "command": "show interfaces flood-rate", **data}, indent=2
        )

    @mcp.tool()
    async def aos_show_lldp_remote_system(host: str) -> str:
        """Return LLDP neighbour information discovered on all ports.

        Runs ``show lldp remote-system`` and returns chassis ID, remote
        port, system name, system description, capabilities and
        management IP for every LLDP neighbour.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with LLDP neighbour list or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_lldp_remote_system: host=%s", host)
        output = await execute_command(host, "show lldp remote-system")
        if output.startswith("ERROR:"):
            return output
        data = _parse_lldp_remote_system(output)
        return json.dumps(
            {"host": host, "command": "show lldp remote-system", **data}, indent=2
        )

    @mcp.tool()
    async def aos_show_lldp_port(host: str, port: str) -> str:
        """Return LLDP remote-system information for a single port.

        Runs ``show lldp port <port> remote-system`` and returns structured
        LLDP neighbor data for the specified port.

        Args:
            host: IP address or hostname of the OmniSwitch.
            port: Port identifier in ``chassis/slot/port`` format, e.g. ``"1/1/1"``.

        Returns:
            JSON string with LLDP neighbor data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = f"show lldp port {port} remote-system"
        logger.debug("aos_show_lldp_port: host=%s port=%s", host, port)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_lldp_remote_system(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)
