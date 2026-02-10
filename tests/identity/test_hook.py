"""Tests for the IdentityHook lifecycle hook."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mcp_zero.context import HookContext, RequestContext
from mcp_zero.identity.errors import JWKSFetchError, TokenValidationError
from mcp_zero.identity.hook import IdentityHook
from mcp_zero.identity.jwt import TokenClaims
from mcp_zero.pipeline.errors import ShortCircuitError


def _make_ctx(authorization: str = "") -> HookContext:
    return HookContext(
        request=RequestContext(),
        extras={"authorization": authorization},
    )


class TestIdentityHook:
    @pytest.mark.asyncio
    async def test_valid_auth_populates_context(self):
        validator = AsyncMock()
        validator.validate_token = AsyncMock(
            return_value=TokenClaims(
                user_id="user-123",
                email="user@example.com",
                groups=["admin"],
                raw_claims={"sub": "user-123"},
            )
        )

        hook = IdentityHook(validator)
        ctx = _make_ctx("Bearer valid-token-here")
        result = await hook.on_pre_validation(ctx)

        assert result.request.identity is not None
        assert result.request.identity.user_id == "user-123"
        assert result.request.identity.email == "user@example.com"
        assert result.request.identity.groups == ["admin"]
        validator.validate_token.assert_called_once_with("valid-token-here")

    @pytest.mark.asyncio
    async def test_missing_header_denied(self):
        validator = AsyncMock()
        hook = IdentityHook(validator)
        ctx = _make_ctx("")

        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_pre_validation(ctx)
        assert exc_info.value.deny is True
        assert "Missing" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_no_authorization_key_denied(self):
        validator = AsyncMock()
        hook = IdentityHook(validator)
        ctx = HookContext(request=RequestContext(), extras={})

        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_pre_validation(ctx)
        assert exc_info.value.deny is True

    @pytest.mark.asyncio
    async def test_malformed_header_not_bearer(self):
        validator = AsyncMock()
        hook = IdentityHook(validator)
        ctx = _make_ctx("Basic dXNlcjpwYXNz")

        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_pre_validation(ctx)
        assert exc_info.value.deny is True
        assert "Malformed" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_malformed_header_no_token(self):
        validator = AsyncMock()
        hook = IdentityHook(validator)
        ctx = _make_ctx("Bearer")

        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_pre_validation(ctx)
        assert exc_info.value.deny is True
        assert "Malformed" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_validation_failure_denied(self):
        validator = AsyncMock()
        validator.validate_token = AsyncMock(
            side_effect=TokenValidationError("bad token", reason="invalid_signature")
        )

        hook = IdentityHook(validator)
        ctx = _make_ctx("Bearer bad-token")

        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_pre_validation(ctx)
        assert exc_info.value.deny is True
        assert "Authentication failed" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_jwks_failure_denied(self):
        validator = AsyncMock()
        validator.validate_token = AsyncMock(
            side_effect=JWKSFetchError("timeout", issuer="https://okta.example.com")
        )

        hook = IdentityHook(validator)
        ctx = _make_ctx("Bearer some-token")

        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_pre_validation(ctx)
        assert exc_info.value.deny is True

    @pytest.mark.asyncio
    async def test_hook_name(self):
        validator = AsyncMock()
        hook = IdentityHook(validator)
        assert hook.name == "IdentityHook"

    @pytest.mark.asyncio
    async def test_correlation_id_preserved(self):
        validator = AsyncMock()
        validator.validate_token = AsyncMock(return_value=TokenClaims(user_id="user-1"))

        hook = IdentityHook(validator)
        original_request = RequestContext()
        ctx = HookContext(
            request=original_request,
            extras={"authorization": "Bearer token"},
        )
        result = await hook.on_pre_validation(ctx)

        assert result.request.correlation_id == original_request.correlation_id
        assert result.request.trace_id == original_request.trace_id
