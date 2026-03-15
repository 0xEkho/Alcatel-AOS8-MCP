"""Tests for AOS8 MCP tools — Phase 3 network/routing implementation.

Strategy:
  - Inline fixture strings capture real AOS8 CLI output verbatim (provided by
    the field team after correcting invalid commands such as ``show ip arp``
    → ``show arp`` and ``show ntp server`` → ``show ntp client``).
  - ``execute_command`` is mocked at the ``mcp_server.ssh.client`` module level
    so that no real SSH connection is attempted.
  - Each test asserts a single behaviour; names follow
    ``test_<what>_<field_or_context>`` conventions.

Modules covered:
  mcp_server.tools.routing      → aos_show_ip_routes, aos_show_ip_interface,
                                   aos_show_ip_ospf, aos_show_ip_ospf_neighbor,
                                   aos_show_vrf, aos_show_arp
  mcp_server.tools.poe          → aos_show_lanpower_slot
  mcp_server.tools.lacp         → aos_show_linkagg, aos_show_linkagg_port
  mcp_server.tools.ntp          → aos_show_ntp_status
  mcp_server.tools.dhcp         → aos_show_ip_dhcp_relay,
                                   aos_show_ip_dhcp_relay_statistics
  mcp_server.tools.diagnostics  → aos_ping

AOS8 command correctness notes (applied in fixtures and assertions):
  * ``show arp``         — correct  (NOT ``show ip arp``)
  * ``show ntp client``  — correct  (NOT ``show ntp server``)
  * ``show linkagg`` / ``show linkagg port`` — return EMPTY tables on this
    switch (no LAGs configured); both tools must handle this gracefully.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

# ===========================================================================
# Helpers  (identical pattern to test_tools_core.py)
# ===========================================================================


def _mock_exec(return_value: str):
    """Patch ``execute_command`` to return *return_value* without SSH."""
    return patch(
        "mcp_server.ssh.client.execute_command",
        new_callable=AsyncMock,
        return_value=return_value,
    )


def _text(result) -> str:
    """Extract the first TextContent.text from a ``call_tool`` result tuple."""
    content_list = result[0]
    return content_list[0].text


# ===========================================================================
# Inline fixtures — real AOS8 CLI output (captured on a live switch)
# ===========================================================================

SHOW_IP_ROUTES = """
 + = Equal cost multipath routes
 Total 1296 routes

  Dest Address       Gateway Addr        Age        Protocol 
------------------+-------------------+----------+-----------
  0.0.0.0/0            10.0.9.1         112d 4h   OSPF      
  10.0.0.1/32          10.0.9.1         112d 4h   OSPF      
  10.1.0.1/32          10.1.0.1            0d 0h   LOCAL
"""

SHOW_IP_INTERFACE = """
Total 12 interfaces
 Flags (D=Directly-bound)

            Name                 IP Address      Subnet Mask     Status Forward  Device              Flags
--------------------------------+---------------+---------------+------+-------+--------------------+------
Loopback                         127.0.0.1       255.255.255.255 UP     NO      Loopback                
Loopback0                        10.1.0.1        255.255.255.255 UP     YES     Loopback0               
VLAN-0151                        10.1.151.1      255.255.255.0   UP     YES     vlan 151                
"""

SHOW_IP_OSPF = """
Router Id                        = 10.1.0.1,
OSPF Version Number              = 2,
Admin Status                     = Enabled,
# of Routes                      = 1293,
# of Full State Nbrs             = 1,
BFD Status                       = Enabled
"""

SHOW_IP_OSPF_NEIGHBOR = """
  IP Address        Area Id          Router Id       Name     ID      State  Type    
----------------+----------------+----------------+--------+--------+-------+--------
10.0.9.1       0.0.0.0          10.0.0.1         Vlan     1090       Full  Dynamic
"""

SHOW_VRF = """
 Virtual Routers     Profile Protocols
--------------------+-------+-------------------
default              default OSPF PIM VRRP
WORKSTATION          max     OSPF VRRP
SERVICE              max     OSPF VRRP

Total Number of Virtual Routers: 3
"""

SHOW_ARP = """
Total 3 arp entries
 Flags (P=Proxy, A=Authentication, V=VRRP, B=BFD, H=HAVLAN, I=INTF, M=Managed)

 IP Addr           Hardware Addr       Type       Flags   Port              Interface   Name
