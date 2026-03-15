"""
Tests for SSH authentication (auth.py) and SSH client (client.py).

auth.py  — get_credentials(host) → (username, password)
           Resolution order: zone-specific (10.X.*.*) → global fallback
           Never raises, returns empty strings when env vars are absent.

client.py — execute_command(host, command) → str
            One-shot asyncssh connection, ANSI-stripped stdout.
            All errors returned as "ERROR: <Type>: <message>" strings.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_server.ssh.auth import get_credentials
from mcp_server.ssh.client import execute_command


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_asyncssh_context_manager(mock_conn: AsyncMock) -> MagicMock:
    """Return a fake asyncssh.connect() result usable as an async context manager.

    asyncssh.connect() is called as ``async with asyncssh.connect(...) as conn``.
    Python evaluates asyncssh.connect(...) first (gets the context manager object),
    then calls __aenter__ to receive the connection.  Mocking the return value of
    the patched connect() with an object that has AsyncMock __aenter__/__aexit__
    satisfies that protocol without any real network activity.
    """
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm


def _make_run_result(
    stdout: str = "",
    stderr: str = "",
    exit_status: int = 0,
) -> MagicMock:
    """Build a fake asyncssh SSHCompletedProcess-like result."""
    result = MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    result.exit_status = exit_status
    return result


# ──────────────────────────────────────────────────────────────────────────────
# auth.py — get_credentials()
# ──────────────────────────────────────────────────────────────────────────────

def test_get_credentials_global(monkeypatch):
    """Global credentials are returned for any host when no zone vars are set.

    AOS_GLOBAL_USERNAME / AOS_GLOBAL_PASSWORD must be returned as-is when the
    host is not in a 10.X.*.* subnet (or when zone-specific vars are absent).
    """
    monkeypatch.setenv("AOS_GLOBAL_USERNAME", "admin")
    monkeypatch.setenv("AOS_GLOBAL_PASSWORD", "s3cr3t")
    # Ensure no accidental zone-1 variables leak in from the environment
    monkeypatch.delenv("AOS_ZONE1_USERNAME", raising=False)
    monkeypatch.delenv("AOS_ZONE1_PASSWORD", raising=False)

    username, password = get_credentials("172.16.0.1")

    assert username == "admin"
    assert password == "s3cr3t"


def test_get_credentials_zone_fallback(monkeypatch):
    """Zone-2 credentials are preferred for a 10.2.x.x host when configured.

    The second octet of the host IP selects the zone index.
    10.2.5.100 → zone 2 → AOS_ZONE2_USERNAME / AOS_ZONE2_PASSWORD.
    """
    monkeypatch.setenv("AOS_GLOBAL_USERNAME", "global_admin")
    monkeypatch.setenv("AOS_GLOBAL_PASSWORD", "global_pass")
    monkeypatch.setenv("AOS_ZONE2_USERNAME", "zone2_admin")
    monkeypatch.setenv("AOS_ZONE2_PASSWORD", "zone2_pass")

    username, password = get_credentials("10.2.5.100")

    assert username == "zone2_admin"
    assert password == "zone2_pass"


def test_get_credentials_no_zone_fallback(monkeypatch):
    """Global credentials are used when the host is not in a 10.X.*.* subnet.

    192.168.1.1 is not a 10.x address, so no zone lookup is performed and
    the function must return the global credentials directly.
    """
    monkeypatch.setenv("AOS_GLOBAL_USERNAME", "global_admin")
    monkeypatch.setenv("AOS_GLOBAL_PASSWORD", "global_pass")
    # Even if zone-1 vars exist they must NOT be selected for this host
    monkeypatch.setenv("AOS_ZONE1_USERNAME", "zone1_admin")
    monkeypatch.setenv("AOS_ZONE1_PASSWORD", "zone1_pass")

    username, password = get_credentials("192.168.1.1")

    assert username == "global_admin"
    assert password == "global_pass"


def test_get_credentials_zone_not_configured(monkeypatch):
    """Falls back to global credentials when zone env vars are absent.

    When the host is in 10.2.*.* but AOS_ZONE2_USERNAME is not set (or is
    an empty string), the function must silently fall back to the global
    credentials — no exception raised.
    """
    monkeypatch.setenv("AOS_GLOBAL_USERNAME", "global_admin")
    monkeypatch.setenv("AOS_GLOBAL_PASSWORD", "global_pass")
    # Zone-2 variables intentionally absent
    monkeypatch.delenv("AOS_ZONE2_USERNAME", raising=False)
    monkeypatch.delenv("AOS_ZONE2_PASSWORD", raising=False)

    username, password = get_credentials("10.2.5.100")

    assert username == "global_admin"
    assert password == "global_pass"


# ──────────────────────────────────────────────────────────────────────────────
# client.py — execute_command()
# ──────────────────────────────────────────────────────────────────────────────

async def test_execute_command_success(monkeypatch):
    """Successful SSH command returns the stdout of the remote command.

    asyncssh.connect() is mocked to avoid any real network activity.
    The mock connection's run() method returns a fake result whose stdout
    must be propagated back verbatim (minus ANSI codes, which are absent here).
    """
    monkeypatch.setenv("AOS_GLOBAL_USERNAME", "admin")
    monkeypatch.setenv("AOS_GLOBAL_PASSWORD", "pass")
    monkeypatch.setenv("SSH_CONNECT_TIMEOUT", "10")
    monkeypatch.setenv("SSH_COMMAND_TIMEOUT", "30")
    monkeypatch.setenv("SSH_STRICT_HOST_KEY", "false")

    expected_output = "AOS 8.9.0 – OmniSwitch 6900\n"

    mock_conn = AsyncMock()
    mock_conn.run = AsyncMock(return_value=_make_run_result(stdout=expected_output))

    with patch("mcp_server.ssh.client.asyncssh.connect") as mock_connect:
        mock_connect.return_value = _make_asyncssh_context_manager(mock_conn)

        result = await execute_command("192.168.1.1", "show system")

    assert result == expected_output
    # Verify the command was forwarded to the connection unchanged
    mock_conn.run.assert_awaited_once_with("show system", check=False)


async def test_execute_command_ssh_error(monkeypatch):
    """An SSH connection error is caught and returned as an ERROR: prefixed string.

    asyncssh.connect() is made to raise an OSError (e.g. "Connection refused").
    execute_command() must never propagate the exception — instead it returns a
    string starting with "ERROR:" that includes both the error type and message.
    """
    monkeypatch.setenv("AOS_GLOBAL_USERNAME", "admin")
    monkeypatch.setenv("AOS_GLOBAL_PASSWORD", "pass")
    monkeypatch.setenv("SSH_CONNECT_TIMEOUT", "10")
    monkeypatch.setenv("SSH_STRICT_HOST_KEY", "false")

    with patch("mcp_server.ssh.client.asyncssh.connect") as mock_connect:
        mock_connect.side_effect = OSError("Connection refused")

        result = await execute_command("192.168.1.1", "show system")

    assert result.startswith("ERROR:")
    assert "OSError" in result
    assert "Connection refused" in result


async def test_execute_command_strips_ansi(monkeypatch):
    """ANSI/VT100 escape codes present in stdout are removed from the output.

    AOS8 devices sometimes emit colour codes in their CLI output.
    execute_command() must return a clean plain-text string.
    """
    monkeypatch.setenv("AOS_GLOBAL_USERNAME", "admin")
    monkeypatch.setenv("AOS_GLOBAL_PASSWORD", "pass")
    monkeypatch.setenv("SSH_CONNECT_TIMEOUT", "10")
    monkeypatch.setenv("SSH_COMMAND_TIMEOUT", "30")
    monkeypatch.setenv("SSH_STRICT_HOST_KEY", "false")

    # Raw terminal output with SGR colour sequences (bold green + reset)
    raw_output = "\x1b[1;32mOmniSwitch\x1b[0m 6900 ready"
    clean_output = "OmniSwitch 6900 ready"

    mock_conn = AsyncMock()
    mock_conn.run = AsyncMock(return_value=_make_run_result(stdout=raw_output))

    with patch("mcp_server.ssh.client.asyncssh.connect") as mock_connect:
        mock_connect.return_value = _make_asyncssh_context_manager(mock_conn)

        result = await execute_command("192.168.1.1", "show chassis")

    assert result == clean_output
    # Belt-and-suspenders: confirm the raw escape byte is truly gone
    assert "\x1b" not in result
