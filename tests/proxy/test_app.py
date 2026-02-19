"""Tests for ASGI app factory."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware

from mcp_zero.governance.config import CorsConfig
from mcp_zero.proxy.app import _CORSLoggingMiddleware, create_app
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


class TestCreateApp:
    def test_configures_stateful_streamable_http_session_manager(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)

        with patch("mcp_zero.proxy.app.StreamableHTTPSessionManager") as mock_session_mgr_cls:
            create_app(proxy, mgr)

        mock_session_mgr_cls.assert_called_once()
        assert mock_session_mgr_cls.call_args.kwargs["stateless"] is False

    def test_returns_asgi_app_with_middleware(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        app = create_app(proxy, mgr)
        assert isinstance(app, AuthHeaderMiddleware)
        # The inner app should be a Starlette instance
        assert isinstance(app._app, Starlette)

    def test_has_mcp_route(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        app = create_app(proxy, mgr)
        inner_app = app._app
        route_paths = [r.path for r in inner_app.routes]
        assert "/mcp" in route_paths

    def test_no_cors_returns_auth_middleware(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        app = create_app(proxy, mgr, cors_config=None)
        assert isinstance(app, AuthHeaderMiddleware)

    def test_with_cors_returns_cors_middleware_wrapping_auth(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        cors = CorsConfig(allow_origins=["https://example.com"])
        app = create_app(proxy, mgr, cors_config=cors)
        assert isinstance(app, _CORSLoggingMiddleware)
        # The inner CORSMiddleware wraps the AuthHeaderMiddleware
        assert isinstance(app._inner, CORSMiddleware)
        assert isinstance(app._inner.app, AuthHeaderMiddleware)

    @pytest.mark.asyncio
    async def test_cors_preflight_returns_correct_headers(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        cors = CorsConfig(
            allow_origins=["https://example.com"],
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
            max_age=300,
        )
        app = create_app(proxy, mgr, cors_config=cors)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.options(
                "/mcp",
                headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Authorization",
                },
            )
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == "https://example.com"
        assert "POST" in resp.headers["access-control-allow-methods"]
        assert resp.headers["access-control-max-age"] == "300"

    @pytest.mark.asyncio
    async def test_cors_rejects_disallowed_origin(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)
        cors = CorsConfig(allow_origins=["https://allowed.com"])
        app = create_app(proxy, mgr, cors_config=cors)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.options(
                "/mcp",
                headers={
                    "Origin": "https://evil.com",
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert "access-control-allow-origin" not in resp.headers

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
            inner_app = app._app

            # Simulate lifespan
            async with inner_app.router.lifespan_context(inner_app):
                pass

            mgr.disconnect_all.assert_awaited_once()
