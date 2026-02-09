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
    MCP2[External MCP Server
HTTP]
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
    GW -->|"Streamable HTTP
(Act as User)"| MCP2
    GW -->|"stdio
(Spawned Process)"| MCP3

    GW --> Logs
```

---

## Component Responsibilities

### Enterprise AI Tool
- Performs user-interactive OAuth2 login
- Sends all MCP requests through the gateway
- Does not embed governance or masking logic

### MCP Gateway (Data Plane)
- Terminates MCP requests (Streamable HTTP and stdio)
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
- **Remote servers** communicate via Streamable HTTP
- **Gateway-managed servers** communicate via stdio (spawned as child processes by the gateway)

### Logging & SIEM
- Receives stdout logs via platform logging
- Provides retention, search, alerting

---

## Transport Model

The gateway supports two MCP transport modes:

### Streamable HTTP (Remote Servers)
- Gateway connects to remote MCP servers over HTTP
- OBO token exchange provides user-scoped authorization at the downstream server
- Primary model for third-party and externally hosted MCP servers

### stdio (Gateway-Managed Servers)
- Gateway spawns MCP server processes locally and communicates via stdin/stdout
- Server runs as a subprocess of the gateway — no network boundary between gateway and server
- User identity is propagated via the gateway's process context
- Governance, masking, and auditing apply identically to HTTP-connected servers

---

## Trust Boundaries
- OAuth2 token trust boundary at gateway ingress
- Enterprise boundary enforced before external MCP servers
- Sensitive data never leaves boundary unmasked

---

## Explicit Non-Architecture
- No endpoint agent
- No local machine enforcement
- No policy authoring UI

