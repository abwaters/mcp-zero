"""Tests for the OBO auth provider."""

from __future__ import annotations

from unittest.mock import AsyncMock

import jwt as pyjwt
import pytest

from mcp_zero.context import RequestContext, UserIdentity
from mcp_zero.identity.errors import TokenExchangeError
from mcp_zero.proxy.obo_auth import OBOAuthProvider, ServerOBOSettings


def _make_raw_token(jti: str = "jti-123", sub: str = "user-1") -> str:
    """Create an unsigned JWT for testing (signature not checked by OBOAuthProvider)."""
    return pyjwt.encode({"jti": jti, "sub": sub}, key="secret", algorithm="HS256")


def _make_context(raw_token: str | None = None) -> RequestContext:
    return RequestContext(
        identity=UserIdentity(user_id="user-1"),
        raw_token=raw_token,
    )


def _make_settings(
    server_name: str = "weather",
    enabled: bool = True,
    target_audience: str = "api://weather",
    scopes: list[str] | None = None,
) -> ServerOBOSettings:
    return ServerOBOSettings(
        server_name=server_name,
        enabled=enabled,
        target_audience=target_audience,
        scopes=scopes or [],
    )


class TestOBOAuthProvider:
    @pytest.mark.asyncio
    async def test_exchange_enabled(self):
        obo_client = AsyncMock()
        obo_client.exchange_token = AsyncMock(return_value="token-B")

        settings = {"weather": _make_settings()}
        provider = OBOAuthProvider(obo_client, settings)

        raw_token = _make_raw_token()
        ctx = _make_context(raw_token=raw_token)
        result = await provider.get_token("weather", ctx)

        assert result == "token-B"
        obo_client.exchange_token.assert_called_once_with(
            subject_token=raw_token,
            subject_jti="jti-123",
            target_audience="api://weather",
            scopes=[],
        )

    @pytest.mark.asyncio
    async def test_exchange_disabled(self):
        obo_client = AsyncMock()
        settings = {"weather": _make_settings(enabled=False)}
        provider = OBOAuthProvider(obo_client, settings)

        ctx = _make_context(raw_token=_make_raw_token())
        result = await provider.get_token("weather", ctx)

        assert result is None
        obo_client.exchange_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_server_returns_none(self):
        obo_client = AsyncMock()
        provider = OBOAuthProvider(obo_client, {})

        ctx = _make_context(raw_token=_make_raw_token())
        result = await provider.get_token("unknown", ctx)

        assert result is None

    @pytest.mark.asyncio
    async def test_missing_raw_token_returns_none(self):
        obo_client = AsyncMock()
        settings = {"weather": _make_settings()}
        provider = OBOAuthProvider(obo_client, settings)

        ctx = _make_context(raw_token=None)
        result = await provider.get_token("weather", ctx)

        assert result is None
        obo_client.exchange_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_jti_uses_empty_string(self):
        obo_client = AsyncMock()
        obo_client.exchange_token = AsyncMock(return_value="token-B")

        settings = {"weather": _make_settings()}
        provider = OBOAuthProvider(obo_client, settings)

        # Token without jti claim
        raw_token = pyjwt.encode({"sub": "user-1"}, key="secret", algorithm="HS256")
        ctx = _make_context(raw_token=raw_token)
        await provider.get_token("weather", ctx)

        call_kwargs = obo_client.exchange_token.call_args[1]
        assert call_kwargs["subject_jti"] == ""

    @pytest.mark.asyncio
    async def test_exchange_error_propagates(self):
        obo_client = AsyncMock()
        obo_client.exchange_token = AsyncMock(
            side_effect=TokenExchangeError("exchange failed", audience="api://weather")
        )

        settings = {"weather": _make_settings()}
        provider = OBOAuthProvider(obo_client, settings)

        ctx = _make_context(raw_token=_make_raw_token())

        with pytest.raises(TokenExchangeError, match="exchange failed"):
            await provider.get_token("weather", ctx)

    @pytest.mark.asyncio
    async def test_scopes_passed_to_client(self):
        obo_client = AsyncMock()
        obo_client.exchange_token = AsyncMock(return_value="token-B")

        settings = {"weather": _make_settings(scopes=["read", "write"])}
        provider = OBOAuthProvider(obo_client, settings)

        ctx = _make_context(raw_token=_make_raw_token())
        await provider.get_token("weather", ctx)

        call_kwargs = obo_client.exchange_token.call_args[1]
        assert call_kwargs["scopes"] == ["read", "write"]
