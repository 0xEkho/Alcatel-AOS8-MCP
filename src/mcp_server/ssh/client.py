"""
Async SSH client for AOS8 OmniSwitch devices.

Uses asyncssh to open a one-shot SSH connection, execute a single CLI
command, and return the output as a plain string.

Configuration (all via environment variables):

    SSH_STRICT_HOST_KEY   — ``true`` to enforce known_hosts verification
                            (default: ``false``)
    SSH_KNOWN_HOSTS_FILE  — path to the known_hosts file used when
                            strict mode is enabled (default: ``./known_hosts``)
    SSH_CONNECT_TIMEOUT   — TCP/SSH handshake timeout in seconds
                            (default: ``10``)
    SSH_COMMAND_TIMEOUT   — maximum time to wait for command output in
                            seconds (default: ``30``)

Errors are **never raised** — they are returned as a string with the
prefix ``ERROR: <ErrorType>: <message>``.

Logging goes exclusively to ``stderr`` (via the standard ``logging``
module).  No ``print()`` calls target stdout.
"""
import asyncio
import logging
import os
import re

import asyncssh

from mcp_server.ssh.auth import get_credentials

logger = logging.getLogger(__name__)

# Compiled pattern that strips ANSI/VT100 escape sequences from output.
_ANSI_ESCAPE: re.Pattern[str] = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
)


def _strip_ansi(text: str) -> str:
    """Remove ANSI/VT100 escape codes from *text*.

    Args:
        text: Raw terminal output that may contain escape sequences.

    Returns:
        Cleaned string with all ANSI codes removed.
    """
    return _ANSI_ESCAPE.sub("", text)


def _ssh_options() -> dict:
    """Build asyncssh connection options from environment variables.

    Returns:
        Dictionary of keyword arguments suitable for
        :func:`asyncssh.connect`.
    """
    strict = os.getenv("SSH_STRICT_HOST_KEY", "false").strip().lower() == "true"
    known_hosts_file = os.getenv("SSH_KNOWN_HOSTS_FILE", "./known_hosts").strip()

    options: dict = {
        "known_hosts": known_hosts_file if strict else None,
    }

    connect_timeout = int(os.getenv("SSH_CONNECT_TIMEOUT", "10"))
    options["connect_timeout"] = connect_timeout

    return options


async def execute_command(host: str, command: str) -> str:
    """Execute a CLI command on an AOS8 OmniSwitch via SSH.

    Opens a fresh SSH connection for every call (stateless / one-shot),
    executes *command*, then closes the connection.

    All errors (connection refused, authentication failure, timeout, …)
    are caught and returned as a formatted error string so that MCP tool
    callers receive a meaningful message instead of an exception.

    Args:
        host: IP address or hostname of the target OmniSwitch.
        command: CLI command to run (e.g. ``"show system"``).

    Returns:
        Standard output of the command as a string, or
        ``"ERROR: <ErrorType>: <message>"`` on failure.
    """
    username, password = get_credentials(host)
    options = _ssh_options()
    command_timeout = int(os.getenv("SSH_COMMAND_TIMEOUT", "30"))

    logger.debug(
        "SSH execute_command: host=%s user=%s cmd=%r",
        host,
        username,
        command,
    )

    try:
        async with asyncssh.connect(
            host,
            username=username,
            password=password,
            **options,
        ) as conn:
            try:
                result = await asyncio.wait_for(
                    conn.run(command, check=False),
                    timeout=command_timeout,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "Command timeout after %ds on host %s: %r",
                    command_timeout,
                    host,
                    command,
                )
                return (
                    f"ERROR: CommandTimeout: command did not complete within "
                    f"{command_timeout}s on {host}"
                )

        stdout = result.stdout or ""
        stderr_out = result.stderr or ""

        if result.exit_status != 0 and not stdout:
            logger.warning(
                "Command %r on %s exited with status %d — stderr: %s",
                command,
                host,
                result.exit_status,
                stderr_out.strip(),
            )

        output = _strip_ansi(stdout)
        logger.debug("SSH result from %s (%d chars)", host, len(output))
        return output

    except asyncssh.DisconnectError as exc:
        logger.error("SSH disconnect from %s: %s", host, exc)
        return f"ERROR: SSHDisconnect: {exc}"

    except asyncssh.PermissionDenied as exc:
        logger.error("SSH permission denied on %s: %s", host, exc)
        return f"ERROR: PermissionDenied: {exc}"

    except asyncssh.HostKeyNotVerifiable as exc:
        logger.error("SSH host key not verifiable for %s: %s", host, exc)
        return f"ERROR: HostKeyNotVerifiable: {exc}"

    except asyncssh.ConnectionLost as exc:
        logger.error("SSH connection lost to %s: %s", host, exc)
        return f"ERROR: ConnectionLost: {exc}"

    except asyncio.TimeoutError:
        logger.error("SSH connect timeout to %s", host)
        return (
            f"ERROR: ConnectTimeout: could not connect to {host} within "
            f"{options.get('connect_timeout', 10)}s"
        )

    except OSError as exc:
        logger.error("SSH OS error connecting to %s: %s", host, exc)
        return f"ERROR: OSError: {exc}"

    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected SSH error on %s: %s", host, exc, exc_info=True)
        return f"ERROR: {type(exc).__name__}: {exc}"
