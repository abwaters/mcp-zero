"""ASGI application factory for the MCP proxy gateway."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route
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
    sse_enabled: bool = True,
) -> ASGIApp:
    """Build a Starlette ASGI app that serves the MCP proxy on ``/mcp``.

    When *sse_enabled* is ``True`` (the default), the legacy SSE endpoints
    are mounted at ``/mcp/sse`` (GET) and ``/mcp/sse/messages/`` (POST).
    Set ``MCP_SSE_ENABLED=false`` to disable them and reduce attack surface.
    """
    session_manager = StreamableHTTPSessionManager(
        app=proxy_server.mcp_server,
        # Stateful mode avoids per-request transport teardown, which can trigger
        # AnyIO cancel-scope violations during stateless cleanup paths.
        stateless=False,
    )

    # SSE inbound transport (deprecated, for backward-compat clients)
    sse_transport: SseServerTransport | None = None
    if sse_enabled:
        sse_transport = SseServerTransport("/mcp/sse/messages/")
        logger.info(
            "SSE inbound endpoints enabled (deprecated — clients should migrate to Streamable HTTP)"
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

    routes: list[Route | Mount] = [
        Mount("/mcp", app=mcp_asgi),
    ]

    if sse_transport is not None:

        async def handle_sse(request: Request) -> None:
            async with sse_transport.connect_sse(  # type: ignore[union-attr]
                request.scope, request.receive, request._send
            ) as streams:
                await proxy_server.mcp_server.run(
                    streams[0],
                    streams[1],
                    proxy_server.mcp_server.create_initialization_options(),
                )

        async def handle_sse_messages(request: Request) -> None:
            await sse_transport.handle_post_message(  # type: ignore[union-attr]
                request.scope, request.receive, request._send
            )

        routes.extend(
            [
                Route("/mcp/sse", endpoint=handle_sse),
                Route("/mcp/sse/messages/", endpoint=handle_sse_messages, methods=["POST"]),
            ]
        )

    app = Starlette(
        routes=routes,
        lifespan=lifespan,
    )
    return AuthHeaderMiddleware(app)
