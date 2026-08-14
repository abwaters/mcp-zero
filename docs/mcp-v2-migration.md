# mcp v1 → v2 Migration — Phase 0 Confirmed API Mapping

Status: **Migration complete.** Phase 0 (spike + API confirmation) is recorded
below; Phases 1–7 are implemented on `feat/mcp-v2`. The full suite passes on
`mcp==2.0.0`: **1099 non-integration + 39 integration = 1138 tests green**,
`ruff format`/`check` clean. The Phase 0 mapping proved accurate — no surprises
during implementation, and open item #1 (live upstream `session.initialize()`)
is confirmed working by the stdio/SSE integration tests.

This document records the *verified* v2 API surface, introspected against an
actually-installed `mcp==2.0.0` (scratch venv, Python 3.12), not the migration
guide prose — several guide claims proved wrong (noted inline). It supersedes
the guesswork in the original plan and is the source of truth for the port.

Related: this migration branch is `feat/mcp-v2`, opened to supersede Dependabot
PR #199 (which merely widened the range to admit v2 and broke CI).

## Installed dependency delta (mcp 2.0.0)

Installing `mcp==2.0.0` pulled: `mcp-types==2.0.0`, **`httpx2==2.10.0`**
(+`httpcore2`), `starlette==1.6.0`, `pydantic==2.13.x`, `sse-starlette==3.4.x`,
`opentelemetry-api==1.44.x`, `python-multipart`, `uvicorn`, `truststore`.

- **`httpx2`, not `httpx`.** mcp v2 uses `httpx2` internally and does **not**
  install plain `httpx`. Confirmed: `import httpx` fails in an mcp-only venv.
  The gateway's own code (`identity/jwks.py`, `identity/obo.py`) uses `httpx`,
  so **both must be direct dependencies** going forward (they coexist under
  different import names).
- **`starlette==1.6.0`.** Our pin `starlette>=0.36` admits it, but this is a
  major jump from the 0.x line — smoke-test CORS/middleware/Mount behavior.

## The five confirmed breaking changes

### 1. Types are snake_case now (highest blast radius, mechanical)

`mcp.types` is a permanent **alias** for `mcp_types` (confirmed) — keep existing
`import mcp.types as types` imports; no import churn needed.

Field renames (verified via `model_fields`):

| v1 (camelCase) | v2 (snake_case) |
|---|---|
| `Tool.inputSchema` | `Tool.input_schema` |
| `CallToolResult.isError` | `CallToolResult.is_error` |
| `ImageContent.mimeType` | `ImageContent.mime_type` |
| `CallToolResult.structuredContent` | `CallToolResult.structured_content` |

`model_dump()` now emits **snake_case**; `model_dump(by_alias=True)` emits the
**camelCase wire format** (`inputSchema`, `isError`, `structuredContent`,
`_meta`). `model_validate()` accepts snake_case (the field names) — so the
proxy's internal dump→mask→validate round-trip stays consistent if left in
snake_case.

New non-optional-looking fields exist on results (`Tool.execution`,
`Tool.output_schema`, `CallToolResult.result_type`, `ListToolsResult.ttl_ms`,
`cache_scope`) — all have defaults; our constructors don't need them.

Repo sites to change (from grep):
- `src/mcp_zero/proxy/tool_router.py:38` — `inputSchema=tool.inputSchema` → `input_schema=tool.input_schema`
- `src/mcp_zero/proxy/proxy_server.py:252` — `upstream_result.isError` → `.is_error`
- Tests: `tests/fixtures/echo_server.py` (4×), `echo_server_sse.py` (4×),
  `tests/proxy/test_tool_router.py` (`inputSchema=` kwargs + `.inputSchema`
  assert), `test_proxy_server.py:51,57`, `tests/integration/test_stdio_integration.py:240`.
- Masking payload dicts hardcode `"isError"`:
  `tests/masking/test_output_masking.py:55,92,112,496,506`,
  `tests/proxy/test_proxy_server.py:443`. See §Decision below.

