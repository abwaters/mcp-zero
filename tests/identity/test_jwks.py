"""Tests for the JWKS client with async caching."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mcp_zero.identity.config import IdentityConfig
from mcp_zero.identity.errors import JWKSFetchError
from mcp_zero.identity.jwks import JWKSClient

# Minimal RSA public key JWK for testing
_TEST_JWK = {
    "kty": "RSA",
    "kid": "test-key-1",
    "use": "sig",
    "n": (
        "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM78LhWx4cbbfAAtVT86zwu1RK7aPFFxuhD"
        "R1L6tSoc_BJECPebWKRXjBZCiFV4n3oknjhMstn64tZ_2W-5JsGY4Hc5n9yBXArwl93lqt7_RN5w6C"
        "f0h4QyQ5v-65YGjQR0_FDW2QvzqY368QQMicAtaSqzs8KJZgnYb9c7d0zgdAZHzu6qMQvRL5hajrn1"
        "n91CbOpbISD08qNLyrdkt-bFTWhAI4vMQFh6WeZu0fM4lFd2NcRwr3XPksINHaQ-G_xBniIqbw0Ls1"
        "jF44-csFCur-kEgU8awapJzKnqDKgw"
    ),
    "e": "AQAB",
    "alg": "RS256",
}


def _make_config(**overrides):
    defaults = {"issuer": "https://okta.example.com", "audience": "my-app"}
    defaults.update(overrides)
    return IdentityConfig(**defaults)


def _mock_response(json_data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


class TestJWKSClient:
    @pytest.mark.asyncio
    async def test_discovery_and_fetch(self):
        config = _make_config()
        client = JWKSClient(config)

        discovery_resp = _mock_response({"jwks_uri": "https://okta.example.com/v1/keys"})
        jwks_resp = _mock_response({"keys": [_TEST_JWK]})

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=[discovery_resp, jwks_resp])

        with patch("mcp_zero.identity.jwks.httpx.AsyncClient", return_value=mock_http):
            keys = await client.get_signing_keys()

        assert len(keys) == 1
        assert keys[0].key_id == "test-key-1"

    @pytest.mark.asyncio
    async def test_cache_hit_skips_fetch(self):
        config = _make_config()
        client = JWKSClient(config)

        discovery_resp = _mock_response({"jwks_uri": "https://okta.example.com/v1/keys"})
        jwks_resp = _mock_response({"keys": [_TEST_JWK]})

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=[discovery_resp, jwks_resp])

        with patch("mcp_zero.identity.jwks.httpx.AsyncClient", return_value=mock_http):
            keys1 = await client.get_signing_keys()
            keys2 = await client.get_signing_keys()

        assert keys1 is keys2
        # Only 2 HTTP calls total (discovery + jwks), not 4
        assert mock_http.get.call_count == 2

    @pytest.mark.asyncio
    async def test_force_refresh_bypasses_cache(self):
        config = _make_config()
        client = JWKSClient(config)

        discovery_resp = _mock_response({"jwks_uri": "https://okta.example.com/v1/keys"})
        jwks_resp1 = _mock_response({"keys": [_TEST_JWK]})
        jwks_resp2 = _mock_response({"keys": [_TEST_JWK]})

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=[discovery_resp, jwks_resp1, jwks_resp2])

        with patch("mcp_zero.identity.jwks.httpx.AsyncClient", return_value=mock_http):
            await client.get_signing_keys()
            await client.get_signing_keys(force_refresh=True)

        # 3 calls: discovery + first jwks + forced jwks
        assert mock_http.get.call_count == 3

    @pytest.mark.asyncio
    async def test_ttl_expiry_refetches(self):
        config = _make_config(jwks_cache_ttl=0)  # Immediate expiry
        client = JWKSClient(config)

        discovery_resp = _mock_response({"jwks_uri": "https://okta.example.com/v1/keys"})
        jwks_resp1 = _mock_response({"keys": [_TEST_JWK]})
        jwks_resp2 = _mock_response({"keys": [_TEST_JWK]})

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=[discovery_resp, jwks_resp1, jwks_resp2])

        with patch("mcp_zero.identity.jwks.httpx.AsyncClient", return_value=mock_http):
            await client.get_signing_keys()
            # With TTL=0, cache is immediately stale
            await client.get_signing_keys()

        # discovery + 2x jwks
        assert mock_http.get.call_count == 3

    @pytest.mark.asyncio
    async def test_discovery_failure_raises(self):
        config = _make_config()
        client = JWKSClient(config)

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with patch("mcp_zero.identity.jwks.httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(JWKSFetchError, match="OIDC discovery"):
                await client.get_signing_keys()

    @pytest.mark.asyncio
    async def test_jwks_fetch_failure_raises(self):
        config = _make_config()
        client = JWKSClient(config)

        discovery_resp = _mock_response({"jwks_uri": "https://okta.example.com/v1/keys"})

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=[discovery_resp, httpx.ConnectError("refused")])

        with patch("mcp_zero.identity.jwks.httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(JWKSFetchError, match="Failed to fetch JWKS"):
                await client.get_signing_keys()

    @pytest.mark.asyncio
    async def test_no_jwks_uri_in_discovery(self):
        config = _make_config()
        client = JWKSClient(config)

        discovery_resp = _mock_response({"issuer": "https://okta.example.com"})

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=discovery_resp)

        with patch("mcp_zero.identity.jwks.httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(JWKSFetchError, match="No jwks_uri"):
                await client.get_signing_keys()

    @pytest.mark.asyncio
    async def test_empty_keys_raises(self):
        config = _make_config()
        client = JWKSClient(config)

        discovery_resp = _mock_response({"jwks_uri": "https://okta.example.com/v1/keys"})
        jwks_resp = _mock_response({"keys": []})

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=[discovery_resp, jwks_resp])

        with patch("mcp_zero.identity.jwks.httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(JWKSFetchError, match="No keys found"):
                await client.get_signing_keys()

    @pytest.mark.asyncio
    async def test_trailing_slash_stripped_from_issuer(self):
        config = _make_config(issuer="https://okta.example.com/")
        client = JWKSClient(config)

        discovery_resp = _mock_response({"jwks_uri": "https://okta.example.com/v1/keys"})
        jwks_resp = _mock_response({"keys": [_TEST_JWK]})

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=[discovery_resp, jwks_resp])

        with patch("mcp_zero.identity.jwks.httpx.AsyncClient", return_value=mock_http):
            keys = await client.get_signing_keys()

        # Discovery URL should not have double slash
        call_args = mock_http.get.call_args_list[0]
        assert call_args[0][0] == "https://okta.example.com/.well-known/openid-configuration"
        assert len(keys) == 1
