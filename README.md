# mcp-zero

Enterprise MCP Gateway — a centrally hosted control point that enforces governance, identity, data protection, and auditing for [Model Context Protocol](https://modelcontextprotocol.io) traffic in regulated enterprise environments.

```
Enterprise AI Tool ──► MCP Gateway ──► MCP Servers
                         │
              ┌──────────┼──────────┐
          Identity    Governance   Masking
          (Okta)     (Policy)    (Presidio)
```

## Why

Without a gateway, MCP adoption is blocked by security and compliance concerns. AI tools can call arbitrary MCP servers with no access control, no audit trail, and no data protection. mcp-zero provides the minimum viable control surface to make MCP approvable in enterprise environments:

- **Only approved tools are accessible** — default-deny policies by user, group, server, and tool
- **Actions are attributable to real users** — Okta OAuth2 JWT validation with group resolution
- **Sensitive data is masked** — Presidio-based PII/secret detection on inputs and outputs
- **All activity is auditable** — structured logs with correlation IDs and policy decisions

## Features

### Identity & Authentication
- Okta OAuth2 JWT validation at the gateway edge
- User identity resolution (user_id, email, groups) from token claims
- On-Behalf-Of (OBO) token exchange for downstream MCP servers
- Configurable claim mapping

### Governance
- Static YAML/JSON policy files, loaded at startup
- Default-deny with explicit allow/deny rules
- Server, tool, user, and group-level access control
- Wildcard patterns for tools (e.g., `read_*`, `delete_*`)
- Top-down evaluation with explicit deny override

### Data Protection
- Microsoft Presidio integration for PII/secret detection and masking
- Built-in entity types: PERSON, EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD
- Custom recognizers for API_KEY and PASSWORD patterns
- Inline masking — sensitive data is replaced before reaching downstream servers

### Transport
- **Streamable HTTP** — proxy to remote MCP servers with OBO token exchange
- **stdio** — spawn and manage local MCP server processes as subprocesses

### Pipeline Architecture
Hook-based lifecycle with ordered execution points:

```
PRE_VALIDATION → POST_VALIDATION → PRE_MASKING → POST_MASKING → PRE_AUDIT
     │                  │                │                            │
 IdentityHook     GovernanceHook    MaskingHook                  AuditHook
 (priority 10)    (priority 50)    (priority 75)               (priority 150)
```

## Quick Start

### Prerequisites
- Python 3.12+
- An Okta tenant (for identity validation)

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
  claim_mapping:
    user_id: sub
    email: email
    groups: groups

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
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `OKTA_ISSUER` | Okta token issuer URL (fallback if no policy file) | _(none)_ |
| `OKTA_AUDIENCE` | Expected JWT audience claim (fallback if no policy file) | _(none)_ |
| `OKTA_TOKEN_ENDPOINT` | Okta token exchange endpoint (for OBO) | _(none)_ |
| `OKTA_CLIENT_ID` | Gateway client ID (for OBO) | _(none)_ |
| `OKTA_CLIENT_SECRET` | Gateway client secret (for OBO) | _(none)_ |

When `MCP_POLICY_FILE` is set, its identity section takes precedence over `OKTA_*` env vars.

### Policy File

See [`docs/enterprise_mcp_gateway_policy_schema_example.md`](docs/enterprise_mcp_gateway_policy_schema_example.md) for a full annotated example.

Key concepts:
- **`version`**: Must be `1`
- **`default`**: `deny` (recommended) or `allow`
- **`servers`**: Downstream MCP server definitions (HTTP or stdio)
- **`policies`**: Ordered rules evaluated top-down; explicit deny overrides allow
- **`masking`**: Presidio entity detection configuration

### Server Types

**HTTP servers** — remote MCP servers accessed over Streamable HTTP:
```yaml
servers:
  - name: remote-api
    transport: http
    url: https://mcp-server.corp/mcp
    token_exchange: true           # Enable OBO
    target_audience: api://server  # OBO target
    required_scopes: [read, write]
```

**stdio servers** — local processes spawned and managed by the gateway:
```yaml
servers:
  - name: local-tools
    transport: stdio
    command: /usr/local/bin/mcp-server
    args: ["--config", "/etc/config.yaml"]
    env:
      DEBUG: "1"
```

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
├── context.py           # RequestContext, HookContext, UserIdentity
├── identity/            # Okta JWT validation, OBO token exchange
├── governance/          # Policy loading, evaluation, enforcement
├── masking/             # Presidio PII/secret detection and masking
├── pipeline/            # Hook lifecycle, registry, execution
├── proxy/               # Starlette app, server management, tool routing
└── transport/           # HTTP and stdio MCP transport clients
```

### Architecture

The gateway uses a hook-based pipeline architecture. Each request flows through ordered lifecycle hooks that can inspect, modify, or reject the request:

1. **IdentityHook** (PRE_VALIDATION) — validates JWT, resolves user identity
2. **GovernanceHook** (POST_VALIDATION) — evaluates policy rules, allows or denies
3. **MaskingHook** (PRE_MASKING) — detects and replaces PII/secrets in payloads
4. **AuditHook** (PRE_AUDIT) — emits structured log with full request context

Hooks are registered with priorities and executed in order. Any hook can short-circuit the pipeline (e.g., governance denial stops processing immediately).

## Documentation

| Document | Description |
|---|---|
| [`docs/prd.md`](docs/prd.md) | Product requirements and acceptance criteria |
| [`docs/enterprise_mcp_gateway_architecture_diagram.md`](docs/enterprise_mcp_gateway_architecture_diagram.md) | Logical architecture with component diagram |
| [`docs/enterprise_mcp_gateway_implementation_plan_epics.md`](docs/enterprise_mcp_gateway_implementation_plan_epics.md) | Phased implementation plan |
| [`docs/enterprise_mcp_gateway_policy_schema_example.md`](docs/enterprise_mcp_gateway_policy_schema_example.md) | Full annotated policy file example |
| [`docs/enterprise_mcp_gateway_security_compliance_positioning.md`](docs/enterprise_mcp_gateway_security_compliance_positioning.md) | Security controls and compliance alignment |
| [`docs/enterprise_mcp_gateway_threat_model_canvas.md`](docs/enterprise_mcp_gateway_threat_model_canvas.md) | Threat model and mitigations |
| [`docs/okta_obo_for_an_enterprise_mcp_gateway.md`](docs/okta_obo_for_an_enterprise_mcp_gateway.md) | OBO token exchange deep-dive |
| [`docs/enterprise_mcp_gateway_leadership_explainer.md`](docs/enterprise_mcp_gateway_leadership_explainer.md) | Non-technical stakeholder overview |

## License

See [LICENSE](LICENSE) for details.
