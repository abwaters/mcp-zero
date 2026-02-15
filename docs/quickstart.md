# Quickstart Guide

Get from zero to a running mcp-zero gateway in minutes. Pick the path that fits your situation:

- **Path A (Docker Compose)** — one command, batteries included, best for evaluation
- **Path B (Local Python)** — install into a venv, best for development or customization

## Prerequisites

| Requirement | Path A (Docker) | Path B (Local) |
|---|---|---|
| Docker + Docker Compose | Required | Not needed |
| Python 3.12+ | Not needed | Required |
| Node.js (for npx) | Included in image | Required |
| Okta tenant | Optional | Optional |

## Path A — Docker Compose (recommended for evaluation)

```bash
git clone https://github.com/abwaters/mcp-zero.git
cd mcp-zero
docker compose up
```

This starts three services:

| Service | Port | Purpose |
|---|---|---|
| **mcp-zero** | 8080 | The gateway, running `policies/everything.yaml` |
| **Redis** | 6379 | Analytics backend |
| **RedisInsight** | 5540 | Redis GUI at `http://localhost:5540` |

The Docker Compose configuration sets `MCP_ALLOW_INSECURE=true` and uses the `everything.yaml` policy with open access. **This is for dev/evaluation only — never run insecure mode in production.**

Skip ahead to [Run your first request](#run-your-first-request).

## Path B — Local Python install

```bash
git clone https://github.com/abwaters/mcp-zero.git
cd mcp-zero
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate

pip install -e ".[dev]"
```

On Windows, a convenience script does all of the above:

```bash
scripts\install.bat
```

## Run with a stdio server

The `policies/filesystem.yaml` policy spawns a local filesystem MCP server via npx — no external server needed.

**Linux/macOS:**

```bash
export MCP_POLICY_FILE=policies/filesystem.yaml
export MCP_ALLOW_INSECURE=true
python -m mcp_zero
```

Or use the convenience script:

```bash
scripts/run-policy.sh filesystem
```

**Windows:**

```cmd
set MCP_POLICY_FILE=policies\filesystem.yaml
set MCP_ALLOW_INSECURE=true
python -m mcp_zero
```

Or:

```cmd
scripts\run-policy.bat filesystem
```

The gateway starts on `http://localhost:8080`.

## Run your first request

With the gateway running, list available tools:

```bash
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
  }'
```

You should see a JSON response listing the tools exposed by the configured MCP server. For the `filesystem` policy, this includes tools like `read_file`, `write_file`, `list_directory`, and others.

### Call a tool

Create a test file, then read it through the gateway:

```bash
mkdir -p .data
echo "Hello from mcp-zero" > .data/test.txt

curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "read_file",
      "arguments": { "path": ".data/test.txt" }
    }
  }'
```

The response contains the file content, and the gateway logs show a structured audit entry with a correlation ID, policy decision, and timing.

## See the pipeline in action

### Audit logging

Every request produces a structured JSON audit log entry. Look at the gateway's console output — you'll see entries like:

```json
{
  "event": "mcp_request",
  "correlation_id": "a1b2c3d4-...",
  "method": "tools/call",
  "tool": "read_file",
  "policy_decision": "allow",
  "policy_rule": "allow-all",
  "duration_ms": 42
}
```

### PII masking demo

Switch to `policies/filesystem-redacted.yaml` to enable Presidio-based PII masking:

**Linux/macOS:**
```bash
export MCP_POLICY_FILE=policies/filesystem-redacted.yaml
export MCP_ALLOW_INSECURE=true
python -m mcp_zero
```

**Windows:**
```cmd
scripts\run-policy.bat filesystem-redacted
```

Create a file with PII and read it through the gateway:

```bash
echo "Contact John Smith at john@example.com or 555-123-4567" > .data/pii-test.txt

curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "read_file",
      "arguments": { "path": ".data/pii-test.txt" }
    }
  }'
```

The response shows masked content — names, emails, and phone numbers are redacted:

```
Contact <PERSON> at <EMAIL_ADDRESS> or <PHONE_NUMBER>
```

The `filesystem-redacted.yaml` policy enables the Presidio masking plugin for PERSON, EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, API_KEY, and PASSWORD entities.

### Analytics with RedisInsight

If you're using Docker Compose, analytics are automatically captured in Redis. Open RedisInsight at `http://localhost:5540` to browse gateway metrics — request counts, tool usage, latency, and more.

## Add identity (production path)

For production deployments, enable Okta JWT validation by adding an `identity` section to your policy file:

```yaml
identity:
  provider: okta
  issuer: https://your-org.okta.com
  audience: your-app-audience
```

Or set environment variables:

```bash
export OKTA_ISSUER=https://your-org.okta.com
export OKTA_AUDIENCE=your-app-audience
```

With identity enabled:
- Requests without a valid JWT are rejected
- Audit logs include user attribution (subject, groups)
- Policy rules can scope access by user or group

Remove `MCP_ALLOW_INSECURE=true` when identity is configured — the gateway enforces HTTPS and authentication by default.

For OBO (On-Behalf-Of) token exchange with downstream servers, see [`docs/okta_obo_for_an_enterprise_mcp_gateway.md`](okta_obo_for_an_enterprise_mcp_gateway.md).

## Example policies

The `policies/` directory includes ready-to-use policy files:

| Policy file | Description |
|---|---|
| `everything.yaml` | MCP `server-everything` via stdio — open access, all tools allowed |
| `filesystem.yaml` | MCP `server-filesystem` via stdio — exposes `.data/` directory |
| `filesystem-redacted.yaml` | Same as `filesystem.yaml` with Presidio PII masking enabled |
| `time.yaml` | MCP `server-time` via stdio — time and timezone tools |
| `all.yaml` | Combines everything, filesystem, and time servers in one policy |

All example policies use `default: allow` and `MCP_ALLOW_INSECURE=true` for easy evaluation. For production, switch to `default: deny` with explicit allow rules and enable identity validation.

## Next steps

- [Policy schema reference](enterprise_mcp_gateway_policy_schema_example.md) — full annotated policy file example
- [Plugin architecture](plugin-architecture-design.md) — extend the pipeline with custom hooks
- [Security and compliance](enterprise_mcp_gateway_security_compliance_positioning.md) — security controls and compliance alignment
- [Architecture diagram](enterprise_mcp_gateway_architecture_diagram.md) — logical component diagram
- [`policies/`](../policies/) — browse and customize example policies
