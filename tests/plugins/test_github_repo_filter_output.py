"""Tests for GitHubRepoFilterHook output filtering (on_post_masking)."""

import json

import pytest

from mcp_zero.context import HookContext
from mcp_zero.plugins.github_repo_filter import GitHubRepoFilterHook


def _make_hook(mode: str, repos: list[str], servers: list[str] | None = None):
    return GitHubRepoFilterHook(mode=mode, repos=repos, servers=servers)


def _make_response_ctx(
    tool_name: str,
    results: list[dict] | dict,
    server_name: str = "github-server",
):
    """Build a HookContext with results in response_payload."""
    return HookContext(
        tool_name=tool_name,
        server_name=server_name,
        response_payload={"content": [{"type": "text", "text": json.dumps(results)}]},
    )


# -----------------------------------------------------------------------
# Search / list tool output filtering (multi-item)
# -----------------------------------------------------------------------


class TestSearchToolOutputFiltering:
    """Tests for filtering search tool responses (list-style tools)."""

    @pytest.mark.asyncio
    async def test_search_code_filters_disallowed_repos(self):
        """Blocklist strips matching results from search_code."""
        hook = _make_hook("blocklist", ["evil-org/bad-repo"])
        results = [
            {"full_name": "evil-org/bad-repo", "path": "file.py"},
            {"full_name": "good-org/good-repo", "path": "file.py"},
        ]
        ctx = _make_response_ctx("search_code", results)
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
        ctx = _make_response_ctx("search_repositories", results)
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
        ctx = _make_response_ctx("search_issues", results)
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
        ctx = _make_response_ctx("search_code", results)
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        assert len(content) == 1
        assert "All results were filtered" in content[0]["text"]

    @pytest.mark.asyncio
    async def test_allowlist_output_keeps_only_matching(self):
        """Allowlist mode keeps only repos that match patterns."""
        hook = _make_hook("allowlist", ["myorg/*"])
        results = [
            {"full_name": "myorg/repo-a"},
            {"full_name": "other/repo-b"},
            {"full_name": "myorg/repo-c"},
        ]
        ctx = _make_response_ctx("search_code", results)
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
        ctx = _make_response_ctx("search_code", results)
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        parsed = json.loads(content[0]["text"])
        assert len(parsed) == 1
        assert parsed[0]["full_name"] == "good-org/repo-2"


# -----------------------------------------------------------------------
# List tool output filtering (non-search list tools)
# -----------------------------------------------------------------------


class TestListToolOutputFiltering:
    """Tests for filtering list_* tool responses."""

    @pytest.mark.asyncio
    async def test_list_issues_filters_by_repo(self):
        hook = _make_hook("allowlist", ["myorg/allowed"])
        results = [
            {"title": "Issue A", "repository": {"full_name": "myorg/allowed"}},
            {"title": "Issue B", "repository": {"full_name": "myorg/blocked"}},
        ]
        ctx = _make_response_ctx("list_issues", results)
        result = await hook.on_post_masking(ctx)
        parsed = json.loads(result.response_payload["content"][0]["text"])
        assert len(parsed) == 1
        assert parsed[0]["title"] == "Issue A"

    @pytest.mark.asyncio
    async def test_list_pull_requests_filters_by_repo(self):
        hook = _make_hook("blocklist", ["evil/repo"])
        results = [
            {"title": "PR 1", "html_url": "https://github.com/evil/repo/pull/1"},
            {"title": "PR 2", "html_url": "https://github.com/good/repo/pull/2"},
        ]
        ctx = _make_response_ctx("list_pull_requests", results)
        result = await hook.on_post_masking(ctx)
        parsed = json.loads(result.response_payload["content"][0]["text"])
        assert len(parsed) == 1
        assert parsed[0]["title"] == "PR 2"

    @pytest.mark.asyncio
    async def test_list_commits_filters_by_repo_url(self):
        hook = _make_hook("allowlist", ["myorg/my-repo"])
        results = [
            {"sha": "abc", "html_url": "https://github.com/myorg/my-repo/commit/abc"},
            {"sha": "def", "html_url": "https://github.com/other/repo/commit/def"},
        ]
        ctx = _make_response_ctx("list_commits", results)
        result = await hook.on_post_masking(ctx)
        parsed = json.loads(result.response_payload["content"][0]["text"])
        assert len(parsed) == 1
        assert parsed[0]["sha"] == "abc"

    @pytest.mark.asyncio
    async def test_list_branches_filters_by_repo(self):
        hook = _make_hook("blocklist", ["blocked/repo"])
        results = [
            {"name": "main", "repository": {"full_name": "blocked/repo"}},
            {"name": "develop", "repository": {"full_name": "good/repo"}},
        ]
        ctx = _make_response_ctx("list_branches", results)
        result = await hook.on_post_masking(ctx)
        parsed = json.loads(result.response_payload["content"][0]["text"])
        assert len(parsed) == 1
        assert parsed[0]["name"] == "develop"

    @pytest.mark.asyncio
    async def test_list_tags_filters_by_repo(self):
        hook = _make_hook("allowlist", ["myorg/*"])
        results = [
            {"name": "v1.0", "repository": {"full_name": "myorg/repo-a"}},
            {"name": "v2.0", "repository": {"full_name": "other/repo-b"}},
        ]
        ctx = _make_response_ctx("list_tags", results)
        result = await hook.on_post_masking(ctx)
        parsed = json.loads(result.response_payload["content"][0]["text"])
        assert len(parsed) == 1
        assert parsed[0]["name"] == "v1.0"


