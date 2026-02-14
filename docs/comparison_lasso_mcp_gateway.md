# comparison_lasso_mcp_gateway.md

## Gist (read this first)
**Choose Lasso MCP Gateway over `mcp-zero`** when your primary need is a developer-friendly MCP intermediary with plugin-driven extensibility, security scanning, and easy local/client-centric onboarding (including Docker and desktop MCP client configs).

**Choose `mcp-zero` over Lasso MCP Gateway** when you need an enterprise governance control point centered on deterministic access policy, explicit identity claim mapping, and built-in audit/masking architecture for regulated approvals.

---

## Snapshot comparison

| Area | mcp-zero | Lasso MCP Gateway |
|---|---|---|
| Primary focus | Enterprise MCP governance gateway | MCP intermediary + plugin ecosystem |
| Runtime | Python | Python |
| Policy model | Ordered allow/deny rules tied to user/group/server/tool | Plugin-based guardrails and controls |
| Security orientation | Identity-aware governance + masking + audit | Security scanner + sanitization plugins + tracing plugins |
| Hosting model | Self-hosted service operated by enterprise | Local/dev deployment, Docker-based deployment, client-driven integration |
| License | Project license in this repo | MIT |

---

## Feature and use-case comparison

### 1) Access control and governance depth
- **mcp-zero:** governance is first-class and deterministic (deny-by-default, explicit allow/deny rules, user/group/tool scoping; enforced on both HTTP and stdio transports).[^1]
- **Lasso:** focuses on an intermediary control layer with plugin-based capabilities, including security scanning and sensitive data sanitization.

**Where each excels**
- `mcp-zero`: governance-heavy enterprise environments with auditable authorization semantics on both HTTP and stdio transports.
- `lasso mcp gateway`: teams that want quick-to-extend controls via plugins and straightforward client integration.

### 2) Security controls
- **mcp-zero:** built-in identity validation with optional OBO token exchange[^2], policy enforcement (both HTTP and stdio)[^1], PII/secret masking (both HTTP and stdio)[^1], and structured auditing pipeline.
- **Lasso:** explicitly advertises security risk scanning before loading MCP servers plus guardrail plugins (e.g., masking and tracing plugin examples).

**Trade-off**
- `mcp-zero` offers a more prescriptive, governance-oriented structure across all transports.
- `Lasso` offers a flexible plugin-centric path with potentially faster experimentation.

### 3) Developer experience and integration model
- **mcp-zero:** service-style deployment and policy file approach.
- **Lasso:** strong examples for Cursor/Claude configs and Docker invocation patterns.

**Practical outcome**
- Lasso is often attractive for rapid toolchain adoption across desktop MCP clients.
- mcp-zero is attractive when the gateway is part of enterprise control architecture rather than a local helper layer.

---

## Hosting model comparison

### mcp-zero
- Intended as a centrally hosted enterprise control point (self-managed by the organization).
- Works well where platform/security teams own the gateway runtime.

### Lasso MCP Gateway
- Easily run from Python package/CLI and Docker, often in developer-centric flows.
- Well-suited for local, team, or small shared environments where plugin flexibility is key.

---

## License comparison

- **mcp-zero:** see repository license.
- **Lasso MCP Gateway:** MIT.

**Practical implication:** MIT allows broad commercial/internal usage with minimal obligations.

---

## Recommended use-cases

### Prefer mcp-zero when
1. You need explicit enterprise authorization semantics and identity-aware audit trails.
2. You need a compliance narrative around built-in masking/governance controls.
3. You want policy as a central, reviewable artifact.

### Prefer Lasso MCP Gateway when
1. You want plugin-driven gateway behavior and quick experimentation.
2. You need very accessible developer onboarding for desktop MCP clients.
3. Your operational posture favors lightweight deployment over centralized governance depth.

---

## Known limitations and caveats
- The two products are philosophically different: centralized enterprise governance (`mcp-zero`) vs flexible intermediary/plugins (Lasso).
- Validate plugin maturity and enterprise lifecycle requirements for your environment before standardization.

---

## Implementation Notes

[^1]: **Unified transport enforcement**: Both HTTP and stdio transports enforce the same governance, masking, and audit policies through a unified pipeline. Previous versions of this document incorrectly stated that stdio bypassed these controls; this was corrected following integration test validation in PR #101.

[^2]: **OBO token exchange configuration**: OBO token exchange is implemented but requires explicit configuration: (1) set `OKTA_TOKEN_ENDPOINT`, `OKTA_CLIENT_ID`, and `OKTA_CLIENT_SECRET` environment variables, and (2) enable OBO per-server in the policy file with `obo.enabled: true`, `obo.target_audience`, and `obo.scopes`.

---

## Sources
- mcp-zero README: `README.md`
- Lasso MCP Gateway: https://github.com/lasso-security/mcp-gateway
