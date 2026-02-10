"""Tests for the policy evaluation engine."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mcp_zero.governance.config import (
    PolicyConfig,
    PolicyEffect,
    PolicyRule,
    PolicyServerAccess,
    PolicySubjects,
)
from mcp_zero.governance.engine import (
    EvaluationResult,
    PolicyEngine,
    PolicyInput,
    _matches_pattern,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _policy(
    *rules: PolicyRule,
    default: PolicyEffect = PolicyEffect.DENY,
) -> PolicyConfig:
    """Build a minimal PolicyConfig with the given rules."""
    return PolicyConfig(version=1, default=default, policies=list(rules))


def _rule(
    rule_id: str,
    effect: PolicyEffect,
    *,
    users: list[str] | None = None,
    groups: list[str] | None = None,
    servers: list[PolicyServerAccess] | None = None,
) -> PolicyRule:
    """Build a PolicyRule with sensible defaults."""
    subjects = PolicySubjects(
        users=users or [],
        groups=groups or [],
    )
    return PolicyRule(
        id=rule_id,
        description=f"Rule {rule_id}",
        effect=effect,
        subjects=subjects,
        mcp_servers=servers or [],
    )


def _server(name: str, tools: list[str] | None = None) -> PolicyServerAccess:
    """Build a PolicyServerAccess entry."""
    return PolicyServerAccess(name=name, tools=tools or [])


def _input(
    user_id: str = "user@example.com",
    groups: list[str] | None = None,
    mcp_server: str = "api",
    tool: str = "read_file",
) -> PolicyInput:
    return PolicyInput(
        user_id=user_id,
        groups=groups or [],
        mcp_server=mcp_server,
        tool=tool,
    )


# ---------------------------------------------------------------------------
# _matches_pattern unit tests
# ---------------------------------------------------------------------------


class TestMatchesPattern:
    def test_wildcard_matches_everything(self):
        assert _matches_pattern("*", "anything") is True
        assert _matches_pattern("*", "") is True

    def test_prefix_wildcard(self):
        assert _matches_pattern("read_*", "read_file") is True
        assert _matches_pattern("read_*", "read_") is True
        assert _matches_pattern("read_*", "write_file") is False

    def test_suffix_wildcard(self):
        assert _matches_pattern("*_file", "read_file") is True
        assert _matches_pattern("*_file", "_file") is True
        assert _matches_pattern("*_file", "read_config") is False

    def test_exact_match(self):
        assert _matches_pattern("read_file", "read_file") is True
        assert _matches_pattern("read_file", "write_file") is False

    def test_hyphen_in_pattern(self):
        assert _matches_pattern("internal-*", "internal-infra") is True
        assert _matches_pattern("internal-*", "external-infra") is False


# ---------------------------------------------------------------------------
# Subject matching
# ---------------------------------------------------------------------------


class TestSubjectMatching:
    def test_empty_subjects_matches_everyone(self):
        """A rule with no users/groups matches all requests."""
        policy = _policy(
            _rule("r1", PolicyEffect.ALLOW, servers=[_server("api", ["*"])]),
        )
        engine = PolicyEngine(policy)
        result = engine.evaluate(_input(user_id="anyone"))
        assert result.effect == PolicyEffect.ALLOW
        assert result.policy_id == "r1"

    def test_user_id_match(self):
        policy = _policy(
            _rule(
                "r1",
                PolicyEffect.ALLOW,
                users=["alice@corp.com"],
                servers=[_server("api", ["*"])],
            ),
        )
        engine = PolicyEngine(policy)

        assert engine.evaluate(_input(user_id="alice@corp.com")).effect == PolicyEffect.ALLOW
        assert engine.evaluate(_input(user_id="bob@corp.com")).effect == PolicyEffect.DENY

    def test_group_intersection(self):
        policy = _policy(
            _rule(
                "r1",
                PolicyEffect.ALLOW,
                groups=["admins", "sre"],
                servers=[_server("api", ["*"])],
            ),
        )
        engine = PolicyEngine(policy)

        # User in one matching group
        result = engine.evaluate(_input(groups=["admins"]))
        assert result.effect == PolicyEffect.ALLOW

        # User in both matching groups
        result = engine.evaluate(_input(groups=["admins", "sre"]))
        assert result.effect == PolicyEffect.ALLOW

        # User in unrelated group
        result = engine.evaluate(_input(groups=["developers"]))
        assert result.effect == PolicyEffect.DENY

    def test_wildcard_group(self):
        """The group ``*`` should match any user regardless of their groups."""
        policy = _policy(
            _rule(
                "r1",
                PolicyEffect.DENY,
                groups=["*"],
                servers=[_server("api", ["*"])],
            ),
        )
        engine = PolicyEngine(policy)

        result = engine.evaluate(_input(groups=[]))
        assert result.effect == PolicyEffect.DENY
        assert result.policy_id == "r1"

        result = engine.evaluate(_input(groups=["random"]))
        assert result.effect == PolicyEffect.DENY

    def test_user_match_without_group_match(self):
        """User ID match is sufficient even if groups don't overlap."""
        policy = _policy(
            _rule(
                "r1",
                PolicyEffect.ALLOW,
                users=["alice@corp.com"],
                groups=["admins"],
                servers=[_server("api", ["*"])],
            ),
        )
        engine = PolicyEngine(policy)

        result = engine.evaluate(_input(user_id="alice@corp.com", groups=["developers"]))
        assert result.effect == PolicyEffect.ALLOW

    def test_no_match_when_user_and_groups_differ(self):
        policy = _policy(
            _rule(
                "r1",
                PolicyEffect.ALLOW,
                users=["alice@corp.com"],
                groups=["admins"],
                servers=[_server("api", ["*"])],
            ),
        )
        engine = PolicyEngine(policy)

        result = engine.evaluate(_input(user_id="bob@corp.com", groups=["developers"]))
        assert result.effect == PolicyEffect.DENY


