"""Tests for AOS8 MCP tools — Phase 2 core implementation.

Strategy:
  - Real raw_outputs/*.txt files are used as fixture data via the RAW helper.
  - ``execute_command`` is mocked at the ``mcp_server.ssh.client`` module level so
    that no real SSH connection is attempted.  Each tool function performs a
    ``from mcp_server.ssh.client import execute_command`` at call time, which picks
    up the patched symbol while the context manager is active.
  - Each test asserts a single behaviour; names follow
    ``test_<what>_<context>_<expected>`` or ``test_<what>_<field>`` conventions.

Raw output files used:
  raw_outputs/show_system.txt            → aos_show_system
  raw_outputs/show_microcode.txt         → aos_show_microcode
  raw_outputs/show_chassis.txt           → aos_show_chassis
  raw_outputs/show_running_directory.txt → aos_show_running_directory
  raw_outputs/show_vlan.txt              → aos_show_vlan
  raw_outputs/show_vlan_members.txt      → aos_show_vlan_members
  raw_outputs/show_spantree.txt          → aos_show_spantree
  raw_outputs/show_spantree_cist.txt     → aos_show_spantree_cist
  raw_outputs/show_interfaces_status.txt → aos_show_interfaces_status
  raw_outputs/show_interfaces_alias.txt  → aos_show_interfaces_alias
  raw_outputs/show_lldp_remote_system.txt→ aos_show_lldp_remote_system
  raw_outputs/show_health.txt            → aos_show_health
  raw_outputs/show_temp.txt              → aos_show_temp
  raw_outputs/show_fan.txt               → aos_show_fan
  raw_outputs/show_mac_learning.txt      → aos_show_mac_learning
"""
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Paths and helpers
# ---------------------------------------------------------------------------

#: Absolute path to the raw_outputs directory.
RAW = Path(__file__).parent.parent / "raw_outputs"


def _raw(filename: str) -> str:
    """Load a raw_output fixture file.

    Returns the file content, or an empty string when the file does not exist
    so that tests degrade gracefully for commands not yet captured.
    """
    path = RAW / filename
    return path.read_text(encoding="utf-8") if path.exists() else ""


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
    # result is (list[TextContent], dict) — pick the first TextContent
    content_list = result[0]
    return content_list[0].text


# ---------------------------------------------------------------------------
# Inline fixtures for tools without dedicated raw_output files
# ---------------------------------------------------------------------------

#: Minimal fake running-config (used by aos_config_backup tests).
_FAKE_CONFIG = """\
! AOS8 running configuration — test fixture
vlan 1 name "Default"
vlan 10 name "MGT"
ip interface "Mgmt" address 192.168.1.1 mask 255.255.255.0 vlan 10
"""

#: Minimal fake LLDP-port output (used by aos_show_lldp_port tests).
#: Format matches `show lldp port {port} remote-system`, parsed by _parse_lldp_remote_system.
_FAKE_LLDP_PORT = """\
Remote LLDP nearest-bridge Agents on Local Port 1/1/25:

    Chassis 10.0.0.1, Port aa:bb:cc:dd:ee:ff:
      Remote ID                   = 42,
      Chassis Subtype             = 5 (Network Address),
      Port Subtype                = 3 (MAC address),
      Port Description            = uplink,
      System Name                 = TEST-SWITCH,
      System Description          = AOS 8.x test fixture,
      Capabilities Supported      = Bridge,
      Capabilities Enabled        = Bridge,
"""

#: Minimal fake MAC-learning output filtered to a single port.
_FAKE_MAC_LEARNING_PORT = """\
Legend: Mac Address: * = address not valid,
        Mac Address: & = duplicate static address,
        ID = ISID/Vnid/vplsid

   Domain    Vlan/SrvcId[:ID]           Mac Address           Type          Operation          Interface
------------+----------------------+-------------------+------------------+-------------+-------------------------
      VLAN                       18   00:aa:bb:cc:dd:01            dynamic     bridging                    1/1/25
      VLAN                       99   00:aa:bb:cc:dd:01            dynamic     bridging                    1/1/25
"""

