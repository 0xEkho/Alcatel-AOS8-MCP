"""
PoE reboot approval workflow with Microsoft Teams notification.

This module implements a human-in-the-loop approval process before executing
PoE (Power over Ethernet) reboots on AOS8 OmniSwitch ports.

Workflow
--------
1. An LLM calls :func:`aos_poe_reboot_request` (MCP tool) to initiate a request.
2. The tool stores the request with a 30-minute TTL and posts an Adaptive Card
   to Teams via ``TEAMS_WEBHOOK_URL`` containing Approve/Reject buttons.
3. An authorised engineer clicks "Approve" or "Reject" in Teams; the button
   opens ``{MCP_PUBLIC_URL}/webhook/approve/{uuid}?action=approve|reject&secret=…``
   in their browser.
4. The webhook endpoint validates the secret, executes the PoE restarts
   (if approved), posts a confirmation to Teams, and returns an HTML page
   visible in the engineer's browser.

Environment variables
---------------------
``TEAMS_WEBHOOK_URL``   Incoming-webhook URL for the Teams channel.
``MCP_PUBLIC_URL``      Publicly reachable base URL of this MCP server
                        (e.g. ``https://mcp.corp.example.com``).
``WEBHOOK_SECRET``      Shared secret that must appear in the webhook query
                        string; prevents SSRF / replay abuse.
"""
import asyncio
import logging
import os
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory approval store
# ---------------------------------------------------------------------------

#: UUID (str) → approval-request dict.
#: Entries are removed when approved, rejected, or cleaned up after expiry.
PENDING_APPROVALS: dict[str, dict[str, Any]] = {}

_TTL_MINUTES: int = 30


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------


def cleanup_expired_approvals() -> int:
    """Remove pending approvals whose TTL has elapsed from :data:`PENDING_APPROVALS`.

    Only entries with ``status == "pending"`` are considered; already-processed
    entries (approved / rejected) are handled by their respective code paths.

    Returns:
        Number of entries that were purged.
    """
    now = datetime.now(tz=timezone.utc)
    expired_keys = [
        k
        for k, v in PENDING_APPROVALS.items()
        if v["status"] == "pending" and v["expires_at"] <= now
    ]
    for k in expired_keys:
        PENDING_APPROVALS[k]["status"] = "expired"
        del PENDING_APPROVALS[k]
    if expired_keys:
        logger.info(
            "cleanup_expired_approvals: purged %d expired request(s)", len(expired_keys)
        )
    return len(expired_keys)


# ---------------------------------------------------------------------------
# Teams notification helpers
# ---------------------------------------------------------------------------


async def _send_teams_approval_card(
    webhook_url: str,
    approval_id: str,
    requester: str,
    switches: list[str],
    ports: list[str],
    reason: str,
    expires_at: datetime,
    public_url: str,
    webhook_secret: str,
) -> str:
    """Post a Teams MessageCard with Approve / Reject action buttons.

    Uses the legacy ``MessageCard`` format which is supported by all Teams
    incoming-webhook connectors and renders ``OpenUri`` buttons natively.

    Args:
        webhook_url: Teams incoming-webhook URL.
        approval_id: UUID of the approval request.
        requester: Display name of the engineer who initiated the request.
        switches: List of switch IP addresses / hostnames.
        ports: List of port identifiers (e.g. ``["1/1/5", "1/1/6"]``).
        reason: Human-readable justification for the reboot.
        expires_at: Expiry timestamp (UTC-aware).
        public_url: Base URL of this MCP server reachable from Teams.
        webhook_secret: Shared secret appended to the action URLs.

    Returns:
        ``"ok"`` on success, or ``"ERROR: <detail>"`` on failure.
    """
    base = public_url.rstrip("/")
    approve_url = (
        f"{base}/webhook/approve/{approval_id}"
        f"?action=approve&secret={webhook_secret}"
    )
    reject_url = (
        f"{base}/webhook/approve/{approval_id}"
        f"?action=reject&secret={webhook_secret}"
    )

    card: dict[str, Any] = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": "FF8C00",
        "summary": f"PoE reboot request from {requester}",
        "title": "⚡ PoE Reboot Request — approval required",
        "sections": [
            {
                "facts": [
                    {"name": "Requester", "value": requester},
                    {"name": "Switches", "value": ", ".join(switches)},
                    {"name": "Ports", "value": ", ".join(ports)},
                    {"name": "Reason", "value": reason},
                    {
                        "name": "Expires at",
                        "value": expires_at.strftime("%d/%m/%Y %H:%M UTC"),
                    },
                    {"name": "Request ID", "value": f"`{approval_id}`"},
                ],
                "markdown": True,
            }
        ],
        "potentialAction": [
            {
                "@type": "OpenUri",
                "name": "✅ Approve",
                "targets": [{"os": "default", "uri": approve_url}],
            },
            {
                "@type": "OpenUri",
                "name": "❌ Reject",
                "targets": [{"os": "default", "uri": reject_url}],
            },
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=card)
            if resp.status_code not in (200, 201, 202):
                logger.error(
                    "Teams webhook HTTP %d: %.200s", resp.status_code, resp.text
                )
                return (
                    f"ERROR: Teams webhook returned HTTP {resp.status_code}: "
                    f"{resp.text[:200]}"
                )
            return "ok"
    except httpx.TimeoutException as exc:
        logger.error("Teams webhook timeout: %s", exc)
        return f"ERROR: TimeoutException: {exc}"
    except httpx.RequestError as exc:
        logger.error("Teams webhook request error: %s", exc)
        return f"ERROR: RequestError: {exc}"
    except Exception as exc:  # noqa: BLE001
        logger.error("Teams webhook unexpected error: %s", exc, exc_info=True)
        return f"ERROR: {type(exc).__name__}: {exc}"