# ---------------------------------------------------------------------------
# Server name matching
# ---------------------------------------------------------------------------


class TestServerNameMatching:
    def test_exact_server_match(self):
        policy = _policy(
            _rule("r1", PolicyEffect.ALLOW, servers=[_server("api", ["*"])]),
        )
        engine = PolicyEngine(policy)

        assert engine.evaluate(_input(mcp_server="api")).effect == PolicyEffect.ALLOW
        assert engine.evaluate(_input(mcp_server="other")).effect == PolicyEffect.DENY

    def test_wildcard_server(self):
        policy = _policy(
            _rule("r1", PolicyEffect.ALLOW, servers=[_server("*", ["*"])]),
        )
        engine = PolicyEngine(policy)

        assert engine.evaluate(_input(mcp_server="anything")).effect == PolicyEffect.ALLOW

    def test_prefix_server_wildcard(self):
        policy = _policy(
            _rule("r1", PolicyEffect.ALLOW, servers=[_server("internal-*", ["*"])]),
        )
        engine = PolicyEngine(policy)

        assert engine.evaluate(_input(mcp_server="internal-infra")).effect == PolicyEffect.ALLOW
        assert engine.evaluate(_input(mcp_server="internal-tools")).effect == PolicyEffect.ALLOW
        assert engine.evaluate(_input(mcp_server="external-api")).effect == PolicyEffect.DENY

    def test_multiple_server_entries(self):
        """A rule with multiple server entries matches if any one matches."""
        policy = _policy(
            _rule(
                "r1",
                PolicyEffect.ALLOW,
                servers=[
                    _server("api", ["read_file"]),
                    _server("local", ["list_files"]),
                ],
            ),
        )
        engine = PolicyEngine(policy)

        assert (
            engine.evaluate(_input(mcp_server="api", tool="read_file")).effect == PolicyEffect.ALLOW
        )
        assert (
            engine.evaluate(_input(mcp_server="local", tool="list_files")).effect
            == PolicyEffect.ALLOW
        )
        assert (
            engine.evaluate(_input(mcp_server="other", tool="read_file")).effect
            == PolicyEffect.DENY
        )

    def test_no_servers_means_no_match(self):
        """A rule with empty mcp_servers list never matches."""
        policy = _policy(
            _rule("r1", PolicyEffect.ALLOW, servers=[]),
        )
        engine = PolicyEngine(policy)

        result = engine.evaluate(_input())
        assert result.effect == PolicyEffect.DENY


# ---------------------------------------------------------------------------
# Tool matching
# ---------------------------------------------------------------------------


