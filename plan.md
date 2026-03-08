# Implementation Plan: GitHub Repo Filter Plugin

## Overview

A new mcp-zero plugin (`github-repo-filter`) that enforces repository-level allowlist or blocklist filtering for GitHub MCP servers. It operates in two phases:

1. **Input filtering** — blocks tool calls that target a disallowed repo (tools with `owner`/`repo` arguments)
2. **Output filtering** — strips results from disallowed repos out of search responses (search tools that return multi-repo results)

The two modes (`allowlist` / `blocklist`) are mutually exclusive — configuration validation rejects any policy that specifies both.

## GitHub MCP Tool Inventory

The GitHub MCP server exposes ~51 tools. They fall into three categories for filtering purposes:

### Category 1: Tools with `owner`/`repo` input args (blocked at input)

These tools target a single repo. The plugin denies the entire call if the repo is disallowed.

- **Repos**: `create_repository`, `fork_repository`, `create_branch`, `list_branches`, `create_or_update_file`, `delete_file`, `get_file_contents`, `push_files`
- **Issues**: `create_issue`, `get_issue`, `list_issues`, `update_issue`, `add_issue_comment`, `get_issue_comments`
- **PRs**: `create_pull_request`, `get_pull_request`, `list_pull_requests`, `update_pull_request`, `get_pull_request_diff`, `get_pull_request_files`, `get_pull_request_comments`, `get_pull_request_reviews`, `get_pull_request_status`, `update_pull_request_branch`, `merge_pull_request`, `create_pending_pull_request_review`, `add_pull_request_review_comment_to_pending_review`, `delete_pending_pull_request_review`, `create_and_submit_pull_request_review`, `submit_pending_pull_request_review`, `request_copilot_review`
- **Commits/Tags**: `get_commit`, `list_commits`, `get_tag`, `list_tags`
- **Security**: `list_code_scanning_alerts`, `get_code_scanning_alert`, `list_secret_scanning_alerts`, `get_secret_scanning_alert`
- **Other**: `manage_repository_notification_subscription`, `assign_copilot_to_issue`, `search_issues` (when scoped to a repo via `repo:` qualifier)

### Category 2: Search tools returning multi-repo results (filtered at output)

These tools return results spanning many repos. The plugin filters the *response* to strip out entries from disallowed repos.

- **`search_code`** — results contain `repository.full_name` (e.g., `"owner/repo"`)
- **`search_repositories`** — results contain `full_name`
- **`search_issues`** — results contain `repository.full_name` or `repository_url`

### Category 3: Non-repo tools (pass through)

These tools have no repo context and are always allowed through:

- `get_me`, `list_notifications`, `get_notification_details`, `dismiss_notification`, `manage_notification_subscription`, `mark_all_notifications_read`, `search_users`

## Design

### Hook Points & Priority

The plugin registers a single `LifecycleHook` that acts at two hook points:

1. **`on_post_validation`** (priority 55) — **Input filtering**. Runs after GovernanceHook (priority 50). Inspects `request_payload["arguments"]` for `owner`/`repo` and blocks the call if disallowed.

2. **`on_post_masking`** (priority 55) — **Output filtering**. Runs after masking. Inspects `response_payload["content"]` for search results containing repo references. Strips out entries from disallowed repos. Uses fail-closed: if response parsing fails, the response is blocked entirely.

### How It Identifies Repos

**Input (tool arguments):**
- `owner` + `repo` fields → combined into `owner/repo`
- If neither is present → pass through (not a repo-scoped tool)

**Output (search responses):**
- The response payload contains `content` items (typically text). The hook parses text content looking for repository references.
- GitHub MCP search tools return structured text (often JSON or markdown) with `full_name` fields like `"owner/repo"` or `repository_url` patterns like `https://github.com/owner/repo`.
- The hook identifies the tool name from `ctx.tool_name` and only applies output filtering to known search tools: `search_code`, `search_repositories`, `search_issues`.
- For each search result item, the hook extracts the repo reference and checks it against the allowlist/blocklist. Non-matching items are removed from the response.
- If ALL items are filtered out, the response is replaced with an empty results message.

### Matching Logic

- **Allowlist mode**: The resolved `owner/repo` must match at least one entry in the configured list. Non-matching repos are denied/filtered.
- **Blocklist mode**: If the resolved `owner/repo` matches any entry in the configured list, it is denied/filtered. Non-matching repos are allowed.
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

*Input filtering — `on_post_validation(ctx)`*:
- If `servers` is configured and `ctx.server_name` is not in the set → return ctx unchanged
- Extracts `owner` and `repo` from `ctx.request_payload.get("arguments", {})`
- If no `owner`/`repo` found → return ctx unchanged (pass through)
- Builds `owner/repo` string, lowercased for comparison
- In **allowlist** mode: if no pattern matches → `raise ShortCircuitError("Repository '{owner}/{repo}' not in allowlist", deny=True)`
- In **blocklist** mode: if any pattern matches → `raise ShortCircuitError("Repository '{owner}/{repo}' is blocklisted", deny=True)`
- Otherwise → return ctx unchanged

*Output filtering — `on_post_masking(ctx)`*:
- If `servers` is configured and `ctx.server_name` is not in the set → return ctx unchanged
- If `ctx.tool_name` is not in `SEARCH_TOOLS` (`search_code`, `search_repositories`, `search_issues`) → return ctx unchanged
- If `ctx.response_payload` is empty → return ctx unchanged
- Walk through `response_payload["content"]` items
- For each text content item, attempt to parse as JSON
- Extract repo references (`full_name`, `repository.full_name`, or parse from `repository_url`/`html_url`)
- Filter out items/entries where the repo doesn't match the allowlist/blocklist
- Return `ctx.evolve(response_payload=filtered_payload)`
- On parse error → fail-closed: replace response with an error message (never leak unfiltered data)

*Helper — `_repo_matches(repo: str) -> bool`*:
- Lowercases the repo string
- Iterates configured patterns, applying `fnmatch.fnmatch`
- Returns True if any pattern matches

*Helper — `_is_repo_allowed(repo: str) -> bool`*:
- Allowlist mode: returns `_repo_matches(repo)`
- Blocklist mode: returns `not _repo_matches(repo)`

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

**`TestGitHubRepoFilterHookInput`** — input filtering (all async):
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

**`TestGitHubRepoFilterHookOutput`** — output filtering (all async):
- `test_search_code_filters_disallowed_repos` — blocklist mode, response contains results from 3 repos, one is blocklisted → that result is stripped from response
- `test_search_repositories_filters_disallowed_repos` — allowlist mode, response contains 3 repos, only one is in allowlist → only that one remains
- `test_search_issues_filters_disallowed_repos` — similar to above but for issue search results
- `test_all_results_filtered_returns_empty_message` — when every result is filtered out, response is replaced with "No results match the repository filter"
- `test_non_search_tool_passes_through` — tool_name `get_file_contents` → response is not modified
- `test_output_filter_respects_server_scoping` — output filtering only applies when server matches
- `test_output_parse_error_fails_closed` — malformed response content → response is blocked (replaced with error text), never leaks unfiltered data
- `test_allowlist_output_keeps_only_matching` — allowlist mode keeps only matching repos in search results
- `test_blocklist_output_removes_matching` — blocklist mode removes only matching repos from search results

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
