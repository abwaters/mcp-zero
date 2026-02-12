"""ASGI application factory for the MCP proxy gateway."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp_zero.analytics.collector import AnalyticsCollector
from mcp_zero.proxy.middleware import AuthHeaderMiddleware
from mcp_zero.proxy.proxy_server import ProxyServer
from mcp_zero.proxy.server_manager import ServerManager

logger = logging.getLogger(__name__)


def create_app(
    proxy_server: ProxyServer,
    server_manager: ServerManager,
    *,
    analytics_collector: AnalyticsCollector | None = None,
) -> ASGIApp:
    """Build a Starlette ASGI app that serves the MCP proxy on ``/mcp``."""
    session_manager = StreamableHTTPSessionManager(
        app=proxy_server.mcp_server,
        # Stateful mode avoids per-request transport teardown, which can trigger
        # AnyIO cancel-scope violations during stateless cleanup paths.
        stateless=False,
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        # Start analytics collector background tasks
        if analytics_collector is not None:
            await analytics_collector.start()

        try:
            async with session_manager.run():
                yield
        except BaseExceptionGroup:
            # The session manager's task group may raise an ExceptionGroup
            # when cancelled during shutdown (e.g. active SSE streams).
            # This is expected — suppress it for a clean exit.
            logger.debug("Session manager tasks cancelled during shutdown", exc_info=True)
        finally:
            # Stop analytics collector before disconnecting servers
            if analytics_collector is not None:
                await analytics_collector.stop()
            await server_manager.disconnect_all()

    async def mcp_asgi(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    app = Starlette(
        routes=[
            Mount("/mcp", app=mcp_asgi),
        ],
        lifespan=lifespan,
    )
    return AuthHeaderMiddleware(app)
