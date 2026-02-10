"""Tests for the OBO token exchange client."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mcp_zero.identity.errors import TokenExchangeError
from mcp_zero.identity.obo import (
    ExchangeCacheKey,
    ExchangedToken,
    OBOClient,
    OBOConfig,
)


def make_config(**overrides) -> OBOConfig:
    defaults = {
        "token_endpoint": "https://okta.example.com/oauth2/token",
        "client_id": "gateway-client",
        "client_secret": "gateway-secret",
        "cache_ttl": 60,
    }
    defaults.update(overrides)
    return OBOConfig(**defaults)


def make_exchange_response(
    access_token: str = "exchanged-token",
    token_type: str = "Bearer",
    expires_in: int = 3600,
    scope: str = "read",
) -> httpx.Response:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {
        "access_token": access_token,
        "token_type": token_type,
        "expires_in": expires_in,
        "scope": scope,
    }
    return resp


class TestOBOConfig:
    def test_valid(self):
        cfg = make_config()
        assert cfg.token_endpoint == "https://okta.example.com/oauth2/token"
        assert cfg.cache_ttl == 60

    def test_missing_endpoint(self):
        with pytest.raises(ValueError, match="token_endpoint"):
            OBOConfig(token_endpoint="", client_id="x", client_secret="y")

    def test_missing_client_id(self):
        with pytest.raises(ValueError, match="client_id"):
            OBOConfig(token_endpoint="https://x", client_id="", client_secret="y")

    def test_missing_client_secret(self):
        with pytest.raises(ValueError, match="client_secret"):
            OBOConfig(token_endpoint="https://x", client_id="x", client_secret="")


class TestExchangedToken:
    def test_not_expired(self):
        token = ExchangedToken(access_token="t", token_type="Bearer", expires_in=3600, scope="")
        assert token.is_expired(ttl=60) is False

    def test_expired(self):
        token = ExchangedToken(
            access_token="t",
            token_type="Bearer",
            expires_in=100,
            scope="",
            issued_at=0.0,  # long ago in monotonic time
        )
        assert token.is_expired(ttl=60) is True


class TestExchangeCacheKey:
    def test_from_params_sorts_scopes(self):
        key = ExchangeCacheKey.from_params("jti-1", "api://server", ["write", "read"])
        assert key.scopes == ("read", "write")

    def test_equality(self):
        a = ExchangeCacheKey.from_params("jti-1", "api://server", ["read"])
        b = ExchangeCacheKey.from_params("jti-1", "api://server", ["read"])
        assert a == b

    def test_hashable(self):
        key = ExchangeCacheKey.from_params("jti-1", "api://server", ["read"])
        d = {key: "value"}
        assert d[key] == "value"


class TestOBOClient:
    @pytest.mark.asyncio
    async def test_successful_exchange(self):
        config = make_config()
        client = OBOClient(config)

        mock_response = make_exchange_response(access_token="token-B")

        with patch("mcp_zero.identity.obo.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await client.exchange_token(
                subject_token="token-A",
                subject_jti="jti-123",
                target_audience="api://mcp-server",
                scopes=["read"],
            )

        assert result == "token-B"
        mock_http.post.assert_called_once()
        call_kwargs = mock_http.post.call_args
        assert call_kwargs[0][0] == config.token_endpoint
        assert call_kwargs[1]["data"]["subject_token"] == "token-A"
        assert call_kwargs[1]["data"]["audience"] == "api://mcp-server"
        assert call_kwargs[1]["auth"] == (config.client_id, config.client_secret)

    @pytest.mark.asyncio
    async def test_cache_hit_no_http_call(self):
        config = make_config()
        client = OBOClient(config)

        mock_response = make_exchange_response()

        with patch("mcp_zero.identity.obo.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            # First call — hits the endpoint
            await client.exchange_token("token-A", "jti-1", "api://server")
            # Second call — should use cache
            result = await client.exchange_token("token-A", "jti-1", "api://server")

        assert result == "exchanged-token"
        assert mock_http.post.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_expired_refetches(self):
        config = make_config(cache_ttl=60)
        client = OBOClient(config)

        # Pre-populate cache with an expired token
        key = ExchangeCacheKey.from_params("jti-1", "api://server", [])
        client._cache[key] = ExchangedToken(
            access_token="old-token",
            token_type="Bearer",
            expires_in=100,
            scope="",
            issued_at=0.0,
        )

        mock_response = make_exchange_response(access_token="new-token")

        with patch("mcp_zero.identity.obo.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await client.exchange_token("token-A", "jti-1", "api://server")

        assert result == "new-token"

    @pytest.mark.asyncio
    async def test_concurrent_exchange_single_http_call(self):
        config = make_config()
        client = OBOClient(config)

        call_count = {"n": 0}

        async def slow_post(*args, **kwargs):
            call_count["n"] += 1
            await asyncio.sleep(0.05)
            return make_exchange_response()

        with patch("mcp_zero.identity.obo.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(side_effect=slow_post)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            results = await asyncio.gather(
                client.exchange_token("token-A", "jti-1", "api://server"),
                client.exchange_token("token-A", "jti-1", "api://server"),
                client.exchange_token("token-A", "jti-1", "api://server"),
            )

        assert all(r == "exchanged-token" for r in results)
        assert call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_http_400_raises(self):
        config = make_config()
        client = OBOClient(config)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.text = "invalid_grant"

        with patch("mcp_zero.identity.obo.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(TokenExchangeError, match="HTTP 400"):
                await client.exchange_token("token-A", "jti-1", "api://server")

    @pytest.mark.asyncio
    async def test_http_401_raises(self):
        config = make_config()
        client = OBOClient(config)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.text = "unauthorized"

        with patch("mcp_zero.identity.obo.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(TokenExchangeError, match="HTTP 401"):
                await client.exchange_token("token-A", "jti-1", "api://server")

    @pytest.mark.asyncio
    async def test_http_500_raises(self):
        config = make_config()
        client = OBOClient(config)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.text = "internal error"

        with patch("mcp_zero.identity.obo.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(TokenExchangeError, match="HTTP 500"):
                await client.exchange_token("token-A", "jti-1", "api://server")

    @pytest.mark.asyncio
    async def test_missing_access_token_raises(self):
        config = make_config()
        client = OBOClient(config)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"token_type": "Bearer"}

        with patch("mcp_zero.identity.obo.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(TokenExchangeError, match="missing 'access_token'"):
                await client.exchange_token("token-A", "jti-1", "api://server")

    @pytest.mark.asyncio
    async def test_network_error_raises(self):
        config = make_config()
        client = OBOClient(config)

        with patch("mcp_zero.identity.obo.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(side_effect=httpx.ConnectError("timeout"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(TokenExchangeError, match="request failed"):
                await client.exchange_token("token-A", "jti-1", "api://server")

    @pytest.mark.asyncio
    async def test_scopes_included_in_post(self):
        config = make_config()
        client = OBOClient(config)

        mock_response = make_exchange_response()

        with patch("mcp_zero.identity.obo.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await client.exchange_token(
                "token-A", "jti-1", "api://server", scopes=["read", "write"]
            )

        call_data = mock_http.post.call_args[1]["data"]
        assert call_data["scope"] == "read write"

    @pytest.mark.asyncio
    async def test_no_scopes_omitted_from_post(self):
        config = make_config()
        client = OBOClient(config)

        mock_response = make_exchange_response()

        with patch("mcp_zero.identity.obo.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await client.exchange_token("token-A", "jti-1", "api://server")

        call_data = mock_http.post.call_args[1]["data"]
        assert "scope" not in call_data