class TestToolMatching:
    def test_exact_tool_match(self):
        policy = _policy(
            _rule("r1", PolicyEffect.ALLOW, servers=[_server("api", ["read_file"])]),
        )
        engine = PolicyEngine(policy)

        assert engine.evaluate(_input(tool="read_file")).effect == PolicyEffect.ALLOW
        assert engine.evaluate(_input(tool="write_file")).effect == PolicyEffect.DENY

    def test_wildcard_tool(self):
        policy = _policy(
            _rule("r1", PolicyEffect.ALLOW, servers=[_server("api", ["*"])]),
        )
        engine = PolicyEngine(policy)

        assert engine.evaluate(_input(tool="anything")).effect == PolicyEffect.ALLOW

    def test_prefix_tool_wildcard(self):
        policy = _policy(
            _rule("r1", PolicyEffect.ALLOW, servers=[_server("api", ["read_*"])]),
        )
        engine = PolicyEngine(policy)

        assert engine.evaluate(_input(tool="read_file")).effect == PolicyEffect.ALLOW
        assert engine.evaluate(_input(tool="read_config")).effect == PolicyEffect.ALLOW
        assert engine.evaluate(_input(tool="write_file")).effect == PolicyEffect.DENY

    def test_suffix_tool_wildcard(self):
        policy = _policy(
            _rule("r1", PolicyEffect.ALLOW, servers=[_server("api", ["*_file"])]),
        )
        engine = PolicyEngine(policy)

        assert engine.evaluate(_input(tool="read_file")).effect == PolicyEffect.ALLOW
        assert engine.evaluate(_input(tool="write_file")).effect == PolicyEffect.ALLOW
        assert engine.evaluate(_input(tool="list_configs")).effect == PolicyEffect.DENY

    def test_empty_tools_matches_all(self):
        """An empty tools list on a server entry matches any tool."""
        policy = _policy(
            _rule("r1", PolicyEffect.ALLOW, servers=[_server("api")]),
        )
        engine = PolicyEngine(policy)

        assert engine.evaluate(_input(tool="anything")).effect == PolicyEffect.ALLOW

    def test_multiple_tool_patterns(self):
        policy = _policy(
            _rule(
                "r1",
                PolicyEffect.ALLOW,
                servers=[_server("api", ["read_file", "list_*"])],
            ),
        )
        engine = PolicyEngine(policy)

        assert engine.evaluate(_input(tool="read_file")).effect == PolicyEffect.ALLOW
        assert engine.evaluate(_input(tool="list_repos")).effect == PolicyEffect.ALLOW
        assert engine.evaluate(_input(tool="delete_file")).effect == PolicyEffect.DENY


# ---------------------------------------------------------------------------
# Deny overrides allow
# ---------------------------------------------------------------------------


class TestDenyOverridesAllow:
    def test_deny_after_allow(self):
        """A deny rule overrides an earlier allow rule."""
        policy = _policy(
            _rule("allow-all", PolicyEffect.ALLOW, servers=[_server("api", ["*"])]),
            _rule("deny-delete", PolicyEffect.DENY, servers=[_server("api", ["delete_*"])]),
        )
        engine = PolicyEngine(policy)

        # Allowed tool → allow (deny rule doesn't match this tool)
        result = engine.evaluate(_input(tool="read_file"))
        assert result.effect == PolicyEffect.ALLOW
        assert result.policy_id == "allow-all"

        # Denied tool → deny (deny rule overrides the allow)
        result = engine.evaluate(_input(tool="delete_record"))
        assert result.effect == PolicyEffect.DENY
        assert result.policy_id == "deny-delete"

    def test_deny_before_allow(self):
        """A deny rule placed before allow still denies."""
        policy = _policy(
            _rule("deny-delete", PolicyEffect.DENY, servers=[_server("api", ["delete_*"])]),
            _rule("allow-all", PolicyEffect.ALLOW, servers=[_server("api", ["*"])]),
        )
        engine = PolicyEngine(policy)

        result = engine.evaluate(_input(tool="delete_record"))
        assert result.effect == PolicyEffect.DENY
        assert result.policy_id == "deny-delete"

    def test_deny_wins_even_with_multiple_allows(self):
        policy = _policy(
            _rule("allow-1", PolicyEffect.ALLOW, servers=[_server("api", ["*"])]),
            _rule("allow-2", PolicyEffect.ALLOW, servers=[_server("api", ["*"])]),
            _rule("deny-1", PolicyEffect.DENY, servers=[_server("api", ["*"])]),
        )
        engine = PolicyEngine(policy)

        result = engine.evaluate(_input())
        assert result.effect == PolicyEffect.DENY
        assert result.policy_id == "deny-1"


# ---------------------------------------------------------------------------
# First-match-wins (among allows)
# ---------------------------------------------------------------------------


