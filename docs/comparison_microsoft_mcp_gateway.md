# comparison_microsoft_mcp_gateway.md

## Gist (read this first)
**Choose Microsoft MCP Gateway over `mcp-zero`** when you need a Kubernetes-native MCP gateway/control-plane system with session-aware routing, adapter/tool lifecycle APIs, and tight alignment to enterprise cluster operations.

**Choose `mcp-zero` over Microsoft MCP Gateway** when your near-term goal is a smaller, easier-to-reason-about enterprise MCP control point focused on policy determinism, identity mapping, masking, and simple deployment.

---

## Snapshot comparison

| Area | mcp-zero | Microsoft MCP Gateway |
|---|---|---|
| Product shape | Focused enterprise MCP gateway | Data plane + control plane for MCP assets |
| Runtime/stack | Python service | .NET + Kubernetes-native architecture |
| Routing model | MCP proxying (HTTP + stdio) | Session-aware routing with adapter and tool gateway concepts |
| Control plane | Policy-file-driven configuration | REST APIs for adapter/tool registration and lifecycle |
| Deployment posture | Self-hosted by enterprise (flexible footprint) | Kubernetes-first, includes local K8s and Azure deployment paths |
| License | Project license in this repo | MIT |

---

## Feature and use-case comparison

### 1) Architecture and operating model
- **mcp-zero:** compact gateway with hook-based control path (identity, governance, masking, audit).
- **Microsoft MCP Gateway:** separates control-plane management APIs from data-plane routing and emphasizes lifecycle operations (deploy/update/delete for adapters/tools).

**Where each excels**
- `mcp-zero`: teams needing fast path to enterprise-safe MCP mediation.
- `microsoft mcp gateway`: platform teams managing many MCP services in cluster environments.

### 2) Routing and session behavior
- **mcp-zero:** straightforward proxy behavior with policy and masking controls around requests.
- **Microsoft MCP Gateway:** explicitly designed for session-aware/stateful routing and multi-instance router patterns.

**Implication**
- If session affinity and dynamic tool routing at scale are core requirements, Microsoft’s model is a stronger native fit.

### 3) Governance vs platform control plane emphasis
- **mcp-zero:** governance semantics are central product identity (enforced on both HTTP and stdio transports through a unified pipeline).[^1]
- **Microsoft MCP Gateway:** platform operations and MCP server lifecycle management are central.

**Trade-off**
- `mcp-zero` may be simpler to adopt for policy-first governance on HTTP traffic.
- Microsoft MCP Gateway may be superior where centralized runtime orchestration is mandatory.

---

## Hosting model comparison

### mcp-zero
- Can be deployed in many hosting patterns with minimal moving parts.
- Often suitable as a centralized but lightweight enterprise policy gateway.

### Microsoft MCP Gateway
- Kubernetes-native by design and documented with local K8s and Azure deployment flows.
- Better fit for organizations already standardized on cluster operations and managed cloud environments.

---

## License comparison

- **mcp-zero:** see repository license.
- **Microsoft MCP Gateway:** MIT.

**Practical implication:** MIT is permissive for enterprise use, including internal forks/extensions.

---

## Recommended use-cases

### Prefer mcp-zero when
1. You want governance-first MCP control with explicit deny/allow policy semantics (enforced on HTTP traffic).
2. You need to explain security controls quickly to compliance stakeholders.
3. You prefer a lightweight service architecture.

### Prefer Microsoft MCP Gateway when
1. You need lifecycle APIs for MCP adapters/tools in a Kubernetes platform.
2. You require session-aware routing and platform-scale operational integration.
3. You plan to align with Azure/Kubernetes enterprise deployment practices.

---

## Known limitations and caveats
- Architectural complexity and team operating model should drive the decision as much as feature checklists.
- Re-verify latest API and deployment docs before implementation planning.

---

## Implementation Notes

[^1]: **Unified transport enforcement**: Both HTTP and stdio transports enforce the same governance, masking, and audit policies through a unified pipeline. Previous versions of this document incorrectly stated that stdio bypassed these controls; this was corrected following integration test validation in PR #101.

---

## Sources
- mcp-zero README: `README.md`
- Microsoft MCP Gateway: https://github.com/microsoft/mcp-gateway
