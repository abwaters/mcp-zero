"""Connection pool managing transports to upstream MCP servers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Self

from mcp import ClientSession

from mcp_zero.context import RequestContext
from mcp_zero.proxy.errors import RoutingError
from mcp_zero.transport.base import MCPTransport, TransportState
from mcp_zero.transport.config import ServerConfig
from mcp_zero.transport.factory import TransportFactory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SessionKey:
    """Cache key for per-user, per-server transport sessions.

    When ``subject_id`` is ``None`` the session is shared (e.g. for
    unauthenticated ``list_tools`` calls).  When set, each user gets
    an isolated transport with their own auth context.  See GitHub
    issue #50.
    """

    server_name: str
    subject_id: str | None = None


class ServerManager:
    """Manages lazy connections to upstream MCP servers.

    Transports are pooled per ``(server_name, subject_id)`` so that
    each authenticated user gets an isolated downstream session with
    their own auth token.  Unauthenticated requests (no identity on
    the context) share a single transport per server.
    """

    def __init__(self, configs: list[ServerConfig]) -> None:
        self._configs: dict[str, ServerConfig] = {c.name: c for c in configs}
        self._transports: dict[_SessionKey, MCPTransport] = {}
        self._locks: dict[_SessionKey, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    @property
    def server_names(self) -> list[str]:
        """Return configured server names."""
        return list(self._configs.keys())

    def get_config(self, server_name: str) -> ServerConfig:
        """Return configuration for *server_name*.

        Raises RoutingError if the server is not configured.
        """
        try:
            return self._configs[server_name]
        except KeyError:
            raise RoutingError(
                f"No configuration for server '{server_name}'",
                server_name=server_name,
            ) from None

    async def get_session(
        self,
        server_name: str,
        context: RequestContext | None = None,
        *,
        auth_token: str | None = None,
    ) -> ClientSession:
        """Return a connected ClientSession for *server_name*.

        Sessions are keyed by ``(server_name, subject_id)`` so that each
        authenticated user gets an isolated transport.  Creates and
        connects the transport lazily on first call.
        """
        config = self.get_config(server_name)
        subject_id = context.identity.user_id if context and context.identity else None
        key = _SessionKey(server_name, subject_id)

        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            lock = self._locks[key]

        async with lock:
            transport = self._transports.get(key)
            if transport is None:
                transport = TransportFactory.create(config)
                self._transports[key] = transport

            if transport.state != TransportState.CONNECTED:
                await transport.connect(context, auth_token=auth_token)

        return transport.session

    async def disconnect(self, server_name: str) -> None:
        """Disconnect all transports for *server_name* (all users)."""
        keys = [k for k in self._transports if k.server_name == server_name]
        for key in keys:
            transport = self._transports.pop(key, None)
            self._locks.pop(key, None)
            if transport is not None:
                await transport.disconnect()

    async def disconnect_all(self) -> None:
        """Disconnect all transports for clean shutdown."""
        keys = list(self._transports.keys())
        for key in keys:
            try:
                transport = self._transports.pop(key, None)
                self._locks.pop(key, None)
                if transport is not None:
                    await transport.disconnect()
            except Exception:
                logger.debug("Error disconnecting server '%s'", key.server_name, exc_info=True)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.disconnect_all()
