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
- **Gateway-proxied HTTP**: hard enforcement — full governance, OBO, masking, auditing
- **Gateway-managed stdio**: hard enforcement — governance, masking, and auditing apply identically to spawned MCP server processes
- **Local developer stdio** (outside gateway): observability-only — monitored through complementary controls
- No endpoint or device control claims

---

### Compliance Alignment (Indicative)
- SOC2: Access control, logging, change traceability
- SOX: Auditability of system actions
- HIPAA (supporting): Data minimization via masking

---

### Explicit Non-Claims
- Does not prevent all local MCP usage
- Does not enforce governance on stdio transport outside the gateway (e.g., local developer MCP clients connecting directly to stdio servers)
- Does not provide DLP guarantees beyond masking
- Does not classify tool risk or intent

---

### Risk Acceptance
Residual risk exists for developer-local MCP usage; mitigated through monitoring and policy.

