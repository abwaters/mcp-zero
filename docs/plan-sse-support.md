# Plan: Add SSE Transport Support to mcp-zero

> **STATUS**: This plan has been **FULLY IMPLEMENTED**. All four phases (outbound SSE
> transport, inbound SSE endpoints, integration tests, and documentation updates) are
> complete. SSE is marked as deprecated in the MCP spec (2025-03-26) but remains available
> for backward compatibility. Controlled by `MCP_SSE_ENABLED` env var (default: `true`).

## Background

The MCP specification (protocol version 2024-11-05) defined an SSE (Server-Sent Events) transport using a dual-endpoint architecture. While officially deprecated in the 2025-03-26 spec in favor of Streamable HTTP, SSE remains widely deployed and many MCP servers/clients still only support it. Adding SSE support to mcp-zero enables the gateway to interoperate with the broader MCP ecosystem.

SSE transport uses two endpoints:
- **GET `/sse`** — Client opens a persistent SSE connection; server immediately sends an `endpoint` event containing the POST URL
- **POST `/messages`** — Client sends JSON-RPC messages; server responds via the SSE stream

The MCP Python SDK (v1.26.0, already a dependency) ships both `mcp.client.sse.sse_client` and `mcp.server.sse.SseServerTransport`, so the core protocol plumbing is available.

## Scope

SSE support touches two distinct surfaces:

| Direction | Role | Description |
|-----------|------|-------------|
| **Outbound** (client-side) | Gateway connects to upstream MCP servers that expose SSE | New `SSETransport` class in `transport/` |
| **Inbound** (server-side) | Gateway accepts connections from older MCP clients via SSE | New SSE endpoint mounting in `proxy/app.py` |

Both surfaces must enforce the full governance pipeline (identity, governance, masking, audit) identically to the existing Streamable HTTP and stdio transports.

---

## Phase 1: Outbound SSE Transport (Gateway → Upstream Server)

Allows mcp-zero to connect to upstream MCP servers that only expose SSE endpoints (not Streamable HTTP).

### 1.1 Add `SSE` to `TransportType` enum

**File:** `src/mcp_zero/transport/config.py`

```python
class TransportType(StrEnum):
    HTTP = "http"
    SSE = "sse"          # <-- new
    STDIO = "stdio"
```

Add validation in `ServerConfig.__post_init__` for the SSE transport type — it requires a `url` field (same as HTTP) and should enforce HTTPS unless `allow_insecure` is set.

### 1.2 Create `SSETransport` class

**New file:** `src/mcp_zero/transport/sse.py`

Follow the same background-task isolation pattern used by `StreamableHTTPTransport` and `StdioTransport`:

```python
from mcp.client.sse import sse_client

class SSETransport(MCPTransport):
    async def connect(self, context, *, auth_token=None):
        # 1. Build headers (X-Correlation-ID, Authorization, etc.)
        # 2. Spawn _connection_owner background task
        # 3. Inside task: enter sse_client(url, headers=headers) context manager
        # 4. Initialize ClientSession
        # 5. Wait on stop_event to keep connection alive

    async def disconnect(self):
        # Signal stop_event, await background task cleanup
```

Key differences from `StreamableHTTPTransport`:
- Uses `sse_client()` instead of `streamable_http_client()`
- `sse_client` accepts `headers` dict directly (no need for a separate `httpx.AsyncClient`)
- The SSE connection is inherently long-lived (persistent GET), so timeout handling differs — the `sse_read_timeout` parameter controls how long the client waits for server events before timing out

### 1.3 Register in `TransportFactory`

**File:** `src/mcp_zero/transport/factory.py`

```python
from mcp_zero.transport.sse import SSETransport

class TransportFactory:
    _registry = {
        TransportType.HTTP: StreamableHTTPTransport,
        TransportType.SSE: SSETransport,           # <-- new
        TransportType.STDIO: StdioTransport,
    }
```

### 1.4 Update policy loader

