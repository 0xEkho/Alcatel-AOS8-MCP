"""
AOS8 Spanning Tree tools.

Covers global STP instance summary and CIST (Common and Internal
Spanning Tree) detailed parameters.
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

def _parse_show_spantree(output: str) -> dict:
    """Parse 'show spantree' output.

    Expected format::

        Spanning Tree Path Cost Mode : AUTO
         Msti STP Status Protocol Priority (Prio:SysID)
           0    ON    MSTP   16384 (0x4000:0x0000)

    Args:
        output: Raw CLI text from ``show spantree``.

    Returns:
        Dict with ``path_cost_mode`` string and ``instances`` list.
    """
    result: dict[str, Any] = {"path_cost_mode": None, "instances": []}
    try:
        for line in output.splitlines():
            stripped = line.strip()
            # Path cost mode line
            m = re.match(
                r"Spanning Tree Path Cost Mode\s*:\s*(\S+)", stripped
            )
            if m:
                result["path_cost_mode"] = m.group(1)
                continue
            # Instance table row: "  0    ON    MSTP   16384 (0x4000:0x0000)"
            m = re.match(
                r"^(\d+)\s+(\S+)\s+(\S+)\s+(\d+)\s+\((.+)\)\s*$",
                stripped,
            )
            if m:
                result["instances"].append(
                    {
                        "msti": int(m.group(1)),
                        "status": m.group(2),
                        "protocol": m.group(3),
                        "priority": int(m.group(4)),
                        "priority_hex": m.group(5),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        result["parse_error"] = str(exc)
    return result


def _parse_show_spantree_cist(output: str) -> dict:
    """Parse 'show spantree cist' output.

    Args:
        output: Raw CLI text from ``show spantree cist``.

    Returns:
        Dict with CIST STP parameters.
    """
    result: dict[str, Any] = {
        "status": None,
        "protocol": None,
        "mode": None,
        "priority": None,
        "bridge_id": None,
        "cst_designated_root": None,
        "cost_to_root": None,
        "root_port": None,
        "topology_changes": None,
        "topology_age": None,
        "max_age": None,
        "forward_delay": None,
        "hello_time": None,
    }
    _FIELD_MAP = {
        "Spanning Tree Status": "status",
        "Protocol": "protocol",
        "mode": "mode",
        "Priority": "priority",
        "Bridge ID": "bridge_id",
        "CST Designated Root": "cst_designated_root",
        "Cost to Root Bridge": "cost_to_root",
        "Root Port": "root_port",
        "Topology Changes": "topology_changes",
        "Topology age": "topology_age",
    }
    try:
        for line in output.splitlines():
            stripped = line.strip().rstrip(",")
            # Key : value pattern (AOS8 spantree uses multiple spaces before colon)
            m = re.match(
                r"^([A-Za-z][A-Za-z\s/]+?)\s*:\s{1,}(.+?)(?:,\s*)?$",
                stripped,
            )
            if m:
                key = m.group(1).strip()
                val = m.group(2).strip().rstrip(",").strip()
                if key in _FIELD_MAP:
                    result[_FIELD_MAP[key]] = val if val else None
                # Priority line also contains "(0xNNNN)" – keep only the int
                if key == "Priority":
                    m2 = re.match(r"(\d+)", val)
                    result["priority"] = int(m2.group(1)) if m2 else None
                continue
            # Timer lines use "=" separator:
            # "  Max Age              =    20,"
            # "  Forward Delay        =    15,"
            # "  Hello Time           =     2"
            # Only capture the *current* parameters section (not the system ones)
            m_eq = re.match(
                r"^\s*(Max Age|Forward Delay|Hello Time)\s*=\s*(\d+)", stripped
            )
            if m_eq:
                key_eq = m_eq.group(1)
                val_eq = int(m_eq.group(2))
                if key_eq == "Max Age" and result["max_age"] is None:
                    result["max_age"] = val_eq
                elif key_eq == "Forward Delay" and result["forward_delay"] is None:
                    result["forward_delay"] = val_eq
                elif key_eq == "Hello Time" and result["hello_time"] is None:
                    result["hello_time"] = val_eq
    except Exception as exc:  # noqa: BLE001
        result["parse_error"] = str(exc)
    return result


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 spanning tree tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_spantree(host: str) -> str:
        """Return the Spanning Tree instance summary for an OmniSwitch.

        Runs ``show spantree`` and returns the path cost mode and the
        status, protocol and priority for each MST instance.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with spanning tree summary or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_spantree: host=%s", host)
        output = await execute_command(host, "show spantree")
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_spantree(output)
        return json.dumps(
            {"host": host, "command": "show spantree", **data}, indent=2
        )

    @mcp.tool()
    async def aos_show_spantree_cist(host: str) -> str:
        """Return CIST Spanning Tree parameters for an OmniSwitch.

        Runs ``show spantree cist`` and returns status, protocol, mode,
        bridge ID, designated root, root port, topology change count,
        topology age and timer parameters (max age, forward delay,
        hello time).

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with CIST parameters or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        logger.debug("aos_show_spantree_cist: host=%s", host)
        output = await execute_command(host, "show spantree cist")
        if output.startswith("ERROR:"):
            return output
        data = _parse_show_spantree_cist(output)
        return json.dumps(
            {"host": host, "command": "show spantree cist", **data}, indent=2
        )
