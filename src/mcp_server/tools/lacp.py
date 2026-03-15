"""
AOS8 Link Aggregation (LACP / linkagg) tools.

Covers link aggregation group (LAG) status and per-port LACP
membership.

Both parsers handle the empty-table case (no LAGs configured) and
return ``[]`` with ``total_count: 0`` rather than an error.
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


def _parse_show_linkagg(output: str) -> dict:
    """Parse ``show linkagg`` output.

    Expected format (may be empty)::

        Number  Aggregate     SNMP Id   Size Admin State  Oper State     Att/Sel Ports
        -------+-------------+---------+----+------------+--------------+-------------
        (no data lines when no LAGs configured)

    Args:
        output: Raw CLI text from ``show linkagg``.

    Returns:
        Dict with ``aggregations`` list and ``total_count``.
    """
    aggregations: list[dict[str, Any]] = []

    try:
        for line in output.splitlines():
            stripped = line.strip()
            if (
                not stripped
                or stripped.lower().startswith("number")
                or stripped.startswith("-")
                or re.match(r"^[- +]+$", stripped)
            ):
                continue

            # Data line: number  name  snmp_id  size  admin_state  oper_state  att_sel_ports
            m = re.match(
                r"^(\d+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$",
                stripped,
            )
            if m:
                aggregations.append(
                    {
                        "number": int(m.group(1)),
                        "aggregate": m.group(2),
                        "snmp_id": int(m.group(3)),
                        "size": int(m.group(4)),
                        "admin_state": m.group(5),
                        "oper_state": m.group(6),
                        "att_sel_ports": m.group(7),
                    }
                )

    except Exception as exc:  # noqa: BLE001
        return {
            "aggregations": aggregations,
            "total_count": len(aggregations),
            "parse_error": str(exc),
        }

    return {"aggregations": aggregations, "total_count": len(aggregations)}


def _parse_show_linkagg_port(output: str) -> dict:
    """Parse ``show linkagg port`` output.

    Expected format (may be empty)::

        Chassis/Slot/Port  Aggregate   SNMP Id   Status    Agg  Oper   Link Prim
        (no data lines when no LACP ports configured)

    Args:
        output: Raw CLI text from ``show linkagg port``.

    Returns:
        Dict with ``ports`` list and ``total_count``.
    """
    ports: list[dict[str, Any]] = []

    try:
        for line in output.splitlines():
            stripped = line.strip()
            if (
                not stripped
                or stripped.lower().startswith("chassis")
                or stripped.startswith("-")
                or re.match(r"^[- +]+$", stripped)
            ):
                continue

            # Data line: port  aggregate  snmp_id  status  agg  oper  link  prim
            m = re.match(
                r"^(\S+)\s+(\S+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$",
                stripped,
            )
            if m:
                ports.append(
                    {
                        "port": m.group(1),
                        "aggregate": m.group(2),
                        "snmp_id": int(m.group(3)),
                        "status": m.group(4),
                        "agg": m.group(5),
                        "oper": m.group(6),
                        "link": m.group(7),
                        "primary": m.group(8),
                    }
                )

    except Exception as exc:  # noqa: BLE001
        return {
            "ports": ports,
            "total_count": len(ports),
            "parse_error": str(exc),
        }

    return {"ports": ports, "total_count": len(ports)}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 link aggregation tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_linkagg(host: str) -> str:
        """Return all link aggregation groups (LAGs) on an OmniSwitch.

        Runs ``show linkagg`` and returns the aggregation number, name,
        SNMP ID, size, administrative state, operational state and
        attached/selected port count for every configured LAG.

        Returns an empty ``aggregations`` list when no LAGs are
        configured.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with ``aggregations`` list and ``total_count``,
            or ``"ERROR: ..."`` string on failure.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show linkagg"
        logger.debug("aos_show_linkagg: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_linkagg(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_linkagg_port(host: str) -> str:
        """Return all ports participating in LACP link aggregation on an OmniSwitch.

        Runs ``show linkagg port`` and returns the chassis/slot/port
        identifier, aggregate membership, SNMP ID, LACP status,
        aggregation state, operational state, link state and primary
        port flag for every LACP-enabled port.

        Returns an empty ``ports`` list when no LACP ports are
        configured.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with ``ports`` list and ``total_count``, or
            ``"ERROR: ..."`` string on failure.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show linkagg port"
        logger.debug("aos_show_linkagg_port: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_linkagg_port(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)
