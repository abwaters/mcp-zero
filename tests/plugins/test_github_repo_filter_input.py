"""Tests for GitHubRepoFilterHook input filtering (on_post_validation)."""

import pytest

from mcp_zero.context import HookContext
from mcp_zero.pipeline.errors import ShortCircuitError
from mcp_zero.plugins.github_repo_filter import GitHubRepoFilterHook


def _make_hook(mode: str, repos: list[str], servers: list[str] | None = None):
    return GitHubRepoFilterHook(mode=mode, repos=repos, servers=servers)


def _make_ctx(owner: str = "", repo: str = "", server_name: str = "github-server", **extra_args):
    arguments = dict(extra_args)
    if owner:
        arguments["owner"] = owner
    if repo:
        arguments["repo"] = repo
    return HookContext(
        request_payload={"arguments": arguments},
        server_name=server_name,
    )


class TestInputOwnerRepoArgs:
    """Tests for the classic owner + repo argument pattern."""

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


class TestInputServerScoping:
    """Tests for server scoping on input filtering."""

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


class TestInputRepositoryArg:
    """Tests for the single 'repository' argument pattern (owner/repo string)."""

    @pytest.mark.asyncio
    async def test_repository_arg_allowlist_allows(self):
        hook = _make_hook("allowlist", ["myorg/my-repo"])
        ctx = HookContext(
            request_payload={"arguments": {"repository": "myorg/my-repo"}},
            server_name="github-server",
        )
        result = await hook.on_post_validation(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_repository_arg_allowlist_denies(self):
        hook = _make_hook("allowlist", ["myorg/allowed"])
        ctx = HookContext(
            request_payload={"arguments": {"repository": "other/repo"}},
            server_name="github-server",
        )
        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_post_validation(ctx)
        assert exc_info.value.deny is True

    @pytest.mark.asyncio
    async def test_repository_arg_blocklist_blocks(self):
        hook = _make_hook("blocklist", ["evil/repo"])
        ctx = HookContext(
            request_payload={"arguments": {"repository": "evil/repo"}},
            server_name="github-server",
        )
        with pytest.raises(ShortCircuitError):
            await hook.on_post_validation(ctx)

    @pytest.mark.asyncio
    async def test_repository_arg_blocklist_allows(self):
        hook = _make_hook("blocklist", ["evil/repo"])
        ctx = HookContext(
            request_payload={"arguments": {"repository": "good/repo"}},
            server_name="github-server",
        )
        result = await hook.on_post_validation(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_repository_arg_without_slash_ignored(self):
        """A 'repository' value without '/' is not treated as owner/repo."""
        hook = _make_hook("allowlist", ["myorg/repo"])
        ctx = HookContext(
            request_payload={"arguments": {"repository": "noslash"}},
            server_name="github-server",
        )
        result = await hook.on_post_validation(ctx)
        assert result is ctx  # no repo extracted, passes through


class TestInputSearchQueryQualifiers:
    """Tests for extracting repo:owner/name from search query strings."""

    @pytest.mark.asyncio
    async def test_query_repo_qualifier_allowlist_allows(self):
        hook = _make_hook("allowlist", ["myorg/my-repo"])
        ctx = HookContext(
            request_payload={"arguments": {"query": "bug repo:myorg/my-repo"}},
            server_name="github-server",
        )
        result = await hook.on_post_validation(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_query_repo_qualifier_allowlist_denies(self):
        hook = _make_hook("allowlist", ["myorg/allowed"])
        ctx = HookContext(
            request_payload={"arguments": {"query": "bug repo:other/disallowed"}},
            server_name="github-server",
        )
        with pytest.raises(ShortCircuitError):
            await hook.on_post_validation(ctx)

    @pytest.mark.asyncio
    async def test_query_multiple_repo_qualifiers_all_must_pass(self):
        """If a query references multiple repos, ALL must be allowed."""
        hook = _make_hook("allowlist", ["myorg/repo-a"])
        ctx = HookContext(
            request_payload={"arguments": {"query": "repo:myorg/repo-a repo:other/repo-b fix"}},
            server_name="github-server",
        )
        with pytest.raises(ShortCircuitError):
            await hook.on_post_validation(ctx)

    @pytest.mark.asyncio
    async def test_query_multiple_repo_qualifiers_all_allowed(self):
        hook = _make_hook("allowlist", ["myorg/*"])
        ctx = HookContext(
            request_payload={"arguments": {"query": "repo:myorg/repo-a repo:myorg/repo-b fix"}},
            server_name="github-server",
        )
        result = await hook.on_post_validation(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_query_without_repo_qualifier_passes(self):
        """Search queries without repo: qualifiers pass through."""
        hook = _make_hook("allowlist", ["myorg/repo"])
        ctx = HookContext(
            request_payload={"arguments": {"query": "some search terms"}},
            server_name="github-server",
        )
        result = await hook.on_post_validation(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_q_argument_also_parsed(self):
        """The 'q' argument is also checked for repo qualifiers."""
        hook = _make_hook("blocklist", ["evil/repo"])
        ctx = HookContext(
            request_payload={"arguments": {"q": "repo:evil/repo bug"}},
            server_name="github-server",
        )
        with pytest.raises(ShortCircuitError):
            await hook.on_post_validation(ctx)


class TestInputEdgeCases:
    """Edge cases for input filtering."""

    @pytest.mark.asyncio
    async def test_non_dict_arguments_passes_through(self):
        hook = _make_hook("allowlist", ["myorg/repo"])
        ctx = HookContext(request_payload={"arguments": "not-a-dict"})
        result = await hook.on_post_validation(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_both_owner_repo_and_repository_checked(self):
        """If both patterns present, both are checked."""
        hook = _make_hook("allowlist", ["myorg/repo-a", "myorg/repo-b"])
        ctx = HookContext(
            request_payload={
                "arguments": {
                    "owner": "myorg",
                    "repo": "repo-a",
                    "repository": "myorg/repo-b",
                }
            },
            server_name="github-server",
        )
        result = await hook.on_post_validation(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_mixed_patterns_one_disallowed_denies(self):
        """If any extracted repo is disallowed, the request is denied."""
        hook = _make_hook("allowlist", ["myorg/repo-a"])
        ctx = HookContext(
            request_payload={
                "arguments": {
                    "owner": "myorg",
                    "repo": "repo-a",
                    "repository": "other/forbidden",
                }
            },
            server_name="github-server",
        )
        with pytest.raises(ShortCircuitError):
            await hook.on_post_validation(ctx)
