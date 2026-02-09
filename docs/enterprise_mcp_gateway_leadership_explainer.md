## What This Is
The Enterprise MCP Gateway is a control point that allows MCP to be used safely in regulated enterprise environments. It supports both HTTP and stdio MCP transports, covering remote MCP servers as well as gateway-managed server processes.

It enables AI tools to use MCP while ensuring:
- Only approved tools are accessible
- Actions are attributable to real users
- Sensitive data is masked
- All activity is auditable

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
- Hosted enterprise AI tools (HTTP or stdio through gateway): **enforced**
- Local developer tools (direct stdio outside gateway): **monitored**

This applies regardless of transport — when traffic flows through the gateway (HTTP or stdio), governance is enforced. Local developer MCP usage outside the gateway remains observability-only, reflecting technical reality and avoiding false security claims.

---

## Bottom Line
The gateway makes MCP *approvable* in enterprise environments.