# ===========================================================================
# Fixtures — one per tool module, each with a fresh FastMCP instance
# ===========================================================================


@pytest.fixture
def mcp_core():
    """FastMCP instance with core tools registered (isolated per test)."""
    instance = FastMCP("test-core")
    from mcp_server.tools.core import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_ports():
    """FastMCP instance with port/interface tools registered."""
    instance = FastMCP("test-ports")
    from mcp_server.tools.ports import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_vlan():
    """FastMCP instance with VLAN tools registered."""
    instance = FastMCP("test-vlan")
    from mcp_server.tools.vlan import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_spantree():
    """FastMCP instance with spanning tree tools registered."""
    instance = FastMCP("test-spantree")
    from mcp_server.tools.spantree import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def mcp_health():
    """FastMCP instance with health/monitoring tools registered."""
    instance = FastMCP("test-health")
    from mcp_server.tools.health import register_tools
    register_tools(instance)
    return instance


# ===========================================================================
# core.py — Tool registration
# ===========================================================================


async def test_core_tools_all_registered(mcp_core):
    """Every tool declared in core.py must appear in list_tools()."""
    tools = {t.name for t in await mcp_core.list_tools()}
    expected = {
        "aos_show_system",
        "aos_show_microcode",
        "aos_show_chassis",
        "aos_show_running_directory",
        "aos_show_cmm",
        "aos_config_backup",
    }
    assert expected.issubset(tools)


# ===========================================================================
# core.py — aos_show_system
# ===========================================================================