**File:** `src/mcp_zero/governance/loader.py`

Ensure `convert_to_server_configs()` accepts `transport: "sse"` in policy YAML and maps it to `TransportType.SSE`. The server config block would look like:

```yaml
servers:
  - name: legacy-server
    transport: sse
    url: https://legacy.example.com/sse
```

### 1.5 Tests

**New file:** `tests/transport/test_sse.py`

Mirror the test structure of `tests/transport/test_http.py`:
- Test connect/disconnect lifecycle
- Test state transitions (DISCONNECTED → CONNECTING → CONNECTED → DISCONNECTING → DISCONNECTED)
- Test error handling (connection refused, timeout, invalid URL)
- Test header propagation (correlation ID, auth token)
- Test reconnection after disconnect
- Mock `sse_client` context manager to avoid real network calls

---

## Phase 2: Inbound SSE Endpoint (Client → Gateway)

Allows older MCP clients that only support SSE to connect to the gateway.

### 2.1 Mount SSE endpoints in the ASGI app

**File:** `src/mcp_zero/proxy/app.py`

Use the SDK's `SseServerTransport` alongside the existing `StreamableHTTPSessionManager`:

```python
from mcp.server.sse import SseServerTransport

def create_app(proxy_server, server_manager, *, analytics_collector=None):
    # Existing Streamable HTTP setup
    session_manager = StreamableHTTPSessionManager(...)

    # New SSE transport
    sse_transport = SseServerTransport("/mcp/sse/messages/")

    async def handle_sse(request):
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await proxy_server.mcp_server.run(
                streams[0], streams[1],
                proxy_server.mcp_server.create_initialization_options(),
            )

    async def handle_sse_messages(request):
        await sse_transport.handle_post_message(
            request.scope, request.receive, request._send
        )

    app = Starlette(
        routes=[
            Mount("/mcp", app=mcp_asgi),                           # Streamable HTTP (existing)
            Route("/mcp/sse", endpoint=handle_sse),                # SSE GET (new)
            Route("/mcp/sse/messages/", endpoint=handle_sse_messages, methods=["POST"]),  # SSE POST (new)
        ],
        lifespan=lifespan,
    )
```

### 2.2 Auth middleware compatibility

**File:** `src/mcp_zero/proxy/middleware.py`

The existing `AuthHeaderMiddleware` already extracts `Authorization` from HTTP requests, so SSE requests (which are HTTP GET/POST) will have auth headers extracted automatically. No changes needed here.

### 2.3 Configuration

Add an environment variable to control whether the SSE inbound endpoint is enabled:

```
MCP_SSE_ENABLED=true|false    # Default: true (for backward compat)
```

This allows operators to disable the legacy SSE endpoint in environments where only Streamable HTTP clients are expected, reducing attack surface.

**File:** `src/mcp_zero/main.py` — pass `sse_enabled` flag to `create_app()`.

### 2.4 Tests

**New file:** `tests/proxy/test_sse_endpoints.py`

- Test GET `/mcp/sse` returns SSE event stream with `endpoint` event
- Test POST `/mcp/sse/messages/` routes JSON-RPC messages correctly
- Test auth header extraction works for SSE requests
- Test full lifecycle: SSE connect → initialize → list_tools → call_tool → disconnect
- Test pipeline enforcement (governance deny, masking, audit) through SSE path
- Test `MCP_SSE_ENABLED=false` disables SSE endpoints

---

## Phase 3: Integration Testing

### 3.1 Outbound SSE integration test

**New file:** `tests/integration/test_sse_integration.py`

