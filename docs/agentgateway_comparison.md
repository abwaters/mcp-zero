# mcp-zero vs agentgateway (agentgateway.dev) — Detailed Comparison

_Date: 2026-02-10_

This document compares the current `mcp-zero` repository to the open-source `agentgateway/agentgateway` project.

## Scope and source basis

- `mcp-zero` sources reviewed: project README, Python package layout, pipeline/governance/identity internals, and test suite.
- `agentgateway` sources reviewed from `https://github.com/agentgateway/agentgateway`: README, architecture docs (`configuration`, `CEL`), config schema docs, and workspace/development metadata.

## Executive summary

- **mcp-zero** is a focused **enterprise MCP gateway** with opinionated controls around **identity (Okta JWT), policy allow/deny, data masking (Presidio), auditing, and MCP proxying** (HTTP + stdio). It is compact, Python-native, and straightforward to reason about.
- **agentgateway** is a broader **agentic AI data plane** in Rust, designed for **MCP + A2A + generalized HTTP policy/filtering**, with dynamic config (including xDS), multi-tenant support, richer policy surface, built-in UI, and larger-scale operational features.
- Practical framing:
  - Pick **mcp-zero** when you need a smaller, MCP-specific control point with explicit enterprise guardrails and faster Python customization.
  - Pick **agentgateway** when you need protocol breadth, high-performance data-plane behavior, richer dynamic policy/transformation primitives, and larger multi-tenant/runtime scale characteristics.

---

## 1) Product intent and problem framing

### mcp-zero
- Positioning is explicitly: “Enterprise MCP Gateway” for regulated environments.
- Core problem statement focuses on enterprise approval blockers: access control, attribution, data protection, and auditability.
- Feature set aligns tightly with those controls.

### agentgateway
- Positioning is broader: a “connectivity solution for Agentic AI” and “data plane” for agent-to-agent and agent-to-tool connectivity.
- Supports interoperable protocols including MCP and A2A, not just MCP.
- Explicitly emphasizes dynamic operation and multi-tenant deployment.

**Bottom line:** mcp-zero is **MCP governance-first**; agentgateway is **agent connectivity platform-first**.

## 2) Core architecture model

### mcp-zero
- Hook pipeline with ordered lifecycle stages (identity → governance → masking → audit).
- Startup configuration path is simple: policy file (preferred) or env-var fallback.
- Governance engine is deterministic and easy to inspect: ordered rule scan, deny override, default fallback, fail-closed error handling.

### agentgateway
- Three configuration planes:
  - static config,
  - local file-driven dynamic config with reload,
  - xDS remote control-plane integration.
- Local/xDS map into a shared IR with design goal of minimizing fan-out and preserving near-direct API↔IR mapping.
- CEL is deeply embedded across authz, transformations, logging/tracing fields, and rate-limiting selection.

**Bottom line:** mcp-zero optimizes for **clarity and explicit enterprise controls**; agentgateway optimizes for **data-plane scale, dynamic control planes, and policy expressiveness**.

## 3) Identity, authentication, and downstream auth

### mcp-zero
- JWT validation at gateway edge (Okta-centric defaults, configurable claim mapping).
- User/group context extraction is first-class input into policy decisions.
- Built-in OBO token exchange support for downstream servers (when enabled per server and env/config is present).

### agentgateway
- Security surface is broader and policy-oriented (authz/filtering infrastructure plus CEL).
- Configuration schema and codebase indicate a variety of auth mechanisms and policy attachments in a generalized gateway model.
- Not specialized to a single IdP model in the same way mcp-zero defaults to Okta patterns.

**Bottom line:** mcp-zero is opinionated and ready for **Okta-style enterprise identity flow**; agentgateway offers a **broader gateway authn/authz foundation**.

## 4) Authorization and policy semantics

### mcp-zero
- Static YAML/JSON policy model with default effect + ordered rule list.
- Rule matching dimensions: subjects (users/groups), server, tool patterns.
- Explicit behavior: deny overrides allow, unmatched requests follow default, and exceptions fail closed.

### agentgateway
- Richer policy categories and route/listener/bind hierarchy implied by schema.
- CEL expressions enable highly dynamic, context-driven policy logic.
- Architecture emphasizes runtime policy merge/precedence from multiple attachment points.

**Bottom line:** mcp-zero policy is **predictable and auditable with low cognitive load**; agentgateway policy is **more expressive and composable**, but with higher operational complexity.

## 5) Data protection and content controls

### mcp-zero
- First-class Presidio masking integration for PII/secrets.
- Masking can run inline pre/post flow according to hook lifecycle and policy settings.
- Built-in entity support and extensibility via Presidio recognizers.

### agentgateway
- Broader AI policy constructs in schema include prompt-guard style controls and transformation primitives.
- Strong flexibility for traffic transformation/modification, but with a different philosophy than mcp-zero’s explicit “mask sensitive text” control point.