-----------------+-------------------+----------+-------+-----------------+-----------+------------------------------------
 10.1.151.100      aa:bb:cc:dd:ee:01   DYNAMIC                      1/1/23  VLAN-0151                                   
 10.0.9.1           aa:bb:cc:dd:ee:02   DYNAMIC                      1/1/25  VLAN-1090                                   
"""

SHOW_LANPOWER_SLOT = """
Port   Maximum(mW) Actual Used(mW)   Status    Priority   On/Off   Class   Type
--------+-----------+---------------+-----------+---------+--------+-------+----------
 1/1/1      30000            0       Searching      Low      ON        *      
 1/1/7      30000         3900       Delivering     Low      ON        2     T    
 1/1/13     30000         4200       Delivering     Low      ON        3     T    
"""

#: Empty PoE slot — only header and separator, no data rows.
SHOW_LANPOWER_SLOT_EMPTY = """
Port   Maximum(mW) Actual Used(mW)   Status    Priority   On/Off   Class   Type
--------+-----------+---------------+-----------+---------+--------+-------+----------
"""

SHOW_LINKAGG_EMPTY = """
Number  Aggregate     SNMP Id   Size Admin State  Oper State     Att/Sel Ports
-------+-------------+---------+----+------------+--------------+-------------
"""

#: ``show linkagg port`` returns an empty table when no LACP ports exist.
SHOW_LINKAGG_PORT_EMPTY = """
Chassis/Slot/Port  Aggregate   SNMP Id   Status    Agg  Oper   Link Prim
-----------------+-----------+---------+----------+----+------+------+------
"""

SHOW_NTP_CLIENT = """
Current time:                   Fri, Mar 13 2026 16:21:58.811 (CET),
Last NTP update:                Fri, Mar 13 2026 16:07:39.358 (CET),
Server reference:               10.0.4.1,
Client mode:                    enabled,
Broadcast client mode:          disabled,
Broadcast delay (microseconds): 4000,
Clock status:                   synchronized,
Stratum:                        5,
Maximum Associations Allowed:   128,
Authentication:                 disabled,
Source IP Configured:           Loopback0,
Source IP:                      10.1.0.1,
VRF Name:                       default
"""

SHOW_DHCP_RELAY = """
IP DHCP Relay :
  DHCP Relay Admin Status                            =  Enable,
  Forward Delay(seconds)                             =  0,
  Max number of hops                                 =  16,
  Relay Agent Information                            =  Disabled,
  Relay Agent Information Policy                     =  Drop,
  DHCP Relay Opt82 Format                            =  Base MAC,
  DHCP Relay Opt82 String                            =  00:11:22:33:44:55,
  PXE support                                        =  Disabled,
  Relay Mode                                         =  Global,
  Bootup Option                                      =  Disable,
"""

#: Minimal DHCP relay statistics output for structure testing.
SHOW_DHCP_RELAY_STATS = """
Global Statistics :
    Reception From Client :
      Total Count =          0, Delta =          0
    Forw Delay Violation :
      Total Count =          0, Delta =          0
"""

SHOW_PING = """
PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.

