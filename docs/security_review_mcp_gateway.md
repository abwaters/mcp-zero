# MCP Gateway Deep Security / Functional / Compliance Review

Date: 2026-02-10
Reviewed commit: `3162c0c`

## Refresh status

I attempted to re-pull the latest code before reviewing; this environment has no configured git remote/tracking branch for `work`, so a pull cannot be performed here.

## Scope

- `src/mcp_zero/main.py`
- `src/mcp_zero/proxy/*`
- `src/mcp_zero/identity/*`
- `src/mcp_zero/transport/*`
- `src/mcp_zero/governance/*`
- `src/mcp_zero/audit/*`
- `src/mcp_zero/pipeline/*`

## Executive summary

The gateway has strong foundational controls (pipeline short-circuiting, deny-on-missing-identity once enabled, and fail-closed output masking). The largest risks are around **multi-tenant credential isolation**, **token cache key design**, and **secure-by-default deployment behavior**.

### Risk posture at a glance

- **Critical (2)**
- **High (3)**
- **Medium (3)**
- **Low (1)**

## Findings (prioritized)

---

### 1) CRITICAL — Downstream HTTP auth/session can bleed across users

**Category:** Authentication / Authorization isolation

**What I observed**

- A single transport/session is cached per server name.
- HTTP auth headers are bound when the transport is connected, not per-request.
- If a later request uses a different caller identity/token, the existing session may continue using stale auth context.

**Impact**

Cross-user privilege confusion in multi-user deployments, including accidental elevation or data exposure.

**Evidence in code**

- `ServerManager` reuses one transport per server and only reconnects when disconnected.
- `StreamableHTTPTransport.connect()` creates a long-lived `httpx.AsyncClient(headers=...)` with Authorization from connect-time token.

**Recommendation**

- Make downstream auth injection request-scoped.
- If persistent sessions must remain, shard session pools by stable user/security context.
- Force reconnect when effective auth context changes.

---

### 2) CRITICAL — OBO cache key collision when inbound token has no `jti`

**Category:** Token management

**What I observed**

- OBO auth extracts `jti` and falls back to `""` on decode failure/missing claim.
- OBO token cache key uses `(subject_jti, audience, scopes)`.

**Impact**

Different users with tokens lacking `jti` can share cache entries, causing cross-user re-use of exchanged tokens.

**Evidence in code**

- `OBOAuthProvider._extract_jti()` returns empty string if `jti` missing or parsing fails.
- `ExchangeCacheKey.from_params()` depends on `subject_jti`.

**Recommendation**

- Require non-empty `jti` for OBO paths and deny otherwise.
- Better: key cache with validated immutable identity tuple (`iss/sub/aud`) + scopes hash.

---

### 3) HIGH — Gateway may run without identity/governance controls (fail-open startup)

**Category:** Secure defaults / compliance

**What I observed**

- If identity config is absent, pipeline construction returns `None`.
- Service still starts and forwards tool calls.

**Impact**

Inadvertent unauthenticated/unauthorized operation if deployment config is incomplete.

**Recommendation**

- Add strict startup mode as default for enterprise usage (must have identity + policy).
- Require explicit override env for insecure/dev mode and log loudly when enabled.

---

### 4) HIGH — No enforced HTTPS for IdP/OBO/upstream URLs

**Category:** Transport security

**What I observed**

- Issuer/JWKS discovery, token exchange endpoint, and upstream HTTP URLs are not validated for secure schemes.

**Impact**

`http://` misconfiguration can expose bearer tokens/metadata to interception.

**Recommendation**

- Enforce HTTPS by default for all security-sensitive endpoints.
- Allow localhost/dev exceptions via explicit opt-out flag.

---

### 5) HIGH — SSRF-style exposure via untrusted policy/server URL configuration

**Category:** Network boundary / configuration hardening

**What I observed**

- Server URLs from policy are accepted and used directly by the HTTP transport factory path.

**Impact**

If policy source is compromised/mismanaged, gateway could be coerced into connecting to internal metadata/services.

**Recommendation**

- Add URL allowlist/denylist controls (CIDR/domain constraints).
- Block link-local and cloud metadata IP ranges by default.
- Consider signing and provenance checks for policy files.

---

### 6) MEDIUM — Detailed token exchange failures are returned to callers

**Category:** Information disclosure

**What I observed**

- Token exchange exceptions are surfaced in response text.
- Error text can include IdP response body/status details.

**Impact**

Leaks internal auth provider behavior and diagnostics to untrusted clients.

**Recommendation**

- Return generic denial text to client; keep details only in structured logs with correlation IDs.

---

### 7) MEDIUM — Unbounded in-memory audit event retention

**Category:** Availability / operational safety

**What I observed**

- `AuditHook` stores all events in a growing list with no cap.

**Impact**

Potential memory growth and DoS pressure in long-running instances.

**Recommendation**

- Use bounded ring buffer (debug/test), or write-through sink with no long-term in-process accumulation.

---

### 8) MEDIUM — Retry policy can amplify load during persistent failure

**Category:** Resilience / abuse resistance

**What I observed**

- Retries with exponential backoff are present, but no circuit-breaker/open-state suppression.

**Impact**

Repeated failing downstreams may still consume capacity and increase blast radius during incidents.

**Recommendation**

- Add circuit breaker per upstream server and short-circuit after repeated failures.
- Emit metrics and health signals for upstream degradation.

---

### 9) LOW — Header parsing is permissive and may keep malformed authorization values

**Category:** Input robustness

**What I observed**

- Authorization header is passed as latin-1 decoded raw string into pipeline extras.

**Impact**

Low direct risk, but stricter normalization could prevent edge-case parsing ambiguities.

**Recommendation**

- Normalize and validate header characters/format early; reject non-conforming values.

## Positive controls identified

- Pipeline short-circuit on validation/governance errors.
- Governance denies when identity is missing (when governance enabled).
- Output masking fail-closed behavior blocks unprocessed response data.
- Policy loader validates schema, references, and wildcard patterns.
- Correlation/trace IDs are propagated to transports.

## Compliance perspective (high level)

- **SOC 2 CC6 / ISO 27001 A.5 & A.8 (access control):** Risk from fail-open startup and session auth bleed.
- **SOC 2 CC7 / ISO 27001 A.8.16 (monitoring, logging):** Good audit foundation, but unbounded in-memory retention needs hardening.
- **SOC 2 CC6.7 / ISO 27001 A.8.24 (cryptographic/transport controls):** HTTPS enforcement gaps create configuration-driven weakness.
- **Least privilege / separation of duties:** OBO cache-key collision and shared sessions can violate tenant/user separation.

## Recommended remediation order

1. Fix session isolation and request-scoped auth propagation.
2. Redesign OBO cache keying and enforce non-empty subject identity key.
3. Enforce secure startup defaults (authn/authz mandatory unless explicit insecure mode).
4. Enforce HTTPS and network destination guardrails (including SSRF protections).
5. Remove client-visible sensitive error details.
6. Bound audit memory and add production-safe sink behavior.
7. Add circuit breaker / outage protection for downstream failures.
