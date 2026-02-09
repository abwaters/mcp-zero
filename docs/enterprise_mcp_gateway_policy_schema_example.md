## Policy Schema Example (YAML)

This example shows a **static, Git-managed policy file** suitable for MVP. It is intentionally explicit and default-deny.

```yaml
version: 1

default: deny

identity:
  provider: okta
  claim_mapping:
    user_id: sub
    email: email
    groups: groups

# Server connection registry — declares how the gateway reaches each MCP server
servers:
  - name: internal-infra-mcp
    transport: http
    url: https://infra-mcp.internal.corp/mcp
  - name: github-mcp
    transport: http
    url: https://github-mcp.internal.corp/mcp
  - name: audit-mcp
    transport: stdio
    command: /usr/local/bin/audit-mcp-server
    args: ["--config", "/etc/audit-mcp/config.yaml"]
  - name: local-tools-mcp
    transport: stdio
    command: /usr/local/bin/local-tools-server

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

  - id: allow-security-audit
    description: Allow Security team to run audit tools
    effect: allow
    subjects:
      groups:
        - security
        - compliance
    mcp_servers:
      - name: audit-mcp
        tools:
          - generate_audit_report
          - list_access_events

  - id: allow-dev-local-tools
    description: Allow developers to use gateway-managed local tools
    effect: allow
    subjects:
      groups:
        - developers
    mcp_servers:
      - name: local-tools-mcp
        tools:
          - format_code
          - lint_project

logging:
  level: info
  include:
    - user
    - groups
    - mcp_server
    - tool
    - decision
    - correlation_id
    - transport

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

---

## Design Notes
- Policies are evaluated top-down
- Explicit deny overrides allow
- Wildcards allowed for tools and servers
- No dynamic reload in MVP (restart required)
- Group membership is resolved from Okta token claims
- **Transport type** is declared in the `servers` section for connection configuration; it is informational for policy purposes — governance applies equally regardless of whether the server uses HTTP or stdio
- For `http` servers: `url` specifies the server endpoint
- For `stdio` servers: `command` and optional `args` specify the process to spawn