--- 8.8.8.8 ping statistics ---
3 packets transmitted, 0 received, 100% packet loss, time 2037ms
"""

# ===========================================================================
# Fixtures — one FastMCP instance per tool module (isolated per test)
# ===========================================================================


@pytest.fixture
def mcp_routing():
    """FastMCP instance with IP routing tools registered."""
    instance = FastMCP("test-routing")
    from mcp_server.tools.routing import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_poe():
    """FastMCP instance with PoE / LanPower tools registered."""
    instance = FastMCP("test-poe")
    from mcp_server.tools.poe import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_lacp():
    """FastMCP instance with LACP / linkagg tools registered."""
    instance = FastMCP("test-lacp")
    from mcp_server.tools.lacp import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_ntp():
    """FastMCP instance with NTP tools registered."""
    instance = FastMCP("test-ntp")
    from mcp_server.tools.ntp import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_dhcp():
    """FastMCP instance with DHCP relay tools registered."""
    instance = FastMCP("test-dhcp")
    from mcp_server.tools.dhcp import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_diagnostics():
    """FastMCP instance with diagnostics tools registered."""
    instance = FastMCP("test-diagnostics")
    from mcp_server.tools.diagnostics import register_tools
    register_tools(instance)
    return instance


# ===========================================================================
# routing.py — Tool registration
# ===========================================================================


async def test_routing_tools_all_registered(mcp_routing):
    """Every routing tool declared in routing.py must appear in list_tools()."""
    tools = {t.name for t in await mcp_routing.list_tools()}
    expected = {
        "aos_show_ip_routes",
        "aos_show_ip_interface",
        "aos_show_ip_ospf",
        "aos_show_ip_ospf_neighbor",
        "aos_show_vrf",
        "aos_show_arp",
    }
    assert expected.issubset(tools)


# ===========================================================================
# routing.py — aos_show_ip_routes
# ===========================================================================


async def test_show_ip_routes_total_count(mcp_routing):
    """aos_show_ip_routes: total_routes must be >= 1 for a non-empty table."""
    with _mock_exec(SHOW_IP_ROUTES):
        result = await mcp_routing.call_tool("aos_show_ip_routes", {"host": "10.1.0.1"})
    data = json.loads(_text(result))
    assert data["total_routes"] >= 1


async def test_show_ip_routes_has_default_route(mcp_routing):
    """aos_show_ip_routes: default route 0.0.0.0/0 must be present in routes list."""
    with _mock_exec(SHOW_IP_ROUTES):
        result = await mcp_routing.call_tool("aos_show_ip_routes", {"host": "10.1.0.1"})
    data = json.loads(_text(result))
    dests = [r["dest"] for r in data["routes"]]
    assert "0.0.0.0/0" in dests


async def test_show_ip_routes_protocol_ospf(mcp_routing):
    """aos_show_ip_routes: at least one route must carry protocol 'OSPF'."""
    with _mock_exec(SHOW_IP_ROUTES):
        result = await mcp_routing.call_tool("aos_show_ip_routes", {"host": "10.1.0.1"})
    data = json.loads(_text(result))
    protocols = [r["protocol"] for r in data["routes"]]
    assert "OSPF" in protocols


# ===========================================================================
# routing.py — aos_show_ip_interface
# ===========================================================================


async def test_show_ip_interface_total(mcp_routing):
    """aos_show_ip_interface: total_interfaces from 'Total N interfaces' header must be 12.

    The fixture declares 'Total 12 interfaces'; the parser reads this value
    directly, so total_interfaces == 12 regardless of how many rows follow.
    The interfaces list itself contains 3 parsed entries (Loopback, Loopback0,
    VLAN-0151).
    """
    with _mock_exec(SHOW_IP_INTERFACE):
        result = await mcp_routing.call_tool(
            "aos_show_ip_interface", {"host": "10.1.0.1"}
        )
    data = json.loads(_text(result))
    assert data["total_interfaces"] == 12


async def test_show_ip_interface_loopback_up(mcp_routing):
    """aos_show_ip_interface: Loopback0 interface must have status 'UP'."""
    with _mock_exec(SHOW_IP_INTERFACE):
        result = await mcp_routing.call_tool(
            "aos_show_ip_interface", {"host": "10.1.0.1"}
        )
    data = json.loads(_text(result))
    loopback0 = next(
        (i for i in data["interfaces"] if i["name"] == "Loopback0"), None
    )
    assert loopback0 is not None, "Loopback0 interface not found in parsed output"
    assert loopback0["status"] == "UP"


# ===========================================================================
# routing.py — aos_show_ip_ospf
# ===========================================================================


async def test_show_ip_ospf_router_id(mcp_routing):
    """aos_show_ip_ospf: router_id must equal '10.1.0.1'."""
    with _mock_exec(SHOW_IP_OSPF):
        result = await mcp_routing.call_tool("aos_show_ip_ospf", {"host": "10.1.0.1"})
    data = json.loads(_text(result))
    assert data["router_id"] == "10.1.0.1"


async def test_show_ip_ospf_admin_enabled(mcp_routing):
    """aos_show_ip_ospf: admin_status must equal 'Enabled'."""
    with _mock_exec(SHOW_IP_OSPF):
        result = await mcp_routing.call_tool("aos_show_ip_ospf", {"host": "10.1.0.1"})
    data = json.loads(_text(result))
    assert data["admin_status"] == "Enabled"


# ===========================================================================
# routing.py — aos_show_ip_ospf_neighbor
# ===========================================================================


async def test_show_ip_ospf_neighbor_full_state(mcp_routing):
    """aos_show_ip_ospf_neighbor: neighbor adjacency state must be 'Full'."""
    with _mock_exec(SHOW_IP_OSPF_NEIGHBOR):
        result = await mcp_routing.call_tool(
            "aos_show_ip_ospf_neighbor", {"host": "10.1.0.1"}
        )
    data = json.loads(_text(result))
    assert len(data["neighbors"]) > 0
    states = [n["state"] for n in data["neighbors"]]
    assert "Full" in states


async def test_show_ip_ospf_neighbor_router_id(mcp_routing):
    """aos_show_ip_ospf_neighbor: first neighbor router_id must equal '10.0.0.1'."""
    with _mock_exec(SHOW_IP_OSPF_NEIGHBOR):
        result = await mcp_routing.call_tool(
            "aos_show_ip_ospf_neighbor", {"host": "10.1.0.1"}
        )
    data = json.loads(_text(result))
    router_ids = [n["router_id"] for n in data["neighbors"]]
    assert "10.0.0.1" in router_ids


# ===========================================================================
# routing.py — aos_show_vrf
# ===========================================================================


async def test_show_vrf_total_count(mcp_routing):
    """aos_show_vrf: total_count must equal 3 (from 'Total Number of Virtual Routers: 3')."""
    with _mock_exec(SHOW_VRF):
        result = await mcp_routing.call_tool("aos_show_vrf", {"host": "10.1.0.1"})
    data = json.loads(_text(result))
    assert data["total_count"] == 3


async def test_show_vrf_default_vrf(mcp_routing):
    """aos_show_vrf: VRF named 'default' must be present in the vrfs list."""
    with _mock_exec(SHOW_VRF):
        result = await mcp_routing.call_tool("aos_show_vrf", {"host": "10.1.0.1"})
    data = json.loads(_text(result))
    vrf_names = [v["name"] for v in data["vrfs"]]
    assert "default" in vrf_names


async def test_show_vrf_protocols_list(mcp_routing):
    """aos_show_vrf: every VRF entry's 'protocols' field must be a list."""
    with _mock_exec(SHOW_VRF):
        result = await mcp_routing.call_tool("aos_show_vrf", {"host": "10.1.0.1"})
    data = json.loads(_text(result))
    for vrf in data["vrfs"]:
        assert isinstance(vrf["protocols"], list), (
            f"VRF '{vrf['name']}': protocols must be a list, got {type(vrf['protocols'])}"
        )


