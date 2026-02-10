"""Policy evaluation engine.

Evaluates governance policy rules against a request to produce an allow/deny
decision.  Rules are evaluated top-down (file order matters), with explicit deny
overriding allow regardless of position.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from mcp_zero.governance.config import (
    PolicyConfig,
    PolicyEffect,
    PolicyRule,
    PolicyServerAccess,
    PolicySubjects,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input / Output data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyInput:
    """Input for policy evaluation.

    Args:
        user_id: Authenticated user identifier.
        groups: Group memberships resolved from the identity token.
        mcp_server: Target MCP server name.
        tool: Tool being invoked.
    """

    user_id: str
    groups: list[str] = field(default_factory=list)
    mcp_server: str = ""
    tool: str = ""


@dataclass(frozen=True)
class EvaluationResult:
    """Result of a policy evaluation.

    Args:
        effect: The decision — ``allow`` or ``deny``.
        policy_id: ID of the policy rule that matched (``None`` when defaulting).
        reason: Human-readable reason (populated on deny or error).
    """

    effect: PolicyEffect
    policy_id: str | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Pattern matching helpers
# ---------------------------------------------------------------------------


def _matches_pattern(pattern: str, value: str) -> bool:
    """Match *value* against a wildcard *pattern*.

    Supported patterns:
    - ``*`` — matches everything.
    - ``prefix*`` — matches values starting with *prefix*.
    - ``*suffix`` — matches values ending with *suffix*.
    - Otherwise — exact match.
    """
    if pattern == "*":
        return True
    if pattern.endswith("*"):
        return value.startswith(pattern[:-1])
    if pattern.startswith("*"):
        return value.endswith(pattern[1:])
    return pattern == value


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class PolicyEngine:
    """Evaluates loaded policy rules against a request.

    Evaluation semantics:

    1. Rules are scanned top-down in file order.
    2. A rule *matches* when both its **subjects** and at least one of its
       **mcp_servers** entries match the input.
    3. **Deny overrides allow**: if *any* matching rule has effect ``deny``,
       the request is denied — regardless of whether an ``allow`` rule also
       matches or appears earlier in the file.
    4. If only ``allow`` rules match, the first one determines the decision.
    5. When no rule matches, the policy-level ``default`` effect is used.
    6. Any exception during evaluation results in a ``deny`` (fail closed).
    """

    def __init__(self, policy: PolicyConfig) -> None:
        self._policy = policy

    def evaluate(self, policy_input: PolicyInput) -> EvaluationResult:
        """Evaluate the loaded policy against *policy_input*.

        Returns an :class:`EvaluationResult` that is always ``allow`` or
        ``deny`` — never an error enum.  Errors are surfaced as ``deny``
        with a descriptive *reason* (fail-closed).
        """
        try:
            return self._evaluate_rules(policy_input)
        except Exception as exc:
            logger.exception("Policy evaluation error (fail closed)")
            return EvaluationResult(
                effect=PolicyEffect.DENY,
                reason=f"Evaluation error: {exc}",
            )

    # ------------------------------------------------------------------
    # Internal evaluation
    # ------------------------------------------------------------------

    def _evaluate_rules(self, policy_input: PolicyInput) -> EvaluationResult:
        first_allow: PolicyRule | None = None
        first_deny: PolicyRule | None = None

        for rule in self._policy.policies:
            if not self._rule_matches(rule, policy_input):
                continue

            if rule.effect == PolicyEffect.DENY and first_deny is None:
                first_deny = rule
            elif rule.effect == PolicyEffect.ALLOW and first_allow is None:
                first_allow = rule

        # Deny overrides allow
        if first_deny is not None:
            return EvaluationResult(
                effect=PolicyEffect.DENY,
                policy_id=first_deny.id,
                reason=first_deny.description,
            )

        if first_allow is not None:
            return EvaluationResult(
                effect=PolicyEffect.ALLOW,
                policy_id=first_allow.id,
            )

        # No matching rule — fall back to the policy default
        default = self._policy.default
        reason = "No matching policy; default is deny" if default == PolicyEffect.DENY else None
        return EvaluationResult(effect=default, reason=reason)

    # ------------------------------------------------------------------
    # Matching helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _rule_matches(rule: PolicyRule, policy_input: PolicyInput) -> bool:
        """A rule matches when subjects AND at least one server/tool entry match."""
        if not PolicyEngine._subjects_match(rule.subjects, policy_input):
            return False
        return PolicyEngine._servers_match(rule.mcp_servers, policy_input)

    @staticmethod
    def _subjects_match(subjects: PolicySubjects, policy_input: PolicyInput) -> bool:
        """Check whether *policy_input* satisfies the rule's subject constraints.

        An empty/missing subjects field (no users, no groups) is treated as
        matching everyone — this allows blanket rules without enumerating
        subjects.
        """
        if not subjects.users and not subjects.groups:
            return True

        # Direct user match
        if policy_input.user_id in subjects.users:
            return True

        # Group intersection (including wildcard ``*``)
        if "*" in subjects.groups:
            return True
        if set(policy_input.groups) & set(subjects.groups):
            return True

        return False

    @staticmethod
    def _servers_match(mcp_servers: list[PolicyServerAccess], policy_input: PolicyInput) -> bool:
        """Check whether any server access entry matches the input."""
        for access in mcp_servers:
            if _matches_pattern(access.name, policy_input.mcp_server):
                if PolicyEngine._tools_match(access.tools, policy_input.tool):
                    return True
        return False

    @staticmethod
    def _tools_match(tool_patterns: list[str], tool_name: str) -> bool:
        """Check whether *tool_name* matches any of the *tool_patterns*.

        An empty patterns list is treated as matching all tools for that
        server entry.
        """
        if not tool_patterns:
            return True
        return any(_matches_pattern(p, tool_name) for p in tool_patterns)
