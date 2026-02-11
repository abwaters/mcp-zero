"""Tests for server manager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_zero.context import RequestContext, UserIdentity
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
    async def test_different_users_get_different_sessions(self):
        """Each authenticated user should get an isolated transport session."""
        mgr = ServerManager(make_configs())

        transport_a = make_mock_transport(connected=False)
        transport_b = make_mock_transport(connected=False)
        transports = iter([transport_a, transport_b])

        async def fake_connect_a(ctx=None, *, auth_token=None):
            transport_a.state = TransportState.CONNECTED

        async def fake_connect_b(ctx=None, *, auth_token=None):
            transport_b.state = TransportState.CONNECTED

        transport_a.connect = AsyncMock(side_effect=fake_connect_a)
        transport_b.connect = AsyncMock(side_effect=fake_connect_b)

        ctx_a = RequestContext(identity=UserIdentity(user_id="user-A"))
        ctx_b = RequestContext(identity=UserIdentity(user_id="user-B"))

        with patch(
            "mcp_zero.proxy.server_manager.TransportFactory.create",
            side_effect=lambda _: next(transports),
        ):
            session_a = await mgr.get_session("weather", ctx_a, auth_token="tok-A")
            session_b = await mgr.get_session("weather", ctx_b, auth_token="tok-B")

        # Different users get different sessions
        assert session_a is transport_a.session
        assert session_b is transport_b.session
        assert session_a is not session_b

        # Each transport connected with its own auth token
        transport_a.connect.assert_awaited_once_with(ctx_a, auth_token="tok-A")
        transport_b.connect.assert_awaited_once_with(ctx_b, auth_token="tok-B")

    @pytest.mark.asyncio
    async def test_same_user_reuses_session(self):
        """Repeated requests from the same user should reuse the transport."""
        mgr = ServerManager(make_configs())
        mock_transport = make_mock_transport(connected=False)

        async def fake_connect(ctx=None, *, auth_token=None):
            mock_transport.state = TransportState.CONNECTED

        mock_transport.connect = AsyncMock(side_effect=fake_connect)

        ctx1 = RequestContext(identity=UserIdentity(user_id="user-A"))
        ctx2 = RequestContext(identity=UserIdentity(user_id="user-A"))

        with patch(
            "mcp_zero.proxy.server_manager.TransportFactory.create",
            return_value=mock_transport,
        ) as mock_create:
            session1 = await mgr.get_session("weather", ctx1, auth_token="tok-A")
            session2 = await mgr.get_session("weather", ctx2, auth_token="tok-A")

        assert session1 is session2
        mock_create.assert_called_once()
        mock_transport.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_identity_shares_session(self):
        """Requests without identity share a single transport (no auth to isolate)."""
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

        mock_create.assert_called_once()
        mock_transport.connect.assert_awaited_once()

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
    async def test_disconnect_removes_all_user_sessions_for_server(self):
        """disconnect(server_name) should remove all per-user transports for that server."""
        mgr = ServerManager(make_configs())

        transport_a = make_mock_transport(connected=False)
        transport_b = make_mock_transport(connected=False)
        transports = iter([transport_a, transport_b])

        async def fake_connect_a(ctx=None, *, auth_token=None):
            transport_a.state = TransportState.CONNECTED

        async def fake_connect_b(ctx=None, *, auth_token=None):
            transport_b.state = TransportState.CONNECTED

        transport_a.connect = AsyncMock(side_effect=fake_connect_a)
        transport_b.connect = AsyncMock(side_effect=fake_connect_b)

        ctx_a = RequestContext(identity=UserIdentity(user_id="user-A"))
        ctx_b = RequestContext(identity=UserIdentity(user_id="user-B"))

        with patch(
            "mcp_zero.proxy.server_manager.TransportFactory.create",
            side_effect=lambda _: next(transports),
        ):
            await mgr.get_session("weather", ctx_a, auth_token="tok-A")
            await mgr.get_session("weather", ctx_b, auth_token="tok-B")

        await mgr.disconnect("weather")

        transport_a.disconnect.assert_awaited_once()
        transport_b.disconnect.assert_awaited_once()

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