class TestFirstMatchWins:
    def test_first_allow_is_used(self):
        """When multiple allow rules match, the first one determines the policy_id."""
        policy = _policy(
            _rule("first", PolicyEffect.ALLOW, servers=[_server("api", ["*"])]),
            _rule("second", PolicyEffect.ALLOW, servers=[_server("api", ["*"])]),
        )
        engine = PolicyEngine(policy)

        result = engine.evaluate(_input())
        assert result.effect == PolicyEffect.ALLOW
        assert result.policy_id == "first"

    def test_first_deny_is_used(self):
        """When multiple deny rules match, the first one determines the policy_id."""
        policy = _policy(
            _rule("first-deny", PolicyEffect.DENY, servers=[_server("api", ["*"])]),
            _rule("second-deny", PolicyEffect.DENY, servers=[_server("api", ["*"])]),
        )
        engine = PolicyEngine(policy)

        result = engine.evaluate(_input())
        assert result.effect == PolicyEffect.DENY
        assert result.policy_id == "first-deny"


# ---------------------------------------------------------------------------
# Default behavior
# ---------------------------------------------------------------------------


class TestDefaultBehavior:
    def test_default_deny(self):
        """No matching rules + default deny → deny."""
        policy = _policy(
            _rule(
                "r1", PolicyEffect.ALLOW, users=["other@corp.com"], servers=[_server("api", ["*"])]
            ),
            default=PolicyEffect.DENY,
        )
        engine = PolicyEngine(policy)

        result = engine.evaluate(_input(user_id="unmatched@corp.com"))
        assert result.effect == PolicyEffect.DENY
        assert result.policy_id is None
        assert result.reason == "No matching policy; default is deny"

    def test_default_allow(self):
        """No matching rules + default allow → allow."""
        policy = _policy(
            _rule(
                "r1", PolicyEffect.DENY, users=["blocked@corp.com"], servers=[_server("api", ["*"])]
            ),
            default=PolicyEffect.ALLOW,
        )
        engine = PolicyEngine(policy)

        result = engine.evaluate(_input(user_id="unmatched@corp.com"))
        assert result.effect == PolicyEffect.ALLOW
        assert result.policy_id is None
        assert result.reason is None

    def test_no_rules_uses_default(self):
        """An empty policy uses the default."""
        policy = _policy(default=PolicyEffect.DENY)
        engine = PolicyEngine(policy)

        result = engine.evaluate(_input())
        assert result.effect == PolicyEffect.DENY
        assert result.reason == "No matching policy; default is deny"


# ---------------------------------------------------------------------------
# Error handling (fail closed)
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_evaluation_error_produces_deny(self):
        """Any exception during evaluation results in deny."""
        policy = _policy(
            _rule("r1", PolicyEffect.ALLOW, servers=[_server("api", ["*"])]),
        )
        engine = PolicyEngine(policy)

        with patch.object(
            PolicyEngine,
            "_evaluate_rules",
            side_effect=RuntimeError("unexpected error"),
        ):
            result = engine.evaluate(_input())

        assert result.effect == PolicyEffect.DENY
        assert result.policy_id is None
        assert "Evaluation error" in result.reason
        assert "unexpected error" in result.reason

    def test_broken_rule_matching_produces_deny(self):
        """If rule matching raises an unexpected error, fail closed."""
        policy = _policy(
            _rule("r1", PolicyEffect.ALLOW, servers=[_server("api", ["*"])]),
        )
        engine = PolicyEngine(policy)

        with patch.object(
            PolicyEngine,
            "_rule_matches",
            side_effect=TypeError("unexpected"),
        ):
            result = engine.evaluate(_input())

        assert result.effect == PolicyEffect.DENY
        assert "Evaluation error" in result.reason


# ---------------------------------------------------------------------------
# Complex / integration scenarios
# ---------------------------------------------------------------------------