Mirror `tests/integration/test_stdio_integration.py` structure. Start a test MCP server that exposes SSE transport (use SDK's `SseServerTransport`), connect via the gateway, and verify:
- Tool listing through SSE upstream
- Tool calls with full pipeline enforcement
- Governance deny blocks calls
- Input/output PII masking
- Audit trail metadata
- Session reuse across calls
- Error handling (upstream disconnect, timeout)

### 3.2 Inbound SSE integration test

Test the gateway as an SSE server using the SDK's `sse_client`:
- Client connects to gateway `/mcp/sse` endpoint
- Client sends initialize, list_tools, call_tool via `/mcp/sse/messages/`
- Verify full pipeline enforcement on the inbound SSE path
- Test concurrent SSE clients

---

## Phase 4: Documentation and Policy Updates

### 4.1 Update CLAUDE.md

Add SSE to the transport list and document the `MCP_SSE_ENABLED` env var.

### 4.2 Update PRD

**File:** `docs/prd.md`

Add SSE to the supported transports section, noting it's provided for backward compatibility with clients/servers that haven't adopted Streamable HTTP.

### 4.3 Update architecture diagram

**File:** `docs/enterprise_mcp_gateway_architecture_diagram.md`

Show SSE as an additional transport option alongside Streamable HTTP and stdio.

### 4.4 Policy file examples

Update example policy files to show SSE server configuration:

```yaml
servers:
  - name: legacy-mcp-server
    transport: sse
    url: https://legacy.example.com/sse
    timeout_seconds: 30
```

---

## File Change Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `src/mcp_zero/transport/config.py` | Modify | Add `SSE = "sse"` to `TransportType`, add SSE validation in `ServerConfig` |
| `src/mcp_zero/transport/sse.py` | **New** | `SSETransport` class using `mcp.client.sse.sse_client` |
| `src/mcp_zero/transport/factory.py` | Modify | Register `SSETransport` in factory registry |
| `src/mcp_zero/transport/__init__.py` | Modify | Export `SSETransport` |
| `src/mcp_zero/proxy/app.py` | Modify | Mount `/mcp/sse` and `/mcp/sse/messages/` routes |
| `src/mcp_zero/main.py` | Modify | Add `MCP_SSE_ENABLED` env var, pass to `create_app()` |
| `src/mcp_zero/governance/loader.py` | Modify | Accept `transport: "sse"` in policy YAML |
| `tests/transport/test_sse.py` | **New** | Unit tests for `SSETransport` |
| `tests/proxy/test_sse_endpoints.py` | **New** | Unit tests for inbound SSE endpoints |
| `tests/integration/test_sse_integration.py` | **New** | End-to-end SSE integration tests |
| `docs/prd.md` | Modify | Document SSE transport support |
| `docs/enterprise_mcp_gateway_architecture_diagram.md` | Modify | Add SSE to diagram |
| `CLAUDE.md` | Modify | Add SSE env vars and transport notes |

## Implementation Order

1. **Phase 1** (Outbound) — Lowest risk, self-contained transport addition
2. **Phase 2** (Inbound) — Requires app.py changes, moderate risk
3. **Phase 3** (Integration tests) — Validates both phases end-to-end
4. **Phase 4** (Docs) — Final cleanup

## Design Decisions

1. **SSE as a distinct `TransportType`** rather than a flag on HTTP — keeps the factory pattern clean and makes policy files explicit about which protocol the upstream server speaks.

2. **Reuse SDK's `SseServerTransport`** for inbound — the SDK handles the SSE protocol details (event formatting, session routing, DNS rebinding protection). No need to reimplement.

3. **Same pipeline enforcement** — SSE traffic goes through the identical Identity → Governance → Masking → Audit pipeline. No special cases or bypass paths.

4. **`MCP_SSE_ENABLED` defaults to `true`** — maximizes backward compatibility. Operators who want to restrict to Streamable HTTP only can disable it.

5. **Endpoint paths** — `/mcp/sse` and `/mcp/sse/messages/` are nested under `/mcp` to keep all MCP traffic under a single path prefix, simplifying reverse proxy and firewall rules.

6. **Deprecation awareness** — SSE transport is deprecated in the MCP spec. The implementation should log a deprecation notice when SSE connections are established, guiding operators toward Streamable HTTP migration.
