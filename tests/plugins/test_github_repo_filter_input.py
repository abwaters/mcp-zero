"""Tests for GitHubRepoFilterHook input filtering (on_post_validation)."""

import pytest

from mcp_zero.context import HookContext
from mcp_zero.pipeline.errors import ShortCircuitError
from mcp_zero.plugins.github_repo_filter import GitHubRepoFilterHook


def _make_hook(mode: str, repos: list[str], servers: list[str] | None = None):
    return GitHubRepoFilterHook(mode=mode, repos=repos, servers=servers)


def _make_ctx(owner: str = "", repo: str = "", server_name: str = "github-server"):
    arguments = {}
    if owner:
        arguments["owner"] = owner
    if repo:
        arguments["repo"] = repo
    return HookContext(
        request_payload={"arguments": arguments},
        server_name=server_name,
    )


class TestGitHubRepoFilterHookInput:
    @pytest.mark.asyncio
    async def test_allowlist_allows_matching_repo(self):
        hook = _make_hook("allowlist", ["myorg/my-repo"])
        ctx = _make_ctx("myorg", "my-repo")
        result = await hook.on_post_validation(ctx)
        assert result is ctx  # passes through unchanged

    @pytest.mark.asyncio
    async def test_allowlist_denies_non_matching_repo(self):
        hook = _make_hook("allowlist", ["myorg/allowed-repo"])
        ctx = _make_ctx("myorg", "other-repo")
        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_post_validation(ctx)
        assert exc_info.value.deny is True

    @pytest.mark.asyncio
    async def test_blocklist_denies_matching_repo(self):
        hook = _make_hook("blocklist", ["myorg/blocked-repo"])
        ctx = _make_ctx("myorg", "blocked-repo")
        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_post_validation(ctx)
        assert exc_info.value.deny is True

    @pytest.mark.asyncio
    async def test_blocklist_allows_non_matching_repo(self):
        hook = _make_hook("blocklist", ["myorg/blocked-repo"])
        ctx = _make_ctx("myorg", "other-repo")
        result = await hook.on_post_validation(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_no_repo_args_passes_through(self):
        hook = _make_hook("allowlist", ["myorg/repo"])
        ctx = HookContext(request_payload={"arguments": {"some_other": "arg"}})
        result = await hook.on_post_validation(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_pattern_matching_wildcard(self):
        hook = _make_hook("allowlist", ["myorg/*"])
        ctx = _make_ctx("myorg", "any-repo")
        result = await hook.on_post_validation(ctx)
        assert result is ctx  # wildcard matches

    @pytest.mark.asyncio
    async def test_case_insensitive_matching(self):
        hook = _make_hook("allowlist", ["MyOrg/MyRepo"])
        ctx = _make_ctx("myorg", "myrepo")
        result = await hook.on_post_validation(ctx)
        assert result is ctx  # case-insensitive match

    @pytest.mark.asyncio
    async def test_server_scoping_applies_filter(self):
        hook = _make_hook("blocklist", ["myorg/blocked"], servers=["github-server"])
        ctx = _make_ctx("myorg", "blocked", server_name="github-server")
        with pytest.raises(ShortCircuitError):
            await hook.on_post_validation(ctx)

    @pytest.mark.asyncio
    async def test_server_scoping_skips_other_servers(self):
        hook = _make_hook("blocklist", ["myorg/blocked"], servers=["github-server"])
        ctx = _make_ctx("myorg", "blocked", server_name="other-server")
        result = await hook.on_post_validation(ctx)
        assert result is ctx  # skipped because server doesn't match

    @pytest.mark.asyncio
    async def test_no_server_scoping_filters_all(self):
        hook = _make_hook("blocklist", ["myorg/blocked"], servers=None)
        ctx = _make_ctx("myorg", "blocked", server_name="any-server")
        with pytest.raises(ShortCircuitError):
            await hook.on_post_validation(ctx)
