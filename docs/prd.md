## Product Requirements Document (PRD)

### Title  
Enterprise MCP Gateway for Governance, Auditing, and Data Protection

### Author  
Bryan

### Version  
1.0 (MVP)

---

### Summary  
The Enterprise MCP Gateway is a centrally hosted, cloud-based gateway deployed inside the enterprise network that enables secure, compliant use of the Model Context Protocol (MCP) in regulated environments.

Its primary goal is to unblock MCP adoption for enterprise AI tools by providing:
- Governance controls over which MCP servers and tools may be used
- User-scoped authorization using OAuth2 (acting as the current user)
- Comprehensive auditing and logging for security and compliance
- Inline data protection via secret and PII masking using Microsoft Presidio

The gateway provides hard enforcement for hosted enterprise AI tools and observability-only coverage for local developer usage, acknowledging technical limits while still delivering compliance value.

---

### Core User Flow  
1. User interacts with an enterprise AI tool.
2. User authenticates via OAuth2 (Okta).
3. AI tool sends MCP requests through the gateway.
4. Gateway authenticates, evaluates policy, masks sensitive data, and proxies request as user.
5. MCP server executes and returns response.
6. Gateway masks response, logs audit event, and returns output.

---

### Functional Requirements  

#### Identity & Authentication
- Okta integration
- OAuth2 Authorization Code flow (primary)
- Gateway validates user identity via JWT with On-Behalf-Of (OBO) token exchange (RFC 8693, fully implemented — requires explicit configuration)

#### Governance
- Static YAML/JSON policy configuration
- Allow/deny by server, tool, user/group/role
- Synchronous policy evaluation

#### MCP Support
- Full MCP spec support (tools, resources, prompts, sampling)
- Streamable HTTP, SSE (deprecated, for backward compatibility), and stdio transport
- First- and third-party MCP servers
- Best-effort compatibility with MCP spec changes

#### Auditing & Logging
- Structured audit logs including user, tool, policy decision, timestamps
- Logs emitted via stdout

#### Data Protection
- Inline Presidio masking on inputs and outputs
- Mask PII and secrets
- Masked-only persistence

#### Enforcement
- Hard enforcement for hosted enterprise tools
- Observability-only for local usage

#### Transport & Enforcement Model
- **HTTP / Streamable HTTP**: primary enforcement path — full governance, OBO token exchange, data masking, and auditing
- **SSE (deprecated)**: backward-compatible transport for clients/servers that haven't adopted Streamable HTTP — full pipeline enforcement (identity, governance, masking, audit). Controlled by `MCP_SSE_ENABLED` env var (default: `true`)
- **stdio (gateway-managed)**: supported for gateway-spawned MCP server processes — governance, masking, and auditing enforced through the same pipeline as HTTP
- **Local developer stdio**: observability-only — local stdio-based MCP usage outside the gateway is not enforced; monitored through complementary controls

---

### Expected Behavior  
- Disallowed tools are blocked
- Sensitive data is masked before leaving the enterprise boundary
- All actions are logged

---

### Design / UI Components  
- MVP: No UI (config + logs)
- Future: Admin console, approvals, dynamic policy

---

### Acceptance Criteria (Gherkin)
```gherkin
Given an authenticated user
When the user invokes an allowed MCP tool
Then the gateway forwards the request as the user
And masks sensitive data inline
And logs the action with policy decision "allow"

Given an authenticated user
When the user invokes a disallowed MCP tool
Then the gateway blocks the request
And logs the action with policy decision "deny"
```

---

### Success Metrics
- MCP adoption in enterprise AI tools
- 100% audited MCP traffic
- Zero unmasked sensitive data in logs

---

## Implementation Status

### Implemented (MVP)
- ✅ Okta JWT validation
- ✅ YAML/JSON policy configuration
- ✅ Policy evaluation (allow/deny by server, tool, user, group)
- ✅ Presidio masking on HTTP requests (inputs and outputs)
- ✅ Structured audit logging
- ✅ HTTP transport with full pipeline enforcement
- ✅ stdio transport with full enforcement (verified via integration tests)
- ✅ OBO token exchange (fully implemented and operational - requires explicit env var configuration. See [docs/okta_obo_for_an_enterprise_mcp_gateway.md](okta_obo_for_an_enterprise_mcp_gateway.md))
- ✅ Plugin architecture (entry point discovery, hook registration, lifecycle management. See [docs/plugin-architecture-design.md](plugin-architecture-design.md))
- ✅ Analytics/Redis integration (time-bucketed metrics, gateway registry, heartbeat. See [docs/analytics-redis-plan.md](analytics-redis-plan.md))
- ✅ SSE transport support (inbound + outbound, deprecated but available for backward compat. See [docs/plan-sse-support.md](plan-sse-support.md))
- ✅ GitHub repo filter plugin (allowlist/blocklist on GitHub repository access. See [docs/plugins/github-repo-filter.md](plugins/github-repo-filter.md))

### Partially Implemented
- ⚠️ Presidio masking extraction as standalone plugin (Presidio is currently a built-in plugin in core package, not extracted to separate `mcp-zero-presidio` package)

### Planned / Not Implemented
- ❌ Policy authoring UI
- ❌ Dynamic policy reloading
- ❌ Example plugins (rate limiting, OpenTelemetry, regex masking)

