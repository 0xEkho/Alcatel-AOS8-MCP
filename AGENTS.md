# AGENTS.md — ALE OmniSwitch AOS8 MCP Server

> **MANDATORY RULE**: For **every prompt** in this project, Copilot must invoke
> **all 4 agents in parallel**, without exception. Each agent audits and acts on its own domain.
> Never implement directly without going through the agents.

This file describes the Copilot agents available for this project and their collaboration rules.

## Project Overview

This repo is an **MCP (Model Context Protocol) server for Alcatel-Lucent Enterprise OmniSwitch AOS8** network devices.
- Stack: Python ≥3.10 (recommended runtime: 3.12), `uv`, `FastMCP` (mcp>=1.2.0), `asyncssh`
- Transport: `streamable-http` (default), `sse`, or `stdio` — set via `MCP_TRANSPORT`
- Security: Bearer token (`MCP_API_KEY`) + IP allowlist (`MCP_ALLOWED_IPS`) via pure ASGI middleware
- Structure: `src/mcp_server/{server.py, tools/, resources/, prompts/, ssh/}` + `tests/`
- Version: `1.1.0` — see `pyproject.toml`

### Key architectural modules (v1.1)

| Module | Path | Role |
|--------|------|------|
| `poe_approval` | `src/mcp_server/tools/poe_approval.py` | Human-in-the-loop PoE reboot via Teams (`aos_poe_reboot_request` tool + `/webhook/approve` endpoint) |
| `_write_guard` | `src/mcp_server/tools/_write_guard.py` | Architectural contract — blocks any unapproved WRITE tool with a standardised error message |

### WRITE operation policy (non-negotiable)

Any tool that **modifies switch configuration** (WRITE) **must** go through a human approval workflow.
Direct execution of configuration commands without prior human validation is **forbidden**.

- `aos_poe_reboot_request` (in `poe_approval.py`) is the **reference implementation**: it posts a Teams card with Approve/Reject buttons, stores the request with a 30-minute TTL, and only executes after human click.
- `aos_poe_restart` has been **intentionally removed** and replaced by `aos_poe_reboot_request`.
- `write_guard(tool_name)` (in `_write_guard.py`) is the **safety net**: call it at the top of any WRITE tool that does NOT have an approval workflow to return a standard blocked-operation message.

Required environment variables for the Teams approval workflow:

| Variable | Description |
|----------|-------------|
| `TEAMS_WEBHOOK_URL` | Incoming Webhook URL for the Teams channel |
| `WEBHOOK_SECRET` | Shared secret validating every `/webhook/approve` callback |
| `MCP_PUBLIC_URL` | Publicly reachable base URL of the MCP server (used in card buttons) |

## Agents

| Agent | File | Responsibility |
|-------|------|----------------|
| `mcp-scaffolder` | `.github/agents/mcp-scaffolder.agent.md` | Project config (`pyproject.toml`, `.gitignore`, `.env.example`) |
| `mcp-developer` | `.github/agents/mcp-developer.agent.md` | Source code: AOS8 tools, SSH client, resources, prompts |
| `mcp-tester` | `.github/agents/mcp-tester.agent.md` | pytest-asyncio test suite — never modifies `src/` |
| `mcp-documenter` | `.github/agents/mcp-documenter.agent.md` | `README.md`, docstrings, `AGENTS.md` |

## Golden Rule: invoke all 4 agents in parallel on every prompt

```
Every prompt → mcp-scaffolder + mcp-developer + mcp-tester + mcp-documenter (in parallel)
```

Each agent checks its domain even if the task does not directly concern it.
If nothing to do → the agent replies "N/A" but **must be invoked**.

## Workflow for a new AOS8 feature

1. **mcp-scaffolder**: add the dependency to `pyproject.toml` if needed
2. **mcp-developer**: implement the tool in `src/mcp_server/tools/` + SSH call via `src/mcp_server/ssh/`
3. **mcp-tester**: write corresponding tests in `tests/`
4. **mcp-documenter**: update `README.md` and verify docstrings

## MCP Best Practices — non-negotiable rules