# -----------------------------------------------------------------------
# Single-result tool output filtering
# -----------------------------------------------------------------------


class TestSingleResultOutputFiltering:
    """Tests for blocking single-result tool responses (get_*, create_*, etc.)."""

    @pytest.mark.asyncio
    async def test_get_file_contents_allowed(self):
        hook = _make_hook("allowlist", ["myorg/my-repo"])
        result_data = {"content": "...", "full_name": "myorg/my-repo", "path": "README.md"}
        ctx = _make_response_ctx("get_file_contents", result_data)
        result = await hook.on_post_masking(ctx)
        parsed = json.loads(result.response_payload["content"][0]["text"])
        assert parsed["full_name"] == "myorg/my-repo"

    @pytest.mark.asyncio
    async def test_get_file_contents_blocked(self):
        hook = _make_hook("allowlist", ["myorg/allowed"])
        result_data = {"content": "...", "full_name": "other/repo", "path": "secret.txt"}
        ctx = _make_response_ctx("get_file_contents", result_data)
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        assert len(content) == 1
        assert "blocked by repository policy" in content[0]["text"]

    @pytest.mark.asyncio
    async def test_get_issue_allowed(self):
        hook = _make_hook("blocklist", ["evil/repo"])
        result_data = {
            "title": "Bug report",
            "html_url": "https://github.com/good/repo/issues/1",
        }
        ctx = _make_response_ctx("get_issue", result_data)
        result = await hook.on_post_masking(ctx)
        parsed = json.loads(result.response_payload["content"][0]["text"])
        assert parsed["title"] == "Bug report"

    @pytest.mark.asyncio
    async def test_get_issue_blocked(self):
        hook = _make_hook("blocklist", ["evil/repo"])
        result_data = {
            "title": "Secret issue",
            "html_url": "https://github.com/evil/repo/issues/99",
        }
        ctx = _make_response_ctx("get_issue", result_data)
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        assert "blocked by repository policy" in content[0]["text"]

    @pytest.mark.asyncio
    async def test_get_pull_request_allowed(self):
        hook = _make_hook("allowlist", ["myorg/*"])
        result_data = {
            "title": "My PR",
            "repository": {"full_name": "myorg/repo-a"},
        }
        ctx = _make_response_ctx("get_pull_request", result_data)
        result = await hook.on_post_masking(ctx)
        parsed = json.loads(result.response_payload["content"][0]["text"])
        assert parsed["title"] == "My PR"

    @pytest.mark.asyncio
    async def test_get_pull_request_blocked(self):
        hook = _make_hook("allowlist", ["myorg/*"])
        result_data = {
            "title": "Blocked PR",
            "repository": {"full_name": "other/repo"},
        }
        ctx = _make_response_ctx("get_pull_request", result_data)
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        assert "blocked by repository policy" in content[0]["text"]

    @pytest.mark.asyncio
    async def test_get_commit_allowed(self):
        hook = _make_hook("allowlist", ["myorg/repo"])
        result_data = {"sha": "abc123", "html_url": "https://github.com/myorg/repo/commit/abc123"}
        ctx = _make_response_ctx("get_commit", result_data)
        result = await hook.on_post_masking(ctx)
        parsed = json.loads(result.response_payload["content"][0]["text"])
        assert parsed["sha"] == "abc123"

    @pytest.mark.asyncio
    async def test_get_commit_blocked(self):
        hook = _make_hook("allowlist", ["myorg/repo"])
        result_data = {"sha": "def456", "html_url": "https://github.com/other/repo/commit/def456"}
        ctx = _make_response_ctx("get_commit", result_data)
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        assert "blocked by repository policy" in content[0]["text"]

    @pytest.mark.asyncio
    async def test_create_issue_blocked(self):
        """Mutating tool responses are also filtered."""
        hook = _make_hook("allowlist", ["myorg/repo"])
        result_data = {
            "title": "New issue",
            "html_url": "https://github.com/other/repo/issues/5",
        }
        ctx = _make_response_ctx("create_issue", result_data)
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        assert "blocked by repository policy" in content[0]["text"]

    @pytest.mark.asyncio
    async def test_single_result_no_repo_ref_passes_through(self):
        """If no repo reference can be extracted, pass through (cannot filter)."""
        hook = _make_hook("allowlist", ["myorg/repo"])
        result_data = {"login": "octocat", "type": "User"}
        ctx = _make_response_ctx("get_file_contents", result_data)
        result = await hook.on_post_masking(ctx)
        parsed = json.loads(result.response_payload["content"][0]["text"])
        assert parsed["login"] == "octocat"

    @pytest.mark.asyncio
    async def test_single_result_owner_name_extraction(self):
        """Repo extracted from owner.login + name fields."""
        hook = _make_hook("blocklist", ["evil/repo"])
        result_data = {
            "name": "repo",
            "owner": {"login": "evil"},
            "description": "An evil repo",
        }
        ctx = _make_response_ctx("get_file_contents", result_data)
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        assert "blocked by repository policy" in content[0]["text"]


