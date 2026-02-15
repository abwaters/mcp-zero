## Architecture Overview

The Enterprise MCP Gateway is a centrally deployed control plane and data plane component that sits between enterprise AI tools and MCP servers.

---

## High-Level Architecture (Logical)

```mermaid
graph LR
    User[User]
    AI[Enterprise AI Tool]
    IdP[Okta / OAuth2]
    GW[Enterprise MCP Gateway]
    Policy[Policy Config
(YAML/JSON)]
    Presidio[Presidio
Masking Engine]
    MCP1[Remote MCP Server
HTTP]
    MCP2[Legacy MCP Server
SSE]
    MCP3[Gateway-Managed
MCP Server
stdio]
    Logs[Enterprise Logging / SIEM]

    User --> AI
    AI -->|OAuth2 Auth| IdP
    AI -->|MCP over HTTP| GW

    GW --> Policy
    GW --> Presidio

    GW -->|"Streamable HTTP
(Act as User)"| MCP1
    GW -->|"SSE (deprecated)
(Act as User)"| MCP2
    GW -->|"stdio
(Spawned Process)"| MCP3

    GW --> Logs
```

**Note**: All connections (Streamable HTTP, SSE, and stdio) flow through the full Identity → Governance → Masking → Audit pipeline when the gateway's security controls are configured.

---

## Component Responsibilities

### Enterprise AI Tool
- Performs user-interactive OAuth2 login
- Sends all MCP requests through the gateway
- Does not embed governance or masking logic

### MCP Gateway (Data Plane)
- Terminates MCP requests (Streamable HTTP, SSE, and stdio)
- Validates OAuth2 tokens
- Resolves user identity and groups
- Evaluates governance policies
- Applies inline Presidio masking
- Proxies requests to MCP servers
- Emits structured audit logs

### Policy Configuration (Control Plane)
- Static YAML/JSON files
- Loaded at startup
- Defines allow/deny rules by user, group, server, tool

### Presidio Integration
- Inline detection and masking
- Pluggable interface
- No persistence of unmasked data

### MCP Servers
- First-party or third-party
- No awareness of governance logic
- Receive already-masked inputs
- **Remote servers** communicate via Streamable HTTP or SSE (deprecated)
- **Gateway-managed servers** communicate via stdio (spawned as child processes by the gateway)

### Logging & SIEM
- Receives stdout logs via platform logging
- Provides retention, search, alerting

---

## Transport Model

The gateway supports three MCP transport modes:

### Streamable HTTP (Remote Servers)
- Gateway connects to remote MCP servers over HTTP
- OBO token exchange provides user-scoped authorization at the downstream server
- Primary model for third-party and externally hosted MCP servers

### SSE (Remote Servers — Deprecated)
- Gateway connects to remote MCP servers using the legacy SSE dual-endpoint protocol (GET `/sse` + POST `/messages`)
- Deprecated in MCP protocol version 2025-03-26 in favor of Streamable HTTP
- Provided for backward compatibility with servers/clients that haven't migrated
- Inbound SSE endpoints controlled by `MCP_SSE_ENABLED` env var (default: `true`)
- Full pipeline enforcement (identity, governance, masking, audit) identical to Streamable HTTP

### stdio (Gateway-Managed Servers)
- Gateway spawns MCP server processes locally and communicates via stdin/stdout
- Server runs as a subprocess of the gateway — no network boundary between gateway and server
- Governance, masking, and auditing apply through the same unified pipeline as HTTP connections

---

## Trust Boundaries
- OAuth2 token trust boundary at gateway ingress
- Enterprise boundary enforced before external MCP servers
- Sensitive data never leaves boundary unmasked

**Enforcement Boundaries**:
- HTTP transport: Full enforcement at gateway (identity, governance, masking, audit)
- SSE transport: Full enforcement at gateway (identity, governance, masking, audit)
- stdio transport: Full enforcement at gateway (identity, governance, masking, audit)
- Trust boundary enforcement applies to all transports through the unified pipeline

---

## Explicit Non-Architecture
- No endpoint agent
- No local machine enforcement
- No policy authoring UI