1. ⛔ **Never `print()` to stdout** for STDIO transport — use `logging` to stderr exclusively
2. ⛔ **Never raise exceptions** from a tool to signal a business error → return a JSON error payload
3. ✅ **Type hints** on all tool parameters → JSON schema generated automatically by FastMCP
4. ✅ **Docstrings** on every primitive (tool, resource, prompt) → MCP description generated automatically
5. ✅ **Environment variables** for all secrets (`.env`, never hardcoded)
6. ✅ **Test with MCP Inspector** before integrating in a client: `npx @modelcontextprotocol/inspector uv run mcp-server`

## Reference Commands

```bash
uv sync                                  # install dependencies
uv run mcp-server                        # start the server (streamable-http by default)
MCP_TRANSPORT=stdio uv run mcp-server    # stdio mode for Claude Desktop
uv run pytest                            # run all tests
uv run pytest --cov=mcp_server           # with coverage report
npx @modelcontextprotocol/inspector uv run mcp-server  # MCP Inspector
```

---

## Canonical Tool Registry

> ⚠️ **Always read this list before writing any script that calls MCP tools. Never guess tool names.**
>
> This is the **single source of truth** for all registered tools. It is extracted directly from the source
> code and must stay in sync with `src/mcp_server/tools/`. If you add a new tool, **update this section
> immediately** as part of the same PR/commit — before the code is merged.

58 tools are currently registered (alphabetical order):

