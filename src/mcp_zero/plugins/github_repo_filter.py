"""GitHub repository filter plugin for mcp-zero.

Enforces allowlist/blocklist policies on GitHub repository references
flowing through the MCP gateway.

Input filtering:
  - Extracts repos from owner/repo arguments, repository argument,
    search query qualifiers (repo:owner/name), and URL-based arguments.
  - Blocks requests targeting disallowed repos (fail-closed).

Output filtering:
  - Filters ALL tool responses containing repo references, not just search tools.
  - For single-result tools (get_*): blocks entire response if repo is disallowed.
  - For list/search tools (list_*, search_*): filters individual items.
  - Fail-closed: unparseable responses are replaced with a policy message.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
from typing import Any

from mcp_zero.context import HookContext
from mcp_zero.pipeline.errors import ShortCircuitError
from mcp_zero.pipeline.hooks import LifecycleHook
from mcp_zero.pipeline.registry import HookRegistry
from mcp_zero.plugin import BasePlugin

logger = logging.getLogger(__name__)

DEFAULT_PRIORITY = 55

# ---------------------------------------------------------------------------
# Tool classification
# ---------------------------------------------------------------------------

# Tools that return multiple items which can be individually filtered.
_LIST_TOOLS = frozenset(
    {
        "search_code",
        "search_repositories",
        "search_issues",
        "search_users",
        "list_issues",
        "list_pull_requests",
        "list_commits",
        "list_branches",
        "list_tags",
        "list_code_scanning_alerts",
        "list_secret_scanning_alerts",
        "list_notifications",
    }
)

# Tools that return a single result tied to a specific repo.
_SINGLE_RESULT_TOOLS = frozenset(
    {
        "get_file_contents",
        "get_issue",
        "get_pull_request",
        "get_pull_request_diff",
        "get_pull_request_files",
        "get_pull_request_reviews",
        "get_pull_request_comments",
        "get_pull_request_status",
        "get_issue_comments",
        "get_commit",
        "get_tag",
        "get_code_scanning_alert",
        "get_secret_scanning_alert",
        "get_notification_details",
        "create_issue",
        "create_pull_request",
        "create_branch",
        "create_or_update_file",
        "update_pull_request",
        "add_issue_comment",
        "merge_pull_request",
        "push_files",
        "fork_repository",
        "create_repository",
    }
)

# Union of all tools that may carry repo references in responses.
_REPO_AWARE_TOOLS = _LIST_TOOLS | _SINGLE_RESULT_TOOLS


class GitHubRepoFilterHook(LifecycleHook):
    """Lifecycle hook that filters GitHub repository references."""

    _GITHUB_URL_RE = re.compile(r"github\.com/([^/]+/[^/\s?#]+)")
    _QUERY_REPO_RE = re.compile(r"\brepo:([^\s]+)", re.IGNORECASE)

    def __init__(
        self,
        *,
        mode: str,
        repos: list[str],
        servers: list[str] | None = None,
    ) -> None:
        self._mode = mode
        self._repos = repos
        self._servers = servers

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _matches_repo(self, repo_full_name: str) -> bool:
        """Check if a repo matches any configured pattern."""
        normalized = repo_full_name.lower()
        return any(fnmatch.fnmatch(normalized, p.lower()) for p in self._repos)

    def _should_keep(self, repo_full_name: str) -> bool:
        """Return True if the item should be kept based on mode."""
        matched = self._matches_repo(repo_full_name)
        if self._mode == "allowlist":
            return matched
        else:  # blocklist
            return not matched

    def _check_repo(self, full_repo: str, display_name: str | None = None) -> None:
        """Raise ShortCircuitError if repo is disallowed by policy."""
        label = display_name or full_repo
        if self._mode == "allowlist":
            if not self._matches_repo(full_repo):
                raise ShortCircuitError(f"Repository '{label}' is not in the allowlist", deny=True)
        elif self._mode == "blocklist":
            if self._matches_repo(full_repo):
                raise ShortCircuitError(f"Repository '{label}' is blocked", deny=True)

    def _extract_repo_from_item(self, item: dict) -> str | None:
        """Extract a repo full_name from a response item."""
        # Direct full_name (e.g. search_repositories results)
        full_name = item.get("full_name")
        if isinstance(full_name, str) and "/" in full_name:
            return full_name

        # Nested repository.full_name (e.g. search_issues results)
        repo_obj = item.get("repository")
        if isinstance(repo_obj, dict):
            nested = repo_obj.get("full_name")
            if isinstance(nested, str) and "/" in nested:
                return nested

        # owner.login + name combo (common in GitHub API responses)
        owner_obj = item.get("owner")
        name = item.get("name")
        if isinstance(owner_obj, dict) and isinstance(name, str):
            login = owner_obj.get("login")
            if isinstance(login, str):
                return f"{login}/{name}"

        # Parse from URLs
        for key in ("repository_url", "html_url", "url"):
            url = item.get(key, "")
            if isinstance(url, str):
                m = self._GITHUB_URL_RE.search(url)
                if m:
                    return m.group(1)

        return None

    def _extract_repos_from_arguments(self, arguments: dict[str, Any]) -> list[str]:
        """Extract all repo references from tool call arguments.

        Returns a list of "owner/repo" strings found in the arguments.
        """
        repos: list[str] = []

        # Pattern 1: separate owner + repo arguments
        owner = arguments.get("owner")
        repo = arguments.get("repo")
        if owner and repo:
            repos.append(f"{owner}/{repo}")

        # Pattern 2: single "repository" argument ("owner/repo")
        repository = arguments.get("repository")
        if isinstance(repository, str) and "/" in repository:
            repos.append(repository)

        # Pattern 3: repo:owner/name qualifiers inside search query strings
        query = arguments.get("query") or arguments.get("q")
        if isinstance(query, str):
            for m in self._QUERY_REPO_RE.finditer(query):
                qualifier = m.group(1)
                if "/" in qualifier:
                    repos.append(qualifier)

        # Pattern 4: URL-based arguments
        for key in ("url", "html_url"):
            url_val = arguments.get(key)
            if isinstance(url_val, str):
                m = self._GITHUB_URL_RE.search(url_val)
                if m:
                    repos.append(m.group(1))

        return repos

    # ------------------------------------------------------------------
    # Lifecycle hook: input filtering
    # ------------------------------------------------------------------

    async def on_post_validation(self, ctx: HookContext) -> HookContext:
        """Filter requests based on GitHub repository allowlist/blocklist."""
        # Server scoping: skip if this server is not in scope
        if self._servers and ctx.server_name not in self._servers:
            logger.debug(
                "Skipping repo filter for server %r (not in scoped servers)", ctx.server_name
            )
            return ctx

        # Extract all repo references from request arguments
        arguments = ctx.request_payload.get("arguments", {})
        if not isinstance(arguments, dict):
            return ctx

        repos_found = self._extract_repos_from_arguments(arguments)
        if not repos_found:
            logger.debug("No repo references in request arguments; skipping repo filter")
            return ctx

        # Check each extracted repo against policy
        for full_repo in repos_found:
            normalized = full_repo.lower()
            logger.debug("Checking repo %r against %s policy", normalized, self._mode)
            self._check_repo(normalized, full_repo)

        return ctx

    # ------------------------------------------------------------------
    # Lifecycle hook: output filtering
    # ------------------------------------------------------------------

    def _make_policy_message(self, message: str) -> dict[str, Any]:
        """Build a response payload with a single policy text message."""
        return {"type": "text", "text": message}

    def _fail_closed_response(self, ctx: HookContext, reason: str) -> HookContext:
        """Return a context with content replaced by a policy message (fail-closed)."""
        logger.warning("Repo filter fail-closed: %s", reason)
        return ctx.evolve(
            response_payload={
                **ctx.response_payload,
                "content": [self._make_policy_message(f"Response filtered: {reason}")],
            }
        )

    def _filter_list_response(
        self, parsed: Any, content_item: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Filter items from a list/search response. Returns new content_item or None."""
        if isinstance(parsed, list):
            items = parsed
        elif isinstance(parsed, dict):
            items = [parsed]
        else:
            return content_item

        kept: list[dict] = []
        for entry in items:
            if not isinstance(entry, dict):
                kept.append(entry)
                continue
            repo = self._extract_repo_from_item(entry)
            if repo is None or self._should_keep(repo):
                kept.append(entry)

        if not kept:
            return None

        # Reconstruct: if original was a list, keep as list
        rebuilt = kept if isinstance(parsed, list) else kept[0]
        return {"type": "text", "text": json.dumps(rebuilt)}

    def _check_single_result_response(self, parsed: Any) -> bool:
        """Check if a single-result response should be kept. Returns True to keep."""
        if not isinstance(parsed, dict):
            return True
        repo = self._extract_repo_from_item(parsed)
        if repo is None:
            # No repo reference found — allow through (cannot filter without evidence)
            return True
        return self._should_keep(repo)

    async def on_post_masking(self, ctx: HookContext) -> HookContext:
        """Filter tool responses based on repository policy."""
        # Server scoping
        if self._servers and ctx.server_name not in self._servers:
            return ctx

        # Only apply to tools that may carry repo references
        if ctx.tool_name not in _REPO_AWARE_TOOLS:
            return ctx

        content = ctx.response_payload.get("content", [])
        if not isinstance(content, list):
            return ctx

        is_list_tool = ctx.tool_name in _LIST_TOOLS
        is_single_tool = ctx.tool_name in _SINGLE_RESULT_TOOLS

        filtered_content: list[dict[str, Any]] = []
        for content_item in content:
            if not isinstance(content_item, dict) or content_item.get("type") != "text":
                filtered_content.append(content_item)
                continue

            text_value = content_item.get("text", "")
            try:
                parsed = json.loads(text_value)
            except (json.JSONDecodeError, TypeError):
                # Fail-closed: cannot parse, replace entirely
                return self._fail_closed_response(
                    ctx, "unable to parse response for repository filtering."
                )

            if is_list_tool:
                result = self._filter_list_response(parsed, content_item)
                if result is not None:
                    filtered_content.append(result)
            elif is_single_tool:
                if self._check_single_result_response(parsed):
                    filtered_content.append(content_item)
                else:
                    # Single result is disallowed — block entire response
                    return ctx.evolve(
                        response_payload={
                            **ctx.response_payload,
                            "content": [
                                self._make_policy_message("Response blocked by repository policy.")
                            ],
                        }
                    )
            else:
                filtered_content.append(content_item)

        # If everything was filtered out, return policy message
        if not filtered_content:
            filtered_content = [
                self._make_policy_message("All results were filtered by repository policy.")
            ]

        return ctx.evolve(response_payload={**ctx.response_payload, "content": filtered_content})


