"""
AOS8 Core system tools.

Covers system identity, firmware, chassis, CMM, running directory and
configuration backup primitives.
"""
import json
import logging
import re

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _null(value: str) -> str | None:
    """Return *None* when *value* is a dash, empty string or only whitespace.

    Args:
        value: Raw string extracted from CLI output.

    Returns:
        Stripped string or ``None``.
    """
    v = value.strip().rstrip(",") if value else ""
    return None if v in ("-", "--", "") else v


def _parse_kv(line: str) -> tuple[str, str] | None:
    """Extract a key/value pair from an AOS8 CLI line.

    AOS8 uses two distinct spacing conventions:
    * ``Key:    value,``  — colon **then** multiple spaces
    * ``Key              :  value,`` — multiple spaces **before** colon

    Args:
        line: A single CLI output line.

    Returns:
        ``(key, value)`` tuple with trailing commas stripped, or ``None``
        when the line does not match the key/value pattern.
    """
    m = re.match(
        r"^\s*([A-Za-z][A-Za-z0-9\s&/()\-]+?)\s*:\s{1,}(.+?)(?:,\s*)?$",
        line,
    )
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip().rstrip(",").strip()


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_show_system(output: str) -> dict:
    """Parse 'show system' CLI output into a structured dict."""
    result: dict = {
        "description": None,
        "uptime": None,
        "contact": None,
        "name": None,
        "location": None,
        "date_time": None,
        "flash_available_bytes": None,
    }
    _FIELD_MAP = {
        "Description": "description",
        "Up Time": "uptime",
        "Contact": "contact",
        "Name": "name",
        "Location": "location",
        "Date & Time": "date_time",
    }
    try:
        for line in output.splitlines():
            kv = _parse_kv(line)
            if kv is None:
                continue
            key, val = kv
            if key in _FIELD_MAP:
                result[_FIELD_MAP[key]] = _null(val)
            elif re.match(r"Available\s*\(bytes\)", key):
                try:
                    result["flash_available_bytes"] = int(val.replace(",", ""))
                except ValueError:
                    result["flash_available_bytes"] = _null(val)
    except Exception as exc:  # noqa: BLE001
        result["parse_error"] = str(exc)
    return result


def _parse_show_microcode(output: str) -> dict:
    """Parse 'show microcode' CLI output into a structured dict."""
    result: dict = {"directory": None, "packages": []}
    try:
        directory: str | None = None
        in_table = False
        for line in output.splitlines():
            stripped = line.strip()
            # Directory line: /flash/working or /flash/certified
            if stripped.startswith("/flash/"):
                directory = stripped
                in_table = False
                continue
            # Separator line marks start of table data
            if re.match(r"^-{3,}", stripped):
                in_table = True
                continue
            if in_table and stripped:
                # Package  Release  Size  Description
                m = re.match(
                    r"^(\S+)\s+(\S+)\s+(\d+)\s+(.+)$", stripped
                )
                if m:
                    result["packages"].append(
                        {
                            "directory": directory,
                            "package": m.group(1),
                            "release": m.group(2),
                            "size": int(m.group(3)),
                            "description": m.group(4).strip(),
                        }
                    )
        result["directory"] = directory
    except Exception as exc:  # noqa: BLE001
        result["parse_error"] = str(exc)
    return result


def _parse_show_chassis(output: str) -> dict:
    """Parse 'show chassis' CLI output into a structured dict."""
    result: dict = {
        "chassis_id": None,
        "role": None,
        "model_name": None,
        "description": None,
        "part_number": None,
        "hardware_revision": None,
        "serial_number": None,
        "manufacture_date": None,
        "admin_status": None,
        "operational_status": None,
        "number_of_resets": None,
        "mac_address": None,
    }
    _FIELD_MAP = {
        "Model Name": "model_name",
        "Description": "description",
        "Part Number": "part_number",
        "Hardware Revision": "hardware_revision",
        "Serial Number": "serial_number",
        "Manufacture Date": "manufacture_date",
        "Admin Status": "admin_status",
        "Operational Status": "operational_status",
        "Number Of Resets": "number_of_resets",
        "MAC Address": "mac_address",
    }
    try:
        for line in output.splitlines():
            stripped = line.strip()
            # First line: "Local Chassis ID 1 (Master)"
            m = re.match(
                r"(?:Local\s+)?Chassis\s+ID\s+(\d+)(?:\s+\((\w+)\))?",
                stripped,
            )
            if m:
                result["chassis_id"] = int(m.group(1))
                result["role"] = m.group(2)  # Master / Slave / None
                continue
            kv = _parse_kv(line)
            if kv is None:
                continue
            key, val = kv
            if key in _FIELD_MAP:
                result[_FIELD_MAP[key]] = _null(val)
    except Exception as exc:  # noqa: BLE001
        result["parse_error"] = str(exc)
    return result