# ===========================================================================
# routing.py — aos_show_arp
#
# Note: correct AOS8 command is ``show arp``, NOT ``show ip arp``.
# ===========================================================================


async def test_show_arp_total_entries(mcp_routing):
    """aos_show_arp: total_entries from 'Total N arp entries' header must equal 3."""
    with _mock_exec(SHOW_ARP):
        result = await mcp_routing.call_tool("aos_show_arp", {"host": "10.1.0.1"})
    data = json.loads(_text(result))
    # Fixture header: "Total 3 arp entries"  → parser returns 3
    assert data["total_entries"] == 3


async def test_show_arp_entry_mac(mcp_routing):
    """aos_show_arp: entry for 10.1.151.100 must have MAC 'aa:bb:cc:dd:ee:01'."""
    with _mock_exec(SHOW_ARP):
        result = await mcp_routing.call_tool("aos_show_arp", {"host": "10.1.0.1"})
    data = json.loads(_text(result))
    macs = [e["hardware_addr"] for e in data["entries"]]
    assert "aa:bb:cc:dd:ee:01" in macs


# ===========================================================================
# poe.py — Tool registration
# ===========================================================================


async def test_poe_tools_all_registered(mcp_poe):
    """Every PoE tool declared in poe.py must appear in list_tools().

    Note: aos_poe_restart has been intentionally removed — PoE reboots
    must go through aos_poe_reboot_request (Teams approval workflow).
    """
    tools = {t.name for t in await mcp_poe.list_tools()}
    expected = {
        "aos_show_lanpower_slot",
        "aos_show_lanpower_slot_port",
    }
    assert expected.issubset(tools)
    assert "aos_poe_restart" not in tools, (
        "aos_poe_restart must remain removed — "
        "use aos_poe_reboot_request instead"
    )


# ===========================================================================
# poe.py — aos_show_lanpower_slot
# ===========================================================================


async def test_show_lanpower_slot_delivering(mcp_poe):
    """aos_show_lanpower_slot: at least one port must have status 'Delivering'."""
    with _mock_exec(SHOW_LANPOWER_SLOT):
        result = await mcp_poe.call_tool(
            "aos_show_lanpower_slot", {"host": "10.1.0.1", "slot": "1/1"}
        )
    data = json.loads(_text(result))
    statuses = [p["status"] for p in data["ports"]]
    assert "Delivering" in statuses