async def test_show_system_parses_hostname(mcp_core):
    """aos_show_system: 'name' must equal the device hostname 'PDF-TEST-6860-P24'."""
    with _mock_exec(_raw("show_system.txt")):
        result = await mcp_core.call_tool("aos_show_system", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["name"] == "PDF-TEST-6860-P24"


async def test_show_system_parses_uptime(mcp_core):
    """aos_show_system: 'uptime' must be non-null and contain 'days'."""
    with _mock_exec(_raw("show_system.txt")):
        result = await mcp_core.call_tool("aos_show_system", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["uptime"] is not None
    assert "days" in data["uptime"].lower()


async def test_show_system_parses_location(mcp_core):
    """aos_show_system: 'location' must be non-null."""
    with _mock_exec(_raw("show_system.txt")):
        result = await mcp_core.call_tool("aos_show_system", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["location"] is not None


async def test_show_system_echoes_host(mcp_core):
    """aos_show_system: JSON response must echo back the queried host."""
    with _mock_exec(_raw("show_system.txt")):
        result = await mcp_core.call_tool("aos_show_system", {"host": "10.0.0.1"})
    data = json.loads(_text(result))
    assert data["host"] == "10.0.0.1"


async def test_show_system_includes_command_key(mcp_core):
    """aos_show_system: JSON response must include a 'command' key."""
    with _mock_exec(_raw("show_system.txt")):
        result = await mcp_core.call_tool("aos_show_system", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["command"] == "show system"


# ===========================================================================
# core.py — aos_show_microcode
# ===========================================================================


async def test_show_microcode_parses_release(mcp_core):
    """aos_show_microcode: first package 'release' must equal '8.9.94.R04'."""
    with _mock_exec(_raw("show_microcode.txt")):
        result = await mcp_core.call_tool("aos_show_microcode", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert len(data["packages"]) > 0
    assert data["packages"][0]["release"] == "8.9.94.R04"


async def test_show_microcode_parses_directory(mcp_core):
    """aos_show_microcode: 'directory' must be '/flash/working'."""
    with _mock_exec(_raw("show_microcode.txt")):
        result = await mcp_core.call_tool("aos_show_microcode", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["directory"] == "/flash/working"


async def test_show_microcode_packages_have_positive_size(mcp_core):
    """aos_show_microcode: every package must have a positive integer 'size'."""
    with _mock_exec(_raw("show_microcode.txt")):
        result = await mcp_core.call_tool("aos_show_microcode", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    for pkg in data["packages"]:
        assert isinstance(pkg["size"], int)
        assert pkg["size"] > 0


# ===========================================================================
# core.py — aos_show_chassis
# ===========================================================================


async def test_show_chassis_parses_model(mcp_core):
    """aos_show_chassis: 'model_name' must equal 'OS6860-P24'."""
    with _mock_exec(_raw("show_chassis.txt")):
        result = await mcp_core.call_tool("aos_show_chassis", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["model_name"] == "OS6860-P24"


async def test_show_chassis_parses_serial(mcp_core):
    """aos_show_chassis: 'serial_number' must equal 'U1782317'."""
    with _mock_exec(_raw("show_chassis.txt")):
        result = await mcp_core.call_tool("aos_show_chassis", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["serial_number"] == "U1782317"


async def test_show_chassis_parses_mac_address(mcp_core):
    """aos_show_chassis: 'mac_address' must be a colon-separated MAC string."""
    with _mock_exec(_raw("show_chassis.txt")):
        result = await mcp_core.call_tool("aos_show_chassis", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["mac_address"] is not None
    assert re.match(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$", data["mac_address"])


async def test_show_chassis_operational_status_up(mcp_core):
    """aos_show_chassis: 'operational_status' must be 'UP'."""
    with _mock_exec(_raw("show_chassis.txt")):
        result = await mcp_core.call_tool("aos_show_chassis", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["operational_status"] == "UP"


# ===========================================================================
# core.py — aos_show_running_directory
# ===========================================================================


async def test_show_running_directory_status(mcp_core):
    """aos_show_running_directory: 'running_configuration' must be 'WORKING'."""
    with _mock_exec(_raw("show_running_directory.txt")):
        result = await mcp_core.call_tool(
            "aos_show_running_directory", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["running_configuration"] == "WORKING"


async def test_show_running_directory_certify_status(mcp_core):
    """aos_show_running_directory: 'certify_restore_status' must be 'CERTIFIED'."""
    with _mock_exec(_raw("show_running_directory.txt")):
        result = await mcp_core.call_tool(
            "aos_show_running_directory", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["certify_restore_status"] == "CERTIFIED"


# ===========================================================================
# core.py — aos_config_backup
# ===========================================================================


async def test_config_backup_returns_raw_text(mcp_core):
    """aos_config_backup: result must be plain text, NOT a JSON object."""
    with _mock_exec(_FAKE_CONFIG):
        result = await mcp_core.call_tool("aos_config_backup", {"host": "192.168.1.1"})
    assert len(result) > 0
    text = _text(result)
    # Plain CLI output is not valid JSON
    with pytest.raises((json.JSONDecodeError, ValueError)):
        json.loads(text)


async def test_config_backup_passthrough_content(mcp_core):
    """aos_config_backup: full CLI text must be returned unmodified."""
    with _mock_exec(_FAKE_CONFIG):
        result = await mcp_core.call_tool("aos_config_backup", {"host": "192.168.1.1"})
    assert _text(result) == _FAKE_CONFIG


async def test_config_backup_contains_vlan_keyword(mcp_core):
    """aos_config_backup: returned text must contain CLI keywords."""
    with _mock_exec(_FAKE_CONFIG):
        result = await mcp_core.call_tool("aos_config_backup", {"host": "192.168.1.1"})
    assert "vlan" in _text(result).lower()


# ===========================================================================
# vlan.py — Tool registration
# ===========================================================================


async def test_vlan_tools_all_registered(mcp_vlan):
    """Both VLAN tools must appear in list_tools()."""
    tools = {t.name for t in await mcp_vlan.list_tools()}
    assert "aos_show_vlan" in tools
    assert "aos_show_vlan_members" in tools


# ===========================================================================
# vlan.py — aos_show_vlan
# ===========================================================================


async def test_show_vlan_count(mcp_vlan):
    """aos_show_vlan: 'total_count' must equal 73 (number of VLANs in raw_output)."""
    with _mock_exec(_raw("show_vlan.txt")):
        result = await mcp_vlan.call_tool("aos_show_vlan", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["total_count"] == 73


async def test_show_vlan_includes_vcm(mcp_vlan):
    """aos_show_vlan: VLAN 4094 of type 'vcm' must be present."""
    with _mock_exec(_raw("show_vlan.txt")):
        result = await mcp_vlan.call_tool("aos_show_vlan", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    vcm_vlans = [v for v in data["vlans"] if v["vlan_id"] == 4094]
    assert len(vcm_vlans) == 1
    assert vcm_vlans[0]["type"] == "vcm"


async def test_show_vlan_entries_have_required_fields(mcp_vlan):
    """aos_show_vlan: every VLAN entry must contain the required field set."""
    with _mock_exec(_raw("show_vlan.txt")):
        result = await mcp_vlan.call_tool("aos_show_vlan", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    required = {"vlan_id", "type", "admin", "oper", "ip", "mtu"}
    for vlan in data["vlans"]:
        assert required.issubset(vlan.keys()), (
            f"VLAN {vlan.get('vlan_id')} is missing required fields"
        )


async def test_show_vlan_total_count_matches_list_length(mcp_vlan):
    """aos_show_vlan: 'total_count' must equal len(vlans)."""
    with _mock_exec(_raw("show_vlan.txt")):
        result = await mcp_vlan.call_tool("aos_show_vlan", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["total_count"] == len(data["vlans"])


# ===========================================================================
# vlan.py — aos_show_vlan_members
# ===========================================================================


async def test_show_vlan_members_forwarding(mcp_vlan):
    """aos_show_vlan_members: at least one entry must have status 'forwarding'."""
    with _mock_exec(_raw("show_vlan_members.txt")):
        result = await mcp_vlan.call_tool(
            "aos_show_vlan_members", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    forwarding = [m for m in data["members"] if m["status"] == "forwarding"]
    assert len(forwarding) > 0


async def test_show_vlan_members_total_count_matches_list(mcp_vlan):
    """aos_show_vlan_members: 'total_count' must equal len(members)."""
    with _mock_exec(_raw("show_vlan_members.txt")):
        result = await mcp_vlan.call_tool(
            "aos_show_vlan_members", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["total_count"] == len(data["members"])


async def test_show_vlan_members_entry_has_port_field(mcp_vlan):
    """aos_show_vlan_members: every entry must contain a 'port' field."""
    with _mock_exec(_raw("show_vlan_members.txt")):
        result = await mcp_vlan.call_tool(
            "aos_show_vlan_members", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    for member in data["members"]:
        assert "port" in member


# ===========================================================================
# spantree.py — Tool registration
# ===========================================================================


async def test_spantree_tools_all_registered(mcp_spantree):
    """Both spanning-tree tools must appear in list_tools()."""
    tools = {t.name for t in await mcp_spantree.list_tools()}
    assert "aos_show_spantree" in tools
    assert "aos_show_spantree_cist" in tools


# ===========================================================================
# spantree.py — aos_show_spantree_cist
# ===========================================================================


async def test_show_spantree_cist_root_port(mcp_spantree):
    """aos_show_spantree_cist: 'root_port' must equal '1/1/25'."""
    with _mock_exec(_raw("show_spantree_cist.txt")):
        result = await mcp_spantree.call_tool(
            "aos_show_spantree_cist", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["root_port"] == "1/1/25"


async def test_show_spantree_cist_bridge_id(mcp_spantree):
    """aos_show_spantree_cist: 'bridge_id' must contain a MAC-like string."""
    with _mock_exec(_raw("show_spantree_cist.txt")):
        result = await mcp_spantree.call_tool(
            "aos_show_spantree_cist", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["bridge_id"] is not None
    assert ":" in data["bridge_id"]


async def test_show_spantree_cist_status_on(mcp_spantree):
    """aos_show_spantree_cist: 'status' must be 'ON'."""
    with _mock_exec(_raw("show_spantree_cist.txt")):
        result = await mcp_spantree.call_tool(
            "aos_show_spantree_cist", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["status"] == "ON"


async def test_show_spantree_cist_timers_are_integers(mcp_spantree):
    """aos_show_spantree_cist: max_age, forward_delay and hello_time must be ints."""
    with _mock_exec(_raw("show_spantree_cist.txt")):
        result = await mcp_spantree.call_tool(
            "aos_show_spantree_cist", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert isinstance(data["max_age"], int), "max_age must be an integer"
    assert isinstance(data["forward_delay"], int), "forward_delay must be an integer"
    assert isinstance(data["hello_time"], int), "hello_time must be an integer"


# ===========================================================================
# spantree.py — aos_show_spantree
# ===========================================================================


async def test_show_spantree_path_cost_mode_auto(mcp_spantree):
    """aos_show_spantree: 'path_cost_mode' must be 'AUTO'."""
    with _mock_exec(_raw("show_spantree.txt")):
        result = await mcp_spantree.call_tool(
            "aos_show_spantree", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["path_cost_mode"] == "AUTO"


async def test_show_spantree_instances_present(mcp_spantree):
    """aos_show_spantree: 'instances' list must be non-empty."""
    with _mock_exec(_raw("show_spantree.txt")):
        result = await mcp_spantree.call_tool(
            "aos_show_spantree", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert len(data["instances"]) > 0


async def test_show_spantree_instance_fields(mcp_spantree):
    """aos_show_spantree: each instance must have msti, status, protocol, priority."""
    with _mock_exec(_raw("show_spantree.txt")):
        result = await mcp_spantree.call_tool(
            "aos_show_spantree", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    required = {"msti", "status", "protocol", "priority"}
    for inst in data["instances"]:
        assert required.issubset(inst.keys())


# ===========================================================================
# ports.py — Tool registration
# ===========================================================================


async def test_ports_tools_all_registered(mcp_ports):
    """All port/interface tools must appear in list_tools()."""
    tools = {t.name for t in await mcp_ports.list_tools()}
    expected = {
        "aos_show_interfaces_status",
        "aos_show_interfaces_alias",
        "aos_show_interfaces_counters_errors",
        "aos_show_interfaces_ddm",
        "aos_show_interfaces_port",
        "aos_show_interfaces_flood_rate",
        "aos_show_lldp_remote_system",
        "aos_show_lldp_port",
    }
    assert expected.issubset(tools)


# ===========================================================================
# ports.py — aos_show_interfaces_status
# ===========================================================================


async def test_show_interfaces_status_count(mcp_ports):
    """aos_show_interfaces_status: must return exactly 30 ports from raw_output."""
    with _mock_exec(_raw("show_interfaces_status.txt")):
        result = await mcp_ports.call_tool(
            "aos_show_interfaces_status", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert len(data["ports"]) == 30


async def test_show_interfaces_status_port_id_format(mcp_ports):
    """aos_show_interfaces_status: every port ID must match 'chassis/slot/port'."""
    with _mock_exec(_raw("show_interfaces_status.txt")):
        result = await mcp_ports.call_tool(
            "aos_show_interfaces_status", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    for port in data["ports"]:
        assert re.match(r"^\d+/\d+/\d+$", port["port"]), (
            f"Port '{port['port']}' does not match chassis/slot/port format"
        )


async def test_show_interfaces_status_has_admin_field(mcp_ports):
    """aos_show_interfaces_status: every entry must have an 'admin_status' field."""
    with _mock_exec(_raw("show_interfaces_status.txt")):
        result = await mcp_ports.call_tool(
            "aos_show_interfaces_status", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    for port in data["ports"]:
        assert "admin_status" in port


# ===========================================================================
# ports.py — aos_show_interfaces_alias
# ===========================================================================


async def test_show_interfaces_alias_has_entries(mcp_ports):
    """aos_show_interfaces_alias: ports list must be non-empty."""
    with _mock_exec(_raw("show_interfaces_alias.txt")):
        result = await mcp_ports.call_tool(
            "aos_show_interfaces_alias", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert len(data["ports"]) > 0


async def test_show_interfaces_alias_known_alias(mcp_ports):
    """aos_show_interfaces_alias: port 1/1/11 must have alias 'Test_PortSecu_Cam'."""
    with _mock_exec(_raw("show_interfaces_alias.txt")):
        result = await mcp_ports.call_tool(
            "aos_show_interfaces_alias", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    port_map = {p["port"]: p for p in data["ports"]}
    assert "1/1/11" in port_map
    assert port_map["1/1/11"]["alias"] == "Test_PortSecu_Cam"


async def test_show_interfaces_alias_empty_alias_is_none(mcp_ports):
    """aos_show_interfaces_alias: ports with empty alias string must have alias=None."""
    with _mock_exec(_raw("show_interfaces_alias.txt")):
        result = await mcp_ports.call_tool(
            "aos_show_interfaces_alias", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    # Port 1/1/1 has alias "" in raw_output → should be None after parsing
    port_map = {p["port"]: p for p in data["ports"]}
    if "1/1/1" in port_map:
        assert port_map["1/1/1"]["alias"] is None


# ===========================================================================
# ports.py — aos_show_lldp_remote_system
# ===========================================================================


async def test_show_lldp_remote_system_neighbors(mcp_ports):
    """aos_show_lldp_remote_system: neighbor 'PDF-COEUR-6900-V48C8' must be present."""
    with _mock_exec(_raw("show_lldp_remote_system.txt")):
        result = await mcp_ports.call_tool(
            "aos_show_lldp_remote_system", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    names = {n["system_name"] for n in data["neighbors"] if n.get("system_name")}
    assert "PDF-COEUR-6900-V48C8" in names


async def test_show_lldp_remote_system_every_neighbor_has_local_port(mcp_ports):
    """aos_show_lldp_remote_system: every neighbor entry must reference a local_port."""
    with _mock_exec(_raw("show_lldp_remote_system.txt")):
        result = await mcp_ports.call_tool(
            "aos_show_lldp_remote_system", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    for nbr in data["neighbors"]:
        assert nbr.get("local_port") is not None, (
            f"Neighbor '{nbr.get('system_name')}' has no local_port"
        )


async def test_show_lldp_remote_system_non_empty(mcp_ports):
    """aos_show_lldp_remote_system: neighbors list must be non-empty."""
    with _mock_exec(_raw("show_lldp_remote_system.txt")):
        result = await mcp_ports.call_tool(
            "aos_show_lldp_remote_system", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert len(data["neighbors"]) > 0


# ===========================================================================
# ports.py — aos_show_lldp_port
# ===========================================================================


async def test_show_lldp_port_returns_json_with_output_field(mcp_ports):
    """aos_show_lldp_port: response must be JSON containing a 'neighbors' field."""
    with _mock_exec(_FAKE_LLDP_PORT):
        result = await mcp_ports.call_tool(
            "aos_show_lldp_port", {"host": "192.168.1.1", "port": "1/1/25"}
        )
    data = json.loads(_text(result))
    assert "neighbors" in data
    assert data["neighbors"] is not None


async def test_show_lldp_port_echoes_command(mcp_ports):
    """aos_show_lldp_port: JSON response must echo back the CLI command used."""
    with _mock_exec(_FAKE_LLDP_PORT):
        result = await mcp_ports.call_tool(
            "aos_show_lldp_port", {"host": "192.168.1.1", "port": "1/1/25"}
        )
    data = json.loads(_text(result))
    assert data["command"] == "show lldp port 1/1/25 remote-system"


async def test_show_lldp_port_empty_output_returns_null(mcp_ports):
    """aos_show_lldp_port: empty CLI output must produce an empty neighbors list."""
    with _mock_exec(""):
        result = await mcp_ports.call_tool(
            "aos_show_lldp_port", {"host": "192.168.1.1", "port": "1/1/1"}
        )
    data = json.loads(_text(result))
    assert data["neighbors"] == []


# ===========================================================================
# health.py — Tool registration
# ===========================================================================


async def test_health_tools_all_registered(mcp_health):
    """All health/monitoring tools must appear in list_tools()."""
    tools = {t.name for t in await mcp_health.list_tools()}
    expected = {
        "aos_show_health",
        "aos_show_temp",
        "aos_show_fan",
        "aos_show_mac_learning",
        "aos_show_mac_learning_port",
    }
    assert expected.issubset(tools)


# ===========================================================================
# health.py — aos_show_health
# ===========================================================================


async def test_show_health_cpu_present(mcp_health):
    """aos_show_health: 'CPU' resource must appear in the resources list."""
    with _mock_exec(_raw("show_health.txt")):
        result = await mcp_health.call_tool("aos_show_health", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    resource_names = [r["resource"] for r in data["resources"]]
    assert "CPU" in resource_names


async def test_show_health_memory_present(mcp_health):
    """aos_show_health: 'Memory' resource must appear in the resources list."""
    with _mock_exec(_raw("show_health.txt")):
        result = await mcp_health.call_tool("aos_show_health", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    resource_names = [r["resource"] for r in data["resources"]]
    assert "Memory" in resource_names


async def test_show_health_resource_has_all_percentage_fields(mcp_health):
    """aos_show_health: each resource must have all four percentage fields."""
    with _mock_exec(_raw("show_health.txt")):
        result = await mcp_health.call_tool("aos_show_health", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    required = {"resource", "current_pct", "avg_1min_pct", "avg_1hr_pct", "avg_1day_pct"}
    for resource in data["resources"]:
        assert required.issubset(resource.keys()), (
            f"Resource '{resource.get('resource')}' is missing fields"
        )


# ===========================================================================
# health.py — aos_show_temp
# ===========================================================================


async def test_show_temp_under_threshold(mcp_health):
    """aos_show_temp: first sensor status must be 'UNDER THRESHOLD'."""
    with _mock_exec(_raw("show_temp.txt")):
        result = await mcp_health.call_tool("aos_show_temp", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert len(data["sensors"]) > 0
    assert data["sensors"][0]["status"] == "UNDER THRESHOLD"


async def test_show_temp_sensor_current_temperature(mcp_health):
    """aos_show_temp: 'current_c' must be a positive integer (device is on)."""
    with _mock_exec(_raw("show_temp.txt")):
        result = await mcp_health.call_tool("aos_show_temp", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    for sensor in data["sensors"]:
        assert isinstance(sensor["current_c"], int)
        assert sensor["current_c"] > 0


async def test_show_temp_sensor_has_all_fields(mcp_health):
    """aos_show_temp: each sensor must have device, current_c, thresh_c and status."""
    with _mock_exec(_raw("show_temp.txt")):
        result = await mcp_health.call_tool("aos_show_temp", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    required = {"device", "current_c", "range_min_c", "range_max_c", "danger_c", "thresh_c", "status"}
    for sensor in data["sensors"]:
        assert required.issubset(sensor.keys())


# ===========================================================================
# health.py — aos_show_fan
# ===========================================================================


async def test_show_fan_functional(mcp_health):
    """aos_show_fan: fan must be reported as functional (functional == True)."""
    with _mock_exec(_raw("show_fan.txt")):
        result = await mcp_health.call_tool("aos_show_fan", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert len(data["fans"]) > 0
    assert data["fans"][0]["functional"] is True


async def test_show_fan_entry_has_all_fields(mcp_health):
    """aos_show_fan: each fan entry must have chassis_tray, fan and functional."""
    with _mock_exec(_raw("show_fan.txt")):
        result = await mcp_health.call_tool("aos_show_fan", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    for fan in data["fans"]:
        assert "chassis_tray" in fan
        assert "fan" in fan
        assert "functional" in fan


async def test_show_fan_functional_is_boolean(mcp_health):
    """aos_show_fan: 'functional' field must be a Python bool, not a string."""
    with _mock_exec(_raw("show_fan.txt")):
        result = await mcp_health.call_tool("aos_show_fan", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    for fan in data["fans"]:
        assert isinstance(fan["functional"], bool)


# ===========================================================================
# health.py — aos_show_mac_learning
# ===========================================================================


async def test_show_mac_learning_entries(mcp_health):
    """aos_show_mac_learning: entries list must be non-empty and count must match."""
    with _mock_exec(_raw("show_mac_learning.txt")):
        result = await mcp_health.call_tool(
            "aos_show_mac_learning", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["total_count"] > 0
    assert len(data["entries"]) == data["total_count"]


async def test_show_mac_learning_entry_has_all_fields(mcp_health):
    """aos_show_mac_learning: every entry must have the full set of MAC table fields."""
    with _mock_exec(_raw("show_mac_learning.txt")):
        result = await mcp_health.call_tool(
            "aos_show_mac_learning", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    required = {"domain", "vlan_id", "mac_address", "type", "operation", "interface"}
    for entry in data["entries"]:
        assert required.issubset(entry.keys())


async def test_show_mac_learning_port_filters_by_port(mcp_health):
    """aos_show_mac_learning_port: all returned entries must reference the queried port."""
    with _mock_exec(_FAKE_MAC_LEARNING_PORT):
        result = await mcp_health.call_tool(
            "aos_show_mac_learning_port",
            {"host": "192.168.1.1", "port": "1/1/25"},
        )
    data = json.loads(_text(result))
    assert data["total_count"] == 2
    for entry in data["entries"]:
        assert entry["interface"] == "1/1/25"


async def test_show_mac_learning_port_command_includes_port(mcp_health):
    """aos_show_mac_learning_port: 'command' field must include the port argument."""
    with _mock_exec(_FAKE_MAC_LEARNING_PORT):
        result = await mcp_health.call_tool(
            "aos_show_mac_learning_port",
            {"host": "192.168.1.1", "port": "1/1/25"},
        )
    data = json.loads(_text(result))
    assert "1/1/25" in data["command"]


# ===========================================================================
# Error handling — cross-module tests
# ===========================================================================


async def test_tool_returns_error_string_on_ssh_failure(mcp_core):
    """SSH failure: tool must return the 'ERROR: ...' string, not raise an exception."""
    with _mock_exec("ERROR: OSError: [Errno 111] Connection refused"):
        result = await mcp_core.call_tool("aos_show_system", {"host": "10.0.0.99"})
    assert len(result) > 0
    assert _text(result).startswith("ERROR:")
    # Error string must NOT be valid JSON
    with pytest.raises((json.JSONDecodeError, ValueError)):
        json.loads(_text(result))


async def test_tool_returns_json_on_empty_output(mcp_vlan):
    """Empty SSH output: tool must return valid JSON with an empty vlans list."""
    with _mock_exec(""):
        result = await mcp_vlan.call_tool("aos_show_vlan", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert isinstance(data, dict)
    assert data["vlans"] == []
    assert data["total_count"] == 0


async def test_ssh_permission_denied_passthrough(mcp_vlan):
    """PermissionDenied error: tool must return the error string as-is."""
    with _mock_exec("ERROR: PermissionDenied: Bad password"):
        result = await mcp_vlan.call_tool("aos_show_vlan", {"host": "192.168.1.1"})
    assert _text(result) == "ERROR: PermissionDenied: Bad password"


async def test_ssh_timeout_error_passthrough(mcp_health):
    """ConnectTimeout error: health tool must return the error string as-is."""
    timeout_msg = "ERROR: ConnectTimeout: could not connect to 10.0.0.1 within 10s"
    with _mock_exec(timeout_msg):
        result = await mcp_health.call_tool("aos_show_health", {"host": "10.0.0.1"})
    assert _text(result) == timeout_msg


async def test_ssh_error_passthrough_for_spantree(mcp_spantree):
    """SSHDisconnect error: spantree tool must return the error string as-is."""
    with _mock_exec("ERROR: SSHDisconnect: Connection reset by peer"):
        result = await mcp_spantree.call_tool(
            "aos_show_spantree_cist", {"host": "10.0.0.1"}
        )
    assert _text(result).startswith("ERROR:")


async def test_empty_output_health_returns_empty_resources(mcp_health):
    """Empty SSH output for health: tool must return valid JSON with empty resources."""
    with _mock_exec(""):
        result = await mcp_health.call_tool("aos_show_health", {"host": "192.168.1.1"})
    data = json.loads(_text(result))
    assert data["resources"] == []


async def test_empty_output_vlan_members_returns_empty_list(mcp_vlan):
    """Empty SSH output for vlan_members: tool must return JSON with empty members."""
    with _mock_exec(""):
        result = await mcp_vlan.call_tool(
            "aos_show_vlan_members", {"host": "192.168.1.1"}
        )
    data = json.loads(_text(result))
    assert data["members"] == []
    assert data["total_count"] == 0
