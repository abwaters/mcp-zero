"""GitHub repository filter plugin for mcp-zero.

Enforces allowlist/blocklist policies on GitHub repository references
flowing through the MCP gateway.
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


class GitHubRepoFilterHook(LifecycleHook):
    """Lifecycle hook that filters GitHub repository references."""

    _SEARCH_TOOLS = frozenset({"search_code", "search_repositories", "search_issues"})
    _GITHUB_URL_RE = re.compile(r"github\.com/([^/]+/[^/\s?#]+)")

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

    def _extract_repo_from_item(self, item: dict) -> str | None:
        """Extract a repo full_name from a search result item."""
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

        # Parse from URLs
        for key in ("repository_url", "html_url"):
            url = item.get(key, "")
            if isinstance(url, str):
                m = self._GITHUB_URL_RE.search(url)
                if m:
                    return m.group(1)

        return None

    def _should_keep(self, repo_full_name: str) -> bool:
        """Return True if the item should be kept based on mode."""
        matched = self._matches_repo(repo_full_name)
        if self._mode == "allowlist":
            return matched
        else:  # blocklist
            return not matched

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

        # Extract owner/repo from request arguments
        arguments = ctx.request_payload.get("arguments", {})
        owner = arguments.get("owner")
        repo = arguments.get("repo")

        if not owner or not repo:
            logger.debug("No owner/repo in request arguments; skipping repo filter")
            return ctx

        # Combine and normalize for case-insensitive comparison
        full_repo = f"{owner}/{repo}".lower()

        if self._mode == "allowlist":
            if not self._matches_repo(full_repo):
                logger.debug("Repository %r not in allowlist; denying", full_repo)
                raise ShortCircuitError(
                    f"Repository '{owner}/{repo}' is not in the allowlist", deny=True
                )
            logger.debug("Repository %r matched allowlist", full_repo)

        elif self._mode == "blocklist":
            if self._matches_repo(full_repo):
                logger.debug("Repository %r matched blocklist; denying", full_repo)
                raise ShortCircuitError(f"Repository '{owner}/{repo}' is blocked", deny=True)
            logger.debug("Repository %r not in blocklist; allowing", full_repo)

        return ctx

    # ------------------------------------------------------------------
    # Lifecycle hook: output filtering
    # ------------------------------------------------------------------

    async def on_post_masking(self, ctx: HookContext) -> HookContext:
        """Filter search tool responses based on repository policy."""
        # Server scoping
        if self._servers and ctx.server_name not in self._servers:
            return ctx

        # Only apply to search tools
        if ctx.tool_name not in self._SEARCH_TOOLS:
            return ctx

        content = ctx.response_payload.get("content", [])
        if not isinstance(content, list):
            return ctx

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
                logger.warning(
                    "Failed to parse response JSON for repo filtering; replacing content"
                )
                return ctx.evolve(
                    response_payload={
                        **ctx.response_payload,
                        "content": [
                            {
                                "type": "text",
                                "text": "Response filtered: unable to parse response "
                                "for repository filtering.",
                            }
                        ],
                    }
                )

            # Handle both a list of items and a single dict item
            if isinstance(parsed, list):
                items = parsed
            elif isinstance(parsed, dict):
                items = [parsed]
            else:
                filtered_content.append(content_item)
                continue

            kept: list[dict] = []
            for entry in items:
                if not isinstance(entry, dict):
                    kept.append(entry)
                    continue
                repo = self._extract_repo_from_item(entry)
                if repo is None or self._should_keep(repo):
                    kept.append(entry)

            if kept:
                # Reconstruct: if original was a list, keep as list
                rebuilt = kept if isinstance(parsed, list) else kept[0]
                filtered_content.append({"type": "text", "text": json.dumps(rebuilt)})

        # If everything was filtered out, return policy message
        if not filtered_content:
            filtered_content = [
                {"type": "text", "text": "All results were filtered by repository policy."}
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
