"""Tests for GitHubRepoFilterPlugin scaffold and configuration validation."""

import pytest

from mcp_zero.pipeline.registry import HookRegistry
from mcp_zero.plugin import Plugin
from mcp_zero.plugins.github_repo_filter import (
    DEFAULT_PRIORITY,
    GitHubRepoFilterHook,
    GitHubRepoFilterPlugin,
)


class TestPluginProtocol:
    def test_satisfies_plugin_protocol(self):
        plugin = GitHubRepoFilterPlugin()
        assert isinstance(plugin, Plugin)

    def test_name_returns_github_repo_filter(self):
        plugin = GitHubRepoFilterPlugin()
        assert plugin.name == "github-repo-filter"


class TestConfigureMode:
    def test_allowlist_mode_accepted(self):
        plugin = GitHubRepoFilterPlugin()
        plugin.configure({"mode": "allowlist", "repos": ["org/repo"]})
        assert plugin._mode == "allowlist"

    def test_blocklist_mode_accepted(self):
        plugin = GitHubRepoFilterPlugin()
        plugin.configure({"mode": "blocklist", "repos": ["org/repo"]})
        assert plugin._mode == "blocklist"

    def test_missing_mode_raises(self):
        plugin = GitHubRepoFilterPlugin()
        with pytest.raises(ValueError, match="'allowlist' or 'blocklist'"):
            plugin.configure({"repos": ["org/repo"]})

    def test_invalid_mode_raises(self):
        plugin = GitHubRepoFilterPlugin()
        with pytest.raises(ValueError, match="'allowlist' or 'blocklist'"):
            plugin.configure({"mode": "denylist", "repos": ["org/repo"]})


class TestConfigureRepos:
    def test_valid_repos_accepted(self):
        plugin = GitHubRepoFilterPlugin()
        plugin.configure({"mode": "allowlist", "repos": ["org/repo-a", "org/repo-b"]})
        assert plugin._repos == ["org/repo-a", "org/repo-b"]

    def test_empty_repos_raises(self):
        plugin = GitHubRepoFilterPlugin()
        with pytest.raises(ValueError, match="non-empty 'repos' list"):
            plugin.configure({"mode": "allowlist", "repos": []})

    def test_missing_repos_raises(self):
        plugin = GitHubRepoFilterPlugin()
        with pytest.raises(ValueError, match="non-empty 'repos' list"):
            plugin.configure({"mode": "allowlist"})

    def test_repo_without_slash_raises(self):
        plugin = GitHubRepoFilterPlugin()
        with pytest.raises(ValueError, match="containing '/'"):
            plugin.configure({"mode": "allowlist", "repos": ["no-slash"]})

    def test_non_string_repo_raises(self):
        plugin = GitHubRepoFilterPlugin()
        with pytest.raises(ValueError, match="containing '/'"):
            plugin.configure({"mode": "allowlist", "repos": [123]})


class TestConfigureOptionalFields:
    def test_servers_stored(self):
        plugin = GitHubRepoFilterPlugin()
        plugin.configure(
            {
                "mode": "allowlist",
                "repos": ["org/repo"],
                "servers": ["github-server"],
            }
        )
        assert plugin._servers == ["github-server"]

    def test_servers_defaults_to_none(self):
        plugin = GitHubRepoFilterPlugin()
        plugin.configure({"mode": "allowlist", "repos": ["org/repo"]})
        assert plugin._servers is None

    def test_invalid_servers_raises(self):
        plugin = GitHubRepoFilterPlugin()
        with pytest.raises(ValueError, match="'servers' must be a list"):
            plugin.configure(
                {
                    "mode": "allowlist",
                    "repos": ["org/repo"],
                    "servers": "not-a-list",
                }
            )

    def test_priority_override(self):
        plugin = GitHubRepoFilterPlugin()
        plugin.configure(
            {
                "mode": "allowlist",
                "repos": ["org/repo"],
                "priority": 30,
            }
        )
        assert plugin._priority == 30

    def test_priority_defaults(self):
        plugin = GitHubRepoFilterPlugin()
        plugin.configure({"mode": "allowlist", "repos": ["org/repo"]})
        assert plugin._priority == DEFAULT_PRIORITY


class TestRegister:
    def test_registers_hook_in_registry(self):
        plugin = GitHubRepoFilterPlugin()
        plugin.configure({"mode": "allowlist", "repos": ["org/repo"]})
        registry = HookRegistry()
        plugin.register(registry)
        registry.build()
        hooks = registry.get_hooks()
        assert len(hooks) == 1
        assert isinstance(hooks[0], GitHubRepoFilterHook)

    def test_hook_receives_config(self):
        plugin = GitHubRepoFilterPlugin()
        plugin.configure(
            {
                "mode": "blocklist",
                "repos": ["org/repo-a", "org/repo-b"],
                "servers": ["srv-1"],
            }
        )
        registry = HookRegistry()
        plugin.register(registry)
        registry.build()
        hook = registry.get_hooks()[0]
        assert hook._mode == "blocklist"
        assert hook._repos == ["org/repo-a", "org/repo-b"]
        assert hook._servers == ["srv-1"]
