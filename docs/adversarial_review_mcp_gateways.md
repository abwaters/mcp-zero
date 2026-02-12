# Adversarial Review: mcp-zero vs lasso mcp-gateway vs microsoft mcp-gateway

**Review Date**: Original review date unknown; **Updated**: 2026-02-12

## Scope and methodology

This review used static analysis of:

- `mcp-zero` source in this repository.
- `lasso-security/mcp-gateway` (HEAD at clone time).
- `microsoft/mcp-gateway` (HEAD at clone time).

The assessment is **adversarial**: it models concrete attacker paths (external caller, authenticated but unauthorized user, malicious upstream MCP server, and misconfigured operator), then maps those paths to code-level controls and gaps.

No dynamic penetration tests were executed against running deployments in this pass.

## Important clarification: stdio transport enforcement

**CORRECTION**: The original review may have suggested that stdio transport lacks enforcement capabilities. This is **incorrect**. As validated through comprehensive integration tests (PR #87) and code analysis:

- **stdio transport DOES enforce** full governance, identity validation, masking, and auditing when the pipeline is configured.
- Both HTTP and stdio transports use the **same** `ProxyServer` and pipeline architecture.
- Policy decisions, masking operations, and audit events apply **equally** to both transports.
- The only scenario where enforcement is absent is when identity/governance are not configured at startup (affecting **both** transports equally).

See `tests/integration/test_stdio_integration.py` for test coverage including:
- `TestStdioGovernanceDeny` — verifies policy enforcement blocks stdio calls
- `TestStdioInputMasking` — verifies PII masking on stdio request arguments
- `TestStdioOutputMasking` — verifies PII masking on stdio response content
- `TestStdioAuditTrail` — verifies audit event generation for stdio flows

## Executive summary

**UPDATE 2026-02-12**: mcp-zero has resolved all critical multi-user security boundary issues identified in the initial adversarial review (January 2026). Per-user session isolation and OBO token cache collision fixes have been merged and validated through comprehensive integration tests.

- **mcp-zero** has a strong security intent (identity validation, governance policy engine, OBO token exchange, masking hooks) with **critical multi-user isolation issues now resolved**. Remaining risks are around configuration defaults (tool discovery bypass, fail-open configuration fallbacks). Both HTTP and stdio transports **DO enforce** full governance, identity validation, and masking through the unified pipeline architecture.
- **lasso mcp-gateway** is strong on plugin-driven sanitization and ecosystem scanning, but is oriented more as a local MCP aggregation/sanitization layer than an enterprise zero-trust gateway. It appears to have fewer native identity/RBAC controls compared with mcp-zero and Microsoft.
- **microsoft mcp-gateway** is strongest on enterprise control-plane patterns (AAD/Entra auth, role-based authorization, managed resource APIs, distributed stores, Kubernetes-native deployment), but does not natively emphasize prompt/data masking at parity with mcp-zero/lasso plugin approaches.

### Overall ranking (security architecture maturity)

1. **microsoft mcp-gateway** — strongest enterprise IAM + authorization + operational hardening at scale.
2. **mcp-zero** — best policy+masking-first design with strong isolation guarantees; remaining gaps are in secure defaults and discovery authorization.
3. **lasso mcp-gateway** — useful guardrails/scanning and practical local usage, but less complete as a centralized enterprise policy enforcement point.

## Threat model lens

### Adversaries

1. **Unauthenticated network client** calling gateway endpoints.
2. **Authenticated but unauthorized user** probing tools/servers.
3. **Malicious or compromised upstream MCP server** returning toxic content.
4. **Operator misconfiguration** (missing env vars/policy).
5. **Insider with policy file write access**.

### Security objectives

- Enforce authentication for all MCP operations.
- Enforce per-user/group/server/tool authorization.
- Prevent sensitive data exfiltration in request/response payloads.
- Minimize blast radius of misconfiguration.
- Ensure auditable, attributable activity.

---

## Deep findings for mcp-zero

## Finding MZ-01 (High): tool discovery path bypasses policy + identity pipeline ⚠️ OPEN

**Status**: ⚠️ **OPEN** (confirmed in current implementation as of 2026-02-12)

### What happens

`ProxyServer._list_tools()` directly enumerates tools from all configured upstream servers. It does **not** run the pipeline hooks used in `call_tool` (identity/governance/masking), so tool metadata can be exposed without policy filtering.

### Why it matters adversarially

- A low-privilege or unauthenticated caller can build an internal capability map (server names/tool names).
- Discovery leakage accelerates follow-on attacks (targeted calls, social engineering, prompt-injection targeting specific tools).

### Evidence in mcp-zero

- `handle_list_tools` -> `_list_tools` returns aggregated namespaced tools (proxy_server.py lines 61-92).
- Pipeline is only executed in `_call_tool`, not `_list_tools`.
- No identity extraction or policy evaluation occurs in the list path.

### Remediation

- Gate `list_tools` behind the same authn/authz decision flow as `call_tool`.
- Option A: run pipeline for each candidate tool and return only allowed tools.
- Option B: enforce a separate `list_tools` policy capability with deny-by-default.

### Impact on stdio transport

This finding applies **equally to both HTTP and stdio transports** since they share the same `ProxyServer._list_tools()` code path. The bypass is at the proxy layer, not the transport layer.

## Finding MZ-02 (High): identity/governance controls can be silently disabled (fail-open deployment posture) ⚠️ OPEN

**Status**: ⚠️ **OPEN** (confirmed in current implementation as of 2026-02-12)

### What happens

If no policy file is configured, startup falls back to `MCP_UPSTREAM_URL` mode. In that mode, if `OKTA_ISSUER`/`OKTA_AUDIENCE` are missing, `_build_pipeline` returns `None`, effectively disabling identity and governance checks. The gateway still starts and proxies requests in an unauthenticated mode.

### Why it matters adversarially

A small deployment mistake (missing env var, wrong startup path) can produce a functional but weakly protected gateway. This fail-open behavior can violate enterprise security expectations and compliance requirements.

### Remediation

- Add a strict production mode (`MCP_STRICT_SECURITY=true`) that refuses startup when identity/governance are absent.
- Emit startup `ERROR` and hard-exit when policy/identity is expected but incomplete.
- Prefer explicit mode selection over implicit fallback.
- Add clear startup logging indicating the current security posture (authenticated vs unauthenticated mode).

### Impact on stdio transport

This finding applies **equally to both HTTP and stdio transports**. When the pipeline is `None` (due to missing identity/governance config), both transport types operate without enforcement. When the pipeline is configured, **both transports fully enforce** identity, governance, and masking policies.

## Finding MZ-03 (Medium): sensitive error detail can be echoed back to callers ✅ PARTIALLY RESOLVED

**Status**: ✅ **PARTIALLY RESOLVED** (token exchange errors fixed in PR #54, #79; other error paths may remain)

### What happened (original finding)

Some failure responses returned exception text to callers (for example token exchange failures and aggregate upstream errors). This could disclose internal endpoints, timeout behavior, auth backend details, or stack-like messages.

### Why it matters adversarially

Error detail leakage improves attacker reconnaissance and can reveal internal infrastructure clues.

### Resolution

Token exchange errors now return generic "Access denied" messages with correlation IDs only (PR #54, #79). Detailed exception information is logged server-side. Other error paths (upstream timeouts, transport errors) should be audited to ensure consistent generic error handling.

## Finding MZ-04 (Medium): policy evaluation coverage asymmetry (call path stronger than discovery path)

Even with robust policy semantics (default deny + explicit deny override), the effective security envelope is uneven when different MCP methods are not consistently mediated by policy.

### Remediation

- Define and enforce a complete operation matrix: `list_tools`, `call_tool`, `list_resources`, `read_resource`, prompts, etc.
- Add regression tests asserting deny-by-default on every externally reachable method.

## Finding MZ-05 (Low/Design risk): dual pipeline execution may re-run pre-validation hooks on post-processing pass

`_call_tool` executes the full pipeline before upstream call and again after upstream response (for output masking). This can re-run identity/governance hooks unnecessarily and raises complexity for future hook authors.

### Remediation

- Split pipeline into inbound/outbound phases or execute only needed hook points in post-pass.

---

## Comparative analysis

## 1) Identity and authorization

### mcp-zero

- JWT validation with JWKS and issuer/audience checks.
- OAuth2 Token Exchange (OBO/RFC 8693) fully implemented with per-user session isolation.
- Governance policy engine supports users/groups/server/tool wildcards and deny-overrides.
- Strength: explicit ABAC-like policy model with fail-closed enforcement when enabled.
- **Resolved**: Per-user session isolation (PR #50, #78) and OBO cache collision (PR #51, #77).
- **Remaining gaps**: Controls can be absent in fallback mode; discovery coverage gap (list_tools).

### lasso mcp-gateway

- Primary model is plugin-based sanitization and scanning for proxied MCPs.
- Appears focused on local/stdin MCP aggregation and plugin interception rather than centralized IAM/RBAC gateway semantics.
- Security scanner blocks risky servers/tool descriptions, which is valuable for ecosystem hygiene.

### microsoft mcp-gateway

- Strongest built-in authn/authz posture: authenticated controllers, Entra integration, role-based permission provider (`mcp.admin` and resource role checks), and resource-level access checks before proxying.
- Better suited for enterprise multi-team managed access controls.

## 2) Data protection and content security

### mcp-zero

- Native masking architecture (Presidio hook) on both request and response paths.
- Fail-closed response behavior when post-processing fails is a strong data-loss-prevention pattern.

### lasso mcp-gateway

- Plugin-driven sanitization ecosystem (basic/presidio/lasso) is flexible and practical.
- Plus tool-poisoning/reputation scanner is a unique advantage.

### microsoft mcp-gateway

- Emphasizes routing/management/authorization; native prompt/data masking appears less central in core design.

## 3) Operational hardening and production readiness

### mcp-zero

- Clean architecture, comprehensive test suite (including stdio integration tests), and clear control-plane concepts.
- Strong multi-user isolation guarantees (per-user sessions, validated cache keys).
- Bounded audit retention, generic error responses, and fail-closed masking.
- **Remaining gap**: Hardening depends on correct policy/env configuration; no strict mode to prevent fail-open deployment.

### lasso mcp-gateway

- Developer-friendly and easy to run locally; plugin extensibility is a major practical benefit.
- Enterprise production guarantees (IAM model, isolation boundaries, deployment controls) appear less opinionated in core.

### microsoft mcp-gateway

- Most mature ops footprint: Kubernetes-native deployment flows, dedicated management APIs, distributed stores/session routing, and cloud identity defaults.

---

## Recommended hardening roadmap for mcp-zero

### ✅ Priority 0 (immediate) — COMPLETED January 2026

1. ~~Remove detailed exception text from client-visible errors.~~ ✅ **COMPLETED** (PR #54, #79)
2. ~~Fix per-user session isolation for multi-tenant safety.~~ ✅ **COMPLETED** (PR #50, #78)
3. ~~Fix OBO cache key collision when jti is absent.~~ ✅ **COMPLETED** (PR #51, #77)
4. ~~Bound audit retention to prevent unbounded memory growth.~~ ✅ **COMPLETED** (PR #55, #80)

### ⚠️ Priority 1 (near-term) — OPEN as of February 2026

1. **Enforce authz on `list_tools` and any other discovery methods.** ⚠️ OPEN (MZ-01)
2. **Add strict startup guardrails to prevent insecure fallback in production.** ⚠️ OPEN (MZ-02)
3. Introduce operation-level policy coverage tests across all MCP methods.
4. Add explicit configuration mode (`legacy`, `policy-enforced`, `strict-enterprise`).

### Priority 2 (strategic)

5. Separate inbound and outbound pipeline phases to reduce logic ambiguity (currently dual-execution for masking).
6. Add upstream trust controls (allowlisted domains, TLS pinning options, SSRF defenses for HTTP adapters).
7. Add adaptive abuse controls (rate limiting, concurrency quotas, anomaly detection).
8. Add signed policy bundles and change attestation for tamper-resistant governance.

---

## Final verdict

**UPDATE 2026-02-12**: mcp-zero has made significant progress on enterprise readiness:

✅ **Resolved**: All critical multi-user isolation issues (per-user sessions, OBO cache collisions, error leakage, bounded audit retention)

⚠️ **Remaining**: Configuration hardening (strict mode, list_tools authorization)

If your target is a **regulated enterprise gateway**, mcp-zero's architecture is directionally correct and closer to Microsoft's policy-centric model than lasso's plugin-local pattern. The core enforcement mechanisms are solid; remaining work focuses on secure defaults and operational guardrails.

### Decision framework

**Pick microsoft mcp-gateway** when:
- You need immediate enterprise deployment with AAD/Entra integration
- You require Kubernetes-native deployment and distributed session management
- IAM maturity and operational scale are top priorities
- Prompt/data masking is not a primary requirement

**Pick mcp-zero** when:
- You need focused policy+masking enforcement with strong isolation guarantees
- You want transparent, auditable governance with ABAC-style policies
- PII/data protection is a core requirement (Presidio integration, fail-closed masking)
- You can address the remaining configuration hardening gaps (strict mode, discovery authz)
- You need enforcement on both HTTP and stdio transports

**Pick lasso mcp-gateway** when:
- Plugin-based sanitization and MCP ecosystem scanning are primary goals
- Local/dev-centric workflows are the target use case
- Centralized enterprise IAM is not required
