"""Tests for ASGI app factory."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.applications import Starlette

from mcp_zero.proxy.app import create_app
from mcp_zero.proxy.proxy_server import ProxyServer
from mcp_zero.proxy.server_manager import ServerManager
from mcp_zero.transport.config import ServerConfig, TransportType


def make_configs():
    return [
        ServerConfig(name="weather", transport=TransportType.HTTP, url="http://weather:8080"),
    ]


class TestCreateApp:
    def test_returns_starlette_app(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        app = create_app(proxy, mgr)
        assert isinstance(app, Starlette)

    def test_has_mcp_route(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        app = create_app(proxy, mgr)
        route_paths = [r.path for r in app.routes]
        assert "/mcp" in route_paths

    @pytest.mark.asyncio
    async def test_lifespan_disconnects_on_shutdown(self):
        mgr = ServerManager(make_configs())
        mgr.disconnect_all = AsyncMock()
        proxy = ProxyServer(mgr)

        with patch("mcp_zero.proxy.app.StreamableHTTPSessionManager") as mock_session_mgr_cls:
            mock_session_mgr = MagicMock()
            # Make run() return an async context manager
            mock_run_cm = AsyncMock()
            mock_run_cm.__aenter__ = AsyncMock(return_value=None)
            mock_run_cm.__aexit__ = AsyncMock(return_value=False)
            mock_session_mgr.run = MagicMock(return_value=mock_run_cm)
            mock_session_mgr_cls.return_value = mock_session_mgr

            app = create_app(proxy, mgr)

            # Simulate lifespan
            async with app.router.lifespan_context(app):
                pass

            mgr.disconnect_all.assert_awaited_once()
