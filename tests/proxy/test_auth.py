"""Tests for auth provider interface."""

import pytest

from mcp_zero.context import RequestContext
from mcp_zero.proxy.auth import AuthProvider, NoAuthProvider


class TestAuthProviderABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            AuthProvider()  # type: ignore[abstract]

    def test_subclass_must_implement_get_token(self):
        class Incomplete(AuthProvider):
            pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_concrete_subclass(self):
        class FakeAuth(AuthProvider):
            async def get_token(self, server_name: str, context: RequestContext) -> str | None:
                return f"token-for-{server_name}"

        provider = FakeAuth()
        assert isinstance(provider, AuthProvider)


class TestNoAuthProvider:
    @pytest.mark.asyncio
    async def test_returns_none(self):
        provider = NoAuthProvider()
        ctx = RequestContext()
        result = await provider.get_token("any-server", ctx)
        assert result is None

    def test_inherits_auth_provider(self):
        assert issubclass(NoAuthProvider, AuthProvider)
