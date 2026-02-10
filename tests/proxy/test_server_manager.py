"""Tests for server manager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_zero.context import RequestContext
from mcp_zero.proxy.errors import RoutingError
from mcp_zero.proxy.server_manager import ServerManager
from mcp_zero.transport.base import TransportState
from mcp_zero.transport.config import ServerConfig, TransportType


def make_configs():
    return [
        ServerConfig(
            name="weather",
            transport=TransportType.HTTP,
            url="http://weather:8080",
            allow_insecure=True,
        ),
        ServerConfig(
            name="db",
            transport=TransportType.HTTP,
            url="http://db:8080",
            allow_insecure=True,
        ),
    ]


def make_mock_transport(connected=True):
    """Create a mock transport with a mock session."""
    transport = AsyncMock()
    transport.state = TransportState.CONNECTED if connected else TransportState.DISCONNECTED
    transport.session = MagicMock()
    transport.connect = AsyncMock()
    transport.disconnect = AsyncMock()
    return transport


class TestServerManager:
    def test_server_names(self):
        mgr = ServerManager(make_configs())
        assert set(mgr.server_names) == {"weather", "db"}

    def test_get_config(self):
        mgr = ServerManager(make_configs())
        cfg = mgr.get_config("weather")
        assert cfg.name == "weather"

    def test_get_config_unknown_raises(self):
        mgr = ServerManager(make_configs())
        with pytest.raises(RoutingError, match="No configuration"):
            mgr.get_config("unknown")

    @pytest.mark.asyncio
    async def test_get_session_creates_transport(self):
        mgr = ServerManager(make_configs())
        mock_transport = make_mock_transport(connected=False)

        # After connect(), state should be CONNECTED
        async def fake_connect(ctx=None, *, auth_token=None):
            mock_transport.state = TransportState.CONNECTED

        mock_transport.connect = AsyncMock(side_effect=fake_connect)

        with patch(
            "mcp_zero.proxy.server_manager.TransportFactory.create",
            return_value=mock_transport,
        ):
            session = await mgr.get_session("weather")

        mock_transport.connect.assert_awaited_once()
        assert session is mock_transport.session

    @pytest.mark.asyncio
    async def test_get_session_reuses_transport(self):
        mgr = ServerManager(make_configs())
        mock_transport = make_mock_transport(connected=False)

        async def fake_connect(ctx=None, *, auth_token=None):
            mock_transport.state = TransportState.CONNECTED

        mock_transport.connect = AsyncMock(side_effect=fake_connect)

        with patch(
            "mcp_zero.proxy.server_manager.TransportFactory.create",
            return_value=mock_transport,
        ) as mock_create:
            await mgr.get_session("weather")
            await mgr.get_session("weather")

        # Factory called once; connect called once (already connected on second call)
        mock_create.assert_called_once()
        mock_transport.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_session_passes_context_and_auth(self):
        mgr = ServerManager(make_configs())
        mock_transport = make_mock_transport(connected=False)

        async def fake_connect(ctx=None, *, auth_token=None):
            mock_transport.state = TransportState.CONNECTED

        mock_transport.connect = AsyncMock(side_effect=fake_connect)
        ctx = RequestContext()

        with patch(
            "mcp_zero.proxy.server_manager.TransportFactory.create",
            return_value=mock_transport,
        ):
            await mgr.get_session("weather", ctx, auth_token="tok")

        mock_transport.connect.assert_awaited_once_with(ctx, auth_token="tok")

    @pytest.mark.asyncio
    async def test_disconnect_single(self):
        mgr = ServerManager(make_configs())
        mock_transport = make_mock_transport()

        with patch(
            "mcp_zero.proxy.server_manager.TransportFactory.create",
            return_value=mock_transport,
        ):
            await mgr.get_session("weather")

        await mgr.disconnect("weather")
        mock_transport.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_all(self):
        mgr = ServerManager(make_configs())
        mock_w = make_mock_transport(connected=False)
        mock_d = make_mock_transport(connected=False)

        async def fake_connect_w(ctx=None, *, auth_token=None):
            mock_w.state = TransportState.CONNECTED

        async def fake_connect_d(ctx=None, *, auth_token=None):
            mock_d.state = TransportState.CONNECTED

        mock_w.connect = AsyncMock(side_effect=fake_connect_w)
        mock_d.connect = AsyncMock(side_effect=fake_connect_d)

        transports = {"weather": mock_w, "db": mock_d}
        call_count = {"n": 0}

        def create_side_effect(config):
            call_count["n"] += 1
            return transports[config.name]

        with patch(
            "mcp_zero.proxy.server_manager.TransportFactory.create",
            side_effect=create_side_effect,
        ):
            await mgr.get_session("weather")
            await mgr.get_session("db")

        await mgr.disconnect_all()
        mock_w.disconnect.assert_awaited_once()
        mock_d.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        mgr = ServerManager(make_configs())
        mock_transport = make_mock_transport(connected=False)

        async def fake_connect(ctx=None, *, auth_token=None):
            mock_transport.state = TransportState.CONNECTED

        mock_transport.connect = AsyncMock(side_effect=fake_connect)

        with patch(
            "mcp_zero.proxy.server_manager.TransportFactory.create",
            return_value=mock_transport,
        ):
            async with mgr as m:
                await m.get_session("weather")

        mock_transport.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_is_noop(self):
        mgr = ServerManager(make_configs())
        # Should not raise
        await mgr.disconnect("weather")