**Bottom line:** mcp-zero provides a **clear enterprise-safe default for redaction/masking**; agentgateway provides **richer generalized AI/HTTP policy tooling**.

## 6) Protocol and transport coverage

### mcp-zero
- MCP-focused transports:
  - streamable HTTP upstreams,
  - stdio process-managed upstreams.
- Designed around MCP server routing/control concerns.

### agentgateway
- MCP + A2A support is explicit.
- Includes broader HTTP/gateway capabilities (routes/listeners/policies) and legacy API transformation (OpenAPI -> MCP resources).

**Bottom line:** mcp-zero is **purpose-built for MCP gatewaying**; agentgateway is **multi-protocol and broader connectivity fabric**.

## 7) Runtime performance and scale posture

### mcp-zero
- Python runtime with Starlette/Uvicorn dependencies.
- Appropriate for controlled enterprise gateways and policy-centric use, but not claiming ultra-high-throughput data-plane characteristics.

### agentgateway
- Rust implementation with “highly performant” positioning and architecture decisions aimed at efficiency under dynamic updates.
- Workspace composition and performance-sensitive design choices indicate optimization for scale-out data-plane use.

**Bottom line:** agentgateway has the stronger **high-scale throughput/latency posture**; mcp-zero has the stronger **simplicity and Python customization posture**.

## 8) Operations and deployment model

### mcp-zero
- Operates via env vars + policy file.
- Minimal moving parts for startup and operation.
- Suitable for teams prioritizing understandable control behavior over dynamic control-plane integrations.

### agentgateway
- Supports standalone docs and Kubernetes ecosystem integration path.
- Built-in UI and richer admin/stats/readiness endpoint model in config schema.
- Dynamic reload and xDS paths align with platform-style operations.

**Bottom line:** mcp-zero is **lighter operationally**; agentgateway is **more platform-grade operationally**.

## 9) Developer experience and extensibility

### mcp-zero
- Python package with clear module boundaries (identity/governance/masking/audit/transport/proxy).
- Hook registry model is easy to extend with custom logic.
- Fast iteration for Python teams.

### agentgateway
- Large Rust workspace with multiple crates and more subsystems.
- Very extensible for gateway/platform engineers; steeper learning curve for smaller app teams.

**Bottom line:** mcp-zero favors **small-team speed and direct customization**; agentgateway favors **deep platform extensibility**.

## 10) Maturity indicators from repository shape

### mcp-zero
- Python 3.12 project with focused dependency set.
- Substantial unit/integration test surface in the repo for implemented modules.
- Product messaging and docs are tightly centered on enterprise MCP controls.

### agentgateway
- Multi-crate Rust workspace + Go protobuf tooling + UI assets.
- Larger ecosystem signals (release badges/community links/docs split for standalone vs kgateway environments).
- Broad schema surface and extensive test footprint across subsystems.

## 11) Trade-off matrix

| Dimension | mcp-zero | agentgateway |
|---|---|---|
| Primary scope | Enterprise MCP governance gateway | Agentic AI connectivity data plane |
| Protocol breadth | MCP-centric | MCP + A2A + broad HTTP/gateway features |
| Policy model | Static ordered allow/deny + wildcard matching | Rich route/policy model + CEL-heavy expressions |
| Data protection | Presidio masking first-class | Broad AI/HTTP controls; masking not the sole centerpiece |
| Dynamic control plane | Basic/local startup config | Local hot-reload + xDS integration |
| Multi-tenancy stance | Not central in current messaging | Explicit multi-tenant claim |
| Runtime profile | Python simplicity | Rust performance-first |
| Team fit | Security/compliance teams needing straightforward MCP control | Platform teams building large-scale heterogeneous AI connectivity |

## 12) Suggested positioning for mcp-zero vs agentgateway

To avoid “head-to-head commodity gateway” framing, mcp-zero can lean into:

1. **Regulated-enterprise MCP guardrail pack**
   - Opinionated secure defaults (deny-by-default, fail-closed, mandatory audit fields).
2. **Identity + compliance integration depth**
   - Expand beyond Okta to additional enterprise IdPs while preserving simple semantics.
3. **Masking governance UX**
   - Add richer policy-level controls around masking actions/reporting for compliance workflows.
4. **MCP-native policy ergonomics**
   - Keep policies human-auditable and predictable rather than maximally dynamic.

Conversely, if aiming to compete more directly with agentgateway, likely investments would include:
- dynamic config/watch + remote control plane,
- more expressive policy language (potentially CEL-like),
- broader protocol interoperability beyond MCP,
- operational UI + richer telemetry surface.

---

## Final recommendation by use case

- Choose **mcp-zero** if your near-term objective is: “secure and approve MCP usage in a regulated enterprise quickly with explicit identity/policy/masking/audit controls.”
- Choose **agentgateway** if your objective is: “run a high-performance, multi-tenant, multi-protocol agent connectivity data plane with dynamic policy and control-plane integration.”

