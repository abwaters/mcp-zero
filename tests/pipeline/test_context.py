"""Tests for HookContext and PolicyDecision."""

import time

import pytest

from mcp_zero.context import HookContext, PolicyDecision, RequestContext, UserIdentity


class TestPolicyDecision:
    def test_values(self):
        assert PolicyDecision.PENDING == "pending"
        assert PolicyDecision.ALLOW == "allow"
        assert PolicyDecision.DENY == "deny"

    def test_from_string(self):
        assert PolicyDecision("pending") is PolicyDecision.PENDING
        assert PolicyDecision("allow") is PolicyDecision.ALLOW
        assert PolicyDecision("deny") is PolicyDecision.DENY

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            PolicyDecision("invalid")


class TestHookContext:
    def test_defaults(self):
        ctx = HookContext()
        assert isinstance(ctx.request, RequestContext)
        assert ctx.request_payload == {}
        assert ctx.response_payload == {}
        assert ctx.server_name == ""
        assert ctx.tool_name == ""
        assert ctx.policy_decision == PolicyDecision.PENDING
        assert ctx.policy_rule_id == ""
        assert ctx.masking_applied is False
        assert ctx.masked_fields == []
        assert ctx.short_circuited is False
        assert ctx.short_circuit_reason == ""
        assert ctx.started_at > 0
        assert ctx.extras == {}

    def test_custom_values(self):
        req = RequestContext(identity=UserIdentity(user_id="u1"))
        ctx = HookContext(
            request=req,
            server_name="my-server",
            tool_name="my-tool",
            policy_decision=PolicyDecision.ALLOW,
        )
        assert ctx.request.identity.user_id == "u1"
        assert ctx.server_name == "my-server"
        assert ctx.tool_name == "my-tool"
        assert ctx.policy_decision == PolicyDecision.ALLOW

    def test_frozen(self):
        ctx = HookContext()
        with pytest.raises(AttributeError):
            ctx.server_name = "other"  # type: ignore[misc]

    def test_evolve_returns_new_instance(self):
        ctx = HookContext(server_name="a")
        ctx2 = ctx.evolve(server_name="b")
        assert ctx.server_name == "a"
        assert ctx2.server_name == "b"
        assert ctx is not ctx2

    def test_evolve_preserves_unchanged_fields(self):
        ctx = HookContext(server_name="a", tool_name="t1")
        ctx2 = ctx.evolve(server_name="b")
        assert ctx2.tool_name == "t1"

    def test_evolve_policy_decision(self):
        ctx = HookContext()
        ctx2 = ctx.evolve(policy_decision=PolicyDecision.DENY)
        assert ctx2.policy_decision == PolicyDecision.DENY
        assert ctx.policy_decision == PolicyDecision.PENDING

    def test_evolve_masking_fields(self):
        ctx = HookContext()
        ctx2 = ctx.evolve(masking_applied=True, masked_fields=["email", "ssn"])
        assert ctx2.masking_applied is True
        assert ctx2.masked_fields == ["email", "ssn"]

    def test_masking_stage_completed_default(self):
        ctx = HookContext()
        assert ctx.masking_stage_completed is False

    def test_evolve_masking_stage_completed(self):
        ctx = HookContext()
        ctx2 = ctx.evolve(masking_stage_completed=True)
        assert ctx2.masking_stage_completed is True
        assert ctx.masking_stage_completed is False

    def test_evolve_short_circuit(self):
        ctx = HookContext()
        ctx2 = ctx.evolve(short_circuited=True, short_circuit_reason="denied")
        assert ctx2.short_circuited is True
        assert ctx2.short_circuit_reason == "denied"

    def test_extras_dict(self):
        ctx = HookContext(extras={"custom_key": "custom_value"})
        assert ctx.extras["custom_key"] == "custom_value"

    def test_correlation_id_propagated(self):
        req = RequestContext(correlation_id="abc-123")
        ctx = HookContext(request=req)
        assert ctx.request.correlation_id == "abc-123"

    def test_started_at_is_monotonic(self):
        before = time.monotonic()
        ctx = HookContext()
        after = time.monotonic()
        assert before <= ctx.started_at <= after

    def test_evolve_extras(self):
        ctx = HookContext(extras={"a": 1})
        ctx2 = ctx.evolve(extras={"a": 1, "b": 2})
        assert ctx.extras == {"a": 1}
        assert ctx2.extras == {"a": 1, "b": 2}

    def test_request_payload(self):
        ctx = HookContext(request_payload={"method": "tools/call", "params": {}})
        assert ctx.request_payload["method"] == "tools/call"

    def test_response_payload(self):
        ctx = HookContext(response_payload={"result": "ok"})
        assert ctx.response_payload["result"] == "ok"
