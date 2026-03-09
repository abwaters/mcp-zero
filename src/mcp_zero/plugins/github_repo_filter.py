"""GitHub repository filter plugin for mcp-zero.

Enforces allowlist/blocklist policies on GitHub repository references
flowing through the MCP gateway.
"""

from __future__ import annotations

import fnmatch
import logging
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
            matched = any(fnmatch.fnmatch(full_repo, pattern.lower()) for pattern in self._repos)
            if not matched:
                logger.debug("Repository %r not in allowlist; denying", full_repo)
                raise ShortCircuitError(
                    f"Repository '{owner}/{repo}' is not in the allowlist", deny=True
                )
            logger.debug("Repository %r matched allowlist", full_repo)

        elif self._mode == "blocklist":
            matched = any(fnmatch.fnmatch(full_repo, pattern.lower()) for pattern in self._repos)
            if matched:
                logger.debug("Repository %r matched blocklist; denying", full_repo)
                raise ShortCircuitError(f"Repository '{owner}/{repo}' is blocked", deny=True)
            logger.debug("Repository %r not in blocklist; allowing", full_repo)

        return ctx


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