# -----------------------------------------------------------------------
# Non-repo-aware tools and edge cases
# -----------------------------------------------------------------------


class TestNonRepoAwareToolsAndEdgeCases:
    @pytest.mark.asyncio
    async def test_non_repo_aware_tool_passes_through(self):
        """Tools not in _REPO_AWARE_TOOLS pass through unmodified."""
        hook = _make_hook("blocklist", ["org/repo"])
        ctx = HookContext(
            tool_name="get_me",
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
        ctx = _make_response_ctx("search_code", results, server_name="other-server")
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
    async def test_single_result_parse_error_fails_closed(self):
        """Malformed JSON for single-result tools also fails closed."""
        hook = _make_hook("blocklist", ["org/repo"])
        ctx = HookContext(
            tool_name="get_file_contents",
            server_name="github-server",
            response_payload={"content": [{"type": "text", "text": "{{bad json"}]},
        )
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        assert "unable to parse" in content[0]["text"]

    @pytest.mark.asyncio
    async def test_non_text_content_preserved(self):
        """Non-text content items (e.g. images) are preserved as-is."""
        hook = _make_hook("blocklist", ["org/repo"])
        ctx = HookContext(
            tool_name="search_code",
            server_name="github-server",
            response_payload={
                "content": [
                    {"type": "image", "data": "base64..."},
                    {"type": "text", "text": json.dumps([{"full_name": "good/repo"}])},
                ]
            },
        )
        result = await hook.on_post_masking(ctx)
        content = result.response_payload["content"]
        assert len(content) == 2
        assert content[0]["type"] == "image"

    @pytest.mark.asyncio
    async def test_non_list_content_passes_through(self):
        """If content is not a list, pass through unmodified."""
        hook = _make_hook("blocklist", ["org/repo"])
        ctx = HookContext(
            tool_name="search_code",
            server_name="github-server",
            response_payload={"content": "not-a-list"},
        )
        result = await hook.on_post_masking(ctx)
        assert result is ctx
