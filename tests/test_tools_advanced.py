"""Tests for AOS8 MCP tools — Phase 4 advanced modules.

Strategy:
  - Inline fixture strings are used as mock outputs (no raw_outputs files needed):
    the strings faithfully reproduce what AOS8 CLI returns for each command.
  - ``execute_command`` is mocked at the ``mcp_server.ssh.client`` module level so
    that no real SSH connection is attempted.  Tool functions import the symbol
    lazily (inside the async body), which means the patched symbol is always
    picked up while the context manager is active.
  - Each test asserts a single behaviour; names follow the convention
    ``test_<what>_<context>_<expected>`` or ``test_<what>_<field>``.

Modules covered:
  virtual_chassis, cloud_agent, snmp, sflow, qos, unp, port_security
"""
import json
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.fastmcp import FastMCP


# ---------------------------------------------------------------------------
# Helpers — identical pattern to test_tools_core.py
# ---------------------------------------------------------------------------

def _mock_exec(return_value: str):
    """Return a patch context manager that replaces ``execute_command``.

    Patches ``mcp_server.ssh.client.execute_command`` with an ``AsyncMock``
    that immediately returns *return_value*.

    Usage::

        with _mock_exec("...output..."):
            result = await mcp.call_tool("tool_name", {...})
    """
    return patch(
        "mcp_server.ssh.client.execute_command",
        new_callable=AsyncMock,
        return_value=return_value,
    )


def _text(result) -> str:
    """Extract the text payload from a ``call_tool`` result.

    ``FastMCP.call_tool`` returns a ``(list[TextContent], metadata)`` tuple.
    This helper extracts the first ``TextContent.text`` so individual tests
    stay concise.

    Args:
        result: Return value of ``await mcp.call_tool(...)``.

    Returns:
        The text string of the first content item.
    """
    content_list = result[0]
    return content_list[0].text


# ---------------------------------------------------------------------------
# Inline CLI fixture strings
# ---------------------------------------------------------------------------

SHOW_VC_TOPOLOGY = """
Local Chassis: 1
 Oper                                   Config   Oper                          
 Chas  Role         Status              Chas ID  Pri   Group  MAC-Address      
-----+------------+-------------------+--------+-----+------+------------------
 1     Master       Running             1        100   195    00:11:22:33:44:55
"""

SHOW_VC_CONSISTENCY = """
 Chas* ID     Status    Type*   Group* Interv  Vlan*    Vlan     License* 
------+------+---------+-------+------+-------+--------+--------+----------
 1     1      OK        OS6860  195    15      4094     4094     A         
"""

SHOW_CLOUD_AGENT = """
Admin State                     : Enabled,
Activation Server State         : completeOK,
Device State                    : DeviceManaged,
Error State                     : None,
Cloud Group                     : abc123group,
NTP Server                      : 198.51.100.20, 198.51.100.21, 10.0.4.1,
DNS Server                      : 198.51.100.20, 10.0.4.1,
VPN Server                      : abc123group.tenant.vpn.cloud.example.com:443,
Certificate Status              : Consistent
"""

SHOW_SNMP_STATION = """
ipAddress/port                                      status    protocol user
---------------------------------------------------+---------+--------+-------
198.51.100.10/162                                   enable    v2       ?
203.0.113.50/162                                    enable    v3       CLOUD_RW
"""

SHOW_SNMP_COMMUNITY = """
Community mode : enabled

status        community string                 user name
--------+--------------------------------+--------------------------------
enabled  company_RO                       SNMP_RO
enabled  company_RW                       MGMT_RW
"""

SHOW_SFLOW_AGENT = """
 Agent Version  = 1.0; ALE; 6.1.1
 Agent IP       = 10.1.0.1
"""

SHOW_SFLOW_SAMPLER = """
Instance  Interface  Receiver   Rate     Sample-Header-Size 
--------+----------+----------+--------+--------------------
   1       1/1/1          1        128          128   
   1       1/1/7          1        128          128   
"""

SHOW_SFLOW_RECEIVER = """
 Receiver 1 
 Name       = sflowCollector
 Address    = IP_V4  203.0.113.50
 UDP Port   = 6343 
 Timeout    = No Timeout 
 Packet Size= 1400 
 DatagramVer= 5 
"""

