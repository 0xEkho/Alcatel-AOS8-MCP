"""
AOS8 network diagnostics tools.

Covers on-device ping and system log (swlog) retrieval.

Note on ``show log swlog``
--------------------------
This command can produce very large output and may time out on busy
switches.  The tool uses a reduced command timeout of 15 seconds and
returns whatever partial output was captured before the timeout, with
an explicit warning in the response.
"""
import json
import logging
import os
import re
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _parse_ping(target: str, output: str) -> dict:
    """Parse AOS8 ``ping`` command output.

    Expected format::

        PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
        --- 8.8.8.8 ping statistics ---
        3 packets transmitted, 0 received, 100% packet loss, time 2037ms

    Args:
        target: The IP/hostname that was pinged.
        output: Raw CLI text from the ping command.

    Returns:
        Dict with ``target``, ``packets_transmitted``,
        ``packets_received``, ``packet_loss_pct``, ``time_ms`` and
        ``success``.
    """
    result: dict[str, Any] = {
        "target": target,
        "packets_transmitted": None,
        "packets_received": None,
        "packet_loss_pct": None,
        "time_ms": None,
        "success": False,
    }

    try:
        # "3 packets transmitted, 0 received, 100% packet loss, time 2037ms"
        m_stats = re.search(
            r"(\d+)\s+packets?\s+transmitted,\s+(\d+)\s+received,\s+([\d.]+)%\s+packet\s+loss(?:,\s+time\s+(\d+)ms)?",
            output,
            re.IGNORECASE,
        )
        if m_stats:
            tx = int(m_stats.group(1))
            rx = int(m_stats.group(2))
            loss = float(m_stats.group(3))
            time_ms = int(m_stats.group(4)) if m_stats.group(4) else None
            result.update(
                {
                    "packets_transmitted": tx,
                    "packets_received": rx,
                    "packet_loss_pct": loss,
                    "time_ms": time_ms,
                    "success": rx > 0,
                }
            )

    except Exception as exc:  # noqa: BLE001
        result["parse_error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_tools(mcp: FastMCP) -> None:
    """Register all AOS8 diagnostics tools on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_ping(host: str, target: str, count: int = 3) -> str:
        """Run a ping from an OmniSwitch to a target IP address or hostname.

        Executes ``ping <target> count <count>`` on the switch and returns
        packet statistics: transmitted, received, loss percentage, round-
        trip time and a boolean ``success`` flag.

        Args:
            host: IP address or hostname of the OmniSwitch that will
                originate the ping.
            target: Destination IP address or hostname to ping.
            count: Number of ICMP echo requests to send (default: 3).

        Returns:
            JSON string with ping statistics, or ``"ERROR: ..."`` string
            on failure.
        """
        from mcp_server.ssh.client import execute_command

        cmd = f"ping {target} count {count}"
        logger.debug("aos_ping: host=%s target=%s count=%d", host, target, count)
        output = await execute_command(host, cmd)
        if output.startswith("ERROR:"):
            return output
        data = _parse_ping(target, output)
        return json.dumps({"host": host, "command": cmd, **data}, indent=2)

    @mcp.tool()
    async def aos_show_log_swlog(host: str) -> str:
        """Return the system log (swlog) from an OmniSwitch.

        Runs ``show log swlog`` with a reduced timeout of 15 seconds
        because this command can generate very large output on busy
        switches.  If the command times out the response will contain
        whatever partial data was captured along with a
        ``"timeout_warning"`` field.

        The log content is returned as raw text in the ``"logs"`` field
        (not further parsed) to preserve all log detail for the caller.

        Args:
            host: IP address or hostname of the OmniSwitch.

        Returns:
            JSON string with ``"logs"`` (raw text) and optionally
            ``"timeout_warning"``, or ``"ERROR: ..."`` string on
            connection failure.
        """
        import asyncio

        import asyncssh

        from mcp_server.ssh.auth import get_credentials
        from mcp_server.ssh.client import _ssh_options  # noqa: PLC2701

        cmd = "show log swlog"
        swlog_timeout = 15  # seconds — reduced vs default 30s

        logger.debug("aos_show_log_swlog: host=%s (timeout=%ds)", host, swlog_timeout)

        username, password = get_credentials(host)
        options = _ssh_options()
        timeout_warning: str | None = None
        logs = ""

        try:
            async with asyncssh.connect(
                host,
                username=username,
                password=password,
                **options,
            ) as conn:
                try:
                    result = await asyncio.wait_for(
                        conn.run(cmd, check=False),
                        timeout=swlog_timeout,
                    )
                    logs = result.stdout or ""
                except asyncio.TimeoutError:
                    timeout_warning = (
                        f"Command did not complete within {swlog_timeout}s; "
                        "output may be partial."
                    )
                    logger.warning(
                        "aos_show_log_swlog: timeout after %ds on %s",
                        swlog_timeout,
                        host,
                    )

        except asyncssh.DisconnectError as exc:
            return f"ERROR: SSHDisconnect: {exc}"
        except asyncssh.PermissionDenied as exc:
            return f"ERROR: PermissionDenied: {exc}"
        except asyncssh.ConnectionLost as exc:
            return f"ERROR: ConnectionLost: {exc}"
        except asyncio.TimeoutError:
            return (
                f"ERROR: ConnectTimeout: could not connect to {host} within "
                f"{options.get('connect_timeout', 10)}s"
            )
        except OSError as exc:
            return f"ERROR: OSError: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {type(exc).__name__}: {exc}"

        payload: dict[str, Any] = {
            "host": host,
            "command": cmd,
            "logs": logs,
        }
        if timeout_warning:
            payload["timeout_warning"] = timeout_warning

        return json.dumps(payload, indent=2)
