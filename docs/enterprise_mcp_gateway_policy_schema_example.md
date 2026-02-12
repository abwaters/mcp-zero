## Policy Schema Example (YAML)

This example shows a **static, Git-managed policy file** suitable for MVP. It is intentionally explicit and default-deny.

```yaml
version: 1

default: deny

identity:
  provider: okta
  issuer: https://your-org.okta.com/oauth2/default
  audience: mcp-gateway

# Server connection registry — declares how the gateway reaches each MCP server
servers:
  - name: internal-infra-mcp
    transport: http
    url: https://infra-mcp.internal.corp/mcp
  - name: github-mcp
    transport: http
    url: https://github-mcp.internal.corp/mcp

policies:
  - id: allow-platform-ops-internal-tools
    description: Allow Platform Ops to use approved internal MCP tools
    effect: allow
    subjects:
      groups:
        - platform-ops
        - sre
    mcp_servers:
      - name: internal-infra-mcp
        tools:
          - read_logs
          - query_metrics
          - restart_service

  - id: allow-dev-readonly-external
    description: Allow developers to use read-only external MCP tools
    effect: allow
    subjects:
      groups:
        - developers
    mcp_servers:
      - name: github-mcp
        tools:
          - list_repos
          - read_issues
          - read_pull_requests

  - id: deny-destructive-external
    description: Explicitly deny destructive tools on external MCP servers
    effect: deny
    subjects:
      groups:
        - '*'
    mcp_servers:
      - name: '*'
        tools:
          - delete_*
          - write_*

logging:
  level: INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  format: json  # json (default) or text for human-readable output

masking:
  presidio:
    enabled: true  # Requires separate Presidio plugin installation
    entities:
      - PERSON
      - EMAIL_ADDRESS
      - PHONE_NUMBER
      - CREDIT_CARD
      - API_KEY
      - PASSWORD
```

---

## Design Notes
- Policies are evaluated top-down
- Explicit deny overrides allow
- Wildcards allowed for tools and servers
- No dynamic reload in MVP (restart required)
- Group membership is resolved from Okta token claims
- **HTTP servers only** — Only HTTP servers can be configured in policy files. stdio servers are spawned dynamically by the gateway and are not configured through policy
- **Governance applies to all transports** — Policy enforcement applies equally whether the gateway connects to a server via HTTP or spawns it via stdio
- **Identity configuration** — The `identity` section requires `issuer` and `audience` for JWT validation, in addition to the provider name

