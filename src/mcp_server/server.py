"""
MCP Server — main entry point for ALE OmniSwitch AOS8 MCP Server.

Initialises FastMCP, registers all primitives (tools, resources, prompts),
then starts the appropriate transport based on the ``MCP_TRANSPORT``
environment variable.

Supported transports
--------------------
``stdio``
    Default. Suitable for direct LLM process integration (e.g. Claude
    Desktop).  API-key and IP filtering are **not** applicable.
``sse``
    HTTP + Server-Sent Events.  Suitable for web-based MCP clients.
``streamable-http``
    Streamable HTTP transport (recommended for production HTTP deployments).

Security (HTTP transports only)
--------------------------------
When running with ``sse`` or ``streamable-http``:

* If ``MCP_API_KEY`` is set, every request must carry
  ``Authorization: Bearer <MCP_API_KEY>``.
* If ``MCP_ALLOWED_IPS`` is set (comma-separated CIDR list), requests from
  addresses outside the allowlist are rejected with HTTP 403.

The security check is implemented as a **pure ASGI middleware** so that
streaming responses (SSE, chunked HTTP) are never buffered.

Environment variables
---------------------
``MCP_TRANSPORT``          stdio | sse | streamable-http  (default: stdio)
``MCP_SERVER_NAME``        Server display name
``MCP_HOST``               Bind address for HTTP transports (default: 127.0.0.1)
``MCP_PORT``               Bind port for HTTP transports   (default: 8080)
``MCP_API_KEY``            Bearer token required on HTTP requests
``MCP_ALLOWED_IPS``        Comma-separated CIDR allowlist for client IPs
``LOG_LEVEL``              Python log level (default: INFO)
"""
import importlib
import ipaddress
import logging
import os
import sys
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv

# load_dotenv FIRST — sub-modules must see .env values at import time.
load_dotenv()

from mcp.server.fastmcp import FastMCP  # noqa: E402

from mcp_server.prompts.example import register_prompts  # noqa: E402
from mcp_server.resources.example import register_resources  # noqa: E402

# ---------------------------------------------------------------------------
# Logging — stderr ONLY, never stdout (stdout is reserved for STDIO transport)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastMCP instance — host/port are used by HTTP transports
# ---------------------------------------------------------------------------
mcp = FastMCP(
    os.getenv("MCP_SERVER_NAME", "alcatel-aos8-mcp"),
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("MCP_PORT", "8080")),
    json_response=os.getenv("MCP_JSON_RESPONSE", "true").lower() in ("true", "1", "yes"),
)


# ---------------------------------------------------------------------------
# Pure-ASGI security middleware (streaming-safe: no response buffering)
# ---------------------------------------------------------------------------

