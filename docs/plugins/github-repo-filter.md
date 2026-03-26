# GitHub Repo Filter Plugin

Enforces allowlist or blocklist policies on GitHub repository references flowing through the MCP gateway. Controls which repositories AI agents can read from, write to, or discover via search -- on both the input (request) and output (response) side.

## Entry Point

```
github-repo-filter = "mcp_zero.plugins.github_repo_filter:GitHubRepoFilterPlugin"
```

## Configuration

```yaml
plugins:
  - name: github-repo-filter
    config:
      mode: allowlist          # Required: "allowlist" or "blocklist"
      repos:                   # Required: list of owner/repo patterns
        - myorg/repo-a
        - myorg/repo-b
        - partnerorg/*         # Wildcard: all repos under partnerorg
      servers:                 # Optional: limit to specific MCP servers
        - github-server
      priority: 55             # Optional: hook priority (default: 55)
```

### Config Reference

| Key | Type | Required | Default | Description |
|---|---|---|---|---|
| `mode` | `str` | Yes | -- | `"allowlist"` (only listed repos allowed) or `"blocklist"` (listed repos denied) |
| `repos` | `list[str]` | Yes | -- | Repository patterns in `owner/repo` format. Supports wildcards. |
| `servers` | `list[str]` | No | all servers | Limit filtering to specific MCP server names. Unscoped servers pass through unfiltered. |
| `priority` | `int` | No | `55` | Hook execution priority. Runs after governance (50) by default. |

### Repository Patterns

Patterns use `fnmatch` syntax and are case-insensitive:

| Pattern | Matches |
|---|---|
| `myorg/my-repo` | Exact match only |
| `myorg/*` | All repos under `myorg` |
| `*/security-*` | Any `security-*` repo in any org |
| `myorg/data-*` | Repos starting with `data-` in `myorg` |

## Modes

### Allowlist Mode

Only repositories matching the configured patterns are permitted. Everything else is denied.

```yaml
config:
  mode: allowlist
  repos:
    - myorg/public-api
    - myorg/docs
    - myorg/sdk-*
```

Use case: Restrict an AI agent to a known set of approved repositories.

### Blocklist Mode

Repositories matching the configured patterns are denied. Everything else is permitted.

```yaml
config:
  mode: blocklist
  repos:
    - myorg/secrets-vault
    - myorg/infra-*
    - "*/private-*"
```

Use case: Prevent access to sensitive repos while allowing broad access otherwise.

## How Filtering Works

### Input Filtering (`post_validation` hook)

Every inbound tool call is inspected for repository references before reaching the upstream GitHub MCP server. The plugin extracts repos from multiple argument patterns:

| Pattern | Example Arguments | Extracted Repo |
|---|---|---|
| Separate `owner` + `repo` args | `{"owner": "myorg", "repo": "api"}` | `myorg/api` |
| Single `repository` arg | `{"repository": "myorg/api"}` | `myorg/api` |
| `repo:` qualifier in search queries | `{"query": "bug repo:myorg/api"}` | `myorg/api` |
| GitHub URLs in `url`/`html_url` args | `{"url": "https://github.com/myorg/api/..."}` | `myorg/api` |

If any extracted repo is disallowed, the request is **denied immediately** with a `ShortCircuitError`. This is fail-closed: the request never reaches the upstream server.

### Output Filtering (`post_masking` hook)

Tool responses are filtered after masking to remove references to disallowed repositories. The behavior depends on the tool type:

#### List/Search Tools

Results are filtered individually. Items referencing disallowed repos are removed; allowed items pass through.

Covered tools: `search_code`, `search_repositories`, `search_issues`, `search_users`, `list_issues`, `list_pull_requests`, `list_commits`, `list_branches`, `list_tags`, `list_code_scanning_alerts`, `list_secret_scanning_alerts`, `list_notifications`

#### Single-Result Tools

The entire response is blocked if it references a disallowed repo.

Covered tools: `get_file_contents`, `get_issue`, `get_pull_request`, `get_pull_request_diff`, `get_pull_request_files`, `get_pull_request_reviews`, `get_pull_request_comments`, `get_pull_request_status`, `get_issue_comments`, `get_commit`, `get_tag`, `get_code_scanning_alert`, `get_secret_scanning_alert`, `get_notification_details`, `create_issue`, `create_pull_request`, `create_branch`, `create_or_update_file`, `update_pull_request`, `add_issue_comment`, `merge_pull_request`, `push_files`, `fork_repository`, `create_repository`

#### Repo Extraction from Responses

The plugin extracts repository references from response items using multiple strategies:

1. `item.full_name` (e.g., `search_repositories` results)
2. `item.repository.full_name` (e.g., `search_issues` results)
3. `item.owner.login` + `item.name` (standard GitHub API format)
4. Parsed from `repository_url`, `html_url`, or `url` fields

#### Fail-Closed Behavior

- Unparseable JSON responses are replaced with a policy message
- If all items in a list are filtered out, a policy message is returned
- If a single-result response references a disallowed repo, a policy message is returned

## Server Scoping

By default, the plugin filters all MCP servers. Use `servers` to limit filtering to specific server names:

```yaml
plugins:
  - name: github-repo-filter
    config:
      mode: allowlist
      repos:
        - myorg/*
      servers:
        - github-server
        - github-enterprise-server
```

Requests to servers not in the `servers` list pass through without filtering.

## Examples

### Lock an agent to a single org

```yaml
plugins:
  - name: github-repo-filter
    config:
      mode: allowlist
      repos:
        - myorg/*
```

### Block sensitive repos, allow everything else

```yaml
plugins:
  - name: github-repo-filter
    config:
      mode: blocklist
      repos:
        - myorg/credentials
        - myorg/infra-secrets
        - myorg/salary-data
```

### Combined with PII masking

```yaml
plugins:
  - name: github-repo-filter
    config:
      mode: allowlist
      repos:
        - myorg/*
      servers:
        - github-server

  - name: presidio-masking
    config:
      entities:
        - PERSON
        - EMAIL_ADDRESS
        - API_KEY
```

Pipeline execution order (by priority):
1. **Governance** (50) -- Policy engine checks tool access
2. **GitHub repo filter** (55) -- Validates repo references in request
3. **Presidio masking** (75) -- Masks PII in request/response
4. Output filtering by GitHub repo filter removes disallowed repos from responses

### Full policy file

```yaml
version: 1
default: deny

servers:
  - name: github-server
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"

policies:
  - id: allow-github-tools
    description: Allow all GitHub tools for engineering team
    effect: allow
    mcp_servers:
      - name: github-server
        tools: ["*"]
    groups:
      - engineering

plugins:
  - name: github-repo-filter
    config:
      mode: allowlist
      repos:
        - myorg/frontend
        - myorg/backend
        - myorg/shared-libs
        - myorg/docs
      servers:
        - github-server

  - name: presidio-masking
    config:
      entities:
        - PERSON
        - EMAIL_ADDRESS
        - CREDIT_CARD

logging:
  level: INFO
```
