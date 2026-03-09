"""Tests for GitHubRepoFilterPlugin lifecycle and configuration."""

import pytest

from mcp_zero.pipeline.registry import HookRegistry
from mcp_zero.plugin import Plugin
from mcp_zero.plugins.github_repo_filter import (
    GitHubRepoFilterHook,
    GitHubRepoFilterPlugin,
)


class TestGitHubRepoFilterPlugin:
    def test_satisfies_plugin_protocol(self):
        """isinstance check against Plugin protocol."""
        plugin = GitHubRepoFilterPlugin()
        assert isinstance(plugin, Plugin)

    def test_name(self):
        """Returns 'github-repo-filter'."""
        assert GitHubRepoFilterPlugin().name == "github-repo-filter"

    def test_configure_allowlist(self):
        """Stores allowlist mode and repos."""
        plugin = GitHubRepoFilterPlugin()
        plugin.configure({"mode": "allowlist", "repos": ["org/repo-a", "org/repo-b"]})
        assert plugin._mode == "allowlist"
        assert plugin._repos == ["org/repo-a", "org/repo-b"]

    def test_configure_blocklist(self):
        """Stores blocklist mode and repos."""
        plugin = GitHubRepoFilterPlugin()
        plugin.configure({"mode": "blocklist", "repos": ["org/repo-x"]})
        assert plugin._mode == "blocklist"
        assert plugin._repos == ["org/repo-x"]

    def test_configure_missing_mode_raises(self):
        """ValueError when mode is missing."""
        plugin = GitHubRepoFilterPlugin()
        with pytest.raises(ValueError, match="'allowlist' or 'blocklist'"):
            plugin.configure({"repos": ["org/repo"]})

    def test_configure_invalid_mode_raises(self):
        """ValueError when mode is not allowlist/blocklist."""
        plugin = GitHubRepoFilterPlugin()
        with pytest.raises(ValueError, match="'allowlist' or 'blocklist'"):
            plugin.configure({"mode": "denylist", "repos": ["org/repo"]})

    def test_configure_empty_repos_raises(self):
        """ValueError when repos list is empty."""
        plugin = GitHubRepoFilterPlugin()
        with pytest.raises(ValueError, match="non-empty 'repos' list"):
            plugin.configure({"mode": "allowlist", "repos": []})

    def test_configure_missing_repos_raises(self):
        """ValueError when repos key is missing."""
        plugin = GitHubRepoFilterPlugin()
        with pytest.raises(ValueError, match="non-empty 'repos' list"):
            plugin.configure({"mode": "allowlist"})

    def test_configure_invalid_repo_format_raises(self):
        """ValueError for entries without '/'."""
        plugin = GitHubRepoFilterPlugin()
        with pytest.raises(ValueError, match="containing '/'"):
            plugin.configure({"mode": "allowlist", "repos": ["noslash"]})

    def test_configure_custom_priority(self):
        """Overrides default priority of 55."""
        plugin = GitHubRepoFilterPlugin()
        plugin.configure({"mode": "allowlist", "repos": ["org/repo"], "priority": 30})
        assert plugin._priority == 30

    def test_configure_servers_list(self):
        """Stores server filter list."""
        plugin = GitHubRepoFilterPlugin()
        plugin.configure(
            {
                "mode": "allowlist",
                "repos": ["org/repo"],
                "servers": ["github-server", "gh-enterprise"],
            }
        )
        assert plugin._servers == ["github-server", "gh-enterprise"]

    def test_register_adds_hook_to_registry(self):
        """Verifies hook appears in registry after build()."""
        plugin = GitHubRepoFilterPlugin()
        plugin.configure({"mode": "allowlist", "repos": ["org/repo"]})
        registry = HookRegistry()
        plugin.register(registry)
        registry.build()
        hooks = registry.get_hooks()
        assert len(hooks) == 1
        assert isinstance(hooks[0], GitHubRepoFilterHook)
        # Verify config was passed through
        assert hooks[0]._mode == "allowlist"
        assert hooks[0]._repos == ["org/repo"]
