## Security & Compliance Overview

### Purpose
This document defines the security and compliance posture of the Enterprise MCP Gateway without over-claiming controls beyond technical feasibility.

---

### Security Controls

#### Identity & Access
- OAuth2-based user authentication
- Okta as system of record
- User-scoped authorization enforced at gateway

#### Governance
- Explicit allow/deny policies
- Server- and tool-level controls
- Default-deny posture
- Governance applies across both HTTP and stdio transports

#### Data Protection
- Inline PII and secret masking using Microsoft Presidio
- No persistence of unmasked sensitive data

#### Auditing
- Comprehensive, structured audit logs
- User attribution on every action
- Policy decision capture

---

### Enforcement Model
- **Gateway-proxied traffic** (HTTP or stdio): hard enforcement — governance, masking, and auditing apply to all tool calls
- **On-Behalf-Of (OBO) token exchange**: available for HTTP servers when explicitly configured per-server in policy
- **Local developer usage** (outside gateway): observability-only — monitored through complementary controls
- No endpoint or device control claims

### Scope and Limitations

**Full Enforcement Pipeline Applies To:**
- All tool calls (tools/call) routed through the gateway, regardless of transport (HTTP or stdio)
- Governance policy evaluation (allow/deny)
- Data masking (PII and secrets via Presidio)
- Structured audit logging with user attribution

**Current Implementation Limitations:**
1. **Tool Discovery Bypass**: The tool listing endpoint (tools/list) does not run through the governance pipeline and cannot enforce per-user authorization rules
2. **OBO Token Exchange**: Requires explicit per-server configuration in policy files; not automatic
3. **stdio Transport Constraints**:
   - OBO token exchange is not applicable to stdio servers (process-local execution model)
   - stdio servers spawned by the gateway inherit the gateway's execution context rather than receiving downstream tokens

---

### Compliance Alignment (Indicative)
- SOC2: Access control, logging, change traceability
- SOX: Auditability of system actions
- HIPAA (supporting): Data minimization via masking

---

### Explicit Non-Claims
- Does not prevent all local MCP usage outside the gateway
- Does not enforce governance on direct client-to-server connections that bypass the gateway
- Does not provide DLP guarantees beyond inline masking
- Does not classify tool risk or intent
- Does not enforce authorization on tool listing (tools/list) — only on tool execution (tools/call)

---

### Risk Acceptance
Residual risk exists for developer-local MCP usage; mitigated through monitoring and policy.

