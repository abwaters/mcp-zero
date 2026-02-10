# Adversarial Review: mcp-zero vs lasso mcp-gateway vs microsoft mcp-gateway

## Scope and methodology

This review used static analysis of:

- `mcp-zero` source in this repository.
- `lasso-security/mcp-gateway` (HEAD at clone time).
- `microsoft/mcp-gateway` (HEAD at clone time).

The assessment is **adversarial**: it models concrete attacker paths (external caller, authenticated but unauthorized user, malicious upstream MCP server, and misconfigured operator), then maps those paths to code-level controls and gaps.

No dynamic penetration tests were executed against running deployments in this pass.

## Executive summary

- **mcp-zero** has a strong security intent (identity validation, governance policy engine, OBO token exchange, masking hooks), but currently has a few high-impact implementation/deployment risks. Most notably, tool discovery currently bypasses policy/identity hooks, and security controls can be silently disabled through configuration fallbacks.
- **lasso mcp-gateway** is strong on plugin-driven sanitization and ecosystem scanning, but is oriented more as a local MCP aggregation/sanitization layer than an enterprise zero-trust gateway. It appears to have fewer native identity/RBAC controls compared with mcp-zero and Microsoft.
- **microsoft mcp-gateway** is strongest on enterprise control-plane patterns (AAD/Entra auth, role-based authorization, managed resource APIs, distributed stores, Kubernetes-native deployment), but does not natively emphasize prompt/data masking at parity with mcp-zero/lasso plugin approaches.

### Overall ranking (security architecture maturity)

1. **microsoft mcp-gateway** — strongest enterprise IAM + authorization + operational hardening.
2. **mcp-zero** — best policy+masking-first design simplicity, but currently weakened by fail-open/coverage gaps.
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

## Finding MZ-01 (High): tool discovery path bypasses policy + identity pipeline

### What happens

`ProxyServer._list_tools()` directly enumerates tools from all configured upstream servers. It does **not** run the pipeline hooks used in `call_tool` (identity/governance/masking), so tool metadata can be exposed without policy filtering.

### Why it matters adversarially

- A low-privilege or unauthenticated caller can build an internal capability map (server names/tool names).
- Discovery leakage accelerates follow-on attacks (targeted calls, social engineering, prompt-injection targeting specific tools).

### Evidence in mcp-zero

- `handle_list_tools` -> `_list_tools` returns aggregated namespaced tools.
- Pipeline is only executed in `_call_tool`, not `_list_tools`.

### Remediation

- Gate `list_tools` behind the same authn/authz decision flow as `call_tool`.
- Option A: run pipeline for each candidate tool and return only allowed tools.
- Option B: enforce a separate `list_tools` policy capability with deny-by-default.

## Finding MZ-02 (High): identity/governance controls can be silently disabled (fail-open deployment posture)

### What happens

If no policy file is configured, startup falls back to `MCP_UPSTREAM_URL` mode. In that mode, if `OKTA_ISSUER`/`OKTA_AUDIENCE` are missing, `_build_pipeline` returns `None`, effectively disabling identity and governance checks.

### Why it matters adversarially

A small deployment mistake (missing env var, wrong startup path) can produce a functional but weakly protected gateway.

### Remediation

- Add a strict production mode (`MCP_STRICT_SECURITY=true`) that refuses startup when identity/governance are absent.
- Emit startup `ERROR` and hard-exit when policy/identity is expected but incomplete.
- Prefer explicit mode selection over implicit fallback.

## Finding MZ-03 (Medium): sensitive error detail can be echoed back to callers

### What happens

Some failure responses return exception text to callers (for example token exchange failures and aggregate upstream errors). This may disclose internal endpoints, timeout behavior, auth backend details, or stack-like messages.

### Why it matters adversarially

Error detail leakage improves attacker reconnaissance and can reveal internal infrastructure clues.

### Remediation

- Return generic user-safe messages with correlation IDs.
- Keep detailed causes in structured logs only.

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
- Governance policy engine supports users/groups/server/tool wildcards and deny-overrides.
- Strength: explicit ABAC-like policy model.
- Gap: controls can be absent in fallback mode; discovery coverage gap.

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

- Clean architecture, test suite, and clear control-plane concepts.
- Current hardening depends heavily on correct policy/env configuration.

### lasso mcp-gateway

- Developer-friendly and easy to run locally; plugin extensibility is a major practical benefit.
- Enterprise production guarantees (IAM model, isolation boundaries, deployment controls) appear less opinionated in core.

### microsoft mcp-gateway

- Most mature ops footprint: Kubernetes-native deployment flows, dedicated management APIs, distributed stores/session routing, and cloud identity defaults.

---

## Recommended hardening roadmap for mcp-zero

## Priority 0 (immediate)

1. Enforce authz on `list_tools` and any other discovery methods.
2. Add strict startup guardrails to prevent insecure fallback in production.
3. Remove detailed exception text from client-visible errors.

## Priority 1 (near-term)

4. Introduce operation-level policy coverage tests across all MCP methods.
5. Separate inbound and outbound pipeline phases to reduce logic ambiguity.
6. Add explicit configuration mode (`legacy`, `policy-enforced`, `strict-enterprise`).

## Priority 2 (strategic)

7. Add upstream trust controls (allowlisted domains, TLS pinning options, SSRF defenses for HTTP adapters).
8. Add adaptive abuse controls (rate limiting, concurrency quotas, anomaly detection).
9. Add signed policy bundles and change attestation for tamper-resistant governance.

---

## Final verdict

If your target is a **regulated enterprise gateway**, mcp-zero’s architecture is directionally correct and closer to Microsoft’s policy-centric model than lasso’s plugin-local pattern. However, to withstand adversarial review, mcp-zero should close the discovery/auth coverage gap and remove fail-open startup paths.

In short:

- Pick **microsoft mcp-gateway** when you need immediate enterprise deployment and IAM maturity at scale.
- Pick **mcp-zero** when you want a focused, auditable policy+masking gateway and are willing to harden the identified gaps quickly.
- Pick **lasso mcp-gateway** when plugin-based sanitization and MCP ecosystem scanning are primary goals, especially for local/dev-centric workflows.