async def _post_teams_confirmation(
    webhook_url: str,
    approval_id: str,
    action: str,
    approver: str,
    results: list[dict[str, Any]] | None = None,
) -> None:
    """Post a Teams MessageCard confirming that an approval was processed.

    Args:
        webhook_url: Teams incoming-webhook URL.
        approval_id: UUID of the processed approval request.
        action: ``"approved"`` or ``"rejected"``.
        approver: Display name of the person who actioned the request.
        results: Optional list of PoE-restart result dicts (only when approved).
    """
    if action == "approved":
        theme = "00B050"
        title = f"✅ PoE Reboot approved by {approver}"
        status_lines = ""
        if results:
            lines = []
            for r in results:
                status_icon = "✅" if r.get("status") == "success" else "❌"
                lines.append(
                    f"{status_icon} {r.get('host')} — port {r.get('port')}"
                    + (f" ({r.get('detail', '')})" if r.get("status") != "success" else "")
                )
            status_lines = "\n".join(lines)
    else:
        theme = "C00000"
        title = f"❌ PoE Reboot rejected by {approver}"
        status_lines = "No action was taken on any device."

    card: dict[str, Any] = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": theme,
        "summary": title,
        "title": title,
        "sections": [
            {
                "facts": [
                    {"name": "Request ID", "value": f"`{approval_id}`"},
                    {"name": "Actioned by", "value": approver},
                    *([{"name": "Results", "value": status_lines}] if status_lines else []),
                ],
                "markdown": True,
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=card)
            if resp.status_code not in (200, 201, 202):
                logger.warning(
                    "Teams confirmation webhook HTTP %d: %.200s",
                    resp.status_code,
                    resp.text,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Teams confirmation failed: %s", exc)


# ---------------------------------------------------------------------------
# PoE restart execution
# ---------------------------------------------------------------------------


async def _execute_poe_restarts(
    switches: list[str],
    ports: list[str],
) -> list[dict[str, Any]]:
    """Execute PoE restart (disable → 2 s → enable) for every (switch, port) pair.

    Iterates sequentially to avoid overloading switch CLI sessions.

    Args:
        switches: List of switch IP addresses / hostnames.
        ports: List of port identifiers in ``chassis/slot/port`` format.

    Returns:
        List of result dicts, each containing ``host``, ``port``, ``status``
        (``"success"`` or ``"error"``), and optionally ``step`` and ``detail``.
    """
    from mcp_server.ssh.client import execute_command

    results: list[dict[str, Any]] = []

    for host in switches:
        for port in ports:
            logger.info(
                "_execute_poe_restarts: host=%s port=%s — disabling", host, port
            )
            cmd_disable = f"lanpower port {port} admin-state disable"
            out_disable = await execute_command(host, cmd_disable)
            if out_disable.startswith("ERROR:"):
                logger.error(
                    "PoE disable failed on %s port %s: %s", host, port, out_disable
                )
                results.append(
                    {
                        "host": host,
                        "port": port,
                        "status": "error",
                        "step": "disable",
                        "detail": out_disable,
                    }
                )
                continue

            await asyncio.sleep(2)

            logger.info(
                "_execute_poe_restarts: host=%s port=%s — re-enabling", host, port
            )
            cmd_enable = f"lanpower port {port} admin-state enable"
            out_enable = await execute_command(host, cmd_enable)
            if out_enable.startswith("ERROR:"):
                logger.error(
                    "PoE enable failed on %s port %s: %s", host, port, out_enable
                )
                results.append(
                    {
                        "host": host,
                        "port": port,
                        "status": "error",
                        "step": "enable",
                        "detail": out_enable,
                    }
                )
                continue

            results.append({"host": host, "port": port, "status": "success"})
            logger.info(
                "_execute_poe_restarts: host=%s port=%s — success", host, port
            )

    return results


# ---------------------------------------------------------------------------
# HTML response helper
# ---------------------------------------------------------------------------


def _html_page(title: str, message: str, variant: str) -> str:
    """Render a minimal HTML confirmation page.

    Args:
        title: Page heading.
        message: Body text shown to the engineer.
        variant: One of ``"success"``, ``"rejected"``, ``"warning"``,
            ``"error"``.

    Returns:
        Full HTML document as a string.
    """
    palette: dict[str, str] = {
        "success": "#28a745",
        "rejected": "#dc3545",
        "warning": "#e0a800",
        "error": "#dc3545",
    }
    color = palette.get(variant, "#6c757d")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — PoE Approval</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #f0f2f5;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      margin: 0;
      padding: 1rem;
    }}
    .card {{
      background: #fff;
      border-radius: 10px;
      padding: 2.5rem 3rem;
      box-shadow: 0 4px 20px rgba(0,0,0,.1);
      max-width: 520px;
      width: 100%;
      text-align: center;
    }}
    .badge {{
      display: inline-block;
      width: 64px;
      height: 64px;
      border-radius: 50%;
      background: {color};
      margin-bottom: 1rem;
      line-height: 64px;
      font-size: 2rem;
    }}
    h1 {{ color: {color}; font-size: 1.5rem; margin: 0 0 .75rem; }}
    p  {{ color: #495057; line-height: 1.6; margin: 0; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">{"✅" if variant == "success" else "❌" if variant == "rejected" else "⚠️"}</div>
    <h1>{title}</h1>
    <p>{message}</p>
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Webhook HTTP handler (Starlette route — NOT an MCP tool)
# ---------------------------------------------------------------------------


async def webhook_approve_handler(request: Request) -> HTMLResponse:
    """Handle GET /webhook/approve/{uuid} from Teams approval buttons.

    Query parameters
    ----------------
    ``action``   ``approve`` or ``reject`` (required).
    ``secret``   Must match ``WEBHOOK_SECRET`` env var (required).
    ``approver`` Display name of the person actioning the request (optional).

    The endpoint:
    1. Validates ``secret`` against ``WEBHOOK_SECRET``.
    2. Runs :func:`cleanup_expired_approvals`.
    3. Looks up the approval by UUID.
    4. If approving, executes PoE restarts and posts a Teams confirmation.
    5. If rejecting, updates status and posts a Teams confirmation.
    6. Returns an HTML page the engineer sees in their browser.

    Args:
        request: Starlette HTTP request.

    Returns:
        :class:`~starlette.responses.HTMLResponse` with an appropriate
        status code and a human-readable confirmation page.
    """
    approval_id: str = request.path_params.get("uuid", "")
    action: str = request.query_params.get("action", "")
    secret: str = request.query_params.get("secret", "")
    approver: str = request.query_params.get("approver", "unknown")

    # --- Validate WEBHOOK_SECRET -------------------------------------------------
    expected_secret = os.getenv("WEBHOOK_SECRET", "")
    if not expected_secret:
        logger.error("webhook_approve_handler: WEBHOOK_SECRET is not configured")
        return HTMLResponse(
            _html_page(
                "Configuration Error",
                "The server is not properly configured (WEBHOOK_SECRET missing).",
                "error",
            ),
            status_code=500,
        )
    if secret != expected_secret:
        logger.warning(
            "webhook_approve_handler: invalid secret for approval %s", approval_id
        )
        return HTMLResponse(
            _html_page(
                "Access Denied",
                "The provided secret is invalid. Link is invalid or expired.",
                "error",
            ),
            status_code=403,
        )

    # --- Validate action ---------------------------------------------------------
    if action not in ("approve", "reject"):
        return HTMLResponse(
            _html_page(
                "Invalid Parameter",
                "The 'action' parameter must be 'approve' or 'reject'.",
                "error",
            ),
            status_code=400,
        )

    # --- Housekeeping ------------------------------------------------------------
    cleanup_expired_approvals()

    # --- Find approval -----------------------------------------------------------
    if approval_id not in PENDING_APPROVALS:
        logger.warning(
            "webhook_approve_handler: approval %s not found (expired or already processed)",
            approval_id,
        )
        return HTMLResponse(
            _html_page(
                "Request Not Found",
                (
                    f"Request «\u00a0{approval_id}\u00a0» was not found. "
                    "It may have expired or already been processed."
                ),
                "warning",
            ),
            status_code=404,
        )

    approval = PENDING_APPROVALS[approval_id]

    if approval["status"] != "pending":
        return HTMLResponse(
            _html_page(
                "Request Already Processed",
                f"This request already has status: **{approval['status']}**.",
                "warning",
            ),
            status_code=409,
        )

    # Double-check expiry (edge case: arrived just before cleanup ran)
    if approval["expires_at"] <= datetime.now(tz=timezone.utc):
        approval["status"] = "expired"
        del PENDING_APPROVALS[approval_id]
        return HTMLResponse(
            _html_page(
                "Request Expired",
                "This approval request has exceeded its validity period (30 min).",
                "warning",
            ),
            status_code=410,
        )

    webhook_url: str | None = os.getenv("TEAMS_WEBHOOK_URL")

    # --- Handle REJECTION --------------------------------------------------------
    if action == "reject":
        approval["status"] = "rejected"
        del PENDING_APPROVALS[approval_id]
        logger.info(
            "webhook_approve_handler: approval %s rejected by %s",
            approval_id,
            approver,
        )

        if webhook_url:
            await _post_teams_confirmation(webhook_url, approval_id, "rejected", approver)

        return HTMLResponse(
            _html_page(
                "Rejection Confirmed",
                (
                    f"The PoE reboot request has been <strong>rejected</strong> by "
                    f"<strong>{approver}</strong>.<br>No action was taken on any device."
                ),
                "rejected",
            ),
            status_code=200,
        )

    # --- Handle APPROVAL ---------------------------------------------------------
    approval["status"] = "approved"
    logger.info(
        "webhook_approve_handler: approval %s approved by %s — executing PoE restarts "
        "on %d switch(es) / %d port(s)",
        approval_id,
        approver,
        len(approval["switches"]),
        len(approval["ports"]),
    )

    results = await _execute_poe_restarts(approval["switches"], approval["ports"])

    # Remove from pending store after execution
    del PENDING_APPROVALS[approval_id]

    if webhook_url:
        await _post_teams_confirmation(
            webhook_url, approval_id, "approved", approver, results
        )

    success_count = sum(1 for r in results if r.get("status") == "success")
    error_count = len(results) - success_count

    if error_count == 0:
        body = (
            f"The request has been <strong>approved</strong> by <strong>{approver}</strong>.<br>"
            f"All PoE restarts completed successfully ({success_count} port(s))."
        )
        variant = "success"
    else:
        body = (
            f"The request has been <strong>approved</strong> by <strong>{approver}</strong>.<br>"
            f"{success_count} port(s) restarted successfully, "
            f"{error_count} error(s). Check the Teams channel for details."
        )
        variant = "warning"

    return HTMLResponse(
        _html_page("PoE Reboot Approved ✅", body, variant),
        status_code=200,
    )


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register_tools(mcp: FastMCP) -> None:
    """Register the PoE approval workflow tool on the MCP instance.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def aos_poe_reboot_request(
        requester: str,
        switches: list[str],
        ports: list[str],
        reason: str,
    ) -> str:
        """Submit a PoE reboot request that requires Teams approval.

        ⛔ ONLY authorised entry point for PoE reboots — ``aos_poe_restart``
        has been intentionally removed. Any direct PoE reboot attempt
        that bypasses this workflow is blocked by ``_write_guard``.

        Creates a pending approval entry (TTL 30 min) and posts a Teams
        MessageCard with **Approve** / **Reject** buttons to the channel
        configured in ``TEAMS_WEBHOOK_URL``.  The actual PoE restart is only
        executed after an authorised engineer clicks **Approve** in Teams.

        ⚠️  WRITE OPERATION (deferred) — triggering approval will briefly cut
        power to connected devices (IP phones, APs, cameras …).

        _write_guard: this tool has been audited and complies with the WRITE
        rule — it delegates execution to a human approval workflow.

        Args:
            requester: Name or identifier of the person requesting the reboot
                (e.g. ``"Alice Martin (NOC)"``).
            switches: List of OmniSwitch IP addresses or hostnames on which
                to restart PoE (e.g. ``["10.0.0.1", "10.0.0.2"]``).
            ports: List of port identifiers in ``chassis/slot/port`` format
                (e.g. ``["1/1/5", "1/1/6"]``).  All listed ports will be
                restarted on **every** switch in *switches*.
            reason: Human-readable justification for the reboot
                (e.g. ``"IP phone 192.168.1.42 no longer responding"``).

        Returns:
            Confirmation string with the UUID and expiry time on success, or
            ``"ERROR: ..."`` if a required environment variable is missing or
            the Teams notification fails.
        """
        # --- Housekeeping --------------------------------------------------------
        cleanup_expired_approvals()

        # --- Environment validation ----------------------------------------------
        teams_webhook = os.getenv("TEAMS_WEBHOOK_URL")
        if not teams_webhook:
            return (
                "ERROR: env var TEAMS_WEBHOOK_URL is not configured. "
                "Unable to send Teams notification."
            )

        public_url = os.getenv("MCP_PUBLIC_URL")
        if not public_url:
            return (
                "ERROR: env var MCP_PUBLIC_URL is not configured. "
                "Unable to generate approval URLs."
            )

        webhook_secret = os.getenv("WEBHOOK_SECRET")
        if not webhook_secret:
            return (
                "ERROR: env var WEBHOOK_SECRET is not configured. "
                "Unable to secure approval URLs."
            )

        # --- Create approval entry -----------------------------------------------
        approval_id = str(uuid_lib.uuid4())
        now = datetime.now(tz=timezone.utc)
        expires_at = now + timedelta(minutes=_TTL_MINUTES)

        PENDING_APPROVALS[approval_id] = {
            "uuid": approval_id,
            "requester": requester,
            "switches": switches,
            "ports": ports,
            "reason": reason,
            "requested_at": now,
            "expires_at": expires_at,
            "status": "pending",
        }
        logger.info(
            "aos_poe_reboot_request: created approval %s by '%s' — %d switch(es), %d port(s)",
            approval_id,
            requester,
            len(switches),
            len(ports),
        )

        # --- Send Teams card ------------------------------------------------------
        send_result = await _send_teams_approval_card(
            teams_webhook,
            approval_id,
            requester,
            switches,
            ports,
            reason,
            expires_at,
            public_url,
            webhook_secret,
        )

        if send_result.startswith("ERROR:"):
            # Roll back: remove the pending entry so it doesn't linger
            PENDING_APPROVALS.pop(approval_id, None)
            logger.error(
                "aos_poe_reboot_request: Teams notification failed for %s — %s",
                approval_id,
                send_result,
            )
            return (
                f"ERROR: Teams notification failed — {send_result}. "
                "Request has been cancelled."
            )

        return (
            f"✅ Approval request sent to Teams.\n"
            f"\n"
            f"ID            : {approval_id}\n"
            f"Requester     : {requester}\n"
            f"Switches      : {', '.join(switches)}\n"
            f"Ports         : {', '.join(ports)}\n"
            f"Reason        : {reason}\n"
            f"Expires at    : {expires_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"\n"
            f"Awaiting approval in Teams. The operation will be executed\n"
            f"automatically once an engineer clicks Approve."
        )