def _parse_show_running_directory(output: str) -> dict:
    """Parse 'show running-directory' CLI output into a structured dict."""
    result: dict = {
        "running_cmm": None,
        "cmm_mode": None,
        "current_cmm_slot": None,
        "running_configuration": None,
        "certify_restore_status": None,
        "synchronization_status": None,
    }
    _FIELD_MAP = {
        "Running CMM": "running_cmm",
        "CMM Mode": "cmm_mode",
        "Current CMM Slot": "current_cmm_slot",
        "Running configuration": "running_configuration",
        "Certify/Restore Status": "certify_restore_status",
        "Running Configuration": "synchronization_status",
    }
    try:
        for line in output.splitlines():
            kv = _parse_kv(line)
            if kv is None:
                continue
            key, val = kv
            if key in _FIELD_MAP:
                result[_FIELD_MAP[key]] = _null(val)
    except Exception as exc:  # noqa: BLE001
        result["parse_error"] = str(exc)
    return result


def _parse_show_cmm(output: str) -> dict:
    """Parse 'show cmm' CLI output into a structured dict."""
    result: dict = {
        "chassis_id": None,
        "slot": None,
        "model_name": None,
        "description": None,
        "part_number": None,
        "hardware_revision": None,
        "serial_number": None,
        "manufacture_date": None,
        "admin_status": None,
        "operational_status": None,
        "max_power_w": None,
        "mac_address": None,
        "fpga_versions": {},
    }
    _FIELD_MAP = {
        "Model Name": "model_name",
        "Description": "description",
        "Part Number": "part_number",
        "Hardware Revision": "hardware_revision",
        "Serial Number": "serial_number",
        "Manufacture Date": "manufacture_date",
        "Admin Status": "admin_status",
        "Operational Status": "operational_status",
        "MAC Address": "mac_address",
    }
    try:
        for line in output.splitlines():
            stripped = line.strip()
            # First line: "Chassis ID 1 Module in slot CMM-A"
            m = re.match(
                r"Chassis\s+ID\s+(\d+)\s+Module\s+in\s+slot\s+(\S+)",
                stripped,
            )
            if m:
                result["chassis_id"] = int(m.group(1))
                result["slot"] = m.group(2).rstrip(",")
                continue
            # FPGA lines: "FPGA 1:  0.9"
            m = re.match(r"FPGA\s+(\d+)\s*:\s+(\S+)", stripped)
            if m:
                result["fpga_versions"][f"fpga_{m.group(1)}"] = _null(m.group(2))
                continue
            # Max Power has numeric value
            m = re.match(r"Max Power\s*:\s+(\d+)", stripped)
            if m:
                result["max_power_w"] = int(m.group(1))
                continue
            kv = _parse_kv(line)
            if kv is None:
                continue
            key, val = kv
            if key in _FIELD_MAP:
                result[_FIELD_MAP[key]] = _null(val)
    except Exception as exc:  # noqa: BLE001
        result["parse_error"] = str(exc)
    return result


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP) -> None:
    """Register all core AOS8 system tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_system(host: str) -> str:
        """Return system identity and uptime for an AOS8 OmniSwitch.

        Runs ``show system`` and returns description, uptime, contact,
        name, location, date/time and primary flash availability.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with system information or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_system: host=%s", host)
        output = await execute_command(host, "show system")
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_system(output)
        return json.dumps({"host": host, "command": "show system", **data}, indent=2)

    @mcp.tool()
    async def aos_show_microcode(host: str) -> str:
        """Return firmware package information for an AOS8 OmniSwitch.

        Runs ``show microcode`` and returns the directory, package name,
        release version, size and description of each firmware image.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with microcode information or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_microcode: host=%s", host)
        output = await execute_command(host, "show microcode")
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_microcode(output)
        return json.dumps(
            {"host": host, "command": "show microcode", **data}, indent=2
        )

    @mcp.tool()
    async def aos_show_chassis(host: str) -> str:
        """Return chassis hardware information for an AOS8 OmniSwitch.

        Runs ``show chassis`` and returns model, serial number, hardware
        revision, manufacture date, operational status and MAC address.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with chassis information or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_chassis: host=%s", host)
        output = await execute_command(host, "show chassis")
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_chassis(output)
        return json.dumps(
            {"host": host, "command": "show chassis", **data}, indent=2
        )

    @mcp.tool()
    async def aos_show_running_directory(host: str) -> str:
        """Return the active CMM and running configuration directory.

        Runs ``show running-directory`` and returns the active CMM slot,
        running configuration directory, certify/restore status and
        synchronisation status.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with running directory status or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_running_directory: host=%s", host)
        output = await execute_command(host, "show running-directory")
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_running_directory(output)
        return json.dumps(
            {"host": host, "command": "show running-directory", **data}, indent=2
        )

    @mcp.tool()
    async def aos_show_cmm(host: str) -> str:
        """Return CMM module hardware information for an AOS8 OmniSwitch.

        Runs ``show cmm`` and returns chassis ID, slot, model name,
        serial number, FPGA versions, max power and MAC address.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with CMM information or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_cmm: host=%s", host)
        output = await execute_command(host, "show cmm")
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_cmm(output)
        return json.dumps({"host": host, "command": "show cmm", **data}, indent=2)

    @mcp.tool()
    async def aos_config_backup(host: str) -> str:
        """Return the full running configuration text of an AOS8 OmniSwitch.

        Runs ``write terminal`` and returns the raw configuration text.
        No parsing is performed; the output is returned as-is so it can
        be saved or diffed by the caller.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            Plain-text configuration or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_config_backup: host=%s", host)
        output = await execute_command(host, "write terminal")
        if output.startswith("ERROR:"):
            return output
        return output
