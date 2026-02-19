## Policy Schema Example (YAML)

This example shows a **static, Git-managed policy file** suitable for MVP. It is intentionally explicit and default-deny.

```yaml
version: 1

default: deny

identity:
  provider: okta
  issuer: https://your-org.okta.com/oauth2/default
  audience: mcp-gateway
  # Optional: map non-standard JWT claim names to gateway identity fields.
  # Defaults shown — omit this section if your token uses standard claim names.
  claim_mapping:
    user_id: sub      # claim that identifies the user (default: "sub")
    email: email      # claim for user email (default: "email")
    groups: groups    # claim for group membership (default: "groups")

# Server connection registry — declares how the gateway reaches each MCP server
servers:
  - name: internal-infra-mcp
    transport: http
    url: https://infra-mcp.internal.corp/mcp
  - name: github-mcp
    transport: http
    url: https://github-mcp.internal.corp/mcp
    # OBO token exchange — forward a user-specific token to the downstream server.
    # Requires OKTA_TOKEN_ENDPOINT, OKTA_CLIENT_ID, OKTA_CLIENT_SECRET env vars.
    token_exchange: true                  # enable OBO for this server
    target_audience: api://github-mcp    # audience for the exchanged token
    required_scopes:                      # scopes to request in the exchanged token
      - mcp.read
    allow_insecure: false                 # set true only to disable HTTPS enforcement (dev only)

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

# Plugin declarations — configure pipeline extension hooks loaded via Python entry points.
# Each entry loads one plugin from the mcp_zero.plugins entry-point group.
plugins:
  - name: presidio-masking    # human-readable identifier; used as entry-point key if package omitted
    # package: presidio-masking  # entry-point name (defaults to name if omitted)
    config:
      entities:
        - PERSON
        - EMAIL_ADDRESS
        - PHONE_NUMBER
        - CREDIT_CARD
        - API_KEY
        - PASSWORD
    # priority: 75  # optional hook priority override (default: plugin-defined)

# Analytics — optional Redis-based metrics subsystem.
# Disabled when omitted. Fields can also be set via ANALYTICS_* environment variables.
analytics:
  redis:
    url: "redis://localhost:6379/0"  # Redis connection URL
    cluster: false                   # set true for Redis Cluster
    tls: false                       # enable TLS
    password: null                   # optional auth password
    socket_timeout: 5.0              # connection timeout in seconds
    retry_on_timeout: true
  environment: "production"          # key namespace segment (e.g. production, staging)
  gateway_id: "gateway-east-1"      # unique instance ID (auto-generated UUID if omitted)
  key_prefix: "mcpgw"               # Redis key prefix
  bucket_seconds: 60                 # time bucket width for counters
  retention_seconds: 3600            # TTL for all analytics keys
  heartbeat_seconds: 30              # gateway heartbeat interval
  queue_size: 10000                  # max in-memory event queue depth
  flush_interval: 1.0                # background flush interval in seconds
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
- **`claim_mapping`** — Optional mapping from JWT claim names to gateway identity fields. Useful when your IdP uses non-standard claim names (e.g., `preferred_username` instead of `sub`). Supported keys: `user_id`, `email`, `groups`
- **OBO token exchange** — Set `token_exchange: true` on a server to enable On-Behalf-Of token forwarding to that server. Requires `OKTA_TOKEN_ENDPOINT`, `OKTA_CLIENT_ID`, and `OKTA_CLIENT_SECRET` environment variables. See `docs/okta_obo_for_an_enterprise_mcp_gateway.md` for details
- **Plugins vs masking** — The `plugins:` section is the preferred way to configure masking. A legacy `masking:` section is also supported but the plugin-based approach is more flexible and extensible
- **Analytics** — The `analytics:` section is optional and disabled when omitted. Analytics activates only when a Redis URL is configured (via policy file or `ANALYTICS_REDIS_URL` env var)
