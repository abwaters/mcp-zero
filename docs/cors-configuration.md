# CORS Configuration

This document explains how to configure Cross-Origin Resource Sharing (CORS) in mcp-zero so that browser-based MCP clients (web IDEs, dashboards, internal tools) can connect to the gateway.

## Overview

CORS is **disabled by default**, consistent with the gateway's fail-closed security posture. When enabled, the gateway adds Starlette's `CORSMiddleware` around the authentication layer, so preflight `OPTIONS` requests are handled before auth enforcement.

```
Browser (https://dashboard.corp.com)
  │
  │  OPTIONS /mcp  (preflight)
  ▼
┌──────────────────────────┐
│  CORSMiddleware          │  ← responds to preflight here
│  ┌────────────────────┐  │
│  │ AuthHeaderMiddleware│  │  ← auth enforced on actual requests
│  │  ┌──────────────┐  │  │
│  │  │  Starlette    │  │  │
│  │  │  (routes)     │  │  │
│  │  └──────────────┘  │  │
│  └────────────────────┘  │
└──────────────────────────┘
```

## Quick Start

The fastest way to enable CORS is with environment variables:

```bash
# Allow a single origin
export MCP_CORS_ORIGINS=https://dashboard.corp.com

# Allow multiple origins (comma-separated)
export MCP_CORS_ORIGINS=https://dashboard.corp.com,https://web-ide.corp.com
```

That's it. The gateway will respond with the appropriate CORS headers for requests from those origins.

## Configuration Methods

CORS can be configured through the **policy file**, **environment variables**, or both. Environment variables always take precedence over policy file values.

### Policy File

Add a `cors` section to your policy YAML:

```yaml
cors:
  allow_origins:
    - https://dashboard.corp.com
    - https://web-ide.corp.com
  allow_methods: ["GET", "POST", "OPTIONS"]
  allow_headers: ["Authorization", "Content-Type"]
  allow_credentials: false
  max_age: 600
  expose_headers: []
```

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `MCP_CORS_ORIGINS` | Comma-separated allowed origins (enables CORS when set) | _(none)_ |
| `MCP_CORS_ALLOW_CREDENTIALS` | Allow credentials (`true`, `1`, `yes` to enable) | `false` |
| `MCP_CORS_MAX_AGE` | Preflight cache duration in seconds | `600` |

### Precedence Rules

When both sources are present, the merge logic works as follows:

1. If neither source configures origins, CORS stays **disabled**.
2. If only the policy file has a `cors` section, those values are used.
3. If only env vars are set, they are used with safe defaults for unset fields.
4. If both are present, the policy file provides the base and env vars **override** individual fields (`origins`, `allow_credentials`, `max_age`).

## Configuration Reference

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `allow_origins` | list of strings | Yes | _(none)_ | Origins permitted to make cross-origin requests. |
| `allow_methods` | list of strings | No | `["GET", "POST", "OPTIONS"]` | HTTP methods allowed in cross-origin requests. |
| `allow_headers` | list of strings | No | `["Authorization", "Content-Type"]` | HTTP headers allowed in cross-origin requests. |
| `allow_credentials` | boolean | No | `false` | Whether the browser may send cookies or `Authorization` headers. |
| `max_age` | integer | No | `600` | How long (in seconds) browsers may cache preflight responses. |
| `expose_headers` | list of strings | No | `[]` | Response headers the browser is allowed to read. |

## Validation Rules

The gateway validates CORS configuration at startup and will refuse to start if the configuration is invalid:

- **`allow_origins` must be non-empty.** If you enable CORS, you must specify at least one origin.
- **Wildcard + credentials is forbidden.** Setting `allow_origins: ["*"]` with `allow_credentials: true` is rejected because browsers ignore `Access-Control-Allow-Origin: *` when credentials are involved.
- **`max_age` must be non-negative.** A negative cache duration is rejected.

## Examples

### Single internal dashboard

```yaml
cors:
  allow_origins:
    - https://dashboard.corp.com
```

All other fields use their defaults. The dashboard can make `GET`, `POST`, and `OPTIONS` requests with `Authorization` and `Content-Type` headers.

### Multiple origins with credentials

```yaml
cors:
  allow_origins:
    - https://web-ide.corp.com
    - https://dashboard.corp.com
  allow_credentials: true
  expose_headers: ["X-Request-Id"]
```

This allows browser-based clients to send cookies or bearer tokens via `withCredentials` and read the `X-Request-Id` response header.

### Development / allow all origins

```yaml
cors:
  allow_origins: ["*"]
```

Allows any origin. **Do not use this in production.** Note that `allow_credentials` must remain `false` when using the wildcard origin.

### Environment-only (no policy file)

```bash
export MCP_CORS_ORIGINS=https://dashboard.corp.com,https://web-ide.corp.com
export MCP_CORS_ALLOW_CREDENTIALS=true
export MCP_CORS_MAX_AGE=3600
```

Useful for quick testing or when the gateway runs without a policy file.

### Environment overriding policy file

If the policy file sets:

```yaml
cors:
  allow_origins:
    - https://old-dashboard.corp.com
  max_age: 300
```

And the environment sets:

```bash
export MCP_CORS_ORIGINS=https://new-dashboard.corp.com
export MCP_CORS_MAX_AGE=1800
```

The effective configuration will be:
- **origins**: `https://new-dashboard.corp.com` (env wins)
- **max_age**: `1800` (env wins)
- **allow_methods**: `["GET", "POST", "OPTIONS"]` (policy default)
- **allow_headers**: `["Authorization", "Content-Type"]` (policy default)

## Verifying CORS Is Active

When CORS is enabled, the gateway logs it at startup:

```
INFO  CORS middleware enabled: origins=['https://dashboard.corp.com']
```

The gateway-ready log line also includes CORS status:

```
INFO  Gateway ready: ... cors=enabled ...
```

You can verify with a preflight request:

```bash
curl -i -X OPTIONS https://gateway.corp.com/mcp \
  -H "Origin: https://dashboard.corp.com" \
  -H "Access-Control-Request-Method: POST"
```

A successful response includes:
```
HTTP/1.1 200 OK
access-control-allow-origin: https://dashboard.corp.com
access-control-allow-methods: GET, POST, OPTIONS
access-control-allow-headers: Authorization, Content-Type
access-control-max-age: 600
```

## Security Considerations

- **Prefer explicit origins over wildcards.** Use `["*"]` only for local development.
- **Be cautious with `allow_credentials: true`.** This tells the browser it's safe to send cookies and authorization headers cross-origin. Only enable it when your client needs it and you trust all listed origins.
- **CORS does not replace authentication.** CORS controls which _browsers_ may make requests. Server-to-server traffic is unaffected. The gateway still enforces JWT validation and policy evaluation on all requests.
- **Wildcard + credentials is blocked.** The gateway rejects this combination at startup to prevent a common misconfiguration that browsers would silently ignore.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Browser shows "CORS policy" error | Origin not in `allow_origins` | Add the requesting origin to the list |
| Gateway fails to start with "non-empty list" error | `cors` section present but `allow_origins` is empty | Add at least one origin or remove the `cors` section entirely |
| Gateway fails to start with wildcard/credentials error | `allow_origins: ["*"]` with `allow_credentials: true` | Use explicit origins when credentials are needed |
| Preflight succeeds but request fails with 401 | Auth token missing or invalid on the actual request | Ensure the client sends the `Authorization` header on the main request, not just the preflight |
| `Authorization` header blocked by CORS | `Authorization` not in `allow_headers` | Add `"Authorization"` to `allow_headers` (included by default) |