class TestComplexScenarios:
    def test_full_policy_scenario(self):
        """Mimics the policy schema example from docs."""
        policy = _policy(
            # Platform ops can use internal tools
            _rule(
                "allow-platform-ops",
                PolicyEffect.ALLOW,
                groups=["platform-ops", "sre"],
                servers=[
                    _server("internal-infra-mcp", ["read_logs", "query_metrics", "restart_service"])
                ],
            ),
            # Developers get read-only external access
            _rule(
                "allow-dev-readonly",
                PolicyEffect.ALLOW,
                groups=["developers"],
                servers=[
                    _server("github-mcp", ["list_repos", "read_issues", "read_pull_requests"])
                ],
            ),
            # Deny destructive tools on all servers for everyone
            _rule(
                "deny-destructive",
                PolicyEffect.DENY,
                groups=["*"],
                servers=[_server("*", ["delete_*", "write_*"])],
            ),
        )
        engine = PolicyEngine(policy)

        # SRE reading logs → allowed
        result = engine.evaluate(
            _input(
                user_id="sre1", groups=["sre"], mcp_server="internal-infra-mcp", tool="read_logs"
            )
        )
        assert result.effect == PolicyEffect.ALLOW
        assert result.policy_id == "allow-platform-ops"

        # Developer reading issues → allowed
        result = engine.evaluate(
            _input(
                user_id="dev1", groups=["developers"], mcp_server="github-mcp", tool="read_issues"
            )
        )
        assert result.effect == PolicyEffect.ALLOW
        assert result.policy_id == "allow-dev-readonly"

        # Developer trying to delete → denied (deny-destructive overrides)
        result = engine.evaluate(
            _input(
                user_id="dev1", groups=["developers"], mcp_server="github-mcp", tool="delete_repo"
            )
        )
        assert result.effect == PolicyEffect.DENY
        assert result.policy_id == "deny-destructive"

        # SRE trying to write → denied (deny-destructive overrides)
        result = engine.evaluate(
            _input(
                user_id="sre1", groups=["sre"], mcp_server="internal-infra-mcp", tool="write_config"
            )
        )
        assert result.effect == PolicyEffect.DENY
        assert result.policy_id == "deny-destructive"

        # Unknown user, unmatched server → default deny
        result = engine.evaluate(
            _input(user_id="visitor", groups=[], mcp_server="unknown-server", tool="some_tool")
        )
        assert result.effect == PolicyEffect.DENY
        assert result.policy_id is None

    def test_user_in_multiple_groups(self):
        """User matching multiple group-based rules — first allow wins, deny overrides."""
        policy = _policy(
            _rule(
                "allow-devs",
                PolicyEffect.ALLOW,
                groups=["developers"],
                servers=[_server("api", ["read_*"])],
            ),
            _rule(
                "allow-ops",
                PolicyEffect.ALLOW,
                groups=["ops"],
                servers=[_server("api", ["deploy_*"])],
            ),
        )
        engine = PolicyEngine(policy)

        # User in both groups — first matching allow wins
        result = engine.evaluate(
            _input(groups=["developers", "ops"], mcp_server="api", tool="read_config")
        )
        assert result.effect == PolicyEffect.ALLOW
        assert result.policy_id == "allow-devs"

        # Same user, different tool — second rule matches
        result = engine.evaluate(
            _input(groups=["developers", "ops"], mcp_server="api", tool="deploy_app")
        )
        assert result.effect == PolicyEffect.ALLOW
        assert result.policy_id == "allow-ops"

    def test_server_specific_deny_does_not_affect_other_servers(self):
        """A deny on one server doesn't block access to another."""
        policy = _policy(
            _rule(
                "deny-external",
                PolicyEffect.DENY,
                servers=[_server("external-api", ["*"])],
            ),
            _rule(
                "allow-internal",
                PolicyEffect.ALLOW,
                servers=[_server("internal-api", ["*"])],
            ),
        )
        engine = PolicyEngine(policy)

        result = engine.evaluate(_input(mcp_server="internal-api"))
        assert result.effect == PolicyEffect.ALLOW

        result = engine.evaluate(_input(mcp_server="external-api"))
        assert result.effect == PolicyEffect.DENY


# ---------------------------------------------------------------------------
# Data class tests
# ---------------------------------------------------------------------------


class TestDataClasses:
    def test_policy_input_defaults(self):
        pi = PolicyInput(user_id="alice")
        assert pi.user_id == "alice"
        assert pi.groups == []
        assert pi.mcp_server == ""
        assert pi.tool == ""

    def test_policy_input_frozen(self):
        pi = PolicyInput(user_id="alice")
        with pytest.raises(AttributeError):
            pi.user_id = "bob"

    def test_evaluation_result_defaults(self):
        r = EvaluationResult(effect=PolicyEffect.ALLOW)
        assert r.effect == PolicyEffect.ALLOW
        assert r.policy_id is None
        assert r.reason is None

    def test_evaluation_result_frozen(self):
        r = EvaluationResult(effect=PolicyEffect.DENY, policy_id="r1", reason="blocked")
        with pytest.raises(AttributeError):
            r.effect = PolicyEffect.ALLOW
