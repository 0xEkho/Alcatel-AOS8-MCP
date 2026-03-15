# ALE OmniSwitch AOS8 — MCP Server 🔌

![Version](https://img.shields.io/badge/Version-1.1.0-blue)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![MCP](https://img.shields.io/badge/MCP-%3E%3D1.2.0-green?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PC9zdmc+)
![License](https://img.shields.io/badge/License-MIT-yellow)
![Status](https://img.shields.io/badge/Status-Beta-blue)

An **MCP (Model Context Protocol) server** that exposes Alcatel-Lucent Enterprise OmniSwitch AOS8 network devices as AI-native tools.
Connect any MCP-compatible LLM client (Claude Desktop, OpenWebUI, Cursor…) to your network infrastructure and query, monitor, or troubleshoot your OmniSwitch fleet through natural language.

> **Target audience**: Network engineers and IT administrators who want to interact with AOS8 switches using AI assistants without leaving their workflow.

---

## ✨ Features

- **Dual HTTP transport** — `streamable-http` (recommended) and `SSE`, switchable via a single environment variable
- **SSH connectivity** — connects to OmniSwitch devices over SSH using [asyncssh](https://asyncssh.readthedocs.io/)
- **Multi-switch support** — target any switch by IP; credentials resolved per subnet zone or global fallback
- **Structured JSON output** — every tool returns a consistent, machine-readable JSON payload
- **Security middleware** — Bearer token authentication and IP allowlist (CIDR), enforced at the ASGI layer without buffering streaming responses
- **OpenWebUI compatible** — works out of the box as an MCP Tool Server in OpenWebUI
- **57 AOS8 tools** — one tool per AOS8 show/config command (VLANs, interfaces, spanning-tree, routing, MAC table, LLDP, system info…)
- **Write-guard by design** — no MCP tool can modify a switch configuration without prior human approval; `aos_poe_restart` has been removed in favor of `aos_poe_reboot_request` (Teams approval workflow)

---

## 🔧 Available Tools

### Core & Device Info

| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_system` | `show system` | System info (hostname, uptime, location) |
| `aos_show_microcode` | `show microcode` | Firmware version and package info |
| `aos_show_chassis` | `show chassis` | Chassis hardware details (model, serial, MAC) |
| `aos_show_running_directory` | `show running-directory` | CMM mode and config sync status |
| `aos_show_cmm` | `show cmm` | CMM module details |
| `aos_config_backup` | `write terminal` | Retrieve full running configuration |

### Ports & Interfaces

| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_interfaces_status` | `show interfaces status` | All ports speed/duplex/autoneg status |
| `aos_show_interfaces_alias` | `show interfaces alias` | Port descriptions/aliases and link state |
| `aos_show_interfaces_counters_errors` | `show interfaces counters errors` | Error counters per port |
| `aos_show_interfaces_ddm` | `show interfaces ddm` | SFP/XFP optical transceiver diagnostics |
| `aos_show_interfaces_port` | `show interfaces port <port>` | Detailed single port stats and counters |
| `aos_show_interfaces_flood_rate` | `show interfaces flood-rate` | Broadcast/multicast/unicast flood rate limits |
| `aos_show_lldp_remote_system` | `show lldp remote-system` | All LLDP neighbors |
| `aos_show_lldp_port` | `show lldp port <port> remote-system` | LLDP neighbor on specific port |

### VLAN

| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_vlan` | `show vlan` | All VLANs (type, admin/oper status, name) |
| `aos_show_vlan_members` | `show vlan members` | VLAN port membership and forwarding status |

### Spanning Tree

| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_spantree` | `show spantree` | STP instances overview |
| `aos_show_spantree_cist` | `show spantree cist` | CIST details (root bridge, cost, topology) |

### Health & MAC Learning

| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_health` | `show health` | CPU and memory usage (current + averages) |
| `aos_show_temp` | `show temp` | Temperature sensors status |
| `aos_show_fan` | `show fan` | Fan status |
| `aos_show_mac_learning` | `show mac-learning` | Full MAC learning table |
| `aos_show_mac_learning_port` | `show mac-learning port <port>` | MAC table for a specific port |

### Routing & L3

| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_ip_routes` | `show ip routes` | IP routing table (up to 500 entries, truncated if larger) |
| `aos_show_ip_interface` | `show ip interface` | IP interfaces (name, address, mask, status) |
| `aos_show_ip_ospf` | `show ip ospf` | OSPF global parameters and statistics |
| `aos_show_ip_ospf_neighbor` | `show ip ospf neighbor` | OSPF neighbor adjacencies |
| `aos_show_vrf` | `show vrf` | Virtual Routing and Forwarding instances |
| `aos_show_arp` | `show arp` | ARP table entries |

### PoE (Power over Ethernet)

| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_lanpower_slot` | `show lanpower slot <slot>` | PoE status per slot (power, status, class) |
| `aos_show_lanpower_slot_port` | `show lanpower slot <slot> port` | Detailed PoE config per port |
| ~~`aos_poe_restart`~~ | ~~`lanpower port <port> admin-state disable/enable`~~ | 🚫 **Removed** — replaced by `aos_poe_reboot_request` (Teams approval required) |
| `aos_poe_reboot_request` | Teams workflow + SSH | ✅ **Approved write** — PoE reboot after human approval |

### Diagnostics

| Tool | Command | Description |
|------|---------|-------------|
| `aos_ping` | `ping <target> count <n>` | Ping from switch to destination |
| `aos_show_log_swlog` | `show log swlog` | System log (swlog) — may timeout on busy switches |

### LACP / Link Aggregation

| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_linkagg` | `show linkagg` | Link aggregation groups |
| `aos_show_linkagg_port` | `show linkagg port` | Link aggregation port membership |

### NTP

| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_ntp_status` | `show ntp client` | NTP synchronization status and server reference |
| `aos_show_ntp_keys` | `show ntp keys` | NTP authentication keys |

### DHCP Relay

| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_ip_dhcp_relay` | `show ip dhcp relay` | DHCP relay configuration |
| `aos_show_ip_dhcp_relay_statistics` | `show ip dhcp relay statistics` | DHCP relay counters |

### Virtual Chassis
| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_vc_topology` | `show virtual-chassis topology` | VC members, roles, and MAC addresses |
| `aos_show_vc_consistency` | `show virtual-chassis consistency` | VC consistency check (type, group, VLANs, license) |
| `aos_show_vc_vf_link` | `show virtual-chassis vf-link` | Virtual Fabric Link status |

### Cloud Agent (OmniVista)
| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_cloud_agent_status` | `show cloud-agent status` | Cloud agent state, VPN, OmniVista tenant, certificate status |

### SNMP
| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_snmp_station` | `show snmp station` | SNMP trap stations (IP, port, protocol, user) |
| `aos_show_snmp_community_map` | `show snmp community-map` | SNMP community strings mapping |
| `aos_show_snmp_security` | `show snmp security` | SNMP security configuration |

### sFlow
| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_sflow_agent` | `show sflow agent` | sFlow agent IP and version |
| `aos_show_sflow_sampler` | `show sflow sampler` | sFlow sampling configuration per port |
| `aos_show_sflow_poller` | `show sflow poller` | sFlow polling configuration |
| `aos_show_sflow_receiver` | `show sflow receiver` | sFlow collector (receiver) configuration |

### QoS
| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_qos_config` | `show qos config` | QoS global configuration |

### UNP (Universal Network Profile)
| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_unp_port` | `show unp port` | UNP port configuration (802.1X, MAC auth, classification) |
| `aos_show_unp_user` | `show unp user` | Authenticated UNP users |
| `aos_show_unp_profile` | `show unp profile` | UNP profile definitions |
| `aos_show_unp_statistics` | `show unp statistics` | UNP authentication statistics |

### Port Security
| Tool | Command | Description |
|------|---------|-------------|
| `aos_show_port_security` | `show port-security` | Global port security status |
| `aos_show_port_security_brief` | `show port-security brief` | Port security summary per port |
| `aos_show_port_security_port` | `show port-security port <port>` | Port security detail for a specific port |

---

## 🚀 Quick Start

**Prerequisites**: [Python 3.10+](https://www.python.org/downloads/) and [uv](https://docs.astral.sh/uv/getting-started/installation/)

```bash
# 1. Clone the repository
git clone https://github.com/rpoulard-alcatel/Alcatel-AOS8-MCP.git
cd Alcatel-AOS8-MCP

# 2. Install dependencies (virtualenv created automatically)
uv sync

# 3. Configure your environment
cp .env.example .env
#    → Edit .env: set AOS_GLOBAL_USERNAME, AOS_GLOBAL_PASSWORD, MCP_API_KEY, etc.

# 4. Start the MCP server
uv run mcp-server
```

The server starts on `http://0.0.0.0:8080` by default (Streamable HTTP transport).

### 🐳 Docker (Production)

> **Prerequisites**: [Docker](https://docs.docker.com/get-docker/) with the Compose plugin (`docker compose`)

```bash
# 1. Copy and configure environment variables
cp .env.example .env
#    → Edit .env: set AOS_GLOBAL_USERNAME, AOS_GLOBAL_PASSWORD, MCP_API_KEY, MCP_HOST=0.0.0.0

# 2. (Optional) Prepare known_hosts for strict SSH host key checking
touch ./known_hosts
#    → Populate it, then set SSH_STRICT_HOST_KEY=true in .env

# 3. Build and start the container
docker compose up -d

# 4. Follow live logs
docker compose logs -f
```

The MCP endpoint is available at `http://<host>:${MCP_PORT:-8080}/mcp`.

> **Important**: set `MCP_HOST=0.0.0.0` in `.env` so uvicorn binds on all interfaces inside the container.

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and adjust the values. **Never commit `.env` to version control.**

### MCP Server

| Variable | Default | Description |
|---|---|---|
| `MCP_SERVER_NAME` | `alcatel-aos8-mcp` | Display name shown in MCP clients |
| `MCP_TRANSPORT` | `streamable-http` | Transport mode: `streamable-http`, `sse`, or `stdio` |
| `MCP_HOST` | `0.0.0.0` | Bind address (HTTP transports only) |
| `MCP_PORT` | `8080` | Listening port (HTTP transports only) |

### Security

| Variable | Default | Description |
|---|---|---|
| `MCP_API_KEY` | *(empty)* | Bearer token required in `Authorization: Bearer <token>`. Leave empty to disable. |
| `MCP_ALLOWED_IPS` | `127.0.0.1/32,10.0.0.0/8,192.168.0.0/16` | Comma-separated CIDR allowlist. Leave empty to allow all IPs. |

### SSH — Switch Credentials

| Variable | Default | Description |
|---|---|---|
| `AOS_GLOBAL_USERNAME` | — | Default SSH username for all switches |
| `AOS_GLOBAL_PASSWORD` | — | Default SSH password for all switches |
| `AOS_ZONE{X}_USERNAME` | *(empty)* | Override username for switches on `10.X.0.0/16` |
| `AOS_ZONE{X}_PASSWORD` | *(empty)* | Override password for switches on `10.X.0.0/16` |

> **Zone-based credentials**: set `AOS_ZONE1_USERNAME` / `AOS_ZONE1_PASSWORD` to use different credentials for all switches on `10.1.0.0/16`. Add as many zones as needed (X = second octet of the target subnet).

### SSH Settings

| Variable | Default | Description |
|---|---|---|
| `SSH_STRICT_HOST_KEY` | `false` | Set to `true` in production and populate `SSH_KNOWN_HOSTS_FILE` |
| `SSH_KNOWN_HOSTS_FILE` | `./known_hosts` | Path to known_hosts (used when strict host key is enabled) |
| `SSH_CONNECT_TIMEOUT` | `10` | Connection timeout in seconds |
| `SSH_COMMAND_TIMEOUT` | `30` | Command execution timeout in seconds |

### Logging

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |

---

## 📁 Project Structure

```
Alcatel-AOS8-MCP/
├── src/
│   └── mcp_server/
│       ├── server.py          # Entry point: FastMCP init, transport, security middleware
│       ├── tools/             # MCP tools — one file per AOS8 command category
│       ├── resources/         # MCP resources — read-only context (switch inventory, docs)
│       ├── prompts/           # MCP prompts — reusable templates for network tasks
│       └── ssh/
│           ├── client.py      # asyncssh wrapper — connects and runs AOS8 commands
│           └── auth.py        # Credential resolver (global → zone fallback)
├── tests/
│   ├── test_tools.py
│   ├── test_resources.py
│   ├── test_prompts.py
│   └── test_ssh.py
├── .env.example               # All variables with inline documentation
├── pyproject.toml             # Project metadata and dependencies
├── AGENTS.md                  # Copilot agent instructions
└── LICENSE
```

---

## 🔒 Security Policy — WRITE Operations

### Absolute rule

> **No MCP tool may execute a configuration command on a switch without prior human approval.**

AOS8 switches are critical network equipment. A misrouted WRITE command can cause a production outage. The MCP server enforces a **strict separation** between read and write operations:

- **READ tools** — query the switch (`show ...`). Can be called directly by the AI.
- **WRITE tools** — modify switch configuration. **May never** be executed without explicit approval from a human engineer.

---

### `aos_poe_restart` — intentionally removed

The `aos_poe_restart` tool (direct command `lanpower port <port> admin-state disable/enable`) has been **intentionally removed** from the codebase.

Its replacement is `aos_poe_reboot_request` (module `poe_approval.py`), which enforces a human-in-the-loop approval workflow via Teams before any command is executed on the switch. See [⚡ PoE Approval Workflow (Teams)](#-poe-approval-workflow-teams) for the full flow.

---

### Convention for future WRITE operations

Any developer wishing to add a WRITE tool **MUST** follow these three rules:

1. **Implement an approval workflow** (Teams, e-mail, or equivalent mechanism) — the AI must never trigger a network change on its own initiative.
2. **Use `write_guard()` as a safety net** — if the tool is called without a workflow (design error), `write_guard()` blocks execution and returns an LLM-readable error message without raising an exception.
3. **Mention `_write_guard` in the tool's docstring** to indicate it has been audited.

```python
# ✅ Compliant pattern — WRITE tool with write_guard fallback
from mcp_server.tools._write_guard import write_guard

@mcp.tool()
async def my_write_tool(host: str, port: str) -> str:
    """Perform a WRITE operation after human approval.

    This tool goes through the Teams approval workflow. _write_guard audited.

    Args:
        host: IP address of the target switch.
        port: Port to modify (e.g. "1/1/3").
    """
    # If this code is reached without a workflow → block immediately
    return write_guard("my_write_tool")
```

---

### `_write_guard.py` — architectural reference

The module `src/mcp_server/tools/_write_guard.py` is the **architectural reference point** for all WRITE operations:

- Its module docstring states the full contract (WRITE rule, implementation convention, compliant example).
- The function `write_guard(tool_name: str) -> str` **always** returns a `str` and **never** raises an exception — in accordance with MCP best practices (business errors are returned, not propagated).
- The returned message guides the LLM toward the correct approval workflow (`aos_poe_reboot_request`).

---

### Regression tests — `tests/test_write_guard.py`

The file `tests/test_write_guard.py` is an **automated safety net**. It will fail immediately if someone re-introduces an unapproved WRITE tool:

| Monitored scenario | Concerned test |
|---|---|
| `aos_poe_restart` re-introduced in `poe.py` | `test_aos_poe_restart_absent_from_poe_module` |
| `aos_poe_restart` present on a multi-module instance | `test_aos_poe_restart_absent_from_combined_instance` |
| `aos_poe_reboot_request` removed from `poe_approval.py` | `test_aos_poe_reboot_request_present_in_poe_approval_module` |
| `aos_poe_reboot_request` absent from a combined instance | `test_aos_poe_reboot_request_present_in_combined_instance` |
| `write_guard()` raises an exception instead of returning a `str` | `test_write_guard_returns_string_not_exception` |
| `write_guard()` does not include the blocked tool name | `test_write_guard_contains_tool_name` |
| `write_guard()` does not point toward `aos_poe_reboot_request` | `test_write_guard_mentions_approved_workflow` |
| `write_guard()` crashes on atypical names (empty, special chars…) | `test_write_guard_never_raises_on_arbitrary_tool_name` |

```bash
# Run only the WRITE regression guards
uv run pytest tests/test_write_guard.py -v
```

> ⚠️ These tests must **never** be deleted or bypassed to make a build pass. A failure on `test_write_guard.py` signals a **WRITE security policy violation** — fix the source code, not the test.

---

## ⚡ PoE Approval Workflow (Teams)

Every `aos_poe_reboot_request` operation triggers a **human-in-the-loop** circuit: the AI never touches equipment unless an engineer has explicitly approved the action in Teams.

### 1 — Full flow

```
┌──────────┐  aos_poe_reboot_request()   ┌─────────────────┐
│    AI    │ ───────────────────────▶ │   MCP Server    │
│ (Claude, │                          │                  │
│  OpenWUI)│                          │  • Generates UUID│
└──────────┘                          │  • TTL 30 min   │
                                      │  • POST Teams   │
                                      └────────┬────────┘
                                               │ MessageCard
                                               │ (Adaptive Card)
                                               ▼
                                      ┌─────────────────┐
                                      │  Teams Channel  │
                                      │  ┌───────────┐  │
                                      │  │✅ Approve  │  │
                                      │  │❌ Reject   │  │
                                      │  └───────────┘  │
                                      └────────┬────────┘
                                               │ Engineer clicks
                                               │ (OpenUri → browser)
                                               ▼
                              ┌────────────────────────────────┐
                              │  GET /webhook/approve/{uuid}   │
                              │  ?action=approve&secret=…      │
                              │                                │
                              │  FortiGate VIP ──▶ MCP :8080  │
                              └────────────────┬───────────────┘
                                               │
                                               ▼
                                      ┌─────────────────┐
                                      │   MCP Server    │
                                      │  • Checks TTL   │
                                      │  • Validates    │
                                      │    WEBHOOK_SECRET│
                                      │  • SSH disable  │
                                      │    → sleep 2 s  │
                                      │    → SSH enable │
                                      │  • POST confirm │
                                      │    Teams        │
                                      └─────────────────┘
```

**Key steps:**

| # | Actor | Action |
|---|-------|--------|
| 1 | AI | Calls the MCP tool `aos_poe_reboot_request(requester, switches, ports, reason)` |
| 2 | MCP Server | Creates a `PENDING_APPROVALS[uuid]` entry with a 30-min TTL, posts a `MessageCard` to Teams |
| 3 | Teams | Displays the card with **✅ Approve** / **❌ Reject** buttons in the channel |
| 4 | Engineer | Clicks a button → browser opens `{MCP_PUBLIC_URL}/webhook/approve/{uuid}?action=approve&secret=…` |
| 5 | FortiGate | VIP / port forwarding relays the GET request to the internal MCP server |
| 6 | MCP Server | Validates the `WEBHOOK_SECRET`, executes the PoE SSH reboots, posts a Teams confirmation |
| 7 | Engineer | Sees an HTML confirmation page in the browser |

> **Power Automate variant**: if the MCP server is only reachable from Microsoft IP ranges, configure a Power Automate flow whose **HTTP GET** action is triggered by the card button (the `OpenUri` points to the Power Automate HTTP trigger, which relays to `MCP_PUBLIC_URL`). See the [FortiGate Configuration](#5--fortigate-configuration) section below.

---

### 2 — Required environment variables

Add these three variables to your `.env` file:

```bash
# Teams Incoming Webhook URL (obtained from the channel connector)
TEAMS_WEBHOOK_URL=https://xxxxx.webhook.office.com/webhookb2/...

# Shared secret included in callback query strings — protects against replay attacks
# Generate with: openssl rand -hex 32
WEBHOOK_SECRET=<32-bytes-hex-secret>

# Public URL of the MCP server, reachable from the engineer's browser
# (or from Power Automate depending on your network topology)
# No trailing slash
MCP_PUBLIC_URL=https://mcp.corp.example.com
# or with IP + port:
MCP_PUBLIC_URL=https://1.2.3.4:8443
```

| Variable | Role | Required |
|---|---|---|
| `TEAMS_WEBHOOK_URL` | Teams Incoming Webhook URL used to post the `MessageCard` | ✅ |
| `WEBHOOK_SECRET` | Secret token validated on every callback — blocks unauthorized requests | ✅ |
| `MCP_PUBLIC_URL` | Base URL embedded in the Approve/Reject buttons of the Teams card | ✅ |

> ⚠️ All three variables are **mandatory**: if any is missing, `aos_poe_reboot_request` returns an error immediately without creating a pending request.

---

### 3 — Configure the Teams Incoming Webhook

1. In Teams, open the target notification channel.
2. Click **`…`** (More options) → **Connectors** → **Manage**.
3. Search for **Incoming Webhook**, click **Configure**.
4. Give it a name (e.g. `MCP PoE Approvals`) and optionally an image.
5. Click **Create** — copy the generated URL.
6. Paste it into `.env`: `TEAMS_WEBHOOK_URL=<copied url>`.

> 📌 Teams Incoming Webhooks use the **`MessageCard`** (legacy) format, which natively supports `OpenUri` buttons with no additional configuration.

---

### 4 — Configure a Power Automate flow (optional)

Use Power Automate if the MCP server is **not directly reachable** from the engineer's browser (e.g. behind a FortiGate restricted to Power Automate IP ranges).

**Prerequisites**: a Microsoft 365 subscription with Power Automate.

**Steps:**

1. In [Power Automate](https://make.powerautomate.com), create a new **Automated cloud flow**.
2. Choose the **When a HTTP request is received** trigger.
3. Note the generated trigger URL (you will need it in step 6).
4. Add an **HTTP** action (Premium connector):
   - **Method**: `GET`
   - **URI**: `@{triggerOutputs()?['queries']['callback_url']}`  
     *(the callback URL will be passed as a query string by the card's OpenUri)*
5. Save the flow.
6. In `.env`, set `MCP_PUBLIC_URL` to the Power Automate trigger URL:
   ```bash
   # Teams buttons open → Power Automate → GET to the real MCP server
   MCP_PUBLIC_URL=https://prod-xx.westeurope.logic.azure.com/workflows/…
   ```

> 💡 **Simpler alternative**: if the MCP server is directly reachable from the browser (via HTTPS + FortiGate VIP), point `MCP_PUBLIC_URL` directly at the MCP server. Power Automate is then unnecessary.

---

### 5 — FortiGate Configuration

The `/webhook/approve/{uuid}` endpoint must be reachable from **outside** (engineer's browser or Power Automate) while keeping the rest of the MCP server protected.

#### VIP Port Forwarding

```
# FortiGate CLI — example
config firewall vip
    edit "MCP-PoE-Webhook"
        set type static-nat
        set extip  <FORTIGATE_PUBLIC_IP>
        set extintf "wan1"
        set portforward enable
        set extport 8443
        set mappedip <MCP_SERVER_INTERNAL_IP>
        set mappedport 8080
    next
end
```

#### Firewall policy — source restriction (Power Automate IPs)

If you are using Power Automate as a relay, restrict sources to the [IP ranges published by Microsoft](https://learn.microsoft.com/en-us/connectors/common/outbound-ip-addresses) for your region:

```
# Example: allow only Power Automate West Europe
config firewall policy
    edit 0
        set name "MCP-PoE-Webhook-PA"
        set srcintf "wan1"
        set dstintf "internal"
        set srcaddr <ADDRGRP_POWER_AUTOMATE_IPS>
        set dstaddr "MCP-PoE-Webhook"
        set action accept
        set service "TCP-8443"
        set schedule "always"
    next
end
```

> 📌 If the engineer accesses directly from the browser (not via Power Automate), no source restriction is needed — the `WEBHOOK_SECRET` in the query string guarantees authenticity.

#### MCP endpoint secured separately

The MCP server exposes **two distinct paths**:

| Path | Protection | Accessible from |
|---|---|---|
| `/mcp` or `/sse` | `MCP_API_KEY` + `MCP_ALLOWED_IPS` | LLM clients (internal network) |
| `/webhook/approve/{uuid}` | `WEBHOOK_SECRET` as query string | Engineer's browser or Power Automate |

---

### 6 — Workflow security

#### `WEBHOOK_SECRET` — callback protection

The secret is included in every callback URL generated by the MCP server:

```
https://mcp.corp.example.com/webhook/approve/a1b2c3…?action=approve&secret=<WEBHOOK_SECRET>
```

- The server rejects any request whose `secret` does not match → **HTTP 403**
- Generate a strong secret: `openssl rand -hex 32`
- Never share it outside of `.env` and the Power Automate flow

#### 30-minute TTL

Each approval request expires automatically after **30 minutes**:

```
Request created ──────────────────────────────────────────▶ Expiry
t=0                                                        t+30min
         │                       │                            │
         ▼                       ▼                            ▼
   Teams card              Engineer clicks             Link invalid
   posted                  ✅ OK (within TTL)          → HTTP 410
```

- Expired requests are purged automatically on each webhook call (lazy cleanup).
- An already-processed request (approved or rejected) returns **HTTP 409** if the link is reused.
- The `WEBHOOK_SECRET` **does not change** between requests — never include it in logs.

#### HTTP response codes summary

| Code | Situation |
|---|---|
| `200` | Action executed successfully |
| `400` | Invalid `action` parameter |
| `403` | Incorrect `WEBHOOK_SECRET` |
| `404` | UUID not found (expired or already processed) |
| `409` | Request already processed |
| `410` | Request expired (TTL exceeded) |
| `500` | `WEBHOOK_SECRET` not configured on the server side |

---

## 🌐 OpenWebUI Integration

This server exposes an MCP-over-HTTP endpoint compatible with [OpenWebUI](https://openwebui.com/) (v0.5+).

1. Start the MCP server with `MCP_TRANSPORT=streamable-http` (default):
   ```bash
   uv run mcp-server
   ```

2. In OpenWebUI, navigate to **Settings → Tools → Add Tool Server** and enter:

   | Field | Value |
   |---|---|
   | URL | `http://<server-ip>:8080/mcp` |
   | Auth header | `Authorization: Bearer <your MCP_API_KEY>` |

3. The AOS8 tools will appear automatically in the OpenWebUI tool selector.

> **SSE transport**: if you prefer SSE, set `MCP_TRANSPORT=sse` and use endpoint `/sse` instead of `/mcp`.

---

## 🔧 Claude Desktop Integration

Edit `claude_desktop_config.json`:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "aos8": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/Alcatel-AOS8-MCP",
        "run",
        "mcp-server"
      ],
      "env": {
        "MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

> Replace `/absolute/path/to/Alcatel-AOS8-MCP` with the actual path on your machine.  
> Use `MCP_TRANSPORT=stdio` for Claude Desktop — no network port required.

---

## 🛠 Development

### Install dependencies

```bash
uv sync
```

### Run the server

```bash
# Streamable HTTP (default — recommended for OpenWebUI / HTTP clients)
uv run mcp-server

# SSE transport
MCP_TRANSPORT=sse uv run mcp-server

# STDIO transport (for Claude Desktop or MCP Inspector)
MCP_TRANSPORT=stdio uv run mcp-server
```

### Debug with MCP Inspector

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) lets you interactively test every tool, resource, and prompt from your browser.

```bash
npx @modelcontextprotocol/inspector uv run mcp-server
```

Open the URL shown in the terminal (typically `http://localhost:5173`).

### Run tests

```bash
# All tests
uv run pytest

# With coverage report
uv run pytest --cov=mcp_server

# HTML coverage report (opens in browser)
uv run pytest --cov=mcp_server --cov-report=html

# Single test file, verbose
uv run pytest tests/test_tools.py -v
```

### Add a new AOS8 tool

Create a module under `src/mcp_server/tools/` and register it in `server.py`:

```python
# src/mcp_server/tools/vlan.py
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def register_tools(mcp: Any) -> None:
    """Register VLAN-related tools on the MCP server instance."""

    @mcp.tool()
    async def show_vlan(switch_ip: str, vlan_id: int | None = None) -> str:
        """Show VLAN configuration on an OmniSwitch AOS8 device.

        Args:
            switch_ip: IP address of the target OmniSwitch.
            vlan_id: Optional VLAN ID to filter results. Returns all VLANs if omitted.
        """
        logger.info("show_vlan called: switch=%s vlan=%s", switch_ip, vlan_id)
        # ... SSH call via mcp_server.ssh.client ...
        return json.dumps({"status": "ok", "vlans": []})
```

```python
# src/mcp_server/server.py  — add after existing register_* calls
from mcp_server.tools.vlan import register_tools as register_vlan_tools

register_vlan_tools(mcp)
```

---

## 🔗 Resources

- [Model Context Protocol — Documentation](https://modelcontextprotocol.io)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
- [asyncssh — Documentation](https://asyncssh.readthedocs.io/)
- [OpenWebUI — MCP Tool Servers](https://docs.openwebui.com/)
- [ALE OmniSwitch AOS8 CLI Reference](https://www.al-enterprise.com/en/products/switches/omniswitch-aos)
- [uv — Documentation](https://docs.astral.sh/uv/)

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
