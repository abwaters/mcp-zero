# comparison_mintmcp_gateway.md

## Gist (read this first)
**Choose MintMCP over `mcp-zero`** when your goal is fast consumption of hosted, ready-to-use MCP endpoints and connectors (especially SaaS app integrations), with minimal gateway infrastructure ownership.

**Choose `mcp-zero` over MintMCP** when you need to run your own enterprise gateway control plane with explicit identity-governance-masking-audit controls and direct policy ownership.

---

## Important scope note
This environment could not directly retrieve `https://www.mintmcp.com/` due network/proxy restrictions at execution time, so this comparison uses MintMCP’s public GitHub organization artifacts as the evidence base for hosting posture and product orientation.

---

## Snapshot comparison

| Area | mcp-zero | MintMCP (gateway/platform posture inferred from public artifacts) |
|---|---|---|
| Primary shape | Self-hostable enterprise MCP gateway | Hosted MCP endpoints and managed integration ecosystem |
| Core value | Governance controls (identity/policy/masking/audit) | Fast connectivity to app/data systems via managed MCP services |
| Ownership model | You operate the gateway | Vendor-operated endpoints and orchestration emphasis |
| Hosting model | Self-host by enterprise | Hosted service orientation (with some local tooling options) |
| License model | Project license in this repo | Mixed: open-source components exist; gateway/service license terms may be proprietary/commercial |

---

## Feature and use-case comparison

### 1) Product center of gravity
- **mcp-zero:** control and governance are the center.
- **MintMCP:** access to useful integrations and hosted runtime convenience appear to be the center.

**Where each excels**
- `mcp-zero`: regulated environments that need explicit policy ownership.
- `MintMCP`: teams optimizing for speed-to-value and reduced operational burden.

### 2) Security and compliance posture
- **mcp-zero:** built-in policy enforcement (both HTTP and stdio)[^1], identity mapping with optional OBO token exchange[^2], Presidio masking (both HTTP and stdio)[^1], and structured audit hooks.
- **MintMCP:** public repos indicate security-focused components and hosted orchestration context, but governance semantics equivalent to mcp-zero's deny/allow policy engine are not the primary public framing.

**Trade-off**
- If your compliance process requires self-operated control-plane logic with deterministic authorization semantics, `mcp-zero` is usually the better fit.
- If your priority is rapid integration and vendor-hosted runtime, MintMCP may reduce time-to-deployment.

### 3) Integration delivery model
- **mcp-zero:** proxy/gateway framework you configure.
- **MintMCP:** public server listings and hosted URLs suggest connector-like managed MCP services.

**Implication**
- MintMCP can accelerate onboarding to common app integrations.
- mcp-zero can standardize governance across whichever MCP servers you choose to expose.

---

## Hosting model comparison

### mcp-zero
- Self-hosted enterprise gateway pattern (local/VM/container/K8s as chosen by operator).
- Best for organizations with strict control-plane ownership requirements.

### MintMCP
- Public materials indicate hosted endpoints and hosted orchestration/runtime assumptions.
- Best for organizations preferring managed service consumption over operating a gateway stack.

---

## License comparison

- **mcp-zero:** see this repository license.
- **MintMCP:** multiple open-source repos under the MintMCP org use permissive licenses (e.g., Apache-2.0, MIT), but the full commercial gateway/platform terms are likely governed outside those repo licenses.

**Practical implication:** perform legal/vendor review for production procurement; do not assume hosted platform rights from OSS component licenses alone.

---

## Recommended use-cases

### Prefer mcp-zero when
1. You need enterprise-controlled governance policy with explicit authorization logic (enforced on both HTTP and stdio transports).
2. You need to enforce masking/audit controls in your own trusted boundary (both HTTP and stdio).[^1]
3. You need a gateway framework you can tailor deeply in Python.

### Prefer MintMCP when
1. You want ready-to-use MCP integrations/endpoints quickly.
2. You prefer managed hosting and less gateway infrastructure overhead.
3. You can accept vendor-managed runtime and corresponding commercial/legal terms.

---

## Known limitations and caveats
- Because the primary MintMCP website was inaccessible from this runtime, treat this as a best-effort comparison grounded in public GitHub artifacts rather than full product documentation.
- Re-validate current hosting, SLA, compliance, and licensing terms directly with vendor docs before final decisions.

---

## Implementation Notes

[^1]: **Unified transport enforcement**: Both HTTP and stdio transports enforce the same governance, masking, and audit policies through a unified pipeline. Previous versions of this document incorrectly stated that stdio bypassed these controls; this was corrected following integration test validation in PR #101.

[^2]: **OBO token exchange configuration**: OBO token exchange is implemented but requires explicit configuration: (1) set `OKTA_TOKEN_ENDPOINT`, `OKTA_CLIENT_ID`, and `OKTA_CLIENT_SECRET` environment variables, and (2) enable OBO per-server in the policy file with `obo.enabled: true`, `obo.target_audience`, and `obo.scopes`.

---

## Sources
- mcp-zero README: `README.md`
- MintMCP org: https://github.com/mintmcp
- MintMCP servers repo (public hosted endpoint examples): https://github.com/mintmcp/servers
- MintMCP Snowflake image repo (hosted runtime references): https://github.com/mintmcp/snowflake-mcp
