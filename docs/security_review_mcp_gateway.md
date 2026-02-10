# MCP Gateway Security / Functional / Compliance Review

Date: 2026-02-10

## Review objective

Perform a deep code review of the MCP gateway implementation from three angles:

1. **Functional correctness and isolation** (multi-user correctness, failure behavior).
2. **Security posture** (authentication/authorization, token handling, transport security, error handling).
3. **Compliance readiness** (least privilege, auditability, secure defaults).

## Scope reviewed

- `src/mcp_zero/main.py`
- `src/mcp_zero/proxy/*`
- `src/mcp_zero/identity/*`
- `src/mcp_zero/transport/*`
- `src/mcp_zero/governance/*`
- `src/mcp_zero/audit/*`
- `src/mcp_zero/url_validation.py`

## Method and assumptions

- Static review of control flow and data flow.
- Focus on enterprise deployment patterns (multi-user, shared gateway process, policy-driven governance).
- Assumes gateway may run in either:
  - strict mode (identity+governance enabled), or
  - legacy/compat mode (policy not configured).

## Executive summary

The codebase has strong foundations: JWT signature validation via JWKS, fail-closed governance evaluation once enabled, HTTPS validation helpers, and output-masking fail-closed behavior.

However, there are **two critical issues** that can cause cross-user security boundary failures:

1. **Critical:** downstream HTTP sessions are cached per server, not per identity/token context.
2. **Critical:** OBO token cache key can collapse across users when inbound JWT `jti` is missing.

There are also high/medium risks related to secure defaults, information disclosure, and operational resilience.

## Findings matrix

| ID | Severity | Category | Title |
|---|---|---|---|
| F-01 | Critical | Security / Functional | Cross-user auth context reuse in cached downstream HTTP session |
| F-02 | Critical | Security | OBO cache key collision when `jti` is absent |
| F-03 | High | Security / Compliance | Secure controls can be silently disabled by startup config gaps |
| F-04 | High | Security / Functional | OBO-enabled route can degrade to unauthenticated upstream call |
| F-05 | Medium | Security | Client-visible token exchange errors may leak IdP/internal detail |
| F-06 | Medium | Security / Compliance | Tool inventory can be listed without authz guard |
| F-07 | Medium | Availability / Compliance | Unbounded in-memory audit event retention |
| F-08 | Informational | Security | HTTPS guardrails are present and materially improve posture |

---

## Detailed findings

### F-01 (Critical): Cross-user auth context reuse in cached downstream HTTP session

**What happens**

- `ServerManager` stores exactly one transport per configured server.
- `get_session()` only calls `transport.connect(...)` if the transport is not already connected.
- `StreamableHTTPTransport.connect()` binds Authorization and correlation headers when creating the underlying `httpx.AsyncClient`.
- Later requests to the same server reuse the already-connected session and its client headers.

**Impact**

In a shared gateway process, the first requester/token to establish the upstream HTTP session can set effective auth headers for subsequent users. This is a high-risk multi-tenant isolation break and can cause authorization confusion.

**Likelihood**

High in long-lived gateways with concurrent users.

**Recommended remediation**

- Prefer **per-request auth propagation** to upstream calls (no sticky bearer at transport connect time), or
- Maintain session pools keyed by strong subject context (`iss/sub/token thumbprint`) and rotate on token change.
- Add regression tests that assert user A and user B do not share upstream Authorization context.

---

### F-02 (Critical): OBO cache key collision when `jti` is absent

**What happens**

- `OBOAuthProvider` extracts `jti` from raw token without verification and returns empty string when absent/invalid.
- `OBOClient.ExchangeCacheKey` is derived from `(subject_jti, audience, scopes)`.
- Multiple distinct users with tokens lacking `jti` map to identical cache keys for same audience/scopes.

**Impact**

Cross-user token reuse: one user can receive another user’s exchanged token from cache.

**Likelihood**

Moderate to high, depending on IdP token profile (some providers omit `jti`).

**Recommended remediation**

- Require and enforce `jti` for OBO flows, failing closed if absent, **or**
- Build cache key from validated identity tuple (e.g., `iss + sub + aud + sorted(scopes)`), not unverified token parsing.
- Add tests for no-`jti` tokens to verify per-user isolation.

---

### F-03 (High): Secure controls can be silently disabled by startup config gaps

**What happens**

- If policy file is absent, startup falls back to legacy env behavior.
- If issuer/audience are missing, `_build_pipeline()` returns `None`, disabling identity+governance hooks.
- Gateway still starts and proxies requests.

