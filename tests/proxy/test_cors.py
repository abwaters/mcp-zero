"""Dedicated tests for CORS HTTP behavior."""

import logging

import httpx
import pytest

from mcp_zero.governance.config import CorsConfig
from mcp_zero.proxy.app import create_app
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


def _make_app(cors_config=None):
    """Create an ASGI app with optional CORS config."""
    mgr = ServerManager(make_configs())
    proxy = ProxyServer(mgr)
    return create_app(proxy, mgr, cors_config=cors_config)


class TestCorsDisabled:
    @pytest.mark.asyncio
    async def test_no_cors_headers_when_unconfigured(self):
        app = _make_app(cors_config=None)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.get(
                "/mcp",
                headers={"Origin": "https://example.com"},
            )
        cors_headers = [k for k in resp.headers if k.startswith("access-control-")]
        assert cors_headers == []


class TestCorsPreflightBehavior:
    @pytest.mark.asyncio
    async def test_preflight_allowed_origin(self):
        cors = CorsConfig(
            allow_origins=["https://example.com"],
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
            max_age=300,
        )
        app = _make_app(cors_config=cors)
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
    async def test_preflight_disallowed_origin(self):
        cors = CorsConfig(allow_origins=["https://allowed.com"])
        app = _make_app(cors_config=cors)
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
    async def test_preflight_with_credentials(self):
        cors = CorsConfig(
            allow_origins=["https://example.com"],
            allow_credentials=True,
        )
        app = _make_app(cors_config=cors)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.options(
                "/mcp",
                headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert resp.headers["access-control-allow-credentials"] == "true"
        assert resp.headers["access-control-allow-origin"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_preflight_expose_headers(self):
        cors = CorsConfig(
            allow_origins=["https://example.com"],
            expose_headers=["X-Correlation-ID"],
        )
        app = _make_app(cors_config=cors)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            # expose_headers appears on simple responses, not preflight;
            # send a GET with Origin to check
            resp = await client.get(
                "/mcp",
                headers={"Origin": "https://example.com"},
            )
        assert "x-correlation-id" in resp.headers.get("access-control-expose-headers", "").lower()

    @pytest.mark.asyncio
    async def test_preflight_max_age(self):
        cors = CorsConfig(
            allow_origins=["https://example.com"],
            max_age=1800,
        )
        app = _make_app(cors_config=cors)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.options(
                "/mcp",
                headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert resp.headers["access-control-max-age"] == "1800"


class TestCorsSimpleRequest:
    @pytest.mark.asyncio
    async def test_allowed_origin_gets_cors_headers(self):
        cors = CorsConfig(allow_origins=["https://example.com"])
        app = _make_app(cors_config=cors)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.post(
                "/mcp",
                headers={
                    "Origin": "https://example.com",
                    "Content-Type": "application/json",
                },
                content="{}",
            )
        assert resp.headers["access-control-allow-origin"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_disallowed_origin_no_cors_headers(self):
        cors = CorsConfig(allow_origins=["https://allowed.com"])
        app = _make_app(cors_config=cors)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.post(
                "/mcp",
                headers={
                    "Origin": "https://evil.com",
                    "Content-Type": "application/json",
                },
                content="{}",
            )
        assert "access-control-allow-origin" not in resp.headers


class TestCorsMultipleOrigins:
    @pytest.mark.asyncio
    async def test_first_origin_allowed(self):
        cors = CorsConfig(allow_origins=["https://first.com", "https://second.com"])
        app = _make_app(cors_config=cors)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.options(
                "/mcp",
                headers={
                    "Origin": "https://first.com",
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert resp.headers["access-control-allow-origin"] == "https://first.com"

    @pytest.mark.asyncio
    async def test_second_origin_allowed(self):
        cors = CorsConfig(allow_origins=["https://first.com", "https://second.com"])
        app = _make_app(cors_config=cors)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.options(
                "/mcp",
                headers={
                    "Origin": "https://second.com",
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert resp.headers["access-control-allow-origin"] == "https://second.com"

    @pytest.mark.asyncio
    async def test_unlisted_origin_rejected(self):
        cors = CorsConfig(allow_origins=["https://first.com", "https://second.com"])
        app = _make_app(cors_config=cors)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.options(
                "/mcp",
                headers={
                    "Origin": "https://third.com",
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert "access-control-allow-origin" not in resp.headers


class TestCorsLogging:
    def test_cors_enabled_logs_info(self, caplog):
        cors = CorsConfig(allow_origins=["https://example.com", "https://other.com"])
        with caplog.at_level(logging.INFO, logger="mcp_zero.proxy.app"):
            _make_app(cors_config=cors)
        assert any("CORS middleware enabled" in r.message for r in caplog.records)
        assert any("https://example.com" in r.message for r in caplog.records)
