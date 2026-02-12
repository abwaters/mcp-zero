## Implementation Plan

### Phase 0 – Foundations ✅ COMPLETED
- ✅ Select language/runtime (Python)
- ✅ Define MCP gateway service contract (covering both HTTP and stdio transports)
- ✅ Define policy schema (YAML/JSON)
- ✅ Define audit event schema

---

### Phase 1 – Core Gateway (MVP) ✅ COMPLETED

#### Epic 1: Gateway Core ✅ COMPLETED
- ✅ Story: Implement streamable HTTP MCP proxy
- ✅ Story: Implement stdio transport for gateway-managed MCP servers
- ✅ Story: Transport abstraction layer (HTTP and stdio behind common interface)
- ✅ Story: Request/response lifecycle hooks (Pipeline architecture implemented)
- ✅ Story: Correlation ID propagation

**Status**: All core gateway functionality is implemented. Both HTTP and stdio transports support full policy enforcement, identity validation, masking, and auditing through the unified pipeline architecture.

#### Epic 2: Identity & Auth ✅ COMPLETED
- ✅ Story: Okta OAuth2 integration (JWKS-based JWT validation)
- ✅ Story: Token validation & user identity resolution
- ✅ Story: Acting-as-user token forwarding model (OBO token exchange - RFC 8693)

**Status**: Full identity and authentication system implemented with:
- JWT validation via JWKS endpoint
- OAuth2 Token Exchange (On-Behalf-Of) support
- Per-user session isolation (fixed in #50, #78)
- Subject-based OBO cache keys to prevent collision (fixed in #51, #77)

#### Epic 3: Governance Engine ✅ COMPLETED
- ✅ Story: Policy file loader & validator
- ✅ Story: Policy evaluation engine (server/tool/user)
- ✅ Story: Allow/deny enforcement (deny-overrides-allow semantics)

**Status**: Policy engine fully operational with:
- YAML/JSON policy file support
- Server, tool, user, and group-level controls
- Wildcard matching support
- Fail-closed enforcement on both HTTP and stdio transports

#### Epic 4: Presidio Integration ✅ COMPLETED
- ✅ Story: Presidio plugin interface
- ✅ Story: Inline input masking
- ✅ Story: Inline output masking
- ✅ Story: Masked logging guarantees (fail-closed on masking errors)

**Status**: Full PII masking implementation with:
- Plugin-based masking architecture
- Presidio integration via `presidio-analyzer` and `presidio-anonymizer`
- Configurable entity types
- Fail-closed behavior to prevent unmasked data leakage

#### Epic 5: Auditing & Logging ✅ COMPLETED
- ✅ Story: Structured audit event emitter
- ✅ Story: Stdout logging compatibility (EKS)
- ✅ Story: Correlation & trace IDs
- ✅ Story: Bounded in-memory retention (fixed in #55, #80)

**Status**: Comprehensive audit system with:
- Structured JSON audit events
- Multiple event types (TOOL_INVOCATION, POLICY_DECISION, MASKING_APPLIED, etc.)
- Correlation and trace ID propagation to both HTTP and stdio upstreams
- Bounded in-memory event retention with configurable limits

---

### Phase 2 – Hardening 🔄 IN PROGRESS

#### Completed Hardening Items ✅
- ✅ Per-user session isolation (prevents credential reuse across users)
- ✅ OBO cache key collision fixes (uses validated subject identity)
- ✅ Generic error responses (prevents IdP detail leakage - fixed in #54, #79)
- ✅ Bounded audit retention (prevents unbounded memory growth)
- ✅ Plugin architecture with entry-point loading (#89)
- ✅ Comprehensive stdio integration tests (#87)
- ✅ HTTPS URL validation with secure defaults
- ✅ Retry/reconnection logic for transient failures

#### Remaining Hardening Items 🔄
- 🔄 **Analytics/Redis Integration**: Redis-backed operational metrics (implemented but marked as optional/expansion feature)
- ⚠️ **Tool listing authorization**: `list_tools` currently bypasses identity/governance pipeline (known issue)
- ⚠️ **Strict security mode**: Optional fail-closed startup validation (governance can be silently disabled via config gaps)
- 📋 Documentation & runbooks (in progress)

---

### Phase 3 – Analytics & Observability 🆕 PARTIALLY COMPLETED

#### Epic 6: Analytics Subsystem ✅ IMPLEMENTED (Optional Feature)
- ✅ Story: Redis-backed metrics collection
- ✅ Story: Tool call analytics (volume, latency, payload sizes)
- ✅ Story: Denial tracking by reason category
- ✅ Story: Redaction/masking metrics
- ✅ Story: Gateway heartbeat tracking
- ✅ Story: Time-bucketed aggregation with TTL

**Status**: Full analytics implementation merged (#82). Disabled by default; enabled when `ANALYTICS_REDIS_URL` is configured. Provides operational visibility into gateway usage patterns, policy decisions, and data protection actions.

---

### Non-Goals (Explicit)
- UI or admin console
- Policy approval workflows
- Dynamic policy updates
- Tool risk classification
- ~~Local developer enforcement~~ **NOTE**: Both HTTP and stdio transports DO enforce governance, identity, and masking when pipeline is configured. Only observability-only mode exists when identity/governance are not configured.

