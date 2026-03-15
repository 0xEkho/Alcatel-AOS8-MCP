"""Tests for the PoE reboot approval workflow (poe_approval.py).

Strategy
--------
* ``PENDING_APPROVALS`` is the in-memory store exposed at module level; tests
  manipulate it directly to seed state and verify post-conditions.
* httpx is mocked at ``mcp_server.tools.poe_approval.httpx.AsyncClient`` to
  intercept Teams webhook calls without any real HTTP traffic.
* ``execute_command`` is mocked at ``mcp_server.ssh.client.execute_command``
  (lazy import inside async functions) to avoid SSH connections.
* ``asyncio.sleep`` is mocked at ``mcp_server.tools.poe_approval.asyncio.sleep``
  so PoE disable→enable cycles complete instantly in tests.
* Starlette ``Request`` objects are replaced by ``MagicMock`` instances with
  the expected ``.path_params`` / ``.query_params`` dict attributes.
* Each test asserts a single behaviour; names follow
  ``test_<what>_<context>_<expected>`` conventions.

Environment variables required by the tool are injected via ``monkeypatch``
so they never leak across tests.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

import mcp_server.tools.poe_approval as poe_mod
from mcp_server.tools.poe_approval import (
    PENDING_APPROVALS,
    cleanup_expired_approvals,
    webhook_approve_handler,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_exec(return_value: str = ""):
    """Patch ``execute_command`` to return *return_value* without SSH.

    Patches ``mcp_server.ssh.client.execute_command`` with an ``AsyncMock``
    that immediately returns *return_value*.
    """
    return patch(
        "mcp_server.ssh.client.execute_command",
        new_callable=AsyncMock,
        return_value=return_value,
    )


def _mock_httpx_post(status_code: int = 200, text: str = "1"):
    """Context-manager factory that patches ``httpx.AsyncClient`` in poe_approval.

    The patch replaces ``mcp_server.tools.poe_approval.httpx.AsyncClient``
    so that any ``async with httpx.AsyncClient(...) as client`` block in the
    module uses the mock.  Returns a tuple
    ``(patch_ctx, mock_client_instance)`` so callers can assert on
    ``mock_client.post``.

    Usage::

        with _mock_httpx_post() as (_, mock_client):
            result = await mcp.call_tool("aos_poe_reboot_request", {...})
            mock_client.post.assert_awaited_once()
    """

    class _Ctx:
        def __init__(self):
            self._patch = patch(
                "mcp_server.tools.poe_approval.httpx.AsyncClient"
            )
            self.mock_client = AsyncMock()
            resp = MagicMock()
            resp.status_code = status_code
            resp.text = text
            self.mock_client.post = AsyncMock(return_value=resp)

        def __enter__(self):
            mock_cls = self._patch.__enter__()
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=self.mock_client
            )
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            return mock_cls, self.mock_client

        def __exit__(self, *args):
            return self._patch.__exit__(*args)

    return _Ctx()


def _make_request(
    approval_id: str,
    action: str,
    secret: str,
    approver: str = "TestEngineer",
) -> MagicMock:
    """Build a minimal fake Starlette ``Request`` for webhook tests.

    Args:
        approval_id: UUID used as the ``{uuid}`` path parameter.
        action: ``"approve"`` or ``"reject"`` query parameter.
        secret: Value of the ``secret`` query parameter.
        approver: Display name of the person actioning the request.

    Returns:
        MagicMock mimicking ``starlette.requests.Request``.
    """
    req = MagicMock()
    req.path_params = {"uuid": approval_id}
    req.query_params = {
        "action": action,
        "secret": secret,
        "approver": approver,
    }
    return req


def _pending_entry(
    approval_id: str,
    *,
    minutes_from_now: int = 25,
    status: str = "pending",
) -> dict:
    """Build a minimal approval dict ready to insert into ``PENDING_APPROVALS``.

    Args:
        approval_id: UUID string for this entry.
        minutes_from_now: Positive = future expiry, negative = already expired.
        status: Initial status string (``"pending"`` by default).

    Returns:
        Dict in the format expected by the module.
    """
    now = datetime.now(tz=timezone.utc)
    return {
        "uuid": approval_id,
        "requester": "alice@example.com",
        "switches": ["10.0.0.1"],
        "ports": ["1/1/5"],
        "reason": "IP phone unresponsive",
        "requested_at": now,
        "expires_at": now + timedelta(minutes=minutes_from_now),
        "status": status,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_pending_approvals():
    """Wipe PENDING_APPROVALS before and after every test for isolation.

    The dict is a module-level singleton; without this guard, state from one
    test would bleed into the next.
    """
    PENDING_APPROVALS.clear()
    yield
    PENDING_APPROVALS.clear()


@pytest.fixture
def mcp_with_poe_approval():
    """Fresh FastMCP instance with poe_approval tools registered."""
    instance = FastMCP("test-poe-approval")
    from mcp_server.tools.poe_approval import register_tools
    register_tools(instance)
    return instance


@pytest.fixture
def env_vars(monkeypatch):
    """Inject the three required env variables for aos_poe_reboot_request."""
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://teams.example.com/webhook")
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://mcp.example.com")
    monkeypatch.setenv("WEBHOOK_SECRET", "super-secret-42")


# ---------------------------------------------------------------------------
# 1. test_aos_poe_reboot_request_creates_pending
# ---------------------------------------------------------------------------


async def test_aos_poe_reboot_request_creates_pending(
    mcp_with_poe_approval, env_vars
):
    """A successful aos_poe_reboot_request call must store one 'pending' entry.

    After the tool returns, ``PENDING_APPROVALS`` must contain exactly one
    entry with ``status == "pending"`` that references the supplied switches
    and ports.
    """
    with _mock_httpx_post():
        await mcp_with_poe_approval.call_tool(
            "aos_poe_reboot_request",
            {
                "requester": "Alice (NOC)",
                "switches": ["10.0.0.1"],
                "ports": ["1/1/5"],
                "reason": "IP phone not responding",
            },
        )

    assert len(PENDING_APPROVALS) == 1
    entry = next(iter(PENDING_APPROVALS.values()))
    assert entry["status"] == "pending"
    assert entry["switches"] == ["10.0.0.1"]
    assert entry["ports"] == ["1/1/5"]
    assert entry["requester"] == "Alice (NOC)"


# ---------------------------------------------------------------------------
# 2. test_aos_poe_reboot_request_sends_teams_card
# ---------------------------------------------------------------------------


async def test_aos_poe_reboot_request_sends_teams_card(
    mcp_with_poe_approval, env_vars
):
    """aos_poe_reboot_request must POST an Adaptive Card to the Teams webhook URL.

    The mock httpx client's ``post`` method must be awaited exactly once, and
    the positional argument must be the configured ``TEAMS_WEBHOOK_URL``.
    """
    with _mock_httpx_post() as (_, mock_client):
        result = await mcp_with_poe_approval.call_tool(
            "aos_poe_reboot_request",
            {
                "requester": "Bob (NOC)",
                "switches": ["10.0.0.2"],
                "ports": ["1/1/7"],
                "reason": "AP lost power",
            },
        )

    # Tool must signal success in its return string.
    # result is (list[TextContent], metadata) — pick the first TextContent.
    assert len(result) > 0
    first_text = result[0][0].text
    assert "✅" in first_text or "Approval" in first_text

    # Teams webhook must have been called once with the configured URL
    mock_client.post.assert_awaited_once()
    call_args = mock_client.post.call_args
    posted_url = call_args[0][0] if call_args[0] else call_args[1].get("url")
    assert posted_url == "https://teams.example.com/webhook"


# ---------------------------------------------------------------------------
# 3. test_approve_valid_request
# ---------------------------------------------------------------------------


async def test_approve_valid_request(monkeypatch):
    """Approving a valid pending request must execute PoE and return HTTP 200.

    The webhook handler must:
    - call execute_command (disable then enable) for each (switch, port) pair;
    - return an HTMLResponse with status_code 200;
    - remove the approval from PENDING_APPROVALS.
    """
    approval_id = "aaaaaaaa-0000-0000-0000-000000000001"
    PENDING_APPROVALS[approval_id] = _pending_entry(approval_id)
    monkeypatch.setenv("WEBHOOK_SECRET", "super-secret-42")
    monkeypatch.delenv("TEAMS_WEBHOOK_URL", raising=False)  # skip confirmation

    request = _make_request(approval_id, action="approve", secret="super-secret-42")

    with _mock_exec("") as mock_exec, patch(
        "mcp_server.tools.poe_approval.asyncio.sleep", new_callable=AsyncMock
    ):
        response = await webhook_approve_handler(request)

    assert response.status_code == 200
    assert approval_id not in PENDING_APPROVALS
    # disable + enable = 2 SSH calls per (switch, port) pair → 2 calls total
    assert mock_exec.await_count == 2


# ---------------------------------------------------------------------------
# 4. test_reject_valid_request
# ---------------------------------------------------------------------------


async def test_reject_valid_request(monkeypatch):
    """Rejecting a valid pending request must NOT execute PoE and return 200.

    The webhook handler must:
    - NOT call execute_command (no PoE action on rejection);
    - return an HTMLResponse with status_code 200;
    - remove the approval from PENDING_APPROVALS.
    """
    approval_id = "bbbbbbbb-0000-0000-0000-000000000002"
    PENDING_APPROVALS[approval_id] = _pending_entry(approval_id)
    monkeypatch.setenv("WEBHOOK_SECRET", "super-secret-42")
    monkeypatch.delenv("TEAMS_WEBHOOK_URL", raising=False)

    request = _make_request(approval_id, action="reject", secret="super-secret-42")

    with _mock_exec("") as mock_exec:
        response = await webhook_approve_handler(request)

    assert response.status_code == 200
    assert approval_id not in PENDING_APPROVALS
    # Rejection must never touch SSH
    mock_exec.assert_not_awaited()


# ---------------------------------------------------------------------------
# 5. test_approve_expired_request
# ---------------------------------------------------------------------------


async def test_approve_expired_request(monkeypatch):
    """Approving an already-expired request must return HTTP 404 without PoE.

    ``webhook_approve_handler`` calls ``cleanup_expired_approvals()`` before
    looking up the UUID.  An entry whose ``expires_at`` is in the past is
    purged by that housekeeping call, so the subsequent lookup finds nothing
    and the handler returns HTTP 404 ("Not Found").

    Note: the HTTP 410 guard that lives *after* the lookup is an edge-case
    race-condition path; it is not reachable via normal test execution because
    cleanup always runs first.

    No SSH command must be executed.
    """
    approval_id = "cccccccc-0000-0000-0000-000000000003"
    # minutes_from_now = -1 → expired 1 minute ago
    PENDING_APPROVALS[approval_id] = _pending_entry(
        approval_id, minutes_from_now=-1
    )
    monkeypatch.setenv("WEBHOOK_SECRET", "super-secret-42")

    request = _make_request(approval_id, action="approve", secret="super-secret-42")

    with _mock_exec("") as mock_exec:
        response = await webhook_approve_handler(request)

    # cleanup_expired_approvals() runs first → entry removed → 404
    assert response.status_code == 404
    assert approval_id not in PENDING_APPROVALS
    mock_exec.assert_not_awaited()


# ---------------------------------------------------------------------------
# 6. test_approve_invalid_secret
# ---------------------------------------------------------------------------


async def test_approve_invalid_secret(monkeypatch):
    """A webhook request with a wrong secret must return HTTP 403.

    The secret validation is the first gate in ``webhook_approve_handler``;
    the approval store must remain untouched and no PoE command must run.
    """
    approval_id = "dddddddd-0000-0000-0000-000000000004"
    PENDING_APPROVALS[approval_id] = _pending_entry(approval_id)
    monkeypatch.setenv("WEBHOOK_SECRET", "correct-secret")

    request = _make_request(
        approval_id, action="approve", secret="wrong-secret"
    )

    with _mock_exec("") as mock_exec:
        response = await webhook_approve_handler(request)

    assert response.status_code == 403
    # The approval must still be in the store — nothing was consumed
    assert approval_id in PENDING_APPROVALS
    mock_exec.assert_not_awaited()


# ---------------------------------------------------------------------------
# 7. test_cleanup_expired_approvals
# ---------------------------------------------------------------------------


def test_cleanup_expired_approvals_removes_only_expired():
    """cleanup_expired_approvals must purge stale entries and keep fresh ones.

    Setup: two expired pending entries + one still-valid pending entry.
    Expected: only the two expired ones are removed; the fresh one survives;
    the function return value equals the number of purged entries (2).
    """
    expired_id_1 = "eeeeeeee-0000-0000-0000-000000000005"
    expired_id_2 = "ffffffff-0000-0000-0000-000000000006"
    fresh_id = "11111111-0000-0000-0000-000000000007"

    PENDING_APPROVALS[expired_id_1] = _pending_entry(
        expired_id_1, minutes_from_now=-31
    )
    PENDING_APPROVALS[expired_id_2] = _pending_entry(
        expired_id_2, minutes_from_now=-5
    )
    PENDING_APPROVALS[fresh_id] = _pending_entry(
        fresh_id, minutes_from_now=20
    )

    purged = cleanup_expired_approvals()

    assert purged == 2
    assert expired_id_1 not in PENDING_APPROVALS
    assert expired_id_2 not in PENDING_APPROVALS
    assert fresh_id in PENDING_APPROVALS
    assert PENDING_APPROVALS[fresh_id]["status"] == "pending"