class _SecurityMiddleware:
    """ASGI middleware enforcing API-key and IP-allowlist checks.

    Implemented as a pure ASGI callable so that streaming responses
    (SSE, chunked HTTP) pass through without any buffering.

    The middleware is a no-op for ASGI ``lifespan`` and ``websocket``
    scope types other than ``http``.

    Args:
        app: The inner ASGI application to wrap.
        api_key: Expected Bearer token value, or empty string to skip check.
        allowed_networks: List of :class:`ipaddress.IPv4Network` /
            :class:`ipaddress.IPv6Network` objects.  Empty list skips the
            IP check.
    """

    def __init__(
        self,
        app: Any,
        api_key: str,
        allowed_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
    ) -> None:
        """Initialise the middleware with security parameters.

        Args:
            app: Inner ASGI application to protect.
            api_key: Expected Bearer token value; empty string disables the check.
            allowed_networks: Permitted client IP networks; empty list disables
                the IP check.
        """
        self.app = app
        self.api_key = api_key
        self.allowed_networks = allowed_networks

    async def __call__(
        self,
        scope: dict,
        receive: Callable,
        send: Callable,
    ) -> None:
        """Handle an ASGI request."""
        # Pass lifespan / websocket scopes straight through unchanged.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # --- IP allowlist check -------------------------------------------
        if self.allowed_networks:
            client = scope.get("client")
            client_host: str | None = client[0] if client else None

            if not client_host:
                logger.warning("Rejected request: no client IP in ASGI scope")
                await self._respond(scope, send, 403, "Forbidden: no client IP")
                return

            try:
                client_ip = ipaddress.ip_address(client_host)
                if not any(client_ip in net for net in self.allowed_networks):
                    logger.warning(
                        "Rejected request from %s: not in MCP_ALLOWED_IPS",
                        client_host,
                    )
                    await self._respond(scope, send, 403, "Forbidden: IP not allowed")
                    return
            except ValueError:
                logger.warning("Rejected request: invalid client IP %r", client_host)
                await self._respond(scope, send, 403, "Forbidden: invalid client IP")
                return

        # --- API-key check ------------------------------------------------
        if self.api_key:
            headers: dict[bytes, bytes] = dict(scope.get("headers", []))
            auth_bytes = headers.get(b"authorization", b"")
            auth_header = auth_bytes.decode("latin-1", errors="replace")

            if not auth_header.startswith("Bearer "):
                logger.warning("Rejected request: missing Bearer token")
                await self._respond(
                    scope, send, 401, "Unauthorized: missing Bearer token"
                )
                return

            token = auth_header[len("Bearer "):].strip()
            if token != self.api_key:
                logger.warning("Rejected request: invalid API key")
                await self._respond(scope, send, 401, "Unauthorized: invalid API key")
                return

        # All checks passed — forward to the inner app.
        await self.app(scope, receive, send)

    @staticmethod
    async def _respond(
        scope: dict,
        send: Callable,
        status: int,
        body: str,
    ) -> None:
        """Send a minimal HTTP error response without invoking the inner app.

        Args:
            scope: ASGI connection scope (unused but kept for signature clarity).
            send: ASGI send callable.
            status: HTTP status code to return.
            body: Plain-text response body.
        """
        encoded = body.encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(encoded)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": encoded, "more_body": False})


