# mcp-zero

An open-source gateway that sits between your enterprise AI tools and MCP servers to enforce the security controls that compliance teams require before approving [MCP](https://modelcontextprotocol.io) adoption.

Without it, AI tools can call any MCP server with no access control, no audit trail, and no data protection — a non-starter in regulated environments. mcp-zero adds the missing governance layer: it validates user identity, checks policy rules, masks sensitive data, and logs every action — all inline, before requests ever reach downstream servers.

Deploy it as a single Python service. Configure it with a YAML policy file. No agents to install, no SaaS dependency, no vendor lock-in.

```
Enterprise AI Tool ──► MCP Gateway ──► MCP Servers
                         │
              ┌──────────┴──────────┐
              │   Hook Pipeline     │
              │                     │
              │   Identity  (core)  │
              │   Governance (core) │
              │   ◇ Plugins  (ext)  │
              │   Audit     (core)  │
              └─────────────────────┘
```

## Features

- **Identity** — Okta OAuth2 JWT validation (OBO token exchange requires explicit configuration - see docs/okta_obo_for_an_enterprise_mcp_gateway.md)
- **Governance** — YAML policy files with default-deny rules scoped to server, tool, user, and group
- **Data Protection** — Inline PII and secret masking via Microsoft Presidio on both inputs and outputs
- **Auditing** — Structured logs with user attribution, correlation IDs, and policy decisions
- **Transport** — Streamable HTTP for remote servers, stdio for gateway-managed local processes. Both HTTP and stdio transports enforce the same governance, masking, and audit policies through a unified pipeline.
- **Pipeline** — Hook-based request lifecycle with ordered execution and short-circuit support
- **Plugins** — Entry-point based plugin architecture for extending the pipeline with custom hooks (masking, rate limiting, metrics, etc.)

## Quick Start

### Prerequisites
- Python 3.12+
- An Okta tenant (for identity validation)

### Security Notice

**IMPORTANT**: The gateway is designed with fail-closed defaults but requires proper configuration to enforce security:

- **Policy file recommended**: Set `MCP_POLICY_FILE` to enable governance, identity validation, masking, and audit logging
- **Default-deny**: When policy file is configured, all requests are denied by default unless explicitly allowed
- **Insecure mode**: Setting `MCP_ALLOW_INSECURE=true` disables HTTPS enforcement and allows startup without policy/identity configuration (dev/testing only)
- **Masking dependencies**: PII/secret masking requires Presidio dependencies to be installed (included in standard installation)

**Known Limitations** (see [security review](docs/security_review_mcp_gateway.md) for details):
- Without a policy file, the gateway runs in legacy mode with no identity/governance/masking enforcement (F-03: OPEN)
- Tool discovery (`list_tools`) does not enforce per-user authorization (F-06: documented limitation)
- OBO token exchange requires explicit environment variables (`OKTA_TOKEN_ENDPOINT`, `OKTA_CLIENT_ID`, `OKTA_CLIENT_SECRET`) and per-server configuration

Never run with `MCP_ALLOW_INSECURE=true` in production environments.

### Install

```bash
# Clone and install
git clone https://github.com/abwaters/mcp-zero.git
cd mcp-zero
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate

pip install -e ".[dev]"
```

On Windows, convenience scripts are provided:
```bash
scripts\install.bat    # Creates venv and installs everything
```

### Configure

Create a policy file (e.g., `policy.yaml`):

```yaml
version: 1
default: deny

identity:
  provider: okta
  issuer: https://your-org.okta.com
  audience: your-app-audience

servers:
  - name: my-mcp-server
    transport: http
    url: https://mcp-server.internal.corp/mcp

policies:
  - id: allow-devs
    description: Allow developers to use read tools
    effect: allow
    subjects:
      groups:
        - developers
    mcp_servers:
      - name: my-mcp-server
        tools:
          - read_*
          - list_*

masking:
  presidio:
    enabled: true
    entities:
      - PERSON
      - EMAIL_ADDRESS
      - PHONE_NUMBER
      - CREDIT_CARD
      - API_KEY
      - PASSWORD
```

### Run

```bash
# Set the policy file path
export MCP_POLICY_FILE=policy.yaml

# Start the gateway
python -m mcp_zero
```

Or with environment variables for simple setups:

```bash
export MCP_UPSTREAM_URL=http://localhost:9000
export OKTA_ISSUER=https://your-org.okta.com
export OKTA_AUDIENCE=your-app-audience
python -m mcp_zero
```

The gateway starts on `0.0.0.0:8080` by default (configurable via `MCP_HOST` and `MCP_PORT`).

## Configuration

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `MCP_POLICY_FILE` | Path to YAML/JSON policy file | _(none)_ |
| `MCP_UPSTREAM_URL` | Single upstream MCP server URL (legacy fallback) | _(none)_ |
| `MCP_HOST` | Host to bind the gateway | `0.0.0.0` |
| `MCP_PORT` | Port to bind the gateway | `8080` |
| `MCP_ALLOW_INSECURE` | Allow running without security controls (dev/testing only) | `false` |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `LOG_FORMAT` | Log output format (`json` or `text`) | `json` |
| `OKTA_ISSUER` | Okta token issuer URL (fallback if no policy file) | _(none)_ |
| `OKTA_AUDIENCE` | Expected JWT audience claim (fallback if no policy file) | _(none)_ |
| `OKTA_TOKEN_ENDPOINT` | Okta token exchange endpoint (for OBO) | _(none)_ |
| `OKTA_CLIENT_ID` | Gateway client ID (for OBO) | _(none)_ |
| `OKTA_CLIENT_SECRET` | Gateway client secret (for OBO) | _(none)_ |
| `ANALYTICS_REDIS_URL` | Redis connection URL (enables analytics when set) | _(none)_ |
| `ANALYTICS_REDIS_CLUSTER` | Use Redis Cluster client | `false` |
| `ANALYTICS_REDIS_PASSWORD` | Redis authentication password | _(none)_ |
| `ANALYTICS_ENVIRONMENT` | Analytics key namespace (e.g. `production`) | `default` |
| `ANALYTICS_GATEWAY_ID` | Unique gateway instance ID | _(auto-generated)_ |
| `ANALYTICS_KEY_PREFIX` | Redis key prefix for analytics | `mcpgw` |
| `ANALYTICS_RETENTION_SECONDS` | TTL for analytics keys in seconds | `3600` |
| `MCP_CORS_ORIGINS` | Comma-separated allowed CORS origins (enables CORS when set) | _(none)_ |
| `MCP_CORS_ALLOW_CREDENTIALS` | Allow credentials in CORS requests | `false` |
| `MCP_CORS_MAX_AGE` | Preflight cache duration in seconds | `600` |

When `MCP_POLICY_FILE` is set, its identity section takes precedence over `OKTA_*` env vars. CORS env vars override policy file CORS values.

### Policy File

See [`docs/enterprise_mcp_gateway_policy_schema_example.md`](docs/enterprise_mcp_gateway_policy_schema_example.md) for a full annotated example.

Key concepts:
- **`version`**: Must be `1`
- **`default`**: `deny` (recommended) or `allow`
- **`servers`**: Downstream MCP server definitions (HTTP or stdio)
- **`policies`**: Ordered rules evaluated top-down; explicit deny overrides allow
- **`cors`**: CORS configuration for browser-based clients (disabled by default)
- **`masking`**: Presidio entity detection configuration (legacy — see `plugins` below)
- **`plugins`**: Plugin declarations for extensible pipeline hooks (masking, rate limiting, etc.)

#### CORS Configuration

Add a `cors` section to the policy file to allow browser-based MCP clients:

```yaml
cors:
  allow_origins:
    - https://web-ide.corp.com
    - https://dashboard.corp.com
  allow_methods: ["GET", "POST", "OPTIONS"]
  allow_headers: ["Authorization", "Content-Type"]
  allow_credentials: false
  max_age: 600
```

CORS is disabled by default (fail-closed). Only `allow_origins` is required; all other fields have safe defaults. Environment variables (`MCP_CORS_ORIGINS`, `MCP_CORS_ALLOW_CREDENTIALS`, `MCP_CORS_MAX_AGE`) override policy file values.

### Server Types

**HTTP servers** — remote MCP servers accessed over Streamable HTTP:
```yaml
servers:
  - name: remote-api
    transport: http
    url: https://mcp-server.corp/mcp
```

**stdio servers** — local processes spawned and managed by the gateway. Note: stdio servers are spawned dynamically and cannot currently be configured via policy files.

## Development

```bash
# Run tests
python -m pytest                          # all tests
python -m pytest tests/masking/ -v        # specific module
python -m pytest tests/test_main.py -v    # specific file

# Lint and format
ruff check src tests
ruff format src tests

# Run the gateway
python -m mcp_zero
```

On Windows, use the provided scripts:
```bash
scripts\test.bat           # Run tests
scripts\lint.bat           # Lint
scripts\format.bat         # Format
scripts\run.bat            # Run gateway
```

### Project Structure

```
src/mcp_zero/
├── main.py              # Application entry point
├── plugin.py            # Plugin protocol and base class
├── plugin_manager.py    # Plugin discovery and lifecycle
├── context.py           # RequestContext, HookContext, UserIdentity
├── identity/            # Okta JWT validation, OBO token exchange
├── governance/          # Policy loading, evaluation, enforcement
├── masking/             # Masking engine interface and hook
├── plugins/             # Built-in plugins (Presidio masking)
├── pipeline/            # Hook lifecycle, registry, execution
├── proxy/               # Starlette app, server management, tool routing
├── analytics/           # Optional Redis-based analytics
└── transport/           # HTTP and stdio MCP transport clients
```

### Architecture

The gateway uses a hook-based pipeline with a plugin system. Core hooks handle identity, governance, and audit. Everything else — masking, rate limiting, metrics — is a plugin loaded from the policy file.

**Core hooks** (always present):

| Priority | Hook | Phase | Purpose |
|----------|------|-------|---------|
| 10 | IdentityHook | PRE_VALIDATION | Validates JWT, resolves user identity |
| 50 | GovernanceHook | POST_VALIDATION | Evaluates policy rules, allows or denies |
| 145 | AnalyticsHook | PRE_AUDIT | Records metrics to Redis (when configured) |
| 150 | AuditHook | PRE_AUDIT | Emits structured log with full request context |

**Plugin hooks** (loaded from policy file `plugins:` section):

| Priority Range | Slot | Examples |
|----------------|------|---------|
| 20–49 | Pre-governance | Rate limiting, request validation |
| 70–99 | Post-governance | Masking (Presidio at 75), transformation |
| 100–139 | General | Metrics, caching, custom hooks |

Hooks execute in priority order. Any hook can short-circuit the pipeline (e.g., governance denial stops processing immediately).

**Plugin system**: Plugins are discovered via Python entry points (`mcp_zero.plugins` group), configured in the policy file, and registered into the pipeline at startup. See [`docs/plugin-architecture-design.md`](docs/plugin-architecture-design.md) for details.

## Documentation

| Document | Description |
|---|---|
| [`docs/quickstart.md`](docs/quickstart.md) | Step-by-step quickstart with Docker Compose and local paths |
| [`docs/prd.md`](docs/prd.md) | Product requirements and acceptance criteria |
| [`docs/enterprise_mcp_gateway_architecture_diagram.md`](docs/enterprise_mcp_gateway_architecture_diagram.md) | Logical architecture with component diagram |
| [`docs/enterprise_mcp_gateway_implementation_plan_epics.md`](docs/enterprise_mcp_gateway_implementation_plan_epics.md) | Phased implementation plan |
| [`docs/enterprise_mcp_gateway_policy_schema_example.md`](docs/enterprise_mcp_gateway_policy_schema_example.md) | Full annotated policy file example |
| [`docs/enterprise_mcp_gateway_security_compliance_positioning.md`](docs/enterprise_mcp_gateway_security_compliance_positioning.md) | Security controls and compliance alignment |
| [`docs/enterprise_mcp_gateway_threat_model_canvas.md`](docs/enterprise_mcp_gateway_threat_model_canvas.md) | Threat model and mitigations |
| [`docs/okta_obo_for_an_enterprise_mcp_gateway.md`](docs/okta_obo_for_an_enterprise_mcp_gateway.md) | OBO token exchange deep-dive |
| [`docs/enterprise_mcp_gateway_leadership_explainer.md`](docs/enterprise_mcp_gateway_leadership_explainer.md) | Non-technical stakeholder overview |

## Comparison

How mcp-zero compares to other MCP gateways:

| Capability | mcp-zero | [AgentGateway](https://github.com/agentgateway/agentgateway) | [MintMCP](https://www.mintmcp.com/) | [Microsoft MCP Gateway](https://github.com/microsoft/mcp-gateway) | [Lasso MCP Gateway](https://github.com/lasso-security/mcp-gateway) |
|---|---|---|---|---|---|
| **License** | ✅ MIT | ✅ Apache 2.0 (Linux Foundation) | ❌ Commercial SaaS | ✅ MIT | ✅ MIT |
| **Language** | Python | Rust / Go | Proprietary | .NET / C# | Python |
| **Transport** | ✅ Streamable HTTP, stdio | ✅ Streamable HTTP, SSE, stdio | ✅ HTTP, SSE, stdio | Streamable HTTP only | stdio only |
| **Authentication** | ✅ Okta OAuth2 JWT | ✅ JWT, API keys, OAuth (Auth0, Keycloak), MCP auth spec | ✅ OAuth 2.0, SAML, SSO (Okta, Azure AD) | Azure Entra ID / OAuth 2.0 | ❌ None built-in |
| **Governance** | ✅ YAML/JSON policy files, default-deny, server/tool/user/group rules | ✅ RBAC, Cedar policy engine, rate limiting | RBAC/ABAC, Virtual MCP role-based endpoints | RBAC via Entra ID roles | ❌ Plugin-based only |
| **Data protection** | ✅ Inline Presidio masking on inputs and outputs | ❌ None built-in | ✅ PII redaction, secrets scanning, content filtering | ❌ None built-in | Presidio PII + regex secret masking |
| **Auditing** | ✅ Structured logs with user attribution, correlation IDs, policy decisions | ✅ OpenTelemetry metrics, logs, distributed tracing | ✅ Immutable audit trail, dashboards, SOC 2 | Azure Application Insights | SQLite-based tool call tracing |
| **Deployment** | ✅ Self-hosted, lightweight | ✅ Self-hosted (binary, Docker, Kubernetes) | Managed cloud SaaS (self-hosted available) | Self-hosted on Kubernetes (AKS) | Local proxy process |
| **Multi-tenant** | ✅ User/group-level policies | ✅ Multi-tenant with per-tenant resources | ✅ Role-based endpoints | ✅ Resource-level RBAC | ❌ Single-user local proxy |
| **Primary focus** | Governance + data protection for regulated enterprises | High-performance connectivity + observability for agentic AI at scale | Managed governance + deployment platform | Scalable Kubernetes routing + lifecycle management | Security guardrails for local MCP usage |

### When to choose what

- **mcp-zero** — You need a self-hosted, lightweight gateway with policy-as-code governance, inline PII masking, and structured audit logging for compliance. No vendor lock-in, no cloud dependency.
- **AgentGateway** — You need a high-performance, Rust-based proxy for agent-to-agent and agent-to-tool connectivity at scale, with OpenTelemetry observability and Cedar-based policy. Strong fit if you need A2A protocol support or LLM gateway routing alongside MCP. No built-in PII masking.
- **MintMCP** — You want a managed SaaS platform that handles deployment, hosting, and governance with minimal operational overhead. Budget for commercial licensing.
- **Microsoft MCP Gateway** — You're already on Azure/AKS and need Kubernetes-native MCP server orchestration with Entra ID integration. Bring your own data protection and policy engine.
- **Lasso MCP Gateway** — You need a lightweight local proxy focused on secret/PII masking for individual developer workstations. Advanced features require the commercial Lasso platform.

## License

See [LICENSE](LICENSE) for details.
