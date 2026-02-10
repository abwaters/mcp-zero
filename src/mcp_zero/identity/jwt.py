"""JWT validation using JWKS signing keys."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import jwt as pyjwt
from jwt import PyJWK

from mcp_zero.identity.config import IdentityConfig
from mcp_zero.identity.errors import TokenExpiredError, TokenValidationError
from mcp_zero.identity.jwks import JWKSClient

logger = logging.getLogger(__name__)

_SUPPORTED_ALGORITHMS = ["RS256", "RS384", "RS512"]


@dataclass(frozen=True)
class TokenClaims:
    """Validated identity claims extracted from a JWT."""

    user_id: str
    email: str | None = None
    groups: list[str] = field(default_factory=list)
    raw_claims: dict[str, Any] = field(default_factory=dict)


class JWTValidator:
    """Validates JWTs against JWKS signing keys with automatic key rotation retry."""

    def __init__(self, config: IdentityConfig, jwks_client: JWKSClient) -> None:
        self._config = config
        self._jwks_client = jwks_client

    async def validate_token(self, token: str) -> TokenClaims:
        """Decode and validate a JWT, returning extracted claims.

        On signature failure, force-refreshes JWKS keys and retries once
        to handle key rotation gracefully.
        """
        keys = await self._jwks_client.get_signing_keys()

        try:
            return self._decode_with_keys(token, keys)
        except TokenValidationError as exc:
            if exc.reason != "invalid_signature":
                raise

        # Key rotation retry: force-refresh and try once more
        logger.info("Signature validation failed, retrying with refreshed JWKS keys")
        keys = await self._jwks_client.get_signing_keys(force_refresh=True)
        return self._decode_with_keys(token, keys)

    def _decode_with_keys(self, token: str, keys: list[PyJWK]) -> TokenClaims:
        """Try decoding with each key until one succeeds."""
        last_error: Exception | None = None

        for key in keys:
            try:
                claims = pyjwt.decode(
                    token,
                    key=key.key,
                    algorithms=_SUPPORTED_ALGORITHMS,
                    issuer=self._config.issuer,
                    audience=self._config.audience,
                    options={"require": ["exp", "iss", "aud", "sub"]},
                )
                return self._extract_claims(claims)
            except pyjwt.ExpiredSignatureError as exc:
                raise TokenExpiredError() from exc
            except pyjwt.ImmatureSignatureError as exc:
                raise TokenValidationError(
                    f"Token is not yet valid (nbf): {exc}", reason="not_yet_valid"
                ) from exc
            except pyjwt.InvalidIssuerError as exc:
                raise TokenValidationError(
                    f"Invalid issuer: {exc}", reason="invalid_issuer"
                ) from exc
            except pyjwt.InvalidAudienceError as exc:
                raise TokenValidationError(
                    f"Invalid audience: {exc}", reason="invalid_audience"
                ) from exc
            except pyjwt.MissingRequiredClaimError as exc:
                raise TokenValidationError(
                    f"Missing required claim: {exc}", reason="missing_claim"
                ) from exc
            except pyjwt.InvalidSignatureError as exc:
                last_error = exc
                continue
            except pyjwt.PyJWTError as exc:
                raise TokenValidationError(
                    f"Token validation failed: {exc}", reason="invalid_token"
                ) from exc

        raise TokenValidationError(
            f"No matching signing key found: {last_error}",
            reason="invalid_signature",
        )

    def _extract_claims(self, claims: dict[str, Any]) -> TokenClaims:
        """Map raw JWT claims to TokenClaims using the configured mapping."""
        mapping = self._config.claim_mapping

        user_id = claims.get(mapping.user_id)
        if not user_id:
            raise TokenValidationError(
                f"Required claim '{mapping.user_id}' is missing or empty",
                reason="missing_claim",
            )

        email = claims.get(mapping.email)
        groups_raw = claims.get(mapping.groups, [])
        groups = groups_raw if isinstance(groups_raw, list) else []

        return TokenClaims(
            user_id=user_id,
            email=email,
            groups=groups,
            raw_claims=claims,
        )
