# GitHub MCP OAuth Flow — Analysis & Implementation Plan

## Problem Statement

mcp-zero needs to connect to GitHub's remote MCP server (`https://api.githubcopilot.com/mcp/`) using **each user's own GitHub privileges**, not a shared static token.

## Current State Analysis

### What mcp-zero has today

| Mechanism | How it works | GitHub-compatible? |
|-----------|-------------|-------------------|
| **Static token** (`${GITHUB_TOKEN}` in headers) | Single PAT expanded at startup, shared by all users | Partially — works but all users share one identity |
| **OBO token exchange** (RFC 8693) | Exchanges user's inbound Okta JWT for a downstream token via Okta's token endpoint | **No** — GitHub doesn't accept Okta-issued tokens |

### What GitHub's remote MCP server expects

GitHub's remote MCP server (GA since Sept 2025) supports two auth methods:

1. **OAuth 2.1 + PKCE** (recommended) — user authorizes scopes in a browser, gets short-lived tokens with automatic refresh
2. **Personal Access Tokens** (fallback) — classic `ghp_*` tokens in the `Authorization` header

### The Gap

The OBO flow **cannot work** for GitHub because:

- OBO exchanges tokens **within the same identity provider** (e.g., Okta→Okta). The downstream service must accept tokens issued by that IdP.
- GitHub MCP requires **GitHub-issued tokens** (either OAuth access tokens or PATs). It does not accept tokens minted by external IdPs like Okta.
- There is no federation path from Okta to GitHub's token system — they are separate OAuth ecosystems.

The static `${GITHUB_TOKEN}` approach works technically but violates the requirement: all users share one GitHub identity, there's no per-user privilege isolation, and audit trails on GitHub's side all show the same actor.

## MCP Protocol OAuth Specification

The MCP spec (2025-03-26) defines an authorization framework for remote servers:

1. **Discovery**: Client fetches `/.well-known/oauth-authorization-server` from the MCP server
2. **Dynamic Client Registration** (RFC 7591): Client registers itself to get a `client_id` (GitHub may not support this — requires a pre-registered GitHub OAuth App)
3. **Authorization Code + PKCE** (RFC 7636): User authorizes the client in a browser
4. **Resource Indicators** (RFC 8707): Client specifies the target resource in token requests
5. **Token refresh**: Client uses refresh tokens to get new access tokens

### Critical constraint

GitHub does **not** support Dynamic Client Registration (RFC 7591). The gateway must be registered as a GitHub OAuth App manually (one-time setup by an admin).

## Proposed Architecture

### Option A: Gateway-Brokered OAuth (Recommended)

The gateway acts as an OAuth client to GitHub on behalf of each enterprise user.

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐     ┌──────────────┐
│  AI Tool /  │────▶│   mcp-zero       │────▶│  GitHub MCP  │────▶│  GitHub API  │
│  MCP Client │     │   Gateway        │     │  Server      │     │              │
│             │◀────│                  │◀────│              │◀────│              │
└─────────────┘     └──────┬───────────┘     └──────────────┘     └──────────────┘
                           │
                    ┌──────▼───────────┐
                    │  GitHub OAuth     │
                    │  Token Store      │
                    │  (per-user)       │
                    └──────────────────┘
                           │
                    ┌──────▼───────────┐
                    │  GitHub OAuth     │
                    │  Authorization    │
                    │  (browser flow)   │
                    └──────────────────┘
