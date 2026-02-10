"""Integration test: IdentityHook in a real Pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mcp_zero.context import HookContext, PolicyDecision, RequestContext
from mcp_zero.identity.hook import IdentityHook
from mcp_zero.identity.jwt import TokenClaims
from mcp_zero.pipeline import HookRegistry, Pipeline


class TestIdentityPipelineIntegration:
    @pytest.mark.asyncio
    async def test_unauthenticated_request_denied(self):
        """A request with no auth header is denied by the pipeline."""
        validator = AsyncMock()
        hook = IdentityHook(validator)

        registry = HookRegistry()
        registry.register(hook, priority=10)
        registry.build()
        pipeline = Pipeline(registry)

        ctx = HookContext(
            request=RequestContext(),
            server_name="test-server",
            tool_name="test-tool",
            extras={},
        )

        result = await pipeline.execute(ctx)

        assert not result.success
        assert result.context.policy_decision == PolicyDecision.DENY
        assert result.context.short_circuited is True

    @pytest.mark.asyncio
    async def test_authenticated_request_succeeds(self):
        """A request with a valid bearer token populates identity and succeeds."""
        validator = AsyncMock()
        validator.validate_token = AsyncMock(
            return_value=TokenClaims(
                user_id="user-42",
                email="user42@corp.com",
                groups=["engineering"],
                raw_claims={"sub": "user-42"},
            )
        )
        hook = IdentityHook(validator)

        registry = HookRegistry()
        registry.register(hook, priority=10)
        registry.build()
        pipeline = Pipeline(registry)

        ctx = HookContext(
            request=RequestContext(),
            server_name="test-server",
            tool_name="test-tool",
            extras={"authorization": "Bearer valid-token"},
        )

        result = await pipeline.execute(ctx)

        assert result.success
        assert result.context.request.identity is not None
        assert result.context.request.identity.user_id == "user-42"
        assert result.context.request.identity.email == "user42@corp.com"
        assert result.context.request.identity.groups == ["engineering"]
        assert result.context.policy_decision == PolicyDecision.PENDING

    @pytest.mark.asyncio
    async def test_hooks_executed_tracking(self):
        """Pipeline correctly tracks which hooks ran."""
        validator = AsyncMock()
        validator.validate_token = AsyncMock(return_value=TokenClaims(user_id="user-1"))
        hook = IdentityHook(validator)

        registry = HookRegistry()
        registry.register(hook, priority=10)
        registry.build()
        pipeline = Pipeline(registry)

        ctx = HookContext(
            request=RequestContext(),
            extras={"authorization": "Bearer token"},
        )

        result = await pipeline.execute(ctx)

        assert result.success
        assert "IdentityHook.on_pre_validation" in result.hooks_executed
