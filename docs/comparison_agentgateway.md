# comparison_agentgateway.md

## Gist (read this first)
**Choose `agentgateway` over `mcp-zero`** when you need a high-performance, multi-tenant, multi-protocol data plane with dynamic control-plane updates (xDS) and Kubernetes-oriented scale operations.

**Choose `mcp-zero` over `agentgateway`** when your immediate priority is a simpler, Python-native, enterprise MCP control point with explicit policy semantics, built-in Okta-centric identity mapping, inline Presidio masking, and straightforward auditability.

---

## Snapshot comparison

| Area | mcp-zero | agentgateway |
|---|---|---|
| Primary focus | Enterprise MCP governance gateway | Agentic AI connectivity data plane |
| Protocol scope | MCP-first | MCP + A2A + broader gateway patterns |
| Runtime | Python | Rust |
| Policy style | Ordered allow/deny with deny override | Rich policy + CEL expression model |
| Dynamic config | Startup policy/env config | Dynamic updates via xDS |
| Multi-tenancy | Not a primary product theme today | Explicitly highlighted |
| Hosting model | Self-hosted gateway process (VM/container/K8s by user choice) | Standalone and Kubernetes-oriented (via kgateway ecosystem) |
| License | Project license in this repo (mcp-zero) | Apache-2.0 |

---

## Feature comparison

### 1) Security and governance
- **mcp-zero excels at explicit enterprise controls**: JWT validation, group-aware policy checks, deny-by-default posture, and deterministic rule evaluation.
- **agentgateway excels at broad, programmable policy controls**: CEL-driven expression power and generalized data-plane governance across more traffic patterns.

**Trade-off:**
- `mcp-zero` is easier to audit quickly.
- `agentgateway` can model more advanced scenarios but with higher operational/policy complexity.

### 2) Identity and authorization model
- **mcp-zero:** opinionated around gateway-edge JWT validation and enterprise claims mapping, with optional OBO support for downstream MCP servers (requires OKTA_TOKEN_ENDPOINT + per-server config).[^1]
- **agentgateway:** emphasizes RBAC and policy-driven security in a broader connectivity model.

**Where each excels**
- `mcp-zero`: enterprise teams that want understandable identity-to-policy decisions fast.
- `agentgateway`: platform teams that need broader authorization composition across many tenants/environments.

### 3) Data protection and content controls
- **mcp-zero:** first-class Presidio masking pipeline for PII/secrets on HTTP traffic (very explicit and practical for compliance narratives; stdio connections bypass masking).[^2]
- **agentgateway:** stronger generalized transformation/policy capability, but not as singularly centered on Presidio-style masking defaults.

### 4) Operational model
- **mcp-zero:** smaller operational surface, easier bootstrap, fewer moving pieces.
- **agentgateway:** larger platform posture (dynamic config, scale orientation, ecosystem integration).

---

## Hosting model comparison

### mcp-zero
- Intended to be run by the enterprise: local, VM, or container/Kubernetes deployment under your control.
- Good fit when hosting ownership and policy transparency are primary requirements.

### agentgateway
- Supports standalone deployments and Kubernetes usage via the kgateway ecosystem.
- Better fit for platform teams already operating centralized gateway/control-plane workflows.

---

## License comparison

- **mcp-zero:** see this repository's licensing.
- **agentgateway:** Apache-2.0.

**Practical implication:** Apache-2.0 is generally enterprise-friendly for internal distribution and extension.

---

## Recommended use-cases

### Prefer mcp-zero when
1. You need an enterprise MCP "guardrail gateway" now.
2. Your security/compliance stakeholders want deterministic policy behavior and explicit masking.
3. Your team prefers Python customization velocity.

### Prefer agentgateway when
1. You are building a multi-tenant, high-scale agent platform.
2. You need protocol breadth (including A2A) and dynamic runtime control.
3. You want to align with Kubernetes-native control-plane patterns.

---

## Known limitations and caveats
- This comparison focuses on publicly documented features and architectural posture, not benchmarked throughput numbers.
- Both projects move quickly; re-check current release docs before final platform commitment.

---

## Implementation Notes

[^1]: **OBO token exchange configuration**: OBO token exchange is implemented but requires explicit configuration: (1) set `OKTA_TOKEN_ENDPOINT`, `OKTA_CLIENT_ID`, and `OKTA_CLIENT_SECRET` environment variables, and (2) enable OBO per-server in the policy file with `obo.enabled: true`, `obo.target_audience`, and `obo.scopes`.

[^2]: **stdio transport limitation**: mcp-zero supports stdio connections for gateway-spawned MCP server processes, but governance policy evaluation and Presidio masking are **only enforced on HTTP/Streamable HTTP** traffic. stdio connections bypass the governance and masking pipeline.

---

## Sources
- mcp-zero README: `README.md`
- agentgateway project: https://github.com/agentgateway/agentgateway
- agentgateway standalone and Kubernetes docs references surfaced in that repository.