async def test_show_lanpower_slot_total_mw(mcp_poe):
    """aos_show_lanpower_slot: total_actual_mw must equal sum of per-port actual_mw.

    Fixture: 1/1/1 → 0 mW (Searching), 1/1/7 → 3900 mW, 1/1/13 → 4200 mW.
    Expected total: 8100 mW.
    """
    with _mock_exec(SHOW_LANPOWER_SLOT):
        result = await mcp_poe.call_tool(
            "aos_show_lanpower_slot", {"host": "10.1.0.1", "slot": "1/1"}
        )
    data = json.loads(_text(result))
    assert data["total_actual_mw"] == 8100


async def test_show_lanpower_slot_format(mcp_poe):
    """aos_show_lanpower_slot: JSON response must contain 'slot' and 'ports' keys."""
    with _mock_exec(SHOW_LANPOWER_SLOT):
        result = await mcp_poe.call_tool(
            "aos_show_lanpower_slot", {"host": "10.1.0.1", "slot": "1/1"}
        )
    data = json.loads(_text(result))
    assert "slot" in data
    assert "ports" in data


# ===========================================================================
# lacp.py — Tool registration
# ===========================================================================


async def test_lacp_tools_all_registered(mcp_lacp):
    """Both LACP tools declared in lacp.py must appear in list_tools()."""
    tools = {t.name for t in await mcp_lacp.list_tools()}
    assert "aos_show_linkagg" in tools
    assert "aos_show_linkagg_port" in tools


# ===========================================================================
# lacp.py — aos_show_linkagg (empty table — no LAGs configured on this switch)
# ===========================================================================


async def test_show_linkagg_empty(mcp_lacp):
    """aos_show_linkagg: empty table must yield aggregations=[] and total_count=0."""
    with _mock_exec(SHOW_LINKAGG_EMPTY):
        result = await mcp_lacp.call_tool("aos_show_linkagg", {"host": "10.1.0.1"})
    data = json.loads(_text(result))
    assert data["aggregations"] == []
    assert data["total_count"] == 0


async def test_show_linkagg_port_empty(mcp_lacp):
    """aos_show_linkagg_port: empty table must yield ports=[] and total_count=0."""
    with _mock_exec(SHOW_LINKAGG_PORT_EMPTY):
        result = await mcp_lacp.call_tool(
            "aos_show_linkagg_port", {"host": "10.1.0.1"}
        )
    data = json.loads(_text(result))
    assert data["ports"] == []
    assert data["total_count"] == 0


# ===========================================================================
# ntp.py — Tool registration
# ===========================================================================


async def test_ntp_tools_all_registered(mcp_ntp):
    """Both NTP tools declared in ntp.py must appear in list_tools()."""
    tools = {t.name for t in await mcp_ntp.list_tools()}
    assert "aos_show_ntp_status" in tools
    assert "aos_show_ntp_keys" in tools


# ===========================================================================
# ntp.py — aos_show_ntp_status
#
# Note: underlying AOS8 command is ``show ntp client``, NOT ``show ntp server``.
# ===========================================================================


async def test_show_ntp_status_synchronized(mcp_ntp):
    """aos_show_ntp_status: clock_status must equal 'synchronized'."""
    with _mock_exec(SHOW_NTP_CLIENT):
        result = await mcp_ntp.call_tool("aos_show_ntp_status", {"host": "10.1.0.1"})
    data = json.loads(_text(result))
    assert data["clock_status"] == "synchronized"


async def test_show_ntp_status_stratum(mcp_ntp):
    """aos_show_ntp_status: stratum must equal 5 (parsed as int from 'Stratum: 5')."""
    with _mock_exec(SHOW_NTP_CLIENT):
        result = await mcp_ntp.call_tool("aos_show_ntp_status", {"host": "10.1.0.1"})
    data = json.loads(_text(result))
    assert data["stratum"] == 5
    assert isinstance(data["stratum"], int)


async def test_show_ntp_status_server(mcp_ntp):
    """aos_show_ntp_status: server_reference must equal '10.0.4.1'."""
    with _mock_exec(SHOW_NTP_CLIENT):
        result = await mcp_ntp.call_tool("aos_show_ntp_status", {"host": "10.1.0.1"})
    data = json.loads(_text(result))
    assert data["server_reference"] == "10.0.4.1"


# ===========================================================================
# dhcp.py — Tool registration
# ===========================================================================


