## What This Is
The Enterprise MCP Gateway is a control point that allows MCP to be used safely in regulated enterprise environments. It supports both HTTP and stdio MCP transports, covering remote MCP servers as well as gateway-managed server processes.

For tool calls routed through the gateway, it provides:
- Governance policies that control which tools can be invoked
- User attribution on all actions
- Inline masking of sensitive data (PII and secrets)
- Comprehensive audit logging

---

## What This Is Not
- It is not a device control or endpoint lockdown tool
- It does not prevent all local developer MCP usage
- It is not a full DLP or intent-classification system

---

## Why This Matters
Without a gateway, MCP adoption is blocked by security and compliance concerns. This system provides the minimum viable control surface required to approve MCP usage without halting innovation.

---

## Enforcement Reality
- Tool calls routed through the gateway (HTTP or stdio): **full enforcement**
- Tool discovery requests (tools/list): **no per-user authorization**
- Local developer tools (bypassing gateway): **observability-only**

When tool calls flow through the gateway, governance policies, data masking, and audit logging apply regardless of transport. Tool listing shows the same catalog to all authenticated users. Local developer MCP usage outside the gateway cannot be controlled by the gateway.

---

## Current Limitations
1. **Tool Discovery**: The tools/list endpoint does not enforce per-user authorization rules — all users see the same tool catalog
2. **OBO Token Exchange**: Available for HTTP servers but requires explicit per-server configuration in policy files
3. **stdio Transport**: Does not support OBO token exchange (process-local execution model)

---

## Bottom Line
The gateway makes MCP *approvable* in enterprise environments.