class GitHubRepoFilterPlugin(BasePlugin):
    """Plugin that enforces allowlist/blocklist policies on GitHub repos.

    Configuration (via ``plugins[].config`` in the policy file)::

        plugins:
          - name: github-repo-filter
            config:
              mode: allowlist          # or "blocklist"
              repos:
                - myorg/repo-a
                - myorg/repo-b
              servers:                 # optional: limit to specific servers
                - github-server
              priority: 55             # optional priority override
    """

    def __init__(self) -> None:
        self._mode: str = ""
        self._repos: list[str] = []
        self._servers: list[str] | None = None
        self._priority: int = DEFAULT_PRIORITY

    @property
    def name(self) -> str:
        return "github-repo-filter"

    def configure(self, config: dict[str, Any]) -> None:
        # Validate mode
        mode = config.get("mode", "")
        if mode not in ("allowlist", "blocklist"):
            raise ValueError(
                "github-repo-filter plugin requires 'mode' to be 'allowlist' or 'blocklist', "
                f"got {mode!r}"
            )
        self._mode = mode

        # Validate repos
        repos = config.get("repos", [])
        if not isinstance(repos, list) or not repos:
            raise ValueError(
                "github-repo-filter plugin requires a non-empty 'repos' list in config"
            )
        for repo in repos:
            if not isinstance(repo, str) or "/" not in repo:
                raise ValueError(
                    f"github-repo-filter plugin: each repo must be a string containing '/', "
                    f"got {repo!r}"
                )
        self._repos = repos

        # Optional: servers list
        servers = config.get("servers")
        if servers is not None:
            if not isinstance(servers, list):
                raise ValueError("github-repo-filter plugin: 'servers' must be a list of strings")
            self._servers = servers

        # Optional: priority override
        if "priority" in config:
            self._priority = int(config["priority"])

    def register(self, registry: HookRegistry) -> None:
        hook = GitHubRepoFilterHook(
            mode=self._mode,
            repos=self._repos,
            servers=self._servers,
        )
        registry.register(hook, priority=self._priority)
        logger.info(
            "GitHub repo filter plugin registered (mode=%s, repos=%d, priority=%d)",
            self._mode,
            len(self._repos),
            self._priority,
        )
