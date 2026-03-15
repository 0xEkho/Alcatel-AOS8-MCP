"""
AOS8 IP routing tools.

Covers IP route table, IP interfaces, OSPF status, OSPF neighbours,
VRF table and ARP table.

Note on AOS8 command correctness
---------------------------------
* ``show arp``        — correct (NOT ``show ip arp``)
* ``show ip routes``  — correct
* ``show ip ospf``    — correct
* ``show vrf``        — correct
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

_MAX_ROUTE_LINES = 500


def _parse_show_ip_routes(output: str) -> dict:
    """Parse ``show ip routes`` output.

    Expected format::

         + = Equal cost multipath routes
         Total 1296 routes

          Dest Address       Gateway Addr        Age        Protocol
        ------------------+-------------------+----------+-----------
          0.0.0.0/0            10.0.9.1         112d 4h   OSPF
          10.0.151.0/24        10.0.151.1        0d 0h   LOCAL

    For very large tables (> 500 data lines) only the first 500 entries
    are parsed and ``"truncated": true`` is added to the result.

    Args:
        output: Raw CLI text from ``show ip routes``.

    Returns:
        Dict with ``total_routes``, ``routes`` list and optionally
        ``truncated``.
    """
    routes: list[dict[str, Any]] = []
    total_routes: int | None = None
    truncated = False

    try:
        lines = output.splitlines()
        data_lines_seen = 0

        for line in lines:
            stripped = line.strip()

            # "Total 1296 routes"
            m_total = re.match(r"^Total\s+(\d+)\s+routes?", stripped, re.IGNORECASE)
            if m_total:
                total_routes = int(m_total.group(1))
                continue

            # Skip separators and headers
            if (
                not stripped
                or stripped.startswith("+")
                or stripped.startswith("-")
                or re.match(r"^Dest\s+Address", stripped, re.IGNORECASE)
            ):
                continue

            # Truncation guard
            if data_lines_seen >= _MAX_ROUTE_LINES:
                truncated = True
                continue

            # Data line: "  0.0.0.0/0   10.0.9.1   112d 4h   OSPF"
            # Age may be "0d 0h" (two tokens) or "112d 4h" (two tokens)
            m = re.match(
                r"^(\S+)\s+(\S+)\s+(\d+d\s+\d+h)\s+(\S+)\s*$",
                stripped,
            )
            if m:
                routes.append(
                    {
                        "dest": m.group(1),
                        "gateway": m.group(2),
                        "age": m.group(3),
                        "protocol": m.group(4),
                    }
                )
                data_lines_seen += 1

    except Exception as exc:  # noqa: BLE001
        result: dict[str, Any] = {
            "total_routes": total_routes,
            "routes": routes,
            "parse_error": str(exc),
        }
        if truncated:
            result["truncated"] = True
        return result

    result = {
        "total_routes": total_routes if total_routes is not None else len(routes),
        "routes": routes,
    }
    if truncated:
        result["truncated"] = True
    return result


def _parse_show_ip_interface(output: str) -> dict:
    """Parse ``show ip interface`` output.

    Expected format::

        Total 12 interfaces
                    Name                 IP Address      Subnet Mask     Status Forward  Device
        Loopback                         127.0.0.1       255.255.255.255 UP     NO      Loopback
        VLAN-0002                        10.1.2.1        255.255.255.0   DOWN   NO      vlan 2
        cloudManaged                     203.0.113.98    255.255.224.0   UP     YES     VPN tunnel

    Args:
        output: Raw CLI text from ``show ip interface``.

    Returns:
        Dict with ``total_interfaces`` and ``interfaces`` list.
    """
    interfaces: list[dict[str, Any]] = []
    total_interfaces: int | None = None

    try:
        for line in output.splitlines():
            stripped = line.strip()

            m_total = re.match(r"^Total\s+(\d+)\s+interfaces?", stripped, re.IGNORECASE)
            if m_total:
                total_interfaces = int(m_total.group(1))
                continue

            # Skip header / separator lines
            if (
                not stripped
                or stripped.lower().startswith("name")
                or stripped.startswith("-")
            ):
                continue

            # Data line — flexible: Device may contain spaces ("vlan 2", "VPN tunnel")
            # Format: Name  IP_Address  Subnet_Mask  Status  Forward  Device...
            m = re.match(
                r"^(\S+)\s+([\d.]+)\s+([\d.]+)\s+(UP|DOWN)\s+(YES|NO)\s+(.+)$",
                stripped,
                re.IGNORECASE,
            )
            if m:
                interfaces.append(
                    {
                        "name": m.group(1),
                        "ip_address": m.group(2),
                        "subnet_mask": m.group(3),
                        "status": m.group(4).upper(),
                        "forward": m.group(5).upper() == "YES",
                        "device": m.group(6).strip(),
                    }
                )

    except Exception as exc:  # noqa: BLE001
        return {
            "total_interfaces": total_interfaces,
            "interfaces": interfaces,
            "parse_error": str(exc),
        }

    return {
        "total_interfaces": (
            total_interfaces if total_interfaces is not None else len(interfaces)
        ),
        "interfaces": interfaces,
    }


def _parse_show_ip_ospf(output: str) -> dict:
    """Parse ``show ip ospf`` output.

    Expected format (key = value pairs)::

        Router Id                        = 10.1.0.1,
        OSPF Version Number              = 2,
        Admin Status                     = Enabled,
        # of Routes                      = 1293,
        # of Full State Nbrs             = 1,
        # of attached areas              = 1,
        BFD Status                       = Enabled

    All key/value pairs are parsed dynamically and normalised into
    snake_case keys for JSON stability.

    Args:
        output: Raw CLI text from ``show ip ospf``.

    Returns:
        Dict with all parsed OSPF fields.
    """
    data: dict[str, Any] = {}
    _KEY_MAP = {
        "router id": "router_id",
        "ospf version number": "ospf_version",
        "admin status": "admin_status",
        "# of routes": "routes_count",
        "# of full state nbrs": "full_state_nbrs",
        "# of attached areas": "attached_areas",
        "bfd status": "bfd_status",
    }

    try:
        for line in output.splitlines():
            stripped = line.strip().rstrip(",")
            m = re.match(r"^(.+?)\s*=\s*(.+)$", stripped)
            if not m:
                continue
            raw_key = m.group(1).strip().lower()
            value = m.group(2).strip()
            # Map to canonical key or generate snake_case fallback
            key = _KEY_MAP.get(raw_key, re.sub(r"[^a-z0-9]+", "_", raw_key).strip("_"))
            # Coerce numeric strings
            if re.match(r"^\d+$", value):
                data[key] = int(value)
            else:
                data[key] = value

    except Exception as exc:  # noqa: BLE001
        data["parse_error"] = str(exc)

    return data


def _parse_show_ip_ospf_neighbor(output: str) -> dict:
    """Parse ``show ip ospf neighbor`` output.

    Expected format::

          IP Address        Area Id          Router Id       Name     ID      State  Type
        10.0.9.1       0.0.0.0          10.0.0.1         Vlan     1090       Full  Dynamic

    Args:
        output: Raw CLI text from ``show ip ospf neighbor``.

    Returns:
        Dict with ``neighbors`` list.
    """
    neighbors: list[dict[str, Any]] = []

    try:
        for line in output.splitlines():
            stripped = line.strip()
            if (
                not stripped
                or stripped.lower().startswith("ip address")
                or stripped.startswith("-")
            ):
                continue

            # Data line: ip  area  router_id  name  id  state  type
            m = re.match(
                r"^([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\S+)\s+(\d+)\s+(\S+)\s+(\S+)\s*$",
                stripped,
            )
            if m:
                neighbors.append(
                    {
                        "ip_address": m.group(1),
                        "area_id": m.group(2),
                        "router_id": m.group(3),
                        "domain_name": m.group(4),
                        "domain_id": int(m.group(5)),
                        "state": m.group(6),
                        "type": m.group(7),
                    }
                )

    except Exception as exc:  # noqa: BLE001
        return {"neighbors": neighbors, "parse_error": str(exc)}

    return {"neighbors": neighbors}


def _parse_show_vrf(output: str) -> dict:
    """Parse ``show vrf`` output.

    Expected format::

         Virtual Routers     Profile Protocols
        default              default OSPF PIM VRRP
        WORKSTATION          max     OSPF VRRP
        Total Number of Virtual Routers: 7

    Args:
        output: Raw CLI text from ``show vrf``.

    Returns:
        Dict with ``vrfs`` list and ``total_count``.
    """
    vrfs: list[dict[str, Any]] = []
    total_count: int | None = None

    try:
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            # Total line
            m_total = re.match(
                r"^Total\s+Number\s+of\s+Virtual\s+Routers\s*:\s*(\d+)",
                stripped,
                re.IGNORECASE,
            )
            if m_total:
                total_count = int(m_total.group(1))
                continue

            # Skip header / separator
            if (
                stripped.lower().startswith("virtual router")
                or stripped.startswith("-")
            ):
                continue

            # Data line: name  profile  proto1 proto2 ...
            # At minimum: name + profile (no protocols is valid)
            m = re.match(r"^(\S+)\s+(\S+)(?:\s+(.+))?$", stripped)
            if m:
                protocols_raw = m.group(3) or ""
                protocols = [p.strip() for p in protocols_raw.split() if p.strip()]
                vrfs.append(
                    {
                        "name": m.group(1),
                        "profile": m.group(2),
                        "protocols": protocols,
                    }
                )

    except Exception as exc:  # noqa: BLE001
        return {
            "vrfs": vrfs,
            "total_count": total_count if total_count is not None else len(vrfs),
            "parse_error": str(exc),
        }

    return {
        "vrfs": vrfs,
        "total_count": total_count if total_count is not None else len(vrfs),
    }


def _parse_show_arp(output: str) -> dict:
    """Parse ``show arp`` output.

    Expected format::

        Total 3 arp entries
         IP Addr           Hardware Addr       Type       Flags   Port              Interface   Name
         10.1.151.100      aa:bb:cc:dd:ee:01   DYNAMIC                      1/1/23  VLAN-0151

    Note: AOS8 uses ``show arp``, **not** ``show ip arp``.

    Args:
        output: Raw CLI text from ``show arp``.

    Returns:
        Dict with ``total_entries`` and ``entries`` list.
    """
    entries: list[dict[str, Any]] = []
    total_entries: int | None = None

    try:
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            m_total = re.match(r"^Total\s+(\d+)\s+arp\s+entries?", stripped, re.IGNORECASE)
            if m_total:
                total_entries = int(m_total.group(1))
                continue

            # Skip headers / separators
            if (
                stripped.lower().startswith("ip addr")
                or stripped.startswith("-")
            ):
                continue

            # Data line: ip  mac  type  flags  port  interface  [name]
            # Flags column may be empty → use liberal regex
            m = re.match(
                r"^([\d.]+)\s+([0-9a-fA-F:]{17})\s+(\S+)\s*(.*?)\s+(\S+)\s+(\S+)(?:\s+(\S+))?\s*$",
                stripped,
            )
            if m:
                entries.append(
                    {
                        "ip_addr": m.group(1),
                        "hardware_addr": m.group(2).lower(),
                        "type": m.group(3),
                        "flags": m.group(4).strip(),
                        "port": m.group(5),
                        "interface": m.group(6),
                        "name": m.group(7) or "",
                    }
                )

    except Exception as exc:  # noqa: BLE001
        return {
            "total_entries": total_entries,
            "entries": entries,
            "parse_error": str(exc),
        }

    return {
        "total_entries": (
            total_entries if total_entries is not None else len(entries)
        ),
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 IP routing tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_ip_routes(host: str) -> str:
        """Return the IP route table for an OmniSwitch.

        Runs ``show ip routes`` and returns every route entry with
        destination, gateway, age and routing protocol.

        For very large tables (> 500 entries) only the first 500 routes
        are returned and ``"truncated": true`` is included in the response
        to avoid overwhelming the LLM context window.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with ``total_routes`` and ``routes`` list, or
            ``"ERROR: ..."`` string on failure.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show ip routes"
        logger.debug("aos_show_ip_routes: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_ip_routes(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_ip_interface(host: str) -> str:
        """Return all IP interfaces configured on an OmniSwitch.

        Runs ``show ip interface`` and returns name, IP address, subnet
        mask, operational status (UP/DOWN), forwarding flag and device
        binding for every interface.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with ``total_interfaces`` and ``interfaces`` list,
            or ``"ERROR: ..."`` string on failure.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show ip interface"
        logger.debug("aos_show_ip_interface: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_ip_interface(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_ip_ospf(host: str) -> str:
        """Return OSPF global configuration and status for an OmniSwitch.

        Runs ``show ip ospf`` and returns router ID, OSPF version,
        administrative status, route count, neighbour counts, attached
        area count and BFD status.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with OSPF parameters, or ``"ERROR: ..."`` string
            on failure.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show ip ospf"
        logger.debug("aos_show_ip_ospf: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_ip_ospf(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_ip_ospf_neighbor(host: str) -> str:
        """Return the OSPF neighbour table for an OmniSwitch.

        Runs ``show ip ospf neighbor`` and returns IP address, area ID,
        router ID, domain name, domain ID, adjacency state and neighbour
        type for every OSPF neighbour.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with ``neighbors`` list, or ``"ERROR: ..."`` string
            on failure.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show ip ospf neighbor"
        logger.debug("aos_show_ip_ospf_neighbor: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_ip_ospf_neighbor(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_vrf(host: str) -> str:
        """Return all Virtual Routing and Forwarding (VRF) instances.

        Runs ``show vrf`` and returns the VRF name, profile and list of
        active routing protocols for each virtual router, plus the total
        VRF count.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with ``vrfs`` list and ``total_count``, or
            ``"ERROR: ..."`` string on failure.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show vrf"
        logger.debug("aos_show_vrf: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_vrf(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_arp(host: str) -> str:
        """Return the ARP table for an OmniSwitch.

        Runs ``show arp`` (the correct AOS8 command — NOT ``show ip arp``
        which is invalid on AOS8) and returns IP address, MAC address,
        entry type, flags, port, interface and name for every ARP entry.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with ``total_entries`` and ``entries`` list, or
            ``"ERROR: ..."`` string on failure.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show arp"
        logger.debug("aos_show_arp: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_arp(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)
