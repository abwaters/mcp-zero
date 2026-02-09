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

### 6. stdio Server Governance
**Threat:** Gateway-managed MCP servers spawned via stdio operate without governance or auditing.

**Mitigation:**
- When MCP servers are spawned by the gateway via stdio, governance policies, data masking, and audit logging apply identically to HTTP-connected servers
- The gateway wraps all stdio communication with the same policy evaluation, Presidio masking, and audit emission pipeline
- The enforcement boundary is the gateway, not the transport — stdio servers managed by the gateway receive the same controls as HTTP servers

---

## Threats Explicitly Accepted

### 1. Local Developer MCP Usage
**Risk:** Developers run MCP clients locally without gateway enforcement, including local stdio-based MCP servers not routed through the gateway.

**Rationale:**
- MCP protocol does not mandate centralized enforcement
- Endpoint control is out of scope for this product
- Local stdio connections between developer tools and MCP servers bypass the gateway entirely

**Compensating Controls:**
- Monitoring (e.g., CrowdStrike)
- Policy and developer education

---

### 2. Malicious Tool Logic
**Risk:** Approved MCP tools behave maliciously or unexpectedly.

**Rationale:**
- Gateway does not inspect tool intent or logic

**Compensating Controls:**
- Tool approval processes (outside MVP)
- Server ownership and reviews

---

### 3. Over-Masking or Under-Masking
**Risk:** Presidio misses sensitive data or masks too aggressively.

**Rationale:**
- NLP-based detection is probabilistic

**Compensating Controls:**
- Conservative masking policies
- Periodic review of detection rules

---

### 4. Denial of Service via Gateway
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
- stdio as a transport is not inherently less secure — the enforcement boundary is the gateway, not the wire protocol

---

## Summary
The MCP Gateway significantly reduces enterprise risk for MCP adoption while explicitly acknowledging and documenting residual risks that require complementary controls.

