"""
AOS8 Port Security tools.

Covers the global port-security state, brief summary table and per-port detail.
"""
import json
import logging
import re
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Sentinel message returned by AOS8 when port-security is not configured.
_NOT_CONFIGURED_MSG = "No Port Security is configured in the system."


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_port_security(output: str) -> dict:
    """Parse ``show port-security`` output.

    When port-security is not configured the switch returns::

        No Port Security is configured in the system.

    Args:
        output: Raw CLI text from ``show port-security``.

    Returns:
        Dict with ``configured`` boolean and ``message`` when unconfigured,
        or raw output otherwise.
    """
    stripped = output.strip()
    if _NOT_CONFIGURED_MSG in stripped:
        return {"configured": False, "message": _NOT_CONFIGURED_MSG}
    # Structured output would be parsed here in a future enhancement
    return {"configured": True, "raw": stripped}


def _parse_port_security_brief(output: str) -> dict:
    """Parse ``show port-security brief`` output.

    Expected format (when entries exist)::

         Slot/                        Max      Max      Nb Macs   Nb Macs     Nb Macs     Nb Macs
         Port       Operation Mode    Bridge   Filter   Dyn Br    Dyn Fltr    Static Br   Static Fltr
        ----------+------------------+--------+--------+---------+-----------+-----------+------------
        1/1/3      learn              10       0        2         0           0           0

    Returns an empty list when no ports have port-security configured.

    Args:
        output: Raw CLI text from ``show port-security brief``.

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
                or stripped.lower().startswith("slot")
                or stripped.lower().startswith("port")
                or stripped.lower().startswith("nb macs")
                or re.match(r"^[-+\s]+$", stripped)
            ):
                continue
            # Data line: "1/1/3  learn  10  0  2  0  0  0"
            m = re.match(
                r"^(\S+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$",
                stripped,
            )
            if m:
                ports.append(
                    {
                        "port": m.group(1),
                        "operation_mode": m.group(2),
                        "max_bridge": int(m.group(3)),
                        "max_filter": int(m.group(4)),
                        "nb_macs_dyn_bridge": int(m.group(5)),
                        "nb_macs_dyn_filter": int(m.group(6)),
                        "nb_macs_static_bridge": int(m.group(7)),
                        "nb_macs_static_filter": int(m.group(8)),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return {"ports": ports, "total_count": len(ports), "parse_error": str(exc)}
    return {"ports": ports, "total_count": len(ports)}


def _parse_port_security_port(output: str, port: str) -> dict:
    """Parse ``show port-security port <port>`` output.

    Returns ``{"configured": False, "port": port}`` when the output is
    empty or contains no structured data (port-security not applied).

    Args:
        output: Raw CLI text from ``show port-security port <port>``.
        port: The queried port identifier.

    Returns:
        Dict with port-security detail for the specified port.
    """
    stripped = output.strip()
    if not stripped:
        return {"configured": False, "port": port}

    # If the global "not configured" message appears, surface it explicitly.
    if _NOT_CONFIGURED_MSG in stripped:
        return {"configured": False, "port": port, "message": _NOT_CONFIGURED_MSG}

    # Attempt structured parsing: "Key : value" pairs
    result: dict[str, Any] = {"configured": True, "port": port}
    parsed_any = False
    for line in stripped.splitlines():
        m = re.match(r"^(.+?)\s*:\s*(.+)$", line.strip())
        if m:
            key = re.sub(r"[^a-z0-9]+", "_", m.group(1).strip().lower()).strip("_")
            result[key] = m.group(2).strip().rstrip(",")
            parsed_any = True

    if not parsed_any:
        result["raw"] = stripped

    return result


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 Port Security tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_port_security(host: str) -> str:
        """Return global port-security status for an OmniSwitch.

        Runs ``show port-security`` and indicates whether port-security is
        configured on the switch.  Returns ``configured: false`` with an
        explanatory message when no port-security configuration exists.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with port-security status or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show port-security"
        logger.debug("aos_show_port_security: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_port_security(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_port_security_brief(host: str) -> str:
        """Return port-security brief summary for all ports of an OmniSwitch.

        Runs ``show port-security brief`` and returns, for each secured port,
        the operation mode, maximum bridge/filter MAC counts and the current
        dynamic and static MAC address counts.  Returns an empty list when
        no ports have port-security configured.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with port-security brief data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show port-security brief"
        logger.debug("aos_show_port_security_brief: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_port_security_brief(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_port_security_port(host: str, port: str) -> str:
        """Return port-security detail for a specific OmniSwitch port.

        Runs ``show port-security port <port>`` and returns the port-security
        configuration for the requested interface.  Returns
        ``configured: false`` when port-security is not applied to that port.

        Args:
            host: IP address or hostname of the OmniSwitch.
            port: Port identifier in ``chassis/slot/port`` format, e.g. ``"1/1/3"``.

        Returns:
            JSON string with per-port security data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = f"show port-security port {port}"
        logger.debug("aos_show_port_security_port: host=%s port=%s", host, port)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_port_security_port(output, port)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)