```

**Flow:**

1. User authenticates to mcp-zero with their Okta JWT (existing flow)
2. Gateway identifies user (e.g., `alice@corp.com`) from the JWT
3. Gateway checks if it has a cached GitHub OAuth token for this user
4. **If no token**: Gateway initiates GitHub OAuth authorization code + PKCE flow
   - Returns a redirect URL to the user/client
   - User authorizes the gateway in their browser on github.com
   - GitHub redirects back to the gateway's callback endpoint
   - Gateway exchanges the authorization code for access + refresh tokens
   - Gateway stores tokens keyed by user identity
5. **If token exists but expired**: Gateway uses the refresh token to get a new access token
6. Gateway calls GitHub MCP with the user's GitHub OAuth token in `Authorization: Bearer <token>`
7. GitHub MCP executes with the user's privileges and scopes

### Option B: Per-User PAT Configuration

Each user provides their own GitHub PAT, stored in a secure token vault and looked up by user identity at request time.

- Simpler to implement
- But: PATs are long-lived, not scoped automatically, require manual rotation, and GitHub is deprecating fine-grained PATs in favor of OAuth

### Recommendation: Option A

Option A aligns with the MCP spec, uses short-lived tokens, supports automatic refresh, and respects GitHub's recommended auth method.

## Implementation Plan (Option A)

### Phase 1: GitHub OAuth Provider

**New files:**
- `src/mcp_zero/oauth/` — new package for external OAuth flows
  - `provider.py` — Abstract base class for external OAuth providers
  - `github.py` — GitHub-specific OAuth 2.1 + PKCE implementation
  - `token_store.py` — Per-user token storage (in-memory + pluggable backend)
  - `config.py` — OAuth provider configuration

**Configuration (policy YAML):**
```yaml
servers:
  - name: github
    transport: http
    url: https://api.githubcopilot.com/mcp/
    oauth:
      provider: github
      client_id: "Iv1.abc123..."          # GitHub OAuth App client ID
      client_secret: "${GITHUB_OAUTH_SECRET}"
      scopes:
        - repo
        - read:org
      # Optional: restrict to specific GitHub orgs
      allowed_orgs: ["my-enterprise"]
```

### Phase 2: Authorization Endpoints

**New gateway HTTP endpoints:**
- `GET /oauth/github/authorize` — Initiates OAuth flow, returns redirect to GitHub
- `GET /oauth/github/callback` — Receives authorization code from GitHub, exchanges for tokens
- `GET /oauth/github/status` — Check if current user has a valid GitHub token

**PKCE flow:**
- Generate `code_verifier` + `code_challenge` per authorization request
- Store in session state keyed by `state` parameter
- Verify on callback

### Phase 3: Token Lifecycle Management

- Cache tokens per `(user_id, provider)` tuple
- Automatic refresh using refresh tokens before expiry
- Token revocation on user logout/disconnect
- Pluggable storage backend (in-memory default, Redis/DB for production)

### Phase 4: Transport Integration

Modify `ServerManager` and `StreamableHTTPTransport`:
- When a server config has `oauth` instead of `token_exchange` or static `headers`, use the OAuth provider to get the user's token
- If no token exists, return a structured error with the authorization URL
- New `AuthProvider` implementation: `OAuthAuthProvider` (alongside existing `OBOAuthProvider`)

### Phase 5: Client-Side Flow Support

For MCP clients that can't redirect to a browser:
- Support a device authorization flow (RFC 8628) as alternative
- Or return a URL the user can open manually to complete authorization

## Files That Need Changes

| File | Change |
|------|--------|
| `src/mcp_zero/oauth/` (new) | Entire OAuth package |
| `src/mcp_zero/transport/config.py` | Add `oauth` field to `ServerConfig` |
| `src/mcp_zero/proxy/auth.py` | Add `OAuthAuthProvider` implementation |
| `src/mcp_zero/proxy/server_manager.py` | Route to OAuth provider when configured |
| `src/mcp_zero/proxy/proxy_server.py` | Handle "needs authorization" responses |
| `src/mcp_zero/main.py` | Wire OAuth endpoints, build OAuth providers |
| `src/mcp_zero/proxy/middleware.py` | Mount OAuth callback routes |
| `policies/remote-github-oauth.yaml` (new) | Example policy using OAuth |

## Prerequisites / Admin Setup

1. Register a **GitHub OAuth App** at `github.com/settings/developers`
   - Set callback URL to `https://<gateway-host>/oauth/github/callback`
   - Note the `client_id` and `client_secret`
2. Configure the gateway with `GITHUB_OAUTH_CLIENT_ID` and `GITHUB_OAUTH_SECRET`
3. Ensure the gateway is reachable at the callback URL (HTTPS required)

## Open Questions

1. **Token storage backend**: In-memory is fine for single-instance dev, but production needs Redis or a database. Should we support both from day one?
2. **Multi-provider**: Should the OAuth framework support arbitrary providers (Google, Azure, etc.) from the start, or GitHub-first?
3. **Device flow**: Should we support RFC 8628 device authorization for headless clients?
4. **SAML/SSO enforcement**: GitHub Enterprise can enforce SAML SSO — should the gateway handle SAML re-auth prompts?
