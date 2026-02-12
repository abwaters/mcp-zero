## Threat Model Canvas

This canvas documents **what the MCP Gateway mitigates** and **what risks are explicitly accepted**. It is designed for Security and Architecture Review Boards.

---

## Assets
- User identity and credentials
- Enterprise data accessed via MCP tools
- Audit logs and compliance evidence
- Governance policy definitions

---

## Threats Mitigated

### 1. Unauthorized Tool Access
**Threat:** Users or agents invoke MCP tools they should not have access to.

**Mitigation:**
- Default-deny governance policies
- Server- and tool-level allow lists
- User/group-based authorization

---

### 2. Loss of Attribution
**Threat:** MCP actions cannot be traced to a specific user.

**Mitigation:**
- OAuth2 user-interactive authentication
- Acting-as-user execution model
- User identity embedded in every audit event

---

### 3. Sensitive Data Exfiltration
**Threat:** PII or secrets are sent to external MCP servers.

**Mitigation:**
- Inline Presidio masking before tool invocation
- Inline masking on tool responses
- No persistence of unmasked data

---

### 4. Compliance Audit Gaps
**Threat:** Inability to demonstrate control over MCP usage.

**Mitigation:**
- Structured, comprehensive audit logging
- Policy decision capture (allow/deny)
- Correlation IDs for traceability

---

### 5. Shadow MCP Usage in Hosted AI
**Threat:** Hosted AI tools bypass governance controls.

**Mitigation:**
- Mandatory gateway enforcement for hosted enterprise AI tools

---

### 6. Unauthorized Tool Invocation
**Threat:** Users invoke tools on gateway-managed servers without proper authorization checks.

**Mitigation:**
- All tool calls (tools/call) run through the full enforcement pipeline (governance, masking, audit), regardless of transport (HTTP or stdio)
- Governance policies evaluate every tool invocation before execution
- Policy decisions (allow/deny) are audited with user attribution

**Limitation:**
- Tool listing (tools/list) does not enforce per-user authorization — all connected users can see the same tool catalog

---

### 7. On-Behalf-Of Token Exchange
**Threat:** HTTP MCP servers receive gateway credentials instead of user-scoped tokens.

**Mitigation:**
- OBO token exchange is available for HTTP servers when explicitly configured per-server
- When enabled, the gateway exchanges inbound user tokens for server-scoped tokens
- Downstream servers receive tokens that maintain user identity and scope

**Limitation:**
- OBO requires explicit per-server configuration in policy files (not automatic)
- stdio servers do not support OBO (process-local execution model)

---

## Threats Explicitly Accepted

### 1. Tool Discovery Information Disclosure
**Risk:** All authenticated users can see the full tool catalog via tools/list, regardless of per-user authorization rules.

**Rationale:**
- Current implementation does not enforce per-user authorization on tool listing
- Tool invocation (tools/call) remains protected by governance policies

**Compensating Controls:**
- Tool names and descriptions should not contain sensitive information
- Enforcement occurs at execution time (tools/call), preventing unauthorized usage

---

### 2. Local Developer MCP Usage
**Risk:** Developers run MCP clients locally without gateway enforcement, connecting directly to MCP servers outside the gateway.

**Rationale:**
- MCP protocol does not mandate centralized enforcement
- Endpoint control is out of scope for this product
- Direct client-to-server connections that bypass the gateway cannot be controlled by the gateway

**Compensating Controls:**
- Monitoring (e.g., CrowdStrike)
- Policy and developer education

---

### 3. Malicious Tool Logic
**Risk:** Approved MCP tools behave maliciously or unexpectedly.

**Rationale:**
- Gateway does not inspect tool intent or logic

**Compensating Controls:**
- Tool approval processes (outside MVP)
- Server ownership and reviews

---

### 4. Over-Masking or Under-Masking
**Risk:** Presidio misses sensitive data or masks too aggressively.

**Rationale:**
- NLP-based detection is probabilistic

**Compensating Controls:**
- Conservative masking policies
- Periodic review of detection rules

---

### 5. Denial of Service via Gateway
**Risk:** Gateway outage blocks MCP usage.

**Rationale:**
- Centralized enforcement introduces a control-plane dependency

**Compensating Controls:**
- High availability deployment
- Clear failure modes and alerts

---

## Non-Threats (Out of Scope)
- Endpoint compromise
- Insider threats outside MCP usage
- Full DLP or intent classification
- Transport-layer security (both HTTP and stdio support TLS/encryption at lower layers when needed)

---

## Summary
The MCP Gateway significantly reduces enterprise risk for MCP adoption while explicitly acknowledging and documenting residual risks that require complementary controls.

