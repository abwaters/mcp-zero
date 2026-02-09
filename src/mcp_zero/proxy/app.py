"""ASGI application factory for the MCP proxy gateway."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from mcp_zero.proxy.proxy_server import ProxyServer
from mcp_zero.proxy.server_manager import ServerManager


def create_app(
    proxy_server: ProxyServer,
    server_manager: ServerManager,
) -> Starlette:
    """Build a Starlette ASGI app that serves the MCP proxy on ``/mcp``."""
    session_manager = StreamableHTTPSessionManager(
        app=proxy_server.mcp_server,
        stateless=True,
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            try:
                yield
            finally:
                await server_manager.disconnect_all()

    async def mcp_asgi(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    return Starlette(
        routes=[
            Mount("/mcp", app=mcp_asgi),
        ],
        lifespan=lifespan,
    )
