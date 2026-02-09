## Implementation Plan

### Phase 0 – Foundations
- Select language/runtime (Python)
- Define MCP gateway service contract (covering both HTTP and stdio transports)
- Define policy schema (YAML/JSON)
- Define audit event schema

---

### Phase 1 – Core Gateway (MVP)

#### Epic 1: Gateway Core
- Story: Implement streamable HTTP MCP proxy
- Story: Implement stdio transport for gateway-managed MCP servers
- Story: Transport abstraction layer (HTTP and stdio behind common interface)
- Story: Request/response lifecycle hooks
- Story: Correlation ID propagation

#### Epic 2: Identity & Auth
- Story: Okta OAuth2 integration
- Story: Token validation & user identity resolution
- Story: Acting-as-user token forwarding model

#### Epic 3: Governance Engine
- Story: Policy file loader & validator
- Story: Policy evaluation engine (server/tool/user)
- Story: Allow/deny enforcement

#### Epic 4: Presidio Integration
- Story: Presidio plugin interface
- Story: Inline input masking
- Story: Inline output masking
- Story: Masked logging guarantees

#### Epic 5: Auditing & Logging
- Story: Structured audit event emitter
- Story: Stdout logging compatibility (EKS)
- Story: Correlation & trace IDs

---

### Phase 2 – Hardening
- Performance tuning
- Failure modes & fallbacks
- Documentation & runbooks

---

### Non-Goals (Explicit)
- UI or admin console
- Policy approval workflows
- Dynamic policy updates
- Tool risk classification
- Local developer enforcement

