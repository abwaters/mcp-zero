# MCP Gateway Security / Functional / Compliance Review

Date: 2026-02-10

## Scope reviewed

- `src/mcp_zero/main.py`
- `src/mcp_zero/proxy/*`
- `src/mcp_zero/identity/*`
- `src/mcp_zero/transport/*`
- `src/mcp_zero/governance/*`

## Executive summary

The gateway architecture is solid in several areas (fail-closed governance hook behavior, policy validation, and output-masking fail-closed behavior). However, I identified **two critical security issues** and several high/medium concerns:

- **Critical:** Downstream HTTP session authentication can be reused across users because the server manager caches one connected session per server and does not rotate on token/context change.
- **Critical:** OBO token cache keys can collapse to a shared empty `subject_jti` when incoming tokens do not have `jti`, enabling cross-user token reuse.
- **High:** The app can run with identity/governance disabled (fail-open posture) when policy/identity env config is absent.
- **High:** No explicit HTTPS requirement for OIDC discovery/JWKS, OBO token endpoint, or upstream MCP URLs.
- **Medium:** Token exchange failures are reflected to clients with exception detail and potential IdP response body leakage.
- **Medium:** Unbounded in-memory audit event list can create memory pressure/DoS in long-running processes.

## Detailed findings

### 1) Critical — Cross-user credential/session confusion in downstream HTTP transport

**What happens**

- `ServerManager` stores one transport per server and returns it for all requests once connected.
- `StreamableHTTPTransport.connect()` sets Authorization and trace/correlation headers at connection time.
- Subsequent requests for the same server reuse the existing connected session without re-authenticating/rebinding headers.

**Why this is risky**

In multi-user scenarios, the first user/token that established the downstream connection can effectively determine the auth context for later requests, causing privilege confusion and potential unauthorized access.

**Evidence**

- `ServerManager.get_session()` only connects if not already connected and then returns `transport.session`.
- `StreamableHTTPTransport.connect()` injects `Authorization` into a long-lived `httpx.AsyncClient` only during connect.

**Recommended remediation**

- Make downstream auth per request, not per persistent session; or
- Maintain per-user/per-token session pools keyed by stable subject identity; and
- Force reconnect when auth token/context changes.

### 2) Critical — OBO cache key can be shared when JWT `jti` is absent

**What happens**

- OBO provider extracts `jti` from inbound JWT without verification and returns `""` when missing/parse error.
- OBO cache key uses `subject_jti + audience + scopes`.

**Why this is risky**

If multiple users present tokens lacking `jti`, they can map to the same cache key and receive the same exchanged token for a given audience/scope tuple, causing cross-user credential reuse.

**Evidence**

- `_extract_jti()` returns empty string on missing or decode error.
- `ExchangeCacheKey.from_params()` relies on `subject_jti`.

**Recommended remediation**

- Require `jti` in validated identity tokens for OBO-enabled routes; reject otherwise.
- Or key by a stronger stable subject tuple (e.g., `iss+sub+aud+scope hash`) derived from already-validated claims.

### 3) High — Fail-open startup posture when identity config is absent

**What happens**

- If policy file or identity env vars are not configured, `_build_pipeline()` returns `None`.
- Proxy still starts and routes tool calls.

**Why this is risky**

In enterprise environments this can silently run the gateway without authn/authz controls, violating least privilege and common compliance expectations (SOC2/ISO27001 access control controls).

**Recommended remediation**

- Add a secure-by-default startup mode: refuse startup unless identity+policy are configured (or explicit `ALLOW_INSECURE_MODE=true`).
- Emit loud structured startup warnings/metrics when running without authn/authz.

### 4) High — No explicit HTTPS/TLS enforcement for security-critical endpoints

**What happens**

- OIDC discovery/JWKS, OBO token endpoint, and upstream MCP HTTP URLs are accepted from config without scheme validation.

**Why this is risky**

Misconfiguration to `http://` can expose tokens and identity metadata to MITM risks.

**Recommended remediation**

- Enforce `https://` by default for all identity and token exchange endpoints and remote MCP upstream URLs.
- Allow explicit opt-out only for local dev with an explicit insecure flag.

### 5) Medium — Detailed token exchange errors may leak internals to clients

**What happens**

- On OBO failure, `ProxyServer` returns `Request denied: token exchange failed: {exc}`.
- `TokenExchangeError` may include raw HTTP status text/body from IdP responses.

**Why this is risky**

Can disclose sensitive internal diagnostics, policy names, or provider-side details to untrusted callers.

**Recommended remediation**

- Return generic client errors (e.g., `Access denied`) and log detailed error server-side with correlation ID only.

### 6) Medium — Audit hook stores events in unbounded in-memory list

**What happens**

- `AuditHook` appends every event to `self._events` with no cap/eviction.

**Why this is risky**

Long-lived workloads can accumulate memory indefinitely, enabling memory exhaustion or degraded performance.

**Recommended remediation**

- Replace with bounded ring buffer for test mode only, or emit directly to sink and disable in-memory retention in production.

## Positive controls observed

- Governance hook denies when no identity is present (fail closed once governance is enabled).
- Pipeline short-circuit behavior sets policy deny and prevents normal execution.
- Output masking failure blocks response return (prevents accidental unmasked data leakage).
- Policy loader performs strong schema/reference validation.

## Suggested priority order

1. Fix session/token isolation (Finding #1).
2. Fix OBO cache key design and require strong subject keying (Finding #2).
3. Introduce secure-by-default startup guardrails (Finding #3).
4. Enforce HTTPS scheme checks for security endpoints (Finding #4).
5. Reduce client-visible error detail and bound audit memory usage (Findings #5 and #6).
