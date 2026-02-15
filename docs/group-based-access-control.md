# Group-Based Access Control

This document explains how mcp-zero uses group memberships from your identity provider to enforce policy rules. Groups are the primary mechanism for role-based access control (RBAC) in the gateway.

## Key Concept

**Groups are not defined in the gateway.** They originate from your identity provider (e.g., Okta) and arrive in the JWT token as a claim. The gateway reads the groups from each validated token and matches them against the `subjects.groups` lists in your policy rules.

## How It Works

```
┌──────────────────────────────┐
│  1. Okta (or other IdP)      │
│                              │
│  Groups defined here:        │
│  - platform-ops              │
│  - sre                       │
│  - developers                │
│                              │
│  Users assigned to groups    │
│  JWT minted with groups      │
│  claim: ["sre","developers"] │
└──────────────┬───────────────┘
               │ Bearer token
               ▼
┌──────────────────────────────┐
│  2. Identity Hook            │
│                              │
│  Validates JWT signature,    │
│  issuer, audience            │
│                              │
│  Extracts groups from the    │
│  configured claim (default:  │
│  "groups")                   │
│                              │
│  Creates UserIdentity:       │
│    user_id: "alice@corp.com" │
│    groups: ["sre",           │
│             "developers"]    │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  3. Governance Hook          │
│                              │
│  Evaluates policy rules      │
│  top-down, checking if the   │
│  user's groups intersect     │
│  with each rule's            │
│  subjects.groups             │
│                              │
│  Decision: ALLOW or DENY     │
└──────────────────────────────┘
```

## Configuring Groups in the Policy File

### Referencing groups in policy rules

Groups appear in the `subjects.groups` list of each policy rule. These must match the group names your IdP puts into the JWT:

```yaml
policies:
  - id: allow-platform-ops-internal-tools
    description: Allow Platform Ops to use approved internal MCP tools
    effect: allow
    subjects:
      groups:
        - platform-ops
        - sre
    mcp_servers:
      - name: internal-infra-mcp
        tools:
          - read_logs
          - query_metrics
          - restart_service

  - id: allow-dev-readonly-external
    description: Allow developers to use read-only external MCP tools
    effect: allow
    subjects:
      groups:
        - developers
    mcp_servers:
      - name: github-mcp
        tools:
          - list_repos
          - read_issues
          - read_pull_requests
```

A request matches a rule if **any** of the user's groups overlap with the rule's groups. In the first rule above, a user in either `platform-ops` or `sre` (or both) would match.

### Wildcards and special cases

**Match all users** — use `"*"` as a group name:

```yaml
subjects:
  groups:
    - '*'
```

**Match everyone (no restrictions)** — omit `subjects` entirely or leave both `users` and `groups` empty. The rule applies to all requests regardless of identity:

```yaml
- id: deny-destructive-everywhere
  description: Block destructive tools for everyone
  effect: deny
  # No subjects — applies to all users
  mcp_servers:
    - name: '*'
      tools:
        - delete_*
        - write_*
```

### Combining users and groups

You can mix individual user IDs and groups in the same rule. A request matches if the user matches **either** a listed user ID or a listed group:

```yaml
subjects:
  users:
    - admin@corp.com
  groups:
    - sre
```

## Customizing the Groups Claim

By default, the gateway reads groups from the `groups` claim in the JWT. If your IdP uses a different claim name (e.g., `roles`, `memberOf`, `custom:groups`), configure `claim_mapping` in the `identity` section:

```yaml
identity:
  provider: okta
  issuer: https://your-org.okta.com/oauth2/default
  audience: mcp-gateway
  claim_mapping:
    user_id: sub          # JWT claim for user ID (default: sub)
    email: email          # JWT claim for email (default: email)
    groups: roles         # JWT claim for groups (default: groups)
```

The gateway extracts the value of the mapped claim and expects it to be a **JSON array of strings**. If the claim is missing or not an array, the user is treated as having no group memberships.

## Setting Up Groups in Okta

### 1. Create groups

In the Okta Admin Console, go to **Directory > Groups** and create groups that match the names you use in your policy file (e.g., `platform-ops`, `sre`, `developers`).

### 2. Assign users to groups

Add users to the appropriate groups. A user can belong to multiple groups, and all memberships are evaluated during policy matching.

### 3. Add a groups claim to the authorization server

Go to **Security > API > Authorization Servers**, select your authorization server, and add a claim:

| Field | Value |
|---|---|
| **Name** | `groups` |
| **Include in token type** | Access Token |
| **Value type** | Groups |
| **Filter** | Matches regex: `.*` (or a more specific filter) |
| **Include in** | Any scope (or a specific scope) |

This ensures every access token minted by this authorization server includes the user's group memberships in the `groups` claim.

### 4. Verify the token

Decode a test token (e.g., via [jwt.io](https://jwt.io)) and confirm the groups claim is present:

```json
{
  "sub": "alice@corp.com",
  "email": "alice@corp.com",
  "groups": ["developers", "sre"],
  "iss": "https://your-org.okta.com/oauth2/default",
  "aud": "mcp-gateway",
  "exp": 1700000000
}
```

## Policy Evaluation Rules

Understanding how the engine evaluates groups is important for writing correct policies:

1. **Top-down evaluation** — rules are checked in file order
2. **Deny overrides allow** — if any matching rule has `effect: deny`, the request is denied regardless of other allow rules
3. **Set intersection** — a rule matches if `set(user_groups) & set(rule_groups)` is non-empty (at least one group in common)
4. **Default applies when no rule matches** — if no rule matches, the policy's `default` effect applies (`deny` is recommended for production)
5. **Anonymous users** — requests without a valid JWT have no groups and can only match rules with empty subjects or wildcard groups

### Example evaluation

Given a user with `groups: ["developers", "sre"]`:

| Rule subjects.groups | Match? | Reason |
|---|---|---|
| `["platform-ops", "sre"]` | Yes | `sre` is in both |
| `["developers"]` | Yes | `developers` is in both |
| `["platform-ops", "admins"]` | No | No overlap |
| `["*"]` | Yes | Wildcard matches everyone |
| `[]` (empty) | Yes | Empty subjects match everyone |

## Troubleshooting

### User is denied but should be allowed

1. **Check the JWT** — decode the token and verify the `groups` claim contains the expected group names (exact string match, case-sensitive)
2. **Check claim_mapping** — if your IdP uses a non-default claim name, ensure `claim_mapping.groups` matches
3. **Check policy order** — a deny rule earlier in the file may be matching before your allow rule
4. **Check group name spelling** — group names in the policy must exactly match the strings in the JWT

### User is allowed but should be denied

1. **Check for wildcard subjects** — a rule with empty subjects or `groups: ["*"]` matches everyone
2. **Check the default** — if `default: allow`, unmatched requests are permitted. Use `default: deny` in production
3. **Check for overlapping groups** — the user may belong to a group you didn't expect

### Groups claim is empty or missing

- Verify the Okta authorization server has a groups claim configured
- Check the token's scope — the groups claim may be conditional on a specific scope
- Confirm the user is assigned to groups in Okta (not just the application)

## Related Documentation

- [Policy schema reference](enterprise_mcp_gateway_policy_schema_example.md) — full annotated policy file
- [Okta OBO token exchange](okta_obo_for_an_enterprise_mcp_gateway.md) — forwarding user identity to downstream servers
- [Quickstart guide](quickstart.md) — getting started with mcp-zero
