"""Tests for GitHubRepoFilterHook output filtering (on_post_masking)."""

import json

import pytest

from mcp_zero.context import HookContext
from mcp_zero.plugins.github_repo_filter import GitHubRepoFilterHook


def _make_hook(mode: str, repos: list[str], servers: list[str] | None = None):
    return GitHubRepoFilterHook(mode=mode, repos=repos, servers=servers)


def _make_search_ctx(
    tool_name: str,
    results: list[dict],
    server_name: str = "github-server",
):
    """Build a HookContext with search results in response_payload."""
    return HookContext(
        tool_name=tool_name,
        server_name=server_name,
        response_payload={"content": [{"type": "text", "text": json.dumps(results)}]},
    )


class TestGitHubRepoFilterHookOutput:
    @pytest.mark.asyncio
    async def test_search_code_filters_disallowed_repos(self):
        """Blocklist strips matching results from search_code."""
        hook = _make_hook("blocklist", ["evil-org/bad-repo"])
        results = [
            {"full_name": "evil-org/bad-repo", "path": "file.py"},
            {"full_name": "good-org/good-repo", "path": "file.py"},
        ]
        ctx = _make_search_ctx("search_code", results)
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        parsed = json.loads(content[0]["text"])
        assert len(parsed) == 1
        assert parsed[0]["full_name"] == "good-org/good-repo"

    @pytest.mark.asyncio
    async def test_search_repositories_filters_disallowed_repos(self):
        """Allowlist keeps only matching results from search_repositories."""
        hook = _make_hook("allowlist", ["myorg/allowed"])
        results = [
            {"full_name": "myorg/allowed"},
            {"full_name": "myorg/not-allowed"},
        ]
        ctx = _make_search_ctx("search_repositories", results)
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        parsed = json.loads(content[0]["text"])
        assert len(parsed) == 1
        assert parsed[0]["full_name"] == "myorg/allowed"

    @pytest.mark.asyncio
    async def test_search_issues_filters_disallowed_repos(self):
        """Filters issue search results using repository.full_name."""
        hook = _make_hook("blocklist", ["org/blocked"])
        results = [
            {"title": "Issue 1", "repository": {"full_name": "org/blocked"}},
            {"title": "Issue 2", "repository": {"full_name": "org/allowed"}},
        ]
        ctx = _make_search_ctx("search_issues", results)
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        parsed = json.loads(content[0]["text"])
        assert len(parsed) == 1
        assert parsed[0]["title"] == "Issue 2"

    @pytest.mark.asyncio
    async def test_all_results_filtered_returns_empty_message(self):
        """Returns policy message when all items are filtered out."""
        hook = _make_hook("allowlist", ["myorg/only-this"])
        results = [
            {"full_name": "other/repo-1"},
            {"full_name": "other/repo-2"},
        ]
        ctx = _make_search_ctx("search_code", results)
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        assert len(content) == 1
        assert "All results were filtered" in content[0]["text"]

    @pytest.mark.asyncio
    async def test_non_search_tool_passes_through(self):
        """Non-search tools are returned unchanged."""
        hook = _make_hook("blocklist", ["org/repo"])
        ctx = HookContext(
            tool_name="get_file_contents",
            server_name="github-server",
            response_payload={"content": [{"type": "text", "text": "some data"}]},
        )
        result = await hook.on_post_masking(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_output_filter_respects_server_scoping(self):
        """Only applies when server matches the configured servers list."""
        hook = _make_hook("blocklist", ["org/blocked"], servers=["github-server"])
        results = [{"full_name": "org/blocked"}]
        ctx = _make_search_ctx("search_code", results, server_name="other-server")
        result = await hook.on_post_masking(ctx)
        assert result is ctx  # skipped, server doesn't match

    @pytest.mark.asyncio
    async def test_output_parse_error_fails_closed(self):
        """Malformed JSON response is blocked, never leaks unfiltered data."""
        hook = _make_hook("blocklist", ["org/repo"])
        ctx = HookContext(
            tool_name="search_code",
            server_name="github-server",
            response_payload={"content": [{"type": "text", "text": "not valid json{{{"}]},
        )
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        assert "unable to parse" in content[0]["text"]

    @pytest.mark.asyncio
    async def test_allowlist_output_keeps_only_matching(self):
        """Allowlist mode keeps only repos that match patterns."""
        hook = _make_hook("allowlist", ["myorg/*"])
        results = [
            {"full_name": "myorg/repo-a"},
            {"full_name": "other/repo-b"},
            {"full_name": "myorg/repo-c"},
        ]
        ctx = _make_search_ctx("search_code", results)
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        parsed = json.loads(content[0]["text"])
        assert len(parsed) == 2
        assert all(p["full_name"].startswith("myorg/") for p in parsed)

    @pytest.mark.asyncio
    async def test_blocklist_output_removes_matching(self):
        """Blocklist mode removes repos that match patterns."""
        hook = _make_hook("blocklist", ["bad-org/*"])
        results = [
            {"full_name": "bad-org/repo-1"},
            {"full_name": "good-org/repo-2"},
            {"full_name": "bad-org/repo-3"},
        ]
        ctx = _make_search_ctx("search_code", results)
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        parsed = json.loads(content[0]["text"])
        assert len(parsed) == 1
        assert parsed[0]["full_name"] == "good-org/repo-2"
