"""Tests for JWT validation with real RSA key signing."""

from __future__ import annotations

import base64
import time
from unittest.mock import AsyncMock

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from jwt import PyJWK

from mcp_zero.identity.config import ClaimMapping, IdentityConfig
from mcp_zero.identity.errors import TokenExpiredError, TokenValidationError
from mcp_zero.identity.jwt import JWTValidator

_ISSUER = "https://okta.example.com"
_AUDIENCE = "my-app"


def _int_to_base64url(n: int) -> str:
    """Encode an integer as a base64url string (no padding)."""
    byte_length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(byte_length, byteorder="big")).rstrip(b"=").decode()


def _generate_rsa_key_pair():
    """Generate an RSA key pair and return (private_pem, public_key_object)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    return private_pem, private_key.public_key()


def _make_config(**overrides):
    defaults = {"issuer": _ISSUER, "audience": _AUDIENCE}
    defaults.update(overrides)
    return IdentityConfig(**defaults)


# Generate a pair of keys for testing
_PRIVATE_PEM, _PUBLIC_KEY = _generate_rsa_key_pair()
_PRIVATE_PEM_2, _PUBLIC_KEY_2 = _generate_rsa_key_pair()


def _make_pyjwk(public_key, kid: str = "test-key") -> PyJWK:
    """Build a PyJWK from a cryptography RSA public key object."""
    numbers = public_key.public_numbers()
    jwk_dict = {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _int_to_base64url(numbers.n),
        "e": _int_to_base64url(numbers.e),
    }
    return PyJWK(jwk_dict)


def _sign_token(claims: dict, private_pem: bytes = _PRIVATE_PEM, kid: str = "test-key") -> str:
    return pyjwt.encode(
        claims,
        private_pem,
        algorithm="RS256",
        headers={"kid": kid},
    )


def _valid_claims(**overrides) -> dict:
    claims = {
        "sub": "user-123",
        "email": "user@example.com",
        "groups": ["admin", "dev"],
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    claims.update(overrides)
    return claims


class TestJWTValidator:
    @pytest.mark.asyncio
    async def test_valid_token(self):
        config = _make_config()
        jwks_client = AsyncMock()
        jwks_client.get_signing_keys = AsyncMock(return_value=[_make_pyjwk(_PUBLIC_KEY)])

        validator = JWTValidator(config, jwks_client)
        token = _sign_token(_valid_claims())
        claims = await validator.validate_token(token)

        assert claims.user_id == "user-123"
        assert claims.email == "user@example.com"
        assert claims.groups == ["admin", "dev"]
        assert claims.raw_claims["sub"] == "user-123"

    @pytest.mark.asyncio
    async def test_expired_token(self):
        config = _make_config()
        jwks_client = AsyncMock()
        jwks_client.get_signing_keys = AsyncMock(return_value=[_make_pyjwk(_PUBLIC_KEY)])

        validator = JWTValidator(config, jwks_client)
        token = _sign_token(_valid_claims(exp=int(time.time()) - 100))

        with pytest.raises(TokenExpiredError):
            await validator.validate_token(token)

    @pytest.mark.asyncio
    async def test_wrong_issuer(self):
        config = _make_config()
        jwks_client = AsyncMock()
        jwks_client.get_signing_keys = AsyncMock(return_value=[_make_pyjwk(_PUBLIC_KEY)])

        validator = JWTValidator(config, jwks_client)
        token = _sign_token(_valid_claims(iss="https://evil.example.com"))

        with pytest.raises(TokenValidationError, match="Invalid issuer") as exc_info:
            await validator.validate_token(token)
        assert exc_info.value.reason == "invalid_issuer"

    @pytest.mark.asyncio
    async def test_wrong_audience(self):
        config = _make_config()
        jwks_client = AsyncMock()
        jwks_client.get_signing_keys = AsyncMock(return_value=[_make_pyjwk(_PUBLIC_KEY)])

        validator = JWTValidator(config, jwks_client)
        token = _sign_token(_valid_claims(aud="wrong-app"))

        with pytest.raises(TokenValidationError, match="Invalid audience") as exc_info:
            await validator.validate_token(token)
        assert exc_info.value.reason == "invalid_audience"

    @pytest.mark.asyncio
    async def test_missing_sub_claim(self):
        config = _make_config()
        jwks_client = AsyncMock()
        jwks_client.get_signing_keys = AsyncMock(return_value=[_make_pyjwk(_PUBLIC_KEY)])

        validator = JWTValidator(config, jwks_client)
        claims = _valid_claims()
        del claims["sub"]
        token = _sign_token(claims)

        with pytest.raises(TokenValidationError) as exc_info:
            await validator.validate_token(token)
        assert exc_info.value.reason == "missing_claim"

    @pytest.mark.asyncio
    async def test_key_rotation_retry(self):
        """When signature fails with cached keys, force-refresh and retry."""
        config = _make_config()
        jwks_client = AsyncMock()

        # First call returns old key (signature will fail), second returns new key
        old_key = _make_pyjwk(_PUBLIC_KEY_2, kid="old-key")
        new_key = _make_pyjwk(_PUBLIC_KEY, kid="new-key")
        jwks_client.get_signing_keys = AsyncMock(side_effect=[[old_key], [new_key]])

        validator = JWTValidator(config, jwks_client)
        token = _sign_token(_valid_claims(), private_pem=_PRIVATE_PEM, kid="new-key")
        claims = await validator.validate_token(token)

        assert claims.user_id == "user-123"
        # Should have been called twice: once normal, once force_refresh
        assert jwks_client.get_signing_keys.call_count == 2
        jwks_client.get_signing_keys.assert_any_call(force_refresh=True)

    @pytest.mark.asyncio
    async def test_invalid_signature_no_matching_key(self):
        """When no key matches even after refresh, raise error."""
        config = _make_config()
        jwks_client = AsyncMock()

        wrong_key = _make_pyjwk(_PUBLIC_KEY_2, kid="wrong")
        jwks_client.get_signing_keys = AsyncMock(return_value=[wrong_key])

        validator = JWTValidator(config, jwks_client)
        token = _sign_token(_valid_claims(), private_pem=_PRIVATE_PEM)

        with pytest.raises(TokenValidationError) as exc_info:
            await validator.validate_token(token)
        assert exc_info.value.reason == "invalid_signature"

    @pytest.mark.asyncio
    async def test_custom_claim_mapping(self):
        mapping = ClaimMapping(user_id="uid", email="mail", groups="roles")
        config = _make_config(claim_mapping=mapping)
        jwks_client = AsyncMock()
        jwks_client.get_signing_keys = AsyncMock(return_value=[_make_pyjwk(_PUBLIC_KEY)])

        validator = JWTValidator(config, jwks_client)
        claims_data = _valid_claims()
        claims_data["uid"] = "custom-user"
        claims_data["mail"] = "custom@example.com"
        claims_data["roles"] = ["viewer"]
        token = _sign_token(claims_data)

        claims = await validator.validate_token(token)
        assert claims.user_id == "custom-user"
        assert claims.email == "custom@example.com"
        assert claims.groups == ["viewer"]

    @pytest.mark.asyncio
    async def test_missing_email_is_none(self):
        config = _make_config()
        jwks_client = AsyncMock()
        jwks_client.get_signing_keys = AsyncMock(return_value=[_make_pyjwk(_PUBLIC_KEY)])

        validator = JWTValidator(config, jwks_client)
        claims_data = _valid_claims()
        del claims_data["email"]
        token = _sign_token(claims_data)

        claims = await validator.validate_token(token)
        assert claims.email is None

    @pytest.mark.asyncio
    async def test_missing_groups_is_empty(self):
        config = _make_config()
        jwks_client = AsyncMock()
        jwks_client.get_signing_keys = AsyncMock(return_value=[_make_pyjwk(_PUBLIC_KEY)])

        validator = JWTValidator(config, jwks_client)
        claims_data = _valid_claims()
        del claims_data["groups"]
        token = _sign_token(claims_data)

        claims = await validator.validate_token(token)
        assert claims.groups == []

    @pytest.mark.asyncio
    async def test_non_list_groups_treated_as_empty(self):
        config = _make_config()
        jwks_client = AsyncMock()
        jwks_client.get_signing_keys = AsyncMock(return_value=[_make_pyjwk(_PUBLIC_KEY)])

        validator = JWTValidator(config, jwks_client)
        claims_data = _valid_claims(groups="not-a-list")
        token = _sign_token(claims_data)

        claims = await validator.validate_token(token)
        assert claims.groups == []

    @pytest.mark.asyncio
    async def test_multiple_keys_tries_each(self):
        """With multiple keys, the correct one is found."""
        config = _make_config()
        jwks_client = AsyncMock()

        wrong_key = _make_pyjwk(_PUBLIC_KEY_2, kid="wrong")
        right_key = _make_pyjwk(_PUBLIC_KEY, kid="right")
        jwks_client.get_signing_keys = AsyncMock(return_value=[wrong_key, right_key])

        validator = JWTValidator(config, jwks_client)
        token = _sign_token(_valid_claims(), kid="right")
        claims = await validator.validate_token(token)

        assert claims.user_id == "user-123"