def _build_allowed_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse ``MCP_ALLOWED_IPS`` into a list of network objects.

    Invalid CIDR entries are logged and skipped.

    Returns:
        List of network objects (may be empty if the variable is unset or blank).
    """
    raw = os.getenv("MCP_ALLOWED_IPS", "").strip()
    if not raw:
        return []

    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for cidr in raw.split(","):
        cidr = cidr.strip()
        if not cidr:
            continue
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            logger.warning("Invalid CIDR in MCP_ALLOWED_IPS: %r — entry ignored", cidr)

    return networks


def _apply_security(app: Any) -> Any:
    """Wrap *app* with :class:`_SecurityMiddleware` when auth is configured.

    If neither ``MCP_API_KEY`` nor ``MCP_ALLOWED_IPS`` are set the original
    app is returned unchanged (zero overhead).

    Args:
        app: Starlette / ASGI application to protect.

    Returns:
        The original app or a :class:`_SecurityMiddleware`-wrapped version.
    """
    api_key = os.getenv("MCP_API_KEY", "").strip()
    allowed_networks = _build_allowed_networks()

    if not api_key and not allowed_networks:
        logger.debug("No MCP_API_KEY / MCP_ALLOWED_IPS configured — security middleware skipped")
        return app

    logger.info(
        "Security middleware enabled: api_key=%s, allowed_networks=%d entries",
        "yes" if api_key else "no",
        len(allowed_networks),
    )
    return _SecurityMiddleware(app, api_key, allowed_networks)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the MCP server with the transport selected by ``MCP_TRANSPORT``.

    * ``stdio``           → run directly (blocks until stdin closes)
    * ``sse``             → start uvicorn with SSE Starlette app
    * ``streamable-http`` → start uvicorn with Streamable-HTTP Starlette app

    For HTTP transports the Starlette app is optionally wrapped with
    :class:`_SecurityMiddleware` before being handed to uvicorn.
    """
    # --- Register MCP tools --------------------------------------------------
    # Each module is imported individually so that a module still being
    # developed (ImportError) only emits a WARNING and does not abort startup.
    #
    # • example  — legacy tools kept for backward compatibility with existing
    #              tests; remove once Phase 2 coverage is complete.
    # • core     — system identity, firmware, chassis, CMM, running-dir, backup
    # • ports    — port status, counters, configuration
    # • vlan     — VLAN membership, STP port roles, MAC table per VLAN
    # • spantree — Spanning Tree instance and port state
    # • health       — CPU/memory, temperature, fans, MAC learning table
    # • routing      — IP routes, IP interfaces, OSPF, VRF, ARP
    # • poe          — PoE slot status, per-port config, PoE restart (write)
    # • diagnostics  — ping, swlog retrieval
    # • lacp         — link aggregation groups and ports
    # • ntp          — NTP client status and key listing
    # • dhcp         — DHCP relay config and statistics
    # • virtual_chassis — VC topology, consistency, VF-links
    # • cloud_agent  — OmniVista Cloud Agent activation and device state
    # • snmp         — SNMP station table, community-map, security
    # • sflow        — sFlow agent, sampler, poller, receiver
    # • qos          — global QoS switch configuration
    # • unp          — UNP port config, users, profiles, statistics
    # • port_security — port-security global, brief and per-port detail
    _TOOL_MODULES: list[tuple[str, str]] = [
        ("mcp_server.tools.example",         "example"),
        ("mcp_server.tools.core",            "core"),
        ("mcp_server.tools.ports",           "ports"),
        ("mcp_server.tools.vlan",            "vlan"),
        ("mcp_server.tools.spantree",        "spantree"),
        ("mcp_server.tools.health",          "health"),
        ("mcp_server.tools.routing",         "routing"),
        ("mcp_server.tools.poe",             "poe"),
        ("mcp_server.tools.diagnostics",     "diagnostics"),
        ("mcp_server.tools.lacp",            "lacp"),
        ("mcp_server.tools.ntp",             "ntp"),
        ("mcp_server.tools.dhcp",            "dhcp"),
        ("mcp_server.tools.virtual_chassis", "virtual_chassis"),
        ("mcp_server.tools.cloud_agent",     "cloud_agent"),
        ("mcp_server.tools.snmp",            "snmp"),
        ("mcp_server.tools.sflow",           "sflow"),
        ("mcp_server.tools.qos",             "qos"),
        ("mcp_server.tools.unp",             "unp"),
        ("mcp_server.tools.port_security",   "port_security"),
        ("mcp_server.tools.poe_approval",    "poe_approval"),
    ]
    for _mod_path, _mod_name in _TOOL_MODULES:
        try:
            _mod = importlib.import_module(_mod_path)
            _mod.register_tools(mcp)
            logger.debug("Tools registered: %s", _mod_name)
        except ImportError:
            logger.warning(
                "Tool module %r not found — skipping registration", _mod_path
            )

    # --- Register MCP resources and prompts ----------------------------------
    register_resources(mcp)
    register_prompts(mcp)

    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    logger.info("Starting MCP server (transport=%s) …", transport)

    if transport == "stdio":
        # STDIO transport: security middleware does not apply.
        mcp.run(transport="stdio")
        return

    if transport not in ("sse", "streamable-http"):
        logger.error(
            "Unknown MCP_TRANSPORT=%r — expected stdio, sse or streamable-http",
            transport,
        )
        sys.exit(1)

    # HTTP transports: build Starlette app, apply security, serve via uvicorn.
    import anyio
    import uvicorn

    async def _serve() -> None:
        if transport == "sse":
            mcp_app = mcp.sse_app()
        else:
            mcp_app = mcp.streamable_http_app()

        secured_app = _apply_security(mcp_app)

        config = uvicorn.Config(
            secured_app,
            host=mcp.settings.host,
            port=mcp.settings.port,
            log_level=os.getenv("LOG_LEVEL", "info").lower(),
        )
        server = uvicorn.Server(config)
        logger.info(
            "Uvicorn listening on %s:%d (transport=%s)",
            mcp.settings.host,
            mcp.settings.port,
            transport,
        )
        await server.serve()

    anyio.run(_serve)


if __name__ == "__main__":
    main()