SHOW_QOS_CONFIG = """
QoS Configuration
  Admin                          = enable,
  Switch Group                   = expanded,
  Trust ports                    = no,
  Phones                         = trusted,
  Stats interval                 = 60,
  User-port shutdown             = bpdu,
  Pending changes                = none
"""

SHOW_UNP_PORT = """
 Port    Port    Type         802.1x   Mac      Class.   Default
          Domain              Auth     Auth
--------+-------+------------+--------+--------+--------+-----
1/1/1          0 Bridge       Enabled  Enabled  Enabled  -
"""

SHOW_UNP_USER_EMPTY = "Total users : 0"

SHOW_UNP_PROFILE = """
Profile Name: DEVICE-A
    Qos Policy      = -,
    CP State        = Dis,
    Inact Interval  = 10,
    Mac-Mobility =  Dis

Profile Name: Wi-Fi
    Qos Policy      = -,
    CP State        = Dis,
    Inact Interval  = 10,
    Mac-Mobility =  Dis

Total Profile Count: 2
"""

SHOW_PORT_SECURITY_NONE = "No Port Security is configured in the system."


# ===========================================================================
# Fixtures — one per tool module, each with a fresh FastMCP instance
# ===========================================================================


@pytest.fixture
def mcp_vc():
    """FastMCP instance with virtual_chassis tools registered (isolated per test)."""
    instance = FastMCP("test-virtual-chassis")
    from mcp_server.tools.virtual_chassis import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_cloud():
    """FastMCP instance with cloud_agent tools registered (isolated per test)."""
    instance = FastMCP("test-cloud-agent")
    from mcp_server.tools.cloud_agent import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_snmp():
    """FastMCP instance with snmp tools registered (isolated per test)."""
    instance = FastMCP("test-snmp")
    from mcp_server.tools.snmp import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_sflow():
    """FastMCP instance with sflow tools registered (isolated per test)."""
    instance = FastMCP("test-sflow")
    from mcp_server.tools.sflow import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_qos():
    """FastMCP instance with qos tools registered (isolated per test)."""
    instance = FastMCP("test-qos")
    from mcp_server.tools.qos import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_unp():
    """FastMCP instance with unp tools registered (isolated per test)."""
    instance = FastMCP("test-unp")
    from mcp_server.tools.unp import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_portsec():
    """FastMCP instance with port_security tools registered (isolated per test)."""
    instance = FastMCP("test-port-security")
    from mcp_server.tools.port_security import register_tools
    register_tools(instance)
    return instance


# ===========================================================================
# virtual_chassis.py — Tool registration
# ===========================================================================


async def test_vc_tools_all_registered(mcp_vc):
    """All virtual_chassis tools must appear in list_tools()."""
    tools = {t.name for t in await mcp_vc.list_tools()}
    expected = {
        "aos_show_vc_topology",
        "aos_show_vc_consistency",
        "aos_show_vc_vf_link",
    }
    assert expected.issubset(tools)


# ===========================================================================
# virtual_chassis.py — aos_show_vc_topology
# ===========================================================================


