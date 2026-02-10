"""JWKS client with async caching for token signature verification."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
from jwt import PyJWK

from mcp_zero.identity.config import IdentityConfig
from mcp_zero.identity.errors import JWKSFetchError

logger = logging.getLogger(__name__)


class JWKSClient:
    """Fetches and caches JWKS keys from an OpenID Connect provider.

    Discovers the ``jwks_uri`` from the issuer's ``/.well-known/openid-configuration``
    endpoint, then fetches and caches the signing keys with a configurable TTL.
    """

    def __init__(self, config: IdentityConfig) -> None:
        self._config = config
        self._jwks_uri: str | None = None
        self._keys: list[PyJWK] = []
        self._last_fetch: float = 0.0
        self._lock = asyncio.Lock()

    async def get_signing_keys(self, *, force_refresh: bool = False) -> list[PyJWK]:
        """Return cached JWKS keys, fetching if stale or forced.

        Uses a double-check pattern under an async lock to prevent
        concurrent fetches from multiple requests.
        """
        if not force_refresh and self._is_cache_valid():
            return self._keys

        async with self._lock:
            # Double-check after acquiring lock
            if not force_refresh and self._is_cache_valid():
                return self._keys

            await self._fetch_keys()
            return self._keys

    def _is_cache_valid(self) -> bool:
        if not self._keys or self._last_fetch == 0.0:
            return False
        return (time.monotonic() - self._last_fetch) < self._config.jwks_cache_ttl

    async def _fetch_keys(self) -> None:
        """Discover jwks_uri (if needed) and fetch JWKS keys."""
        issuer = self._config.issuer.rstrip("/")

        if self._jwks_uri is None:
            self._jwks_uri = await self._discover_jwks_uri(issuer)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self._jwks_uri, timeout=10.0)
                response.raise_for_status()
                jwks_data = response.json()
        except Exception as exc:
            raise JWKSFetchError(
                f"Failed to fetch JWKS from {self._jwks_uri}: {exc}",
                issuer=issuer,
            ) from exc

        raw_keys = jwks_data.get("keys", [])
        if not raw_keys:
            raise JWKSFetchError(
                f"No keys found in JWKS response from {self._jwks_uri}",
                issuer=issuer,
            )

        self._keys = [PyJWK(key_data) for key_data in raw_keys]
        self._last_fetch = time.monotonic()
        logger.debug("Fetched %d JWKS keys from %s", len(self._keys), self._jwks_uri)

    async def _discover_jwks_uri(self, issuer: str) -> str:
        """Fetch the OpenID Connect discovery document to find the jwks_uri."""
        discovery_url = f"{issuer}/.well-known/openid-configuration"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(discovery_url, timeout=10.0)
                response.raise_for_status()
                config = response.json()
        except Exception as exc:
            raise JWKSFetchError(
                f"Failed to fetch OIDC discovery from {discovery_url}: {exc}",
                issuer=issuer,
            ) from exc

        jwks_uri = config.get("jwks_uri")
        if not jwks_uri:
            raise JWKSFetchError(
                f"No jwks_uri in OIDC discovery response from {discovery_url}",
                issuer=issuer,
            )

        logger.debug("Discovered jwks_uri: %s", jwks_uri)
        return jwks_uri
