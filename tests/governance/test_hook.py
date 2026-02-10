"""Tests for the GovernanceHook lifecycle hook."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcp_zero.context import HookContext, PolicyDecision, RequestContext, UserIdentity
from mcp_zero.governance.config import PolicyEffect
from mcp_zero.governance.engine import EvaluationResult, PolicyInput
from mcp_zero.governance.hook import GovernanceHook
from mcp_zero.pipeline.errors import ShortCircuitError


def _make_ctx(
    *,
    user_id: str = "user-1",
    groups: list[str] | None = None,
    server_name: str = "weather",
    tool_name: str = "get_forecast",
    identity: UserIdentity | None = ...,  # type: ignore[assignment]
) -> HookContext:
    if identity is ...:
        identity = UserIdentity(user_id=user_id, groups=groups or [])
    return HookContext(
        request=RequestContext(identity=identity),
        server_name=server_name,
        tool_name=tool_name,
    )


class TestGovernanceHookAllow:
    @pytest.mark.asyncio
    async def test_allow_sets_policy_decision(self):
        engine = MagicMock()
        engine.evaluate.return_value = EvaluationResult(
            effect=PolicyEffect.ALLOW, policy_id="rule-1"
        )

        hook = GovernanceHook(engine)
        ctx = _make_ctx()
        result = await hook.on_post_validation(ctx)

        assert result.policy_decision == PolicyDecision.ALLOW
        assert result.policy_rule_id == "rule-1"

    @pytest.mark.asyncio
    async def test_allow_none_policy_id_becomes_empty_string(self):
        engine = MagicMock()
        engine.evaluate.return_value = EvaluationResult(effect=PolicyEffect.ALLOW, policy_id=None)

        hook = GovernanceHook(engine)
        ctx = _make_ctx()
        result = await hook.on_post_validation(ctx)

        assert result.policy_decision == PolicyDecision.ALLOW
        assert result.policy_rule_id == ""

    @pytest.mark.asyncio
    async def test_correct_policy_input_passed_to_engine(self):
        engine = MagicMock()
        engine.evaluate.return_value = EvaluationResult(
            effect=PolicyEffect.ALLOW, policy_id="rule-1"
        )

        hook = GovernanceHook(engine)
        ctx = _make_ctx(
            user_id="alice", groups=["admin", "dev"], server_name="db", tool_name="query"
        )
        await hook.on_post_validation(ctx)

        engine.evaluate.assert_called_once()
        policy_input: PolicyInput = engine.evaluate.call_args[0][0]
        assert policy_input.user_id == "alice"
        assert policy_input.groups == ["admin", "dev"]
        assert policy_input.mcp_server == "db"
        assert policy_input.tool == "query"


class TestGovernanceHookDeny:
    @pytest.mark.asyncio
    async def test_deny_raises_short_circuit(self):
        engine = MagicMock()
        engine.evaluate.return_value = EvaluationResult(
            effect=PolicyEffect.DENY, policy_id="deny-rule", reason="Blocked by admin policy"
        )

        hook = GovernanceHook(engine)
        ctx = _make_ctx()

        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_post_validation(ctx)
        assert exc_info.value.deny is True
        assert "Blocked by admin policy" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_deny_fallback_reason_when_none(self):
        engine = MagicMock()
        engine.evaluate.return_value = EvaluationResult(
            effect=PolicyEffect.DENY, policy_id="deny-rule", reason=None
        )

        hook = GovernanceHook(engine)
        ctx = _make_ctx()

        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_post_validation(ctx)
        assert exc_info.value.deny is True
        assert exc_info.value.reason == "Denied by policy"

    @pytest.mark.asyncio
    async def test_default_deny_short_circuits(self):
        """Default-deny (no matching rule) still raises ShortCircuitError."""
        engine = MagicMock()
        engine.evaluate.return_value = EvaluationResult(
            effect=PolicyEffect.DENY,
            policy_id=None,
            reason="No matching policy; default is deny",
        )

        hook = GovernanceHook(engine)
        ctx = _make_ctx()

        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_post_validation(ctx)
        assert exc_info.value.deny is True


class TestGovernanceHookMissingIdentity:
    @pytest.mark.asyncio
    async def test_no_identity_denies(self):
        engine = MagicMock()
        hook = GovernanceHook(engine)
        ctx = _make_ctx(identity=None)

        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_post_validation(ctx)
        assert exc_info.value.deny is True
        assert "No authenticated identity" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_no_identity_skips_engine(self):
        engine = MagicMock()
        hook = GovernanceHook(engine)
        ctx = _make_ctx(identity=None)

        with pytest.raises(ShortCircuitError):
            await hook.on_post_validation(ctx)

        engine.evaluate.assert_not_called()


class TestGovernanceHookProperties:
    def test_hook_name(self):
        engine = MagicMock()
        hook = GovernanceHook(engine)
        assert hook.name == "GovernanceHook"

    @pytest.mark.asyncio
    async def test_correlation_id_preserved(self):
        engine = MagicMock()
        engine.evaluate.return_value = EvaluationResult(
            effect=PolicyEffect.ALLOW, policy_id="rule-1"
        )

        hook = GovernanceHook(engine)
        original_request = RequestContext(
            identity=UserIdentity(user_id="user-1"),
        )
        ctx = HookContext(
            request=original_request,
            server_name="weather",
            tool_name="get_forecast",
        )
        result = await hook.on_post_validation(ctx)

        assert result.request.correlation_id == original_request.correlation_id
        assert result.request.trace_id == original_request.trace_id
