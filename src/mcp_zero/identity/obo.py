"""OAuth2 Token Exchange (RFC 8693) client for OBO flows."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx

from mcp_zero.identity.errors import TokenExchangeError

logger = logging.getLogger(__name__)

_TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
_SUBJECT_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"


@dataclass(frozen=True)
class OBOConfig:
    """Configuration for the OBO token exchange endpoint."""

    token_endpoint: str
    client_id: str
    client_secret: str
    cache_ttl: int = 300  # seconds before expiry to consider token stale

    def __post_init__(self) -> None:
        if not self.token_endpoint:
            raise ValueError("token_endpoint is required")
        if not self.client_id:
            raise ValueError("client_id is required")
        if not self.client_secret:
            raise ValueError("client_secret is required")


@dataclass(frozen=True)
class ExchangedToken:
    """An access token received from the token exchange endpoint."""

    access_token: str
    token_type: str
    expires_in: int
    scope: str
    issued_at: float = field(default_factory=time.monotonic)

    def is_expired(self, ttl: int) -> bool:
        """Return True if the token is expired or within ``ttl`` seconds of expiry."""
        age = time.monotonic() - self.issued_at
        return age >= (self.expires_in - ttl)


@dataclass(frozen=True)
class ExchangeCacheKey:
    """Cache key for token exchange results."""

    subject_jti: str
    target_audience: str
    scopes: tuple[str, ...]

    @classmethod
    def from_params(
        cls, subject_jti: str, target_audience: str, scopes: list[str]
    ) -> ExchangeCacheKey:
        return cls(
            subject_jti=subject_jti,
            target_audience=target_audience,
            scopes=tuple(sorted(scopes)),
        )


class OBOClient:
    """Performs OAuth2 Token Exchange with caching and per-key locking."""

    def __init__(self, config: OBOConfig) -> None:
        self._config = config
        self._cache: dict[ExchangeCacheKey, ExchangedToken] = {}
        self._locks: dict[ExchangeCacheKey, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def exchange_token(
        self,
        subject_token: str,
        subject_jti: str,
        target_audience: str,
        scopes: list[str] | None = None,
    ) -> str:
        """Exchange a subject token for a server-scoped access token.

        Returns the ``access_token`` string.  Results are cached per
        (jti, audience, scopes) until they expire.
        """
        scopes = scopes or []
        key = ExchangeCacheKey.from_params(subject_jti, target_audience, scopes)

        # Fast path: cache hit
        cached = self._cache.get(key)
        if cached and not cached.is_expired(self._config.cache_ttl):
            return cached.access_token

        # Get or create a per-key lock
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            lock = self._locks[key]

        async with lock:
            # Double-check after acquiring lock
            cached = self._cache.get(key)
            if cached and not cached.is_expired(self._config.cache_ttl):
                return cached.access_token

            token = await self._perform_exchange(subject_token, target_audience, scopes)
            self._cache[key] = token
            return token.access_token

    async def _perform_exchange(
        self,
        subject_token: str,
        target_audience: str,
        scopes: list[str],
    ) -> ExchangedToken:
        """POST to the token endpoint to perform the RFC 8693 exchange."""
        data = {
            "grant_type": _TOKEN_EXCHANGE_GRANT,
            "subject_token": subject_token,
            "subject_token_type": _SUBJECT_TOKEN_TYPE,
            "audience": target_audience,
        }
        if scopes:
            data["scope"] = " ".join(scopes)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._config.token_endpoint,
                    data=data,
                    auth=(self._config.client_id, self._config.client_secret),
                )
        except httpx.HTTPError as exc:
            raise TokenExchangeError(
                f"Token exchange request failed: {exc}",
                audience=target_audience,
            ) from exc

        if response.status_code != 200:
            raise TokenExchangeError(
                f"Token exchange returned HTTP {response.status_code}: {response.text}",
                audience=target_audience,
            )

        body = response.json()
        access_token = body.get("access_token")
        if not access_token:
            raise TokenExchangeError(
                "Token exchange response missing 'access_token'",
                audience=target_audience,
            )

        return ExchangedToken(
            access_token=access_token,
            token_type=body.get("token_type", "Bearer"),
            expires_in=int(body.get("expires_in", 3600)),
            scope=body.get("scope", ""),
        )
