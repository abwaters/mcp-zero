# Implementation Plan: GitHub Repo Filter Plugin

## Overview

A new mcp-zero plugin (`github-repo-filter`) that intercepts tool calls routed through a GitHub MCP server and enforces repository-level allowlist or blocklist filtering. The two modes are mutually exclusive — configuration validation rejects any policy that specifies both.

## Design

### Hook Point & Priority

The plugin registers a `LifecycleHook` at **POST_VALIDATION** with **priority 55** — right after the GovernanceHook (priority 50). This means:
1. Identity has already been resolved (IdentityHook at priority 10)
2. Governance allow/deny has already run (GovernanceHook at priority 50)
3. The repo filter acts as an additional fine-grained layer on top of governance

### How It Identifies Repos

GitHub MCP tools pass repository information as tool arguments. The hook inspects `ctx.request_payload["arguments"]` for:
- `owner` + `repo` fields → combined into `owner/repo`
- If neither is present, the tool call is **allowed through** (it's not repo-scoped, e.g. `get_me`)

### Matching Logic

- **Allowlist mode**: The resolved `owner/repo` must match at least one entry in the configured list. Non-matching repos are denied.
- **Blocklist mode**: If the resolved `owner/repo` matches any entry in the configured list, it is denied. Non-matching repos are allowed.
- Repo entries support **fnmatch-style patterns** (e.g., `myorg/*` matches all repos in `myorg`). This uses Python's `fnmatch.fnmatch` with case-insensitive comparison.

### Scoping to Specific Servers

The plugin accepts an optional `servers` config list. When provided, filtering only applies to tool calls targeting those server names. When omitted, filtering applies to all servers. This lets operators scope the filter to just their GitHub MCP server(s).

### Policy Configuration Example

```yaml
plugins:
  - name: github-repo-filter
    config:
      mode: allowlist          # Required: "allowlist" or "blocklist"
      repos:                   # Required: non-empty list
        - "myorg/approved-repo"
        - "myorg/infra-*"      # fnmatch pattern
      servers:                 # Optional: restrict to these server names
        - "github"
```

## Files to Create/Modify

### 1. `src/mcp_zero/plugins/github_repo_filter.py` (NEW)

The plugin module containing two classes:

**`GitHubRepoFilterHook(LifecycleHook)`**:
- Overrides `on_post_validation(ctx)` only
- Extracts `owner` and `repo` from `ctx.request_payload.get("arguments", {})`
- If no `owner`/`repo` found → return ctx unchanged (pass through)
- If `servers` is configured and `ctx.server_name` is not in the set → return ctx unchanged
- Builds `owner/repo` string, lowercased for comparison
- In **allowlist** mode: if no pattern matches → `raise ShortCircuitError("Repository '{owner}/{repo}' not in allowlist", deny=True)`
- In **blocklist** mode: if any pattern matches → `raise ShortCircuitError("Repository '{owner}/{repo}' is blocklisted", deny=True)`
- Otherwise → return ctx unchanged

**`GitHubRepoFilterPlugin(BasePlugin)`**:
- `name` property → `"github-repo-filter"`
- `configure(config)`:
  - Validates `mode` is present and is either `"allowlist"` or `"blocklist"`
  - Validates `repos` is a non-empty list of strings
  - Validates each repo contains a `/` (basic format check for `owner/repo` or pattern like `org/*`)
  - Stores optional `servers` list
  - Stores optional `priority` override (default 55)
- `register(registry)`:
  - Creates `GitHubRepoFilterHook` with the parsed config
  - Calls `registry.register(hook, priority=self._priority)`

### 2. `tests/plugins/test_github_repo_filter.py` (NEW)

Comprehensive tests organized into classes:

**`TestGitHubRepoFilterPlugin`** — plugin lifecycle:
- `test_satisfies_plugin_protocol` — `isinstance(plugin, Plugin)` check
- `test_name` — returns `"github-repo-filter"`
- `test_configure_allowlist` — stores mode and repos
- `test_configure_blocklist` — stores mode and repos
- `test_configure_missing_mode_raises` — ValueError
- `test_configure_invalid_mode_raises` — ValueError for mode not in {allowlist, blocklist}
- `test_configure_empty_repos_raises` — ValueError
- `test_configure_missing_repos_raises` — ValueError
- `test_configure_invalid_repo_format_raises` — ValueError for entries without `/`
- `test_configure_custom_priority` — overrides default 55
- `test_configure_servers_list` — stores server filter list
- `test_register_adds_hook_to_registry` — verifies hook appears in registry after build()

**`TestGitHubRepoFilterHook`** — hook behavior (all async):
- `test_allowlist_allows_matching_repo` — `owner=myorg, repo=good-repo` with `myorg/good-repo` in allowlist → passes through
- `test_allowlist_denies_non_matching_repo` — `owner=myorg, repo=secret-repo` not in allowlist → ShortCircuitError with deny=True
- `test_blocklist_denies_matching_repo` — `owner=myorg, repo=bad-repo` with `myorg/bad-repo` in blocklist → ShortCircuitError with deny=True
- `test_blocklist_allows_non_matching_repo` — `owner=myorg, repo=good-repo` not in blocklist → passes through
- `test_no_repo_args_passes_through` — arguments with no `owner`/`repo` keys → passes through unchanged
- `test_pattern_matching_wildcard` — `myorg/*` matches `myorg/any-repo`
- `test_case_insensitive_matching` — `MyOrg/Repo` matches `myorg/repo`
- `test_server_scoping_applies_filter` — with `servers=["github"]`, tool call to server `"github"` is filtered
- `test_server_scoping_skips_other_servers` — with `servers=["github"]`, tool call to server `"other"` passes through unfiltered
- `test_no_server_scoping_filters_all` — without `servers`, all server names are filtered

### 3. `pyproject.toml` (MODIFY)

Add entry point under `[project.entry-points."mcp_zero.plugins"]`:
```
github-repo-filter = "mcp_zero.plugins.github_repo_filter:GitHubRepoFilterPlugin"
```

### 4. Re-install package (after pyproject.toml change)

Run `pip install -e ".[dev]"` so the new entry point is discoverable by `importlib.metadata`.

## Execution Order

1. Create `src/mcp_zero/plugins/github_repo_filter.py`
2. Create `tests/plugins/test_github_repo_filter.py`
3. Update `pyproject.toml` with the new entry point
4. Re-install in editable mode
5. Run `ruff format src tests` and `ruff check src tests`
6. Run tests: `python -m pytest tests/plugins/test_github_repo_filter.py -v`
7. Run full test suite to ensure no regressions
8. Commit and push
