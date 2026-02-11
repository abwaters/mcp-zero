"""Connection pool managing transports to upstream MCP servers."""

from __future__ import annotations

import asyncio
import logging
from typing import Self

from mcp import ClientSession

from mcp_zero.context import RequestContext
from mcp_zero.proxy.errors import RoutingError
from mcp_zero.transport.base import MCPTransport
from mcp_zero.transport.config import ServerConfig
from mcp_zero.transport.factory import TransportFactory

logger = logging.getLogger(__name__)


class ServerManager:
    """Manages lazy connections to upstream MCP servers.

    Each server gets its own asyncio.Lock to prevent duplicate concurrent
    connections.  Transports are created via TransportFactory on first use.
    """

    def __init__(self, configs: list[ServerConfig]) -> None:
        self._configs: dict[str, ServerConfig] = {c.name: c for c in configs}
        self._transports: dict[str, MCPTransport] = {}
        self._locks: dict[str, asyncio.Lock] = {c.name: asyncio.Lock() for c in configs}

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

        Creates and connects the transport lazily on first call.
        """
        config = self.get_config(server_name)
        lock = self._locks[server_name]

        async with lock:
            transport = self._transports.get(server_name)
            if transport is None:
                transport = TransportFactory.create(config)
                self._transports[server_name] = transport

            from mcp_zero.transport.base import TransportState

            if transport.state != TransportState.CONNECTED:
                await transport.connect(context, auth_token=auth_token)

        return transport.session

    async def disconnect(self, server_name: str) -> None:
        """Disconnect a single server transport."""
        transport = self._transports.pop(server_name, None)
        if transport is not None:
            await transport.disconnect()

    async def disconnect_all(self) -> None:
        """Disconnect all transports for clean shutdown."""
        names = list(self._transports.keys())
        for name in names:
            try:
                await self.disconnect(name)
            except Exception:
                logger.debug("Error disconnecting server '%s'", name, exc_info=True)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.disconnect_all()