### 2. Low-level `Server`: decorators → constructor callbacks (the real work)

**Verified `Server.__init__`** (keyword-only): `Server(name, *, on_list_tools=,
on_call_tool=, on_read_resource=, lifespan=, ...)`. The `@server.list_tools()`
and `@server.call_tool()` decorators **no longer exist** (`hasattr` == False).

Handler signatures (verified):
```python
on_list_tools: (ctx: ServerRequestContext, params: PaginatedRequestParams | None)
                 -> Awaitable[ListToolsResult]
on_call_tool:  (ctx: ServerRequestContext, params: CallToolRequestParams)
                 -> Awaitable[CallToolResult | InputRequiredResult]
```
- Handlers now **return the full result object**, not a bare list.
  `list[Tool]` → `ListToolsResult(tools=[...])`; `list[content]` →
  `CallToolResult(content=[...], is_error=...)`.
- Args arrive as a **params object**, not positional. `CallToolRequestParams`
  has `.name`, `.arguments` (also `.meta`, `.input_responses`, `.request_state`,
  `.task`). `ServerRequestContext` exposes `.params`, `.request`, `.request_id`,
  `.meta`, `.close_sse_stream`.
- **`Server.run(read, write, initialization_options, raise_exceptions=False)`
  is UNCHANGED** — it still requires `create_initialization_options()`. (The
  migration guide's claim that `run()` drops init options is **wrong**.)

**Verified live** in-memory round trip with this exact pattern: `list_tools`
returned a `Tool` with `input_schema`; `call_tool` returned a `CallToolResult`
with `.is_error=False` and `.content=[TextContent(text=...)]`. ✅

Affected: `src/mcp_zero/proxy/proxy_server.py:50,58-67` (construction +
`_register_handlers`), and the two test fixtures' `_build_server()`.

### 3. Client side barely moves (migration guide was wrong here)

All still exist and are importable:
- `from mcp import ClientSession` — constructor **unchanged**:
  `ClientSession(read_stream, write_stream, ...)`. `.initialize()`,
  `.list_tools()`, `.call_tool(name, arguments)` all present.
  `.list_tools()` → `ListToolsResult`; `.call_tool()` →
  `CallToolResult | InputRequiredResult | Result`.
- `from mcp.client.stdio import stdio_client` — yields **2-tuple** `(read,
  write)`, unchanged. `StdioServerParameters` unchanged (+ new optional `cwd`).
- `from mcp.client.sse import sse_client` — old kwargs `headers=`,
  `sse_read_timeout=` still present; added `httpx_client_factory=`, `auth=`.
- `from mcp.client.streamable_http import streamable_http_client` — **now
  yields a 2-tuple** `TransportStreams = (read, write)`. The old 3rd element
  `get_session_id` was removed. **`http_client=` must now be an
  `httpx2.AsyncClient`** (helper: `create_mcp_http_client(headers, timeout,
  auth)`).

So the "introduce `Client(...).session(transport)` object" from the plan is
**optional**, not required. The manual `ClientSession(read, write)` pattern
survives. Client-side work reduces to:
- `src/mcp_zero/transport/http.py:84-90` — unpack **2** values not 3
  (`get_session_id` gone), and build the client with **httpx2**.
- `session.initialize()` (`transport/{stdio,sse,http}.py`) is fine against
  real 2025-era upstreams. (It only 404s on the modern in-memory path, which
  we don't use for upstreams.) Keep it; verify against a live upstream in
  Phase 3.

Note: `Client` and `client.session` (a **property**, not a method) exist for
the new unified client, and `Client(server_object)` gives in-memory testing —
useful for new tests, but not required for the port.

### 4. Server-side ASGI transports survive nearly intact

- `from mcp.server.sse import SseServerTransport` — `SseServerTransport(endpoint,
  security_settings=None)`, `.connect_sse(scope, receive, send)`,
  `.handle_post_message(scope, receive, send)` — **all unchanged**.
- `from mcp.server.streamable_http_manager import StreamableHTTPSessionManager`
  — `StreamableHTTPSessionManager(app, event_store=None, json_response=False,
  stateless=False, ...)`, `.run()`, `.handle_request(scope, receive, send)` —
  **unchanged**. Current call `StreamableHTTPSessionManager(app=mcp_server,
  stateless=False)` still valid.
- `from mcp.server.stdio import stdio_server` — still a context manager.

So `src/mcp_zero/proxy/app.py` barely changes. `Server` even grows a convenience
`.streamable_http_app(...)` and `.session_manager` — optional, not needed since
we mount manually. **SSE is NOT removed** in v2 → `MCP_SSE_ENABLED` and the SSE
integration tests are **ported, not retired.**

### 5. Config / env vars

`MCP_*` env vars read by the gateway are **our own** config (`main.py`), not SDK
vars — **unaffected**. mcp v2 dropping `pydantic-settings`/`MCP_*` does not touch
us. `StdioServerParameters.env` still carries our `MCP_CORRELATION_ID`/
`MCP_TRACE_ID` injections unchanged.

## Decision: internal payload dict — snake_case vs by_alias

`proxy_server.py:251-252` dumps upstream content to a dict for the masking
pipeline, then rebuilds via `model_validate` (`:327-331`). Options:

- **(Recommended) Keep it snake_case.** Change `.isError`→`.is_error`; leave
  `c.model_dump()` as-is (now snake_case). The dump→mask→validate round-trip is
  self-consistent, and the object returned to the SDK is re-serialized to the
  camelCase wire format by the SDK itself. Cost: update masking tests that
  hardcode `"isError"` → `"is_error"`.
- Alternative: `model_dump(by_alias=True)` + `"isError"` to preserve the old
  dict shape and avoid touching those tests — but then `model_validate` must
  also round-trip camelCase, and we'd be carrying wire format internally for no
  functional gain.

Chosen: **snake_case internal**, update the ~7 test assertions.

## Revised effort assessment (vs original plan)

| Phase | Original fear | Confirmed reality |
|---|---|---|
| 1 Types | wide | **wide but mechanical** — field renames + ~7 test key updates |
| 2 Server | large | **the main work** — handler signature + return-object change |
| 3 Client | large rewrite | **small** — httpx2 client + 3→2-tuple unpack; sessions unchanged |
| 4 ASGI | biggest risk | **minimal** — SSE + session manager APIs unchanged |
| 5 Tests | large | fixtures rewritten to `on_*` callbacks; field renames |
| 6 Deps/CI | — | `mcp>=2,<3`, **add `httpx2`**, keep `httpx`, verify starlette 1.6 |
| 7 Docs | — | update SSE note stays "deprecated but supported"; drop v1 refs |

**Net:** the migration is *smaller and lower-risk* than the pre-spike plan
assumed. The `Client`/transport rewrite and the "SSE removed" contingency are
both off the table. Concentrate effort on Phase 2 (server handlers) and Phase 1
(field renames).

## pyproject deltas (Phase 6 preview)

```toml
dependencies = [
    "mcp>=2.0.0,<3.0.0",   # was >=1.26.0,<2.0.0
    "httpx2>=2.10",        # NEW — for streamable_http_client http_client=
    "httpx>=0.27",         # KEEP — gateway JWKS/OBO code
    "starlette>=1.6",      # verify; was >=0.36
    # uvicorn/pyyaml/presidio/redis/PyJWT unchanged
]
```

## Open items to verify during implementation

1. Live upstream `session.initialize()` handshake against a real 2025-era stdio
   server (Phase 3) — confirm it doesn't 404 like the modern in-memory path.
2. `starlette==1.6.0` CORS middleware + `Mount` behavior in `proxy/app.py`
   (Phase 4 smoke test).
3. New "exceptions in handlers surface as JSON-RPC errors" behavior vs the
   gateway's fail-closed `ShortCircuitError`/`HookError` path — confirm denials
   still render as a proper error to the client (Phase 2).
4. presidio/spacy vs `pydantic==2.13` and `numpy` resolver on Python 3.14 CI.
```