async def test_show_vc_topology_master(mcp_vc):
    """aos_show_vc_topology: chassis[0]['role'] must equal 'Master'."""
    with _mock_exec(SHOW_VC_TOPOLOGY):
        result = await mcp_vc.call_tool("aos_show_vc_topology", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert len(data["chassis"]) > 0
    assert data["chassis"][0]["role"] == "Master"


async def test_show_vc_topology_mac(mcp_vc):
    """aos_show_vc_topology: chassis[0]['mac_address'] must start with '00:11:22'."""
    with _mock_exec(SHOW_VC_TOPOLOGY):
        result = await mcp_vc.call_tool("aos_show_vc_topology", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["chassis"][0]["mac_address"].startswith("00:11:22")


async def test_show_vc_topology_local_chassis(mcp_vc):
    """aos_show_vc_topology: 'local_chassis' must equal 1."""
    with _mock_exec(SHOW_VC_TOPOLOGY):
        result = await mcp_vc.call_tool("aos_show_vc_topology", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["local_chassis"] == 1


async def test_show_vc_topology_echoes_host(mcp_vc):
    """aos_show_vc_topology: JSON response must echo back the queried host."""
    with _mock_exec(SHOW_VC_TOPOLOGY):
        result = await mcp_vc.call_tool("aos_show_vc_topology", {"host": "10.0.0.5"})
    data = json.loads(_text(result))
    assert data["host"] == "10.0.0.5"


# ===========================================================================
# virtual_chassis.py — aos_show_vc_consistency
# ===========================================================================


async def test_show_vc_consistency_ok(mcp_vc):
    """aos_show_vc_consistency: chassis[0]['status'] must equal 'OK'."""
    with _mock_exec(SHOW_VC_CONSISTENCY):
        result = await mcp_vc.call_tool("aos_show_vc_consistency", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert len(data["chassis"]) > 0
    assert data["chassis"][0]["status"] == "OK"


async def test_show_vc_consistency_license(mcp_vc):
    """aos_show_vc_consistency: chassis[0]['license'] must equal 'A'."""
    with _mock_exec(SHOW_VC_CONSISTENCY):
        result = await mcp_vc.call_tool("aos_show_vc_consistency", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["chassis"][0]["license"] == "A"


async def test_show_vc_consistency_chas_type(mcp_vc):
    """aos_show_vc_consistency: chassis[0]['chas_type'] must equal 'OS6860'."""
    with _mock_exec(SHOW_VC_CONSISTENCY):
        result = await mcp_vc.call_tool("aos_show_vc_consistency", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["chassis"][0]["chas_type"] == "OS6860"


# ===========================================================================
# virtual_chassis.py — aos_show_vc_vf_link
# ===========================================================================


async def test_show_vc_vf_link_empty(mcp_vc):
    """aos_show_vc_vf_link: empty output must return vf_links == []."""
    with _mock_exec(""):
        result = await mcp_vc.call_tool("aos_show_vc_vf_link", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["vf_links"] == []


async def test_show_vc_vf_link_total_count_zero_when_empty(mcp_vc):
    """aos_show_vc_vf_link: empty output must return total_count == 0."""
    with _mock_exec(""):
        result = await mcp_vc.call_tool("aos_show_vc_vf_link", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["total_count"] == 0


# ===========================================================================
# cloud_agent.py — Tool registration
# ===========================================================================


async def test_cloud_agent_tools_all_registered(mcp_cloud):
    """The cloud_agent tool must appear in list_tools()."""
    tools = {t.name for t in await mcp_cloud.list_tools()}
    assert "aos_show_cloud_agent_status" in tools


# ===========================================================================
# cloud_agent.py — aos_show_cloud_agent_status
# ===========================================================================


async def test_cloud_agent_managed(mcp_cloud):
    """aos_show_cloud_agent_status: 'device_state' must equal 'DeviceManaged'."""
    with _mock_exec(SHOW_CLOUD_AGENT):
        result = await mcp_cloud.call_tool(
            "aos_show_cloud_agent_status", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["device_state"] == "DeviceManaged"


async def test_cloud_agent_ntp_servers_list(mcp_cloud):
    """aos_show_cloud_agent_status: 'ntp_servers' must be a list with 3 items."""
    with _mock_exec(SHOW_CLOUD_AGENT):
        result = await mcp_cloud.call_tool(
            "aos_show_cloud_agent_status", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert isinstance(data["ntp_servers"], list)
    assert len(data["ntp_servers"]) == 3


async def test_cloud_agent_certificate_ok(mcp_cloud):
    """aos_show_cloud_agent_status: 'certificate_status' must equal 'Consistent'."""
    with _mock_exec(SHOW_CLOUD_AGENT):
        result = await mcp_cloud.call_tool(
            "aos_show_cloud_agent_status", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["certificate_status"] == "Consistent"


async def test_cloud_agent_admin_state(mcp_cloud):
    """aos_show_cloud_agent_status: 'admin_state' must equal 'Enabled'."""
    with _mock_exec(SHOW_CLOUD_AGENT):
        result = await mcp_cloud.call_tool(
            "aos_show_cloud_agent_status", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["admin_state"] == "Enabled"


async def test_cloud_agent_echoes_command(mcp_cloud):
    """aos_show_cloud_agent_status: JSON response must include 'show cloud-agent status'."""
    with _mock_exec(SHOW_CLOUD_AGENT):
        result = await mcp_cloud.call_tool(
            "aos_show_cloud_agent_status", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["command"] == "show cloud-agent status"


# ===========================================================================
# snmp.py — Tool registration
# ===========================================================================


async def test_snmp_tools_all_registered(mcp_snmp):
    """All SNMP tools must appear in list_tools()."""
    tools = {t.name for t in await mcp_snmp.list_tools()}
    expected = {
        "aos_show_snmp_station",
        "aos_show_snmp_community_map",
        "aos_show_snmp_security",
    }
    assert expected.issubset(tools)


# ===========================================================================
# snmp.py — aos_show_snmp_station
# ===========================================================================


async def test_snmp_station_count(mcp_snmp):
    """aos_show_snmp_station: 'total_count' must equal 2."""
    with _mock_exec(SHOW_SNMP_STATION):
        result = await mcp_snmp.call_tool("aos_show_snmp_station", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["total_count"] == 2


async def test_snmp_station_v3_user(mcp_snmp):
    """aos_show_snmp_station: one station must have user 'CLOUD_RW' with protocol 'v3'."""
    with _mock_exec(SHOW_SNMP_STATION):
        result = await mcp_snmp.call_tool("aos_show_snmp_station", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    v3_stations = [s for s in data["stations"] if s["protocol"] == "v3"]
    assert len(v3_stations) == 1
    assert v3_stations[0]["user"] == "CLOUD_RW"


async def test_snmp_station_total_count_matches_list(mcp_snmp):
    """aos_show_snmp_station: 'total_count' must equal len(stations)."""
    with _mock_exec(SHOW_SNMP_STATION):
        result = await mcp_snmp.call_tool("aos_show_snmp_station", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["total_count"] == len(data["stations"])


async def test_snmp_station_has_required_fields(mcp_snmp):
    """aos_show_snmp_station: every station must have ip_address, port, status, protocol, user."""
    with _mock_exec(SHOW_SNMP_STATION):
        result = await mcp_snmp.call_tool("aos_show_snmp_station", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    required = {"ip_address", "port", "status", "protocol", "user"}
    for station in data["stations"]:
        assert required.issubset(station.keys())


# ===========================================================================
# snmp.py — aos_show_snmp_community_map
# ===========================================================================


async def test_snmp_community_mode_enabled(mcp_snmp):
    """aos_show_snmp_community_map: 'community_mode' must equal 'enabled'."""
    with _mock_exec(SHOW_SNMP_COMMUNITY):
        result = await mcp_snmp.call_tool(
            "aos_show_snmp_community_map", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["community_mode"] == "enabled"


async def test_snmp_community_count(mcp_snmp):
    """aos_show_snmp_community_map: 'total_count' must equal 2."""
    with _mock_exec(SHOW_SNMP_COMMUNITY):
        result = await mcp_snmp.call_tool(
            "aos_show_snmp_community_map", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["total_count"] == 2


async def test_snmp_community_count_matches_list(mcp_snmp):
    """aos_show_snmp_community_map: 'total_count' must equal len(communities)."""
    with _mock_exec(SHOW_SNMP_COMMUNITY):
        result = await mcp_snmp.call_tool(
            "aos_show_snmp_community_map", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["total_count"] == len(data["communities"])


async def test_snmp_community_has_required_fields(mcp_snmp):
    """aos_show_snmp_community_map: every entry must have status, community_string, user_name."""
    with _mock_exec(SHOW_SNMP_COMMUNITY):
        result = await mcp_snmp.call_tool(
            "aos_show_snmp_community_map", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    required = {"status", "community_string", "user_name"}
    for community in data["communities"]:
        assert required.issubset(community.keys())


# ===========================================================================
# sflow.py — Tool registration
# ===========================================================================


async def test_sflow_tools_all_registered(mcp_sflow):
    """All sflow tools must appear in list_tools()."""
    tools = {t.name for t in await mcp_sflow.list_tools()}
    expected = {
        "aos_show_sflow_agent",
        "aos_show_sflow_sampler",
        "aos_show_sflow_poller",
        "aos_show_sflow_receiver",
    }
    assert expected.issubset(tools)


# ===========================================================================
# sflow.py — aos_show_sflow_agent
# ===========================================================================


async def test_sflow_agent_ip(mcp_sflow):
    """aos_show_sflow_agent: 'agent_ip' must equal '10.1.0.1'."""
    with _mock_exec(SHOW_SFLOW_AGENT):
        result = await mcp_sflow.call_tool("aos_show_sflow_agent", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["agent_ip"] == "10.1.0.1"


async def test_sflow_agent_vendor(mcp_sflow):
    """aos_show_sflow_agent: 'vendor' must equal 'ALE'."""
    with _mock_exec(SHOW_SFLOW_AGENT):
        result = await mcp_sflow.call_tool("aos_show_sflow_agent", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["vendor"] == "ALE"


async def test_sflow_agent_version(mcp_sflow):
    """aos_show_sflow_agent: 'agent_version' must equal '1.0'."""
    with _mock_exec(SHOW_SFLOW_AGENT):
        result = await mcp_sflow.call_tool("aos_show_sflow_agent", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["agent_version"] == "1.0"


# ===========================================================================
# sflow.py — aos_show_sflow_sampler
# ===========================================================================


async def test_sflow_sampler_count(mcp_sflow):
    """aos_show_sflow_sampler: 'total_count' must equal 2."""
    with _mock_exec(SHOW_SFLOW_SAMPLER):
        result = await mcp_sflow.call_tool("aos_show_sflow_sampler", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["total_count"] == 2


async def test_sflow_sampler_rate(mcp_sflow):
    """aos_show_sflow_sampler: first sampler 'rate' must equal 128."""
    with _mock_exec(SHOW_SFLOW_SAMPLER):
        result = await mcp_sflow.call_tool("aos_show_sflow_sampler", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["samplers"][0]["rate"] == 128


async def test_sflow_sampler_total_count_matches_list(mcp_sflow):
    """aos_show_sflow_sampler: 'total_count' must equal len(samplers)."""
    with _mock_exec(SHOW_SFLOW_SAMPLER):
        result = await mcp_sflow.call_tool("aos_show_sflow_sampler", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["total_count"] == len(data["samplers"])


async def test_sflow_sampler_has_required_fields(mcp_sflow):
    """aos_show_sflow_sampler: every sampler must have instance, interface, receiver, rate."""
    with _mock_exec(SHOW_SFLOW_SAMPLER):
        result = await mcp_sflow.call_tool("aos_show_sflow_sampler", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    required = {"instance", "interface", "receiver", "rate", "sample_header_size"}
    for sampler in data["samplers"]:
        assert required.issubset(sampler.keys())


# ===========================================================================
# sflow.py — aos_show_sflow_receiver
# ===========================================================================


async def test_sflow_receiver_name(mcp_sflow):
    """aos_show_sflow_receiver: receivers[0]['name'] must equal 'sflowCollector'."""
    with _mock_exec(SHOW_SFLOW_RECEIVER):
        result = await mcp_sflow.call_tool(
            "aos_show_sflow_receiver", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert len(data["receivers"]) > 0
    assert data["receivers"][0]["name"] == "sflowCollector"


async def test_sflow_receiver_port(mcp_sflow):
    """aos_show_sflow_receiver: receivers[0]['udp_port'] must equal 6343."""
    with _mock_exec(SHOW_SFLOW_RECEIVER):
        result = await mcp_sflow.call_tool(
            "aos_show_sflow_receiver", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["receivers"][0]["udp_port"] == 6343


async def test_sflow_receiver_address(mcp_sflow):
    """aos_show_sflow_receiver: receivers[0]['address'] must equal '203.0.113.50'."""
    with _mock_exec(SHOW_SFLOW_RECEIVER):
        result = await mcp_sflow.call_tool(
            "aos_show_sflow_receiver", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["receivers"][0]["address"] == "203.0.113.50"


# ===========================================================================
# sflow.py — aos_show_sflow_poller
# ===========================================================================


async def test_sflow_poller_empty(mcp_sflow):
    """aos_show_sflow_poller: empty output must return pollers == []."""
    with _mock_exec(""):
        result = await mcp_sflow.call_tool("aos_show_sflow_poller", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["pollers"] == []


async def test_sflow_poller_total_count_zero_when_empty(mcp_sflow):
    """aos_show_sflow_poller: empty output must return total_count == 0."""
    with _mock_exec(""):
        result = await mcp_sflow.call_tool("aos_show_sflow_poller", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["total_count"] == 0


# ===========================================================================
# qos.py — Tool registration
# ===========================================================================


async def test_qos_tools_all_registered(mcp_qos):
    """The QoS tool must appear in list_tools()."""
    tools = {t.name for t in await mcp_qos.list_tools()}
    assert "aos_show_qos_config" in tools


# ===========================================================================
# qos.py — aos_show_qos_config
# ===========================================================================


async def test_qos_admin_enable(mcp_qos):
    """aos_show_qos_config: 'admin' must equal 'enable'."""
    with _mock_exec(SHOW_QOS_CONFIG):
        result = await mcp_qos.call_tool("aos_show_qos_config", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["admin"] == "enable"


async def test_qos_pending_none(mcp_qos):
    """aos_show_qos_config: 'pending_changes' must equal 'none'."""
    with _mock_exec(SHOW_QOS_CONFIG):
        result = await mcp_qos.call_tool("aos_show_qos_config", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["pending_changes"] == "none"


async def test_qos_switch_group(mcp_qos):
    """aos_show_qos_config: 'switch_group' must equal 'expanded'."""
    with _mock_exec(SHOW_QOS_CONFIG):
        result = await mcp_qos.call_tool("aos_show_qos_config", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["switch_group"] == "expanded"


async def test_qos_echoes_command(mcp_qos):
    """aos_show_qos_config: JSON response must include 'show qos config'."""
    with _mock_exec(SHOW_QOS_CONFIG):
        result = await mcp_qos.call_tool("aos_show_qos_config", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["command"] == "show qos config"


async def test_qos_stats_interval_is_integer(mcp_qos):
    """aos_show_qos_config: 'stats_interval' must be an integer."""
    with _mock_exec(SHOW_QOS_CONFIG):
        result = await mcp_qos.call_tool("aos_show_qos_config", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert isinstance(data["stats_interval"], int)
    assert data["stats_interval"] == 60


# ===========================================================================
# unp.py — Tool registration
# ===========================================================================


async def test_unp_tools_all_registered(mcp_unp):
    """All UNP tools must appear in list_tools()."""
    tools = {t.name for t in await mcp_unp.list_tools()}
    expected = {
        "aos_show_unp_port",
        "aos_show_unp_user",
        "aos_show_unp_profile",
    }
    assert expected.issubset(tools)


# ===========================================================================
# unp.py — aos_show_unp_port
# ===========================================================================


async def test_unp_port_bridge(mcp_unp):
    """aos_show_unp_port: port 1/1/1 must have type 'Bridge'."""
    with _mock_exec(SHOW_UNP_PORT):
        result = await mcp_unp.call_tool("aos_show_unp_port", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert len(data["ports"]) > 0
    port_entry = data["ports"][0]
    assert port_entry["port"] == "1/1/1"
    assert port_entry["type"] == "Bridge"


async def test_unp_port_auth_enabled(mcp_unp):
    """aos_show_unp_port: port 1/1/1 must have auth_802_1x == 'Enabled'."""
    with _mock_exec(SHOW_UNP_PORT):
        result = await mcp_unp.call_tool("aos_show_unp_port", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    port_entry = data["ports"][0]
    assert port_entry["auth_802_1x"] == "Enabled"


async def test_unp_port_total_count_matches_list(mcp_unp):
    """aos_show_unp_port: 'total_count' must equal len(ports)."""
    with _mock_exec(SHOW_UNP_PORT):
        result = await mcp_unp.call_tool("aos_show_unp_port", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["total_count"] == len(data["ports"])


# ===========================================================================
# unp.py — aos_show_unp_user
# ===========================================================================


async def test_unp_user_empty(mcp_unp):
    """aos_show_unp_user: 'Total users : 0' output must return users == [] and total_count == 0."""
    with _mock_exec(SHOW_UNP_USER_EMPTY):
        result = await mcp_unp.call_tool("aos_show_unp_user", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["users"] == []
    assert data["total_count"] == 0


async def test_unp_user_result_is_valid_json(mcp_unp):
    """aos_show_unp_user: result must always be valid JSON."""
    with _mock_exec(SHOW_UNP_USER_EMPTY):
        result = await mcp_unp.call_tool("aos_show_unp_user", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert isinstance(data, dict)


# ===========================================================================
# unp.py — aos_show_unp_profile
# ===========================================================================


async def test_unp_profile_count(mcp_unp):
    """aos_show_unp_profile: 'total_count' must equal 2."""
    with _mock_exec(SHOW_UNP_PROFILE):
        result = await mcp_unp.call_tool("aos_show_unp_profile", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["total_count"] == 2


async def test_unp_profile_names(mcp_unp):
    """aos_show_unp_profile: 'DEVICE-A' and 'Wi-Fi' must be present in profile names."""
    with _mock_exec(SHOW_UNP_PROFILE):
        result = await mcp_unp.call_tool("aos_show_unp_profile", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    profile_names = [p["name"] for p in data["profiles"]]
    assert "DEVICE-A" in profile_names
    assert "Wi-Fi" in profile_names


async def test_unp_profile_count_matches_list(mcp_unp):
    """aos_show_unp_profile: 'total_count' must equal len(profiles)."""
    with _mock_exec(SHOW_UNP_PROFILE):
        result = await mcp_unp.call_tool("aos_show_unp_profile", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["total_count"] == len(data["profiles"])


async def test_unp_profile_has_name_field(mcp_unp):
    """aos_show_unp_profile: every profile entry must have a 'name' field."""
    with _mock_exec(SHOW_UNP_PROFILE):
        result = await mcp_unp.call_tool("aos_show_unp_profile", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    for profile in data["profiles"]:
        assert "name" in profile


# ===========================================================================
# port_security.py — Tool registration
# ===========================================================================


async def test_portsec_tools_all_registered(mcp_portsec):
    """All port_security tools must appear in list_tools()."""
    tools = {t.name for t in await mcp_portsec.list_tools()}
    expected = {
        "aos_show_port_security",
        "aos_show_port_security_brief",
        "aos_show_port_security_port",
    }
    assert expected.issubset(tools)


# ===========================================================================
# port_security.py — aos_show_port_security
# ===========================================================================


async def test_port_security_not_configured(mcp_portsec):
    """aos_show_port_security: sentinel message must produce configured == False."""
    with _mock_exec(SHOW_PORT_SECURITY_NONE):
        result = await mcp_portsec.call_tool(
            "aos_show_port_security", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["configured"] is False


async def test_port_security_not_configured_includes_message(mcp_portsec):
    """aos_show_port_security: unconfigured response must include a 'message' key."""
    with _mock_exec(SHOW_PORT_SECURITY_NONE):
        result = await mcp_portsec.call_tool(
            "aos_show_port_security", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert "message" in data
    assert len(data["message"]) > 0


# ===========================================================================
# port_security.py — aos_show_port_security_brief
# ===========================================================================


async def test_port_security_brief_empty(mcp_portsec):
    """aos_show_port_security_brief: empty output must return ports == []."""
    with _mock_exec(""):
        result = await mcp_portsec.call_tool(
            "aos_show_port_security_brief", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["ports"] == []


async def test_port_security_brief_total_count_zero_when_empty(mcp_portsec):
    """aos_show_port_security_brief: empty output must return total_count == 0."""
    with _mock_exec(""):
        result = await mcp_portsec.call_tool(
            "aos_show_port_security_brief", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["total_count"] == 0


# ===========================================================================
# port_security.py — aos_show_port_security_port
# ===========================================================================


async def test_port_security_port_not_configured(mcp_portsec):
    """aos_show_port_security_port: sentinel message must produce configured == False for a port."""
    with _mock_exec(SHOW_PORT_SECURITY_NONE):
        result = await mcp_portsec.call_tool(
            "aos_show_port_security_port", {"host": "192.168.1.1", "port": "1/1/5"}
        )
    data = json.loads(_text(result))
    assert data["configured"] is False


async def test_port_security_port_empty_output_not_configured(mcp_portsec):
    """aos_show_port_security_port: empty output must produce configured == False."""
    with _mock_exec(""):
        result = await mcp_portsec.call_tool(
            "aos_show_port_security_port", {"host": "192.168.1.1", "port": "1/1/5"}
        )
    data = json.loads(_text(result))
    assert data["configured"] is False


async def test_port_security_port_echoes_port_argument(mcp_portsec):
    """aos_show_port_security_port: JSON response must echo back the queried port."""
    with _mock_exec(""):
        result = await mcp_portsec.call_tool(
            "aos_show_port_security_port", {"host": "192.168.1.1", "port": "1/1/5"}
        )
    data = json.loads(_text(result))
    assert data["port"] == "1/1/5"


# ===========================================================================
# Error handling — SSH passthrough tests (cross-module)
# ===========================================================================


async def test_advanced_ssh_error_passthrough(mcp_vc):
    """SSH failure: aos_show_vc_topology must return 'ERROR: ...' string, not raise."""
    with _mock_exec("ERROR: OSError: [Errno 111] Connection refused"):
        result = await mcp_vc.call_tool(
            "aos_show_vc_topology", {"host": "10.0.0.99"}
        )
    assert len(result) > 0
    assert _text(result).startswith("ERROR:")
    # Error string must NOT be valid JSON
    with pytest.raises((json.JSONDecodeError, ValueError)):
        json.loads(_text(result))


async def test_ssh_error_passthrough_cloud_agent(mcp_cloud):
    """SSH failure: aos_show_cloud_agent_status must return error string unchanged."""
    error_msg = "ERROR: PermissionDenied: Bad password"
    with _mock_exec(error_msg):
        result = await mcp_cloud.call_tool(
            "aos_show_cloud_agent_status", {"host": "10.0.0.1"}
        )
    assert _text(result) == error_msg


async def test_ssh_error_passthrough_snmp(mcp_snmp):
    """SSH failure: aos_show_snmp_station must return error string unchanged."""
    error_msg = "ERROR: ConnectTimeout: could not connect to 10.0.0.1 within 10s"
    with _mock_exec(error_msg):
        result = await mcp_snmp.call_tool(
            "aos_show_snmp_station", {"host": "10.0.0.1"}
        )
    assert _text(result) == error_msg


async def test_ssh_error_passthrough_qos(mcp_qos):
    """SSH failure: aos_show_qos_config must return error string unchanged."""
    error_msg = "ERROR: SSHDisconnect: Connection reset by peer"
    with _mock_exec(error_msg):
        result = await mcp_qos.call_tool("aos_show_qos_config", {"host": "10.0.0.1"})
    assert _text(result).startswith("ERROR:")


async def test_ssh_error_passthrough_port_security(mcp_portsec):
    """SSH failure: aos_show_port_security must return error string unchanged."""
    error_msg = "ERROR: OSError: Network is unreachable"
    with _mock_exec(error_msg):
        result = await mcp_portsec.call_tool(
            "aos_show_port_security", {"host": "10.0.0.1"}
        )
    assert _text(result) == error_msg


# ===========================================================================
# Edge cases — empty output produces valid JSON for list-returning tools
# ===========================================================================


async def test_empty_output_snmp_station_returns_empty_list(mcp_snmp):
    """Empty SSH output: aos_show_snmp_station must return valid JSON with empty stations."""
    with _mock_exec(""):
        result = await mcp_snmp.call_tool("aos_show_snmp_station", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert isinstance(data, dict)
    assert data["stations"] == []
    assert data["total_count"] == 0


async def test_empty_output_sflow_sampler_returns_empty_list(mcp_sflow):
    """Empty SSH output: aos_show_sflow_sampler must return valid JSON with empty samplers."""
    with _mock_exec(""):
        result = await mcp_sflow.call_tool(
            "aos_show_sflow_sampler", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert isinstance(data, dict)
    assert data["samplers"] == []
    assert data["total_count"] == 0


async def test_empty_output_unp_profile_returns_empty_list(mcp_unp):
    """Empty SSH output: aos_show_unp_profile must return valid JSON with empty profiles."""
    with _mock_exec(""):
        result = await mcp_unp.call_tool("aos_show_unp_profile", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert isinstance(data, dict)
    assert data["profiles"] == []
