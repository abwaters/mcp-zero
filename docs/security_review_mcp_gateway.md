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

**UPDATE 2026-02-12**: The two critical cross-user security boundary issues have been **RESOLVED** through fixes merged in January 2026:
- ✅ F-01: Fixed in PR #50 and #78 — sessions now isolated per `(server_name, subject_id)`
- ✅ F-02: Fixed in PR #51 and #77 — OBO cache now uses validated `subject_id` from JWT claims

The codebase has strong foundations: JWT signature validation via JWKS, fail-closed governance evaluation once enabled, HTTPS validation helpers, and output-masking fail-closed behavior.

**Remaining issues** (high/medium severity) relate to:
1. Secure defaults and fail-open configuration fallbacks (F-03, F-04)
2. Information disclosure via tool listing and error responses (F-05, F-06)
3. Operational resilience (F-07 — partially resolved with bounded retention)

## Findings matrix

| ID | Severity | Category | Title | Status |
|---|---|---|---|---|
| F-01 | ~~Critical~~ | Security / Functional | Cross-user auth context reuse in cached downstream HTTP session | ✅ **RESOLVED** (PR #50, #78) |
| F-02 | ~~Critical~~ | Security | OBO cache key collision when `jti` is absent | ✅ **RESOLVED** (PR #51, #77) |
| F-03 | High | Security / Compliance | Secure controls can be silently disabled by startup config gaps | ⚠️ **OPEN** |
| F-04 | High | Security / Functional | OBO-enabled route can degrade to unauthenticated upstream call | ⚠️ **OPEN** |
| F-05 | ~~Medium~~ | Security | Client-visible token exchange errors may leak IdP/internal detail | ✅ **RESOLVED** (PR #54, #79) |
| F-06 | Medium | Security / Compliance | Tool inventory can be listed without authz guard | ⚠️ **OPEN** |
| F-07 | ~~Medium~~ | Availability / Compliance | Unbounded in-memory audit event retention | ✅ **RESOLVED** (PR #55, #80) |
| F-08 | Informational | Security | HTTPS guardrails are present and materially improve posture | ✅ **CONFIRMED** |

---

## Detailed findings

### F-01 (Critical): Cross-user auth context reuse in cached downstream HTTP session ✅ RESOLVED

**Status**: ✅ **RESOLVED** in PR #50 and #78 (January 2026)

**What happened (original finding)**

- `ServerManager` stored exactly one transport per configured server.
- `get_session()` only called `transport.connect(...)` if the transport was not already connected.
- `StreamableHTTPTransport.connect()` bound Authorization and correlation headers when creating the underlying `httpx.AsyncClient`.
- Later requests to the same server reused the already-connected session and its client headers.

**Impact (original)**

In a shared gateway process, the first requester/token to establish the upstream HTTP session could set effective auth headers for subsequent users. This was a high-risk multi-tenant isolation break that could cause authorization confusion.

**Resolution**

`ServerManager` now maintains transport pools keyed by `(server_name, subject_id)` tuple (see `_SessionKey` dataclass). Each authenticated user gets an isolated transport with their own auth context. The `get_session()` method extracts `subject_id` from `context.identity.user_id` and creates per-user transports. Unauthenticated requests (no identity) share a single transport per server.

---

### F-02 (Critical): OBO cache key collision when `jti` is absent ✅ RESOLVED

**Status**: ✅ **RESOLVED** in PR #51 and #77 (January 2026)

**What happened (original finding)**

- `OBOAuthProvider` extracted `jti` from raw token without verification and returned empty string when absent/invalid.
- `OBOClient.ExchangeCacheKey` was derived from `(subject_jti, audience, scopes)`.
- Multiple distinct users with tokens lacking `jti` mapped to identical cache keys for same audience/scopes.

**Impact (original)**

Cross-user token reuse: one user could receive another user's exchanged token from cache.

**Resolution**

`ExchangeCacheKey` now uses validated `subject_id` (the `sub` claim from the JWT after validation) instead of `jti`. The cache key is now `(subject_id, target_audience, scopes)` tuple. The `OBOClient.exchange_token()` method accepts `subject_id` as a parameter extracted from validated identity context, preventing cache collisions even when tokens lack `jti` claims. See GitHub issue #51 for full discussion.

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

### F-05 (Medium): Client-visible token exchange errors may leak internals ✅ RESOLVED

**Status**: ✅ **RESOLVED** in PR #54 and #79 (January 2026)

**What happened (original finding)**

- `ProxyServer` returned token exchange failures to client including exception string.
- `TokenExchangeError` could include HTTP status/body from IdP response.

**Impact (original)**

Potential disclosure of provider-side diagnostics and internal integration details to untrusted callers.

**Resolution**

Token exchange errors now return a generic "Access denied" message to the client with only the correlation ID for tracking. The full exception details (HTTP status, IdP response body, etc.) are logged server-side using `logger.warning()` with `exc_info=True`, keyed by correlation ID. See `proxy_server.py` lines 137-150.

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

### F-07 (Medium): Unbounded in-memory audit event retention ✅ RESOLVED

**Status**: ✅ **RESOLVED** in PR #55 and #80 (January 2026)

**What happened (original finding)**

- `AuditHook` appended each event into `self._events` without bounds.

**Impact (original)**

Long-running process could accumulate memory indefinitely (availability risk). Also raised data retention concerns if in-memory event history was not controlled.

**Resolution**

`AuditHook` now supports configurable retention limits. The hook maintains a bounded event list with a configurable maximum size (defaults to retain recent events for testing/debugging while preventing unbounded growth). When the limit is reached, oldest events are discarded. Production deployments can disable in-memory retention entirely by setting the limit to 0, relying solely on structured log output.

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

### ✅ Completed (January 2026)
1. ~~**Immediate (P0):** Fix F-01 and F-02 before production rollout.~~ ✅ **COMPLETED** (PR #50, #51, #77, #78)
2. ~~**Near-term (P1):** Harden external error responses (F-05).~~ ✅ **COMPLETED** (PR #54, #79)
3. ~~**Short-term (P2):** Bound audit memory retention (F-07).~~ ✅ **COMPLETED** (PR #55, #80)

### ⚠️ Remaining Work (February 2026)
1. **High Priority (P1):** Enforce strict startup posture and fail-closed OBO preconditions (F-03, F-04).
   - Add strict security mode that refuses startup when identity/governance are incomplete
   - Emit clear startup logs indicating security posture (authenticated/unauthenticated mode)
   - Require explicit opt-in for legacy/insecure mode

2. **Medium Priority (P1):** Implement tool-list authorization (F-06).
   - Apply identity/governance pipeline to `list_tools` method
   - Filter returned tools by policy decision for the requester
   - Consider separate `list_tools` capability in policy schema

3. **Ongoing:** Monitor any use of insecure mode and alert on non-dev environments.

## Suggested validation tests after fixes

- Multi-user concurrency test proving no upstream Authorization/header bleed between users.
- OBO cache isolation test for tokens missing `jti` and distinct `sub` values.
- Startup posture tests ensuring strict mode blocks insecure configuration.
- Authorization tests for `list_tools` exposure boundaries.
- Load test verifying audit subsystem memory remains bounded.
