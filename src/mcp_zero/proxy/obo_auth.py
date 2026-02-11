"""OBO auth provider — exchanges inbound JWTs for server-scoped tokens."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from mcp_zero.context import RequestContext
from mcp_zero.identity.obo import OBOClient
from mcp_zero.proxy.auth import AuthProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServerOBOSettings:
    """Per-server OBO exchange settings, derived from ServerConfig."""

    server_name: str
    enabled: bool
    target_audience: str
    scopes: list[str]


class OBOAuthProvider(AuthProvider):
    """Exchanges inbound user JWTs for server-scoped tokens via OBO."""

    def __init__(
        self,
        obo_client: OBOClient,
        server_settings: dict[str, ServerOBOSettings],
    ) -> None:
        self._obo_client = obo_client
        self._server_settings = server_settings

    async def get_token(self, server_name: str, context: RequestContext) -> str | None:
        settings = self._server_settings.get(server_name)
        if not settings or not settings.enabled:
            return None

        if not context.raw_token:
            logger.debug("No raw_token on context for server '%s', skipping OBO", server_name)
            return None

        if not context.identity:
            logger.debug("No identity on context for server '%s', skipping OBO", server_name)
            return None

        return await self._obo_client.exchange_token(
            subject_token=context.raw_token,
            subject_id=context.identity.user_id,
            target_audience=settings.target_audience,
            scopes=settings.scopes,
        )