**Impact**

Fail-open operational posture can violate enterprise access-control expectations and compliance controls (least privilege, authenticated access enforcement).

**Recommended remediation**

- Add a strict secure-by-default mode (or make it default): refuse startup unless identity+governance are configured.
- Require explicit opt-in for insecure/legacy mode.
- Emit machine-parsable startup posture logs/metrics indicating whether authn/authz are active.

---

### F-04 (High): OBO-enabled route can degrade to unauthenticated upstream call

**What happens**

- `OBOAuthProvider.get_token()` returns `None` when `context.raw_token` is missing.
- Caller then proceeds with upstream call without exchanged token.
- This can occur if identity pipeline is disabled or misconfigured while OBO-enabled servers exist.

**Impact**

Policy intent (“server requires token exchange”) may not be enforced at runtime; misconfigurations can silently degrade to weaker auth.

**Recommended remediation**

- Treat missing raw token on OBO-enabled server as hard deny (fail closed).
- Add startup validation: if any server has `token_exchange=true`, require identity pipeline enabled.

---

### F-05 (Medium): Client-visible token exchange errors may leak internals

**What happens**

- `ProxyServer` returns token exchange failures to client including exception string.
- `TokenExchangeError` may include HTTP status/body from IdP response.

**Impact**

Potential disclosure of provider-side diagnostics and internal integration details to untrusted callers.

**Recommended remediation**

- Return generic client error text.
- Keep detailed diagnostics in structured logs only, keyed by correlation ID.

---

### F-06 (Medium): Tool inventory can be listed without authz guard

**What happens**

- `_list_tools()` aggregates tools from all upstreams.
- No identity or governance hook execution is applied in the list path.

**Impact**

Metadata disclosure (tool names/descriptions) to unauthenticated/unauthorized callers. In some environments this is sensitive service discovery data.

**Recommended remediation**

- Apply identity/governance checks to `list_tools`, or
- Filter returned tools by policy decision for the requester.

---

### F-07 (Medium): Unbounded in-memory audit event retention

**What happens**

- `AuditHook` appends each event into `self._events` without bounds.

**Impact**

Long-running process can accumulate memory indefinitely (availability risk). Also raises data retention concerns if in-memory event history is not controlled.

**Recommended remediation**

- Use bounded ring buffer (debug/test only), or
- Disable in-memory retention in production and stream only to sink/logger.

---

### F-08 (Informational): HTTPS guardrails are present and meaningful

**Observation**

- `IdentityConfig`, `OBOConfig`, and `ServerConfig` enforce `https://` unless `allow_insecure=True`.
- This is a strong control against accidental plaintext token/identity transport in production.

**Residual risk**

- Environment-wide `MCP_ALLOW_INSECURE` can disable protections broadly. This should remain dev-only and operationally monitored.

## Functional observations (non-vuln)

- Retry/disconnect logic for upstream failures is sensible and helps transient fault recovery.
- Governance deny-overrides-allow semantics are clear and deterministic.
- Output masking fail-closed behavior is appropriate for sensitive data handling.

## Compliance perspective

### Positive alignment

- Strong basis for **access control** once identity+governance are enabled.
- Structured audit events with correlation IDs support traceability.
- HTTPS validation supports transport confidentiality requirements.

### Gaps to close for enterprise controls

- Enforce authenticated/authorized mode by default (no silent bypass).
- Fix cross-user token/session isolation defects (F-01/F-02) before production use.
- Reduce metadata disclosure (`list_tools`) and client-facing diagnostic leakage.
- Bound audit in-memory retention and define explicit retention/handling policy.

## Prioritized remediation plan

1. **Immediate (P0):** Fix F-01 and F-02 before production rollout.
2. **Near-term (P1):** Enforce strict startup posture and fail-closed OBO preconditions (F-03, F-04).
3. **Near-term (P1):** Harden external error responses and tool-list authorization (F-05, F-06).
4. **Short-term (P2):** Bound audit memory retention and document retention controls (F-07).
5. **Ongoing:** Monitor any use of insecure mode and alert on non-dev environments.

## Suggested validation tests after fixes

- Multi-user concurrency test proving no upstream Authorization/header bleed between users.
- OBO cache isolation test for tokens missing `jti` and distinct `sub` values.
- Startup posture tests ensuring strict mode blocks insecure configuration.
- Authorization tests for `list_tools` exposure boundaries.
- Load test verifying audit subsystem memory remains bounded.