| # | Tool name | Signature |
|---|-----------|-----------|
| 1 | `aos_config_backup` | `aos_config_backup(host: str) -> str` |
| 2 | `aos_ping` | `aos_ping(host: str, target: str, count: int = 3) -> str` |
| 3 | `aos_show_arp` | `aos_show_arp(host: str) -> str` |
| 4 | `aos_show_chassis` | `aos_show_chassis(host: str) -> str` |
| 5 | `aos_show_cloud_agent_status` | `aos_show_cloud_agent_status(host: str) -> str` |
| 6 | `aos_show_cmm` | `aos_show_cmm(host: str) -> str` |
| 7 | `aos_show_fan` | `aos_show_fan(host: str) -> str` |
| 8 | `aos_show_health` | `aos_show_health(host: str) -> str` |
| 9 | `aos_show_interfaces_alias` | `aos_show_interfaces_alias(host: str) -> str` |
| 10 | `aos_show_interfaces_counters_errors` | `aos_show_interfaces_counters_errors(host: str) -> str` |
| 11 | `aos_show_interfaces_ddm` | `aos_show_interfaces_ddm(host: str) -> str` |
| 12 | `aos_show_interfaces_flood_rate` | `aos_show_interfaces_flood_rate(host: str) -> str` |
| 13 | `aos_show_interfaces_port` | `aos_show_interfaces_port(host: str, port: str) -> str` |
| 14 | `aos_show_interfaces_status` | `aos_show_interfaces_status(host: str) -> str` |
| 15 | `aos_show_ip_dhcp_relay` | `aos_show_ip_dhcp_relay(host: str) -> str` |
| 16 | `aos_show_ip_dhcp_relay_statistics` | `aos_show_ip_dhcp_relay_statistics(host: str) -> str` |
| 17 | `aos_show_ip_interface` | `aos_show_ip_interface(host: str) -> str` |
| 18 | `aos_show_ip_ospf` | `aos_show_ip_ospf(host: str) -> str` |
| 19 | `aos_show_ip_ospf_neighbor` | `aos_show_ip_ospf_neighbor(host: str) -> str` |
| 20 | `aos_show_ip_routes` | `aos_show_ip_routes(host: str) -> str` |
| 21 | `aos_show_lanpower_slot` | `aos_show_lanpower_slot(host: str, slot: str) -> str` |
| 22 | `aos_show_lanpower_slot_port` | `aos_show_lanpower_slot_port(host: str, slot: str) -> str` |
| 23 | `aos_show_linkagg` | `aos_show_linkagg(host: str) -> str` |
| 24 | `aos_show_linkagg_port` | `aos_show_linkagg_port(host: str) -> str` |
| 25 | `aos_show_lldp_port` | `aos_show_lldp_port(host: str, port: str) -> str` |
| 26 | `aos_show_lldp_remote_system` | `aos_show_lldp_remote_system(host: str) -> str` |
| 27 | `aos_show_log_swlog` | `aos_show_log_swlog(host: str) -> str` |
| 28 | `aos_show_mac_learning` | `aos_show_mac_learning(host: str) -> str` |
| 29 | `aos_show_mac_learning_port` | `aos_show_mac_learning_port(host: str, port: str) -> str` |
| 30 | `aos_show_microcode` | `aos_show_microcode(host: str) -> str` |
| 31 | `aos_show_ntp_keys` | `aos_show_ntp_keys(host: str) -> str` |
| 32 | `aos_show_ntp_status` | `aos_show_ntp_status(host: str) -> str` |
| 33 | `aos_show_port_security` | `aos_show_port_security(host: str) -> str` |
| 34 | `aos_show_port_security_brief` | `aos_show_port_security_brief(host: str) -> str` |
| 35 | `aos_show_port_security_port` | `aos_show_port_security_port(host: str, port: str) -> str` |
| 36 | `aos_show_qos_config` | `aos_show_qos_config(host: str) -> str` |
| 37 | `aos_show_running_directory` | `aos_show_running_directory(host: str) -> str` |
| 38 | `aos_show_sflow_agent` | `aos_show_sflow_agent(host: str) -> str` |
| 39 | `aos_show_sflow_poller` | `aos_show_sflow_poller(host: str) -> str` |
| 40 | `aos_show_sflow_receiver` | `aos_show_sflow_receiver(host: str) -> str` |
| 41 | `aos_show_sflow_sampler` | `aos_show_sflow_sampler(host: str) -> str` |
| 42 | `aos_show_snmp_community_map` | `aos_show_snmp_community_map(host: str) -> str` |
| 43 | `aos_show_snmp_security` | `aos_show_snmp_security(host: str) -> str` |
| 44 | `aos_show_snmp_station` | `aos_show_snmp_station(host: str) -> str` |
| 45 | `aos_show_spantree` | `aos_show_spantree(host: str) -> str` |
| 46 | `aos_show_spantree_cist` | `aos_show_spantree_cist(host: str) -> str` |
| 47 | `aos_show_system` | `aos_show_system(host: str) -> str` |
| 48 | `aos_show_temp` | `aos_show_temp(host: str) -> str` |
| 49 | `aos_show_unp_port` | `aos_show_unp_port(host: str) -> str` |
| 50 | `aos_show_unp_profile` | `aos_show_unp_profile(host: str) -> str` |
| 51 | `aos_show_unp_user` | `aos_show_unp_user(host: str) -> str` |
| 52 | `aos_show_vc_consistency` | `aos_show_vc_consistency(host: str) -> str` |
| 53 | `aos_show_vc_topology` | `aos_show_vc_topology(host: str) -> str` |
| 54 | `aos_show_vc_vf_link` | `aos_show_vc_vf_link(host: str) -> str` |
| 55 | `aos_show_vlan` | `aos_show_vlan(host: str) -> str` |
| 56 | `aos_show_vlan_members` | `aos_show_vlan_members(host: str, vlan_id: int) -> str` |
| 57 | `aos_show_vrf` | `aos_show_vrf(host: str) -> str` |
| 58 | `aos_echo` | `aos_echo(message: str) -> str` |
| 59 | `aos_fetch_url` | `aos_fetch_url(url: str) -> str` |
| 60 | `aos_poe_reboot_request` | `aos_poe_reboot_request(host: str, slot_port: str, reason: str) -> str` |

> **Note:** `aos_echo` and `aos_fetch_url` are utility/debug tools inherited from the MCP template.
> `aos_poe_reboot_request` is the only WRITE tool; it is gated by a human-approval workflow (Teams card).
> All other tools are read-only (`show` commands or config backup).

### Rule: keeping this registry up to date

When **mcp-developer** registers a new tool in `src/mcp_server/tools/`:

1. Add a row to the table above (maintain alphabetical order, update the count in the heading).
2. Classify it clearly: read-only `show` / `backup`, or WRITE (requires `write_guard` or approval workflow).
3. Commit this file in the **same commit** as the source change — never let the registry drift.
