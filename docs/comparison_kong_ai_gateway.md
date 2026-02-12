# comparison_kong_ai_gateway.md

## Gist (read this first)
**Choose Kong AI Gateway over `mcp-zero`** when you need a high-performance, plugin-extensible API/MCP gateway that can unify LLM traffic, MCP traffic, and traditional API management in a single platform, with auto-generation of MCP servers from existing REST APIs and a mature plugin ecosystem.

**Choose `mcp-zero` over Kong AI Gateway** when you need a focused, lightweight enterprise MCP governance gateway with built-in inline PII masking, deterministic identity-aware policy enforcement, and simple deployment — without enterprise licensing costs or the operational complexity of a full API gateway platform.

---

## Snapshot comparison

| Area | mcp-zero | Kong AI Gateway |
|---|---|---|
| Primary focus | Enterprise MCP governance gateway | Unified API / LLM / MCP gateway platform |
| Runtime/stack | Python service | Lua/Nginx (Kong Gateway core), plugin-extensible |
| Policy model | Ordered allow/deny YAML/JSON rules tied to user/group/server/tool | Plugin-based: MCP Tool ACLs, consumer groups, guardrail plugins |
| Data protection | Inline Presidio-based PII and secret masking | AI PII Sanitizer plugin (Enterprise only); third-party integrations (Azure Content Safety, AWS Guardrails) |
| Hosting model | Self-hosted by enterprise (any environment) | Self-hosted, Kubernetes (Kong Ingress Controller), or Konnect SaaS |
| License | Project license in this repo | Open-source core (Apache-2.0); MCP/AI features require Enterprise license |

---

## Feature and use-case comparison

### 1) Architecture and operating model
- **mcp-zero:** purpose-built MCP governance gateway with a focused control path (identity, governance, masking, audit) in a single Python service.
- **Kong AI Gateway:** general-purpose API gateway extended with AI/MCP capabilities. The MCP Gateway sits alongside the LLM Gateway within the broader Kong AI Gateway product, sharing the same plugin engine, routing layer, and control plane (Kong Konnect).

**Where each excels**
- `mcp-zero`: teams wanting a dedicated MCP governance control point with minimal moving parts.
- `Kong AI Gateway`: organizations that already run Kong for API management and want to extend it to govern MCP and LLM traffic in a single platform.

### 2) MCP protocol handling
- **mcp-zero:** MCP proxying for both Streamable HTTP and stdio transports with governance controls applied inline.
- **Kong AI Gateway:** AI MCP Proxy plugin bridges MCP and HTTP, supporting three modes — proxying MCP requests to upstream MCP servers, converting REST APIs into MCP tools, and exposing grouped tools as an MCP server. Auto-generation of MCP servers from existing REST APIs via Kong's MCP server generation capability.

**Trade-off**
- Kong's REST-to-MCP auto-generation is powerful for organizations with large existing API estates.
- `mcp-zero`'s stdio transport support covers gateway-spawned server scenarios that Kong's HTTP-oriented model does not natively address.

### 3) Identity and authentication
- **mcp-zero:** Okta OAuth2 with on-behalf-of (OBO) token exchange for downstream MCP servers; identity claims mapped through the gateway.
- **Kong AI Gateway:** AI MCP OAuth2 plugin (MCP spec-compliant OAuth 2.1), OIDC via OpenID Connect plugin, JWT authentication, and consumer-based identity. Enterprise tier required for OIDC/SSO.

**Trade-off**
- `mcp-zero`'s OBO model propagates user identity through to downstream servers, maintaining end-to-end attribution.
- Kong provides broader authentication plugin options but the advanced identity integrations (OIDC/SSO) are gated behind Enterprise licensing.

### 4) Authorization and policy
- **mcp-zero:** deterministic deny-by-default policy engine with ordered allow/deny rules in static YAML/JSON files scoped to user, group, server, and tool.
- **Kong AI Gateway:** MCP Tool ACLs (introduced in 3.13) provide tool-level access control via consumer groups and JWT claims. Default-deny policies supported. ACL rules managed via declarative config (decK/Terraform) or control plane API.

**Implication**
- `mcp-zero` policies are self-contained files reviewable by compliance teams without external tooling.
- Kong's ACL model integrates with its existing consumer/consumer-group abstractions, which is natural for teams already using Kong but adds conceptual overhead for MCP-only deployments.

### 5) Data protection and masking
- **mcp-zero:** built-in inline Presidio masking for PII and secrets on both request inputs and response outputs within the gateway data path.
- **Kong AI Gateway:** AI PII Sanitizer plugin (Enterprise only) integrates with an external PII service, supporting 20+ PII categories across 12 languages. Offers replace-with-placeholder and synthetic-replacement modes, plus optional re-insertion of original data in responses. Runs in a self-hosted container for compliance.

