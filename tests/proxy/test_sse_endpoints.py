"""Tests for inbound SSE endpoints in the ASGI app."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.applications import Starlette

from mcp_zero.proxy.app import create_app
from mcp_zero.proxy.middleware import AuthHeaderMiddleware
from mcp_zero.proxy.proxy_server import ProxyServer
from mcp_zero.proxy.server_manager import ServerManager
from mcp_zero.transport.config import ServerConfig, TransportType


def make_configs():
    return [
        ServerConfig(
            name="weather",
            transport=TransportType.HTTP,
            url="http://weather:8080",
            allow_insecure=True,
        ),
    ]


class TestSSEEndpointsEnabled:
    """Tests for SSE inbound endpoints when enabled (default)."""

    def test_sse_routes_present_by_default(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        app = create_app(proxy, mgr)
        inner_app = app._app
        route_paths = [r.path for r in inner_app.routes]
        assert "/mcp/sse" in route_paths
        assert "/mcp/sse/messages/" in route_paths

    def test_sse_routes_present_when_explicitly_enabled(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        app = create_app(proxy, mgr, sse_enabled=True)
        inner_app = app._app
        route_paths = [r.path for r in inner_app.routes]
        assert "/mcp/sse" in route_paths
        assert "/mcp/sse/messages/" in route_paths

    def test_streamable_http_route_still_present(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        app = create_app(proxy, mgr, sse_enabled=True)
        inner_app = app._app
        route_paths = [r.path for r in inner_app.routes]
        assert "/mcp" in route_paths

    def test_returns_asgi_app_with_middleware(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        app = create_app(proxy, mgr, sse_enabled=True)
        assert isinstance(app, AuthHeaderMiddleware)
        assert isinstance(app._app, Starlette)


class TestSSEEndpointsDisabled:
    """Tests for SSE inbound endpoints when disabled."""

    def test_sse_routes_absent_when_disabled(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        app = create_app(proxy, mgr, sse_enabled=False)
        inner_app = app._app
        route_paths = [r.path for r in inner_app.routes]
        assert "/mcp/sse" not in route_paths
        assert "/mcp/sse/messages/" not in route_paths

    def test_streamable_http_route_still_present_when_sse_disabled(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        app = create_app(proxy, mgr, sse_enabled=False)
        inner_app = app._app
        route_paths = [r.path for r in inner_app.routes]
        assert "/mcp" in route_paths

    def test_returns_asgi_app_with_middleware_when_sse_disabled(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        app = create_app(proxy, mgr, sse_enabled=False)
        assert isinstance(app, AuthHeaderMiddleware)
        assert isinstance(app._app, Starlette)

    @pytest.mark.asyncio
    async def test_lifespan_works_with_sse_disabled(self):
        mgr = ServerManager(make_configs())
        mgr.disconnect_all = AsyncMock()
        proxy = ProxyServer(mgr)

        with patch("mcp_zero.proxy.app.StreamableHTTPSessionManager") as mock_session_mgr_cls:
            mock_session_mgr = MagicMock()
            mock_run_cm = AsyncMock()
            mock_run_cm.__aenter__ = AsyncMock(return_value=None)
            mock_run_cm.__aexit__ = AsyncMock(return_value=False)
            mock_session_mgr.run = MagicMock(return_value=mock_run_cm)
            mock_session_mgr_cls.return_value = mock_session_mgr

            app = create_app(proxy, mgr, sse_enabled=False)
            inner_app = app._app

            async with inner_app.router.lifespan_context(inner_app):
                pass

            mgr.disconnect_all.assert_awaited_once()


class TestSSEMessagesRoute:
    """Tests for the SSE messages POST route configuration."""

    def test_sse_messages_route_is_post_only(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        app = create_app(proxy, mgr, sse_enabled=True)
        inner_app = app._app
        for route in inner_app.routes:
            if hasattr(route, "path") and route.path == "/mcp/sse/messages/":
                assert "POST" in route.methods
                break
        else:
            pytest.fail("SSE messages route not found")
