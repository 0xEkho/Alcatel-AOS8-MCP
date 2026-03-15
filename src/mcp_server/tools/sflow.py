"""
AOS8 sFlow tools.

Covers sFlow agent identity, sampler, poller and receiver configuration.
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

def _parse_sflow_agent(output: str) -> dict:
    """Parse ``show sflow agent`` output.

    Expected format::

         Agent Version  = 1.0; ALE; 6.1.1
         Agent IP       = 10.1.0.1

    Args:
        output: Raw CLI text from ``show sflow agent``.

    Returns:
        Dict with ``agent_version``, ``vendor``, ``version_detail`` and
        ``agent_ip``.
    """
    result: dict[str, Any] = {}
    try:
        for line in output.splitlines():
            stripped = line.strip()

            # "Agent Version  = 1.0; ALE; 6.1.1"
            m_ver = re.match(r"^Agent\s+Version\s*=\s*(.+)$", stripped, re.IGNORECASE)
            if m_ver:
                raw = m_ver.group(1).strip()
                parts = [p.strip() for p in raw.split(";")]
                result["agent_version"] = parts[0] if parts else raw
                result["vendor"] = parts[1] if len(parts) > 1 else ""
                result["version_detail"] = parts[2] if len(parts) > 2 else ""
                continue

            # "Agent IP       = 10.1.0.1"
            m_ip = re.match(r"^Agent\s+IP\s*=\s*(\S+)$", stripped, re.IGNORECASE)
            if m_ip:
                result["agent_ip"] = m_ip.group(1)
    except Exception as exc:  # noqa: BLE001
        return {**result, "parse_error": str(exc)}
    return result


def _parse_sflow_sampler(output: str) -> dict:
    """Parse ``show sflow sampler`` output.

    Expected format::

        Instance  Interface  Receiver   Rate     Sample-Header-Size
        --------+----------+----------+--------+--------------------
           1       1/1/1          1        128          128

    Args:
        output: Raw CLI text from ``show sflow sampler``.

    Returns:
        Dict with ``samplers`` list and ``total_count`` integer.
    """
    samplers: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            stripped = line.strip()
            # Skip headers and separators
            if (
                not stripped
                or stripped.lower().startswith("instance")
                or re.match(r"^[-+\s]+$", stripped)
            ):
                continue
            # Data line: "   1       1/1/1          1        128          128"
            m = re.match(
                r"^(\d+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$",
                stripped,
            )
            if m:
                samplers.append(
                    {
                        "instance": int(m.group(1)),
                        "interface": m.group(2),
                        "receiver": int(m.group(3)),
                        "rate": int(m.group(4)),
                        "sample_header_size": int(m.group(5)),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return {"samplers": samplers, "total_count": len(samplers), "parse_error": str(exc)}
    return {"samplers": samplers, "total_count": len(samplers)}


def _parse_sflow_poller(output: str) -> dict:
    """Parse ``show sflow poller`` output.

    Returns an empty list when no pollers are configured.

    Args:
        output: Raw CLI text from ``show sflow poller``.

    Returns:
        Dict with ``pollers`` list and ``total_count`` integer.
    """
    pollers: list[dict[str, Any]] = []
    try:
        for line in output.splitlines():
            stripped = line.strip()
            if (
                not stripped
                or stripped.lower().startswith("instance")
                or stripped.lower().startswith("poller")
                or re.match(r"^[-+\s]+$", stripped)
            ):
                continue
            # Generic data line — columns: instance, interface, receiver, interval
            m = re.match(
                r"^(\d+)\s+(\S+)\s+(\d+)\s+(\d+)\s*$",
                stripped,
            )
            if m:
                pollers.append(
                    {
                        "instance": int(m.group(1)),
                        "interface": m.group(2),
                        "receiver": int(m.group(3)),
                        "interval": int(m.group(4)),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return {"pollers": pollers, "total_count": len(pollers), "parse_error": str(exc)}
    return {"pollers": pollers, "total_count": len(pollers)}


def _parse_sflow_receiver(output: str) -> dict:
    """Parse ``show sflow receiver`` output.

    Expected format::

         Receiver 1
         Name       = sflowCollector
         Address    = IP_V4  203.0.113.50
         UDP Port   = 6343
         Timeout    = No Timeout
         Packet Size= 1400
         DatagramVer= 5

    Multiple receiver blocks may appear; each starts with ``Receiver <id>``.

    Args:
        output: Raw CLI text from ``show sflow receiver``.

    Returns:
        Dict with ``receivers`` list.
    """
    receivers: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    try:
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            # New receiver block: "Receiver 1"
            m_hdr = re.match(r"^Receiver\s+(\d+)\s*$", stripped, re.IGNORECASE)
            if m_hdr:
                if current is not None:
                    receivers.append(current)
                current = {"id": int(m_hdr.group(1))}
                continue

            if current is None:
                continue

            # Key = value lines inside a receiver block
            m_kv = re.match(r"^([^=]+?)\s*=\s*(.+)$", stripped)
            if not m_kv:
                continue
            key_raw = m_kv.group(1).strip().lower()
            val_raw = m_kv.group(2).strip()

            if key_raw == "name":
                current["name"] = val_raw
            elif key_raw == "address":
                # "IP_V4  203.0.113.50"
                parts = val_raw.split()
                current["address_type"] = parts[0] if parts else val_raw
                current["address"] = parts[1] if len(parts) > 1 else ""
            elif key_raw == "udp port":
                current["udp_port"] = int(val_raw) if val_raw.isdigit() else val_raw
            elif key_raw == "timeout":
                current["timeout"] = val_raw
            elif key_raw == "packet size":
                current["packet_size"] = int(val_raw) if val_raw.isdigit() else val_raw
            elif key_raw == "datagramver":
                current["datagram_version"] = int(val_raw) if val_raw.isdigit() else val_raw
            else:
                norm = re.sub(r"[^a-z0-9]+", "_", key_raw).strip("_")
                current[norm] = val_raw

        if current is not None:
            receivers.append(current)
    except Exception as exc:  # noqa: BLE001
        return {"receivers": receivers, "parse_error": str(exc)}
    return {"receivers": receivers}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 sFlow tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_show_sflow_agent(host: str) -> str:
        """Return sFlow agent identity and source IP for an OmniSwitch.

        Runs ``show sflow agent`` and returns the agent version, vendor,
        detailed version string and agent source IP address used in sFlow
        datagrams.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with sFlow agent data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show sflow agent"
        logger.debug("aos_show_sflow_agent: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_sflow_agent(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_sflow_sampler(host: str) -> str:
        """Return sFlow sampler configuration for an OmniSwitch.

        Runs ``show sflow sampler`` and returns per-interface sampling
        configuration including instance, receiver index, sampling rate
        and sample header size.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with sFlow sampler data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show sflow sampler"
        logger.debug("aos_show_sflow_sampler: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_sflow_sampler(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_sflow_poller(host: str) -> str:
        """Return sFlow poller (counter sampling) configuration for an OmniSwitch.

        Runs ``show sflow poller`` and returns per-interface polling
        configuration.  Returns an empty list when no pollers are configured.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with sFlow poller data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show sflow poller"
        logger.debug("aos_show_sflow_poller: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_sflow_poller(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_sflow_receiver(host: str) -> str:
        """Return sFlow receiver (collector) configuration for an OmniSwitch.

        Runs ``show sflow receiver`` and returns each receiver's ID, name,
        collector address and type, UDP port, timeout, packet size and
        datagram version.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with sFlow receiver data or ``"ERROR: ..."`` string.
        """
        from mcp_server.ssh.client import execute_command

        cmd = "show sflow receiver"
        logger.debug("aos_show_sflow_receiver: host=%s", host)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_sflow_receiver(output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)