async def test_dhcp_tools_all_registered(mcp_dhcp):
    """Both DHCP tools declared in dhcp.py must appear in list_tools()."""
    tools = {t.name for t in await mcp_dhcp.list_tools()}
    assert "aos_show_ip_dhcp_relay" in tools
    assert "aos_show_ip_dhcp_relay_statistics" in tools


# ===========================================================================
# dhcp.py — aos_show_ip_dhcp_relay
# ===========================================================================


async def test_show_dhcp_relay_enabled(mcp_dhcp):
    """aos_show_ip_dhcp_relay: admin_status must equal 'Enable'."""
    with _mock_exec(SHOW_DHCP_RELAY):
        result = await mcp_dhcp.call_tool(
            "aos_show_ip_dhcp_relay", {"host": "10.1.0.1"}
        )
    data = json.loads(_text(result))
    assert data["admin_status"] == "Enable"


async def test_show_dhcp_relay_relay_mode(mcp_dhcp):
    """aos_show_ip_dhcp_relay: relay_mode must equal 'Global'."""
    with _mock_exec(SHOW_DHCP_RELAY):
        result = await mcp_dhcp.call_tool(
            "aos_show_ip_dhcp_relay", {"host": "10.1.0.1"}
        )
    data = json.loads(_text(result))
    assert data["relay_mode"] == "Global"


async def test_show_dhcp_relay_stats_structure(mcp_dhcp):
    """aos_show_ip_dhcp_relay_statistics: JSON must contain a 'statistics' list."""
    with _mock_exec(SHOW_DHCP_RELAY_STATS):
        result = await mcp_dhcp.call_tool(
            "aos_show_ip_dhcp_relay_statistics", {"host": "10.1.0.1"}
        )
    data = json.loads(_text(result))
    assert "statistics" in data
    assert isinstance(data["statistics"], list)


# ===========================================================================
# diagnostics.py — Tool registration
# ===========================================================================


async def test_diagnostics_tools_registered(mcp_diagnostics):
    """aos_ping must appear in list_tools()."""
    tools = {t.name for t in await mcp_diagnostics.list_tools()}
    assert "aos_ping" in tools


# ===========================================================================
# diagnostics.py — aos_ping
# ===========================================================================


async def test_ping_parses_loss(mcp_diagnostics):
    """aos_ping: packet_loss_pct must equal 100.0 when 0 packets received."""
    with _mock_exec(SHOW_PING):
        result = await mcp_diagnostics.call_tool(
            "aos_ping", {"host": "10.1.0.1", "target": "8.8.8.8"}
        )
    data = json.loads(_text(result))
    assert data["packet_loss_pct"] == 100.0


async def test_ping_success_false(mcp_diagnostics):
    """aos_ping: success must be False when packet_loss_pct is 100%."""
    with _mock_exec(SHOW_PING):
        result = await mcp_diagnostics.call_tool(
            "aos_ping", {"host": "10.1.0.1", "target": "8.8.8.8"}
        )
    data = json.loads(_text(result))
    assert data["success"] is False


async def test_ping_target_in_response(mcp_diagnostics):
    """aos_ping: 'target' key must be present in JSON and equal the requested target."""
    with _mock_exec(SHOW_PING):
        result = await mcp_diagnostics.call_tool(
            "aos_ping", {"host": "10.1.0.1", "target": "8.8.8.8"}
        )
    data = json.loads(_text(result))
    assert "target" in data
    assert data["target"] == "8.8.8.8"


# ===========================================================================
# Error handling — cross-module
# ===========================================================================


async def test_routing_tool_ssh_error_passthrough(mcp_routing):
    """aos_show_ip_routes: an SSH error string from execute_command must be
    returned as-is (no wrapping in JSON, no exception raised).
    """
    ssh_error = "ERROR: SSH connection refused to 10.1.0.1"
    with _mock_exec(ssh_error):
        result = await mcp_routing.call_tool(
            "aos_show_ip_routes", {"host": "10.1.0.1"}
        )
    text = _text(result)
    assert text == ssh_error


async def test_poe_tool_empty_slot(mcp_poe):
    """aos_show_lanpower_slot: a slot with no powered ports must return a valid
    JSON with an empty 'ports' list rather than raising an exception.
    """
    with _mock_exec(SHOW_LANPOWER_SLOT_EMPTY):
        result = await mcp_poe.call_tool(
            "aos_show_lanpower_slot", {"host": "10.1.0.1", "slot": "1/2"}
        )
    # Must be valid JSON (no exception)
    data = json.loads(_text(result))
    assert "ports" in data
    assert data["ports"] == []
    assert data["total_actual_mw"] == 0
