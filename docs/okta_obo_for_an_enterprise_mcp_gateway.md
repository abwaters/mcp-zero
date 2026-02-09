## Okta OBO (On-Behalf-Of) Explained for an Enterprise MCP Gateway

This document explains **On-Behalf-Of (OBO)** token exchange in the specific context of:
- Okta as the IdP
- An Enterprise MCP Gateway deployed in the enterprise network
- A requirement to execute MCP tool calls **as the current user**

---

## 1) What OBO Is (Precise Definition)

**OBO is a delegated-authorization pattern** where a trusted backend exchanges a **user token** issued for one audience (resource) into a **new user token** issued for a different audience (downstream resource).

The result is a downstream call that:
- still represents the same user
- is constrained by the user’s delegated permissions
- is valid for the downstream system (correct audience/scope)

---

## 2) Why OBO Exists (Problem OBO Solves)

In enterprises, a user token is usually minted for a specific resource (audience), such as:
- enterprise-ai
- internal-agent
- chat-tool

Downstream APIs/MCP servers typically require tokens minted for *their* audience, such as:
- github-mcp
- internal-infra-mcp
- jira-mcp

If you forward the original token, the downstream resource may reject it (wrong audience/scopes). If you use a service account, you lose user attribution and least privilege.

OBO is the standard way to preserve user identity and permissions across service boundaries.

---

## 3) OBO in MCP Gateway Terms

### Actors
- **User**: authenticates interactively
- **Enterprise AI Tool**: primary client UX
- **Okta**: authorization server
- **MCP Gateway**: trusted intermediary
- **MCP Server**: downstream resource/API

### Tokens
- **Token A**: user token for the Enterprise AI Tool audience
- **Token B**: user token for the MCP server audience (minted via OBO)

---

## 4) End-to-End Sequence Diagram (Recommended Pattern)

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant A as Enterprise AI Tool
    participant O as Okta Authorization Server
    participant G as MCP Gateway
    participant S as MCP Server (Downstream)

    U->>A: Sign in (interactive)
    A->>O: OAuth2 Authorization Code
    O-->>A: Access Token A (aud=enterprise-ai)

    A->>G: MCP request + Token A
    G->>G: Validate Token A (sig/iss/aud/exp)
    G->>G: Evaluate policy (server/tool/user/group)
    G->>G: Inline mask input (Presidio)

    G->>O: Token Exchange (OBO) using Token A
    O-->>G: Access Token B (aud=mcp-server, scoped)

    G->>S: MCP call + Token B (as user)
    S-->>G: MCP response

    G->>G: Inline mask output (Presidio)
    G-->>A: Response (masked) + audit log emitted
```

---

## 4.5) Transport Applicability

OBO token exchange is designed for service-to-service boundaries. Its applicability depends on the MCP transport:

### HTTP-based MCP servers
- OBO applies directly — the gateway exchanges the user's token for a downstream token scoped to the MCP server's audience
- This is the primary OBO use case described in this document

### stdio-based MCP servers (gateway-managed)
- The MCP server runs as a subprocess of the gateway — there is no network boundary or separate audience
- OBO token exchange is **not needed** for stdio servers; the gateway propagates user identity via its own process context
- Governance and audit attribution are maintained by the gateway wrapping all stdio communication with the same policy evaluation and audit pipeline
- If a stdio-managed MCP server needs to make its own downstream HTTP calls, the gateway can provide delegated credentials through environment or configuration

### Key principle
Governance and audit attribution are maintained regardless of transport. OBO solves the specific problem of crossing audience boundaries over HTTP; stdio servers under gateway management do not cross that boundary.

---

## 5) Forward vs Exchange (Decision Rule)

### Forward the user token (Token A) when:
- the MCP server accepts Token A (correct audience)
- the resource server trusts the same Okta authorization server
- scopes/claims are already sufficient

### Use OBO token exchange when:
- the MCP server requires a different audience
- you need different scopes
- you need stricter isolation per downstream system
- you are calling external/third-party MCP servers behind an API gateway

### stdio transport (gateway-managed servers):
- Token forwarding and exchange are **not applicable** — the server runs as a gateway subprocess
- User identity is maintained via the gateway's process context
- If the stdio server needs to call downstream HTTP APIs, the gateway can inject delegated credentials via environment or configuration

Practical enterprise default: **prefer exchange** for HTTP downstream calls; **rely on gateway process context** for stdio servers.

---

## 6) Good vs Bad Examples

### Good Example: OBO (Delegated User)
**Scenario:** Developer uses MCP to read GitHub issues.
- User logs into enterprise AI tool
- Gateway validates user
- Gateway exchanges for a github-mcp token
- GitHub MCP server logs action as the user

**Why it’s good**
- Attribution preserved
- Least privilege enforced
- Auditable by user/group/scope

---

### Bad Example: Service Account (Non-Delegated)
**Scenario:** Gateway uses a single service account to call all MCP servers.

**What goes wrong**
- Downstream systems see “gateway-service” not the user
- Audits cannot prove who did what
- A compromise becomes catastrophic (broad permissions)
- Security teams will block this model

---

### Bad Example: Forwarding Wrong-Audience Tokens
**Scenario:** Gateway forwards Token A to a downstream system expecting Token B.

**What goes wrong**
- Downstream rejects calls (audience mismatch)
- Teams work around by disabling token checks
- Security posture degrades

---

## 7) Security Explainer (How to Defend OBO)

### What Security Usually Asks
1. Does this preserve user identity?
2. Can the gateway mint tokens for any user?
3. Is privilege constrained per resource?
4. Is this auditable?

### Security Answers
- OBO **requires a real user token** as the assertion.
- The gateway cannot act for users who are not authenticated.
- The authorization server enforces:
  - which clients can perform exchange
  - which audiences are allowed
  - which scopes are granted
- Every request can be logged:
  - original user identity
  - target audience/scope
  - policy decision

### Security Posture Summary
OBO is **delegated authorization**, not impersonation.

---

## 8) Okta-Specific Implementation Notes (Conceptual)

To support OBO in Okta, you typically need:
- A **Custom Authorization Server** (API Access Management)
- Token exchange enabled/allowed for the gateway client
- Audience and scope design per MCP server
- Group claims configured (if governance relies on groups)

Your gateway should treat Okta as the token issuer and be able to:
- validate incoming access tokens (JWT validation)
- exchange tokens for downstream audiences
- cache exchange results safely (short TTL)

---

## 9) Operational & Failure Modes

### If token exchange fails
- Deny the request
- Emit an audit event with reason

### If Presidio fails
- Recommended default: deny (fail closed) for external MCP servers
- Log reason and correlation ID

### If policy file invalid
- Fail startup
- Prevent silent permissive behavior

---

## 10) Practical Guidance for Your MCP Gateway MVP

MVP recommendation:
- Implement exchange as a pluggable module
- Support per-server configuration:
  - forward vs exchange
  - target audience
  - required scopes
- Log both:
  - upstream user token subject
  - downstream audience/scope

---

## 11) Short Executive Explanation

“OBO lets the gateway call downstream MCP servers with a token that represents the same user, but scoped and audience-bound to that downstream system, so Security can approve MCP usage without losing attribution or least privilege.”