**Trade-off**
- `mcp-zero`'s masking is built-in and requires no external service dependency.
- Kong's PII Sanitizer is more feature-rich (language coverage, synthetic replacement, reversible masking) but requires Enterprise license and an external PII service container.

### 6) Observability and auditing
- **mcp-zero:** structured audit logs with user attribution, correlation IDs, and policy decision records.
- **Kong AI Gateway:** MCP-specific Prometheus metrics (since 3.12), OpenTelemetry distributed tracing, log exports to SIEM systems, and Konnect Advanced Analytics dashboards. Token usage, latency, and cost tracking across LLM and MCP traffic.

**Where each excels**
- `mcp-zero`: self-contained audit trail purpose-built for governance compliance narratives.
- `Kong AI Gateway`: mature observability stack with Prometheus, OpenTelemetry, and SIEM integrations across API, LLM, and MCP traffic.

### 7) Extensibility and plugin ecosystem
- **mcp-zero:** Python-based extensibility; planned plugin architecture (see `docs/plugin-architecture-design.md`).
- **Kong AI Gateway:** mature plugin ecosystem with 100+ plugins spanning authentication, rate limiting, guardrails (AI Prompt Guard, AI Semantic Prompt Guard), content safety integrations (Azure, AWS), and custom Lua/Go/Python plugins.

**Practical outcome**
- Kong's plugin ecosystem is significantly more mature and covers a broader range of cross-cutting concerns.
- `mcp-zero`'s focused scope means less configuration surface area and fewer moving parts for MCP-specific governance.

---

## Hosting model comparison

### mcp-zero
- Self-hosted in any environment (VM, container, Kubernetes, on-prem).
- No cloud vendor or license dependency for core functionality.
- Predictable cost profile; no per-service or per-request billing.

### Kong AI Gateway
- Multiple deployment options: self-hosted, Kubernetes (Kong Ingress Controller), hybrid mode, or Konnect SaaS (fully managed).
- Open-source core (Apache-2.0) available for basic gateway functionality.
- MCP-specific features (AI MCP Proxy, PII Sanitizer, advanced ACLs) require Enterprise license.
- Per-service licensing model; enterprise pricing is sales-negotiated and not publicly transparent.

---

## License comparison

- **mcp-zero:** see repository license.
- **Kong AI Gateway:** open-source core under Apache-2.0 (GitHub: Kong/kong). MCP plugins (AI MCP Proxy, AI MCP OAuth2, AI PII Sanitizer) and advanced governance features are Enterprise-only with commercial licensing.

**Practical implication:** evaluating Kong for MCP governance requires Enterprise-tier procurement. The open-source core does not include the MCP-specific capabilities. Budget for sales-negotiated licensing with per-service pricing.

---

## Recommended use-cases

### Prefer mcp-zero when
1. You need a focused MCP governance gateway without the overhead of a full API gateway platform.
2. You require built-in inline PII masking without external service dependencies or Enterprise licensing.
3. You want simple, file-based policy artifacts that compliance teams can directly review.
4. You need stdio transport support for gateway-spawned MCP servers.

### Prefer Kong AI Gateway when
1. You already run Kong for API management and want to extend governance to MCP and LLM traffic.
2. You need auto-generation of MCP tools from existing REST APIs at scale.
3. You want a mature plugin ecosystem covering authentication, rate limiting, guardrails, and observability.
4. You need a unified platform governing traditional API, LLM, and MCP traffic in one control plane.

---

## Known limitations and caveats
- Kong's MCP capabilities are relatively new (3.12–3.13, late 2025) and evolving rapidly.
- The MCP-specific features are exclusively Enterprise-tier; open-source Kong does not provide MCP governance.
- Kong's pricing model (per-service, sales-negotiated) should be evaluated carefully against deployment scale.
- Re-verify current Kong documentation and plugin availability before implementation planning.

---

## Sources
- mcp-zero README: `README.md`
- Kong AI Gateway docs: https://developer.konghq.com/ai-gateway/
- Kong GitHub: https://github.com/Kong/kong
- Kong Enterprise MCP Gateway blog: https://konghq.com/blog/product-releases/enterprise-mcp-gateway
- Kong MCP security and governance blog: https://konghq.com/blog/product-releases/securing-observing-governing-mcp-servers-with-ai-gateway
- Kong MCP Tool ACLs blog: https://konghq.com/blog/product-releases/mcp-tool-acls-ai-gateway
- Kong AI MCP Proxy plugin docs: https://developer.konghq.com/plugins/ai-mcp-proxy/
- Kong AI PII Sanitizer plugin docs: https://developer.konghq.com/plugins/ai-sanitizer/
- Kong AI Gateway 3.13 release: https://konghq.com/blog/product-releases/ai-gateway-3-13
