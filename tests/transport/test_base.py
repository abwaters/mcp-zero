"""Tests for abstract transport base class."""

import pytest

from mcp_zero.transport.base import MCPTransport, TransportState
from mcp_zero.transport.config import ServerConfig, TransportType
from mcp_zero.transport.errors import TransportClosedError


class TestTransportState:
    def test_values(self):
        assert TransportState.DISCONNECTED == "disconnected"
        assert TransportState.CONNECTING == "connecting"
        assert TransportState.CONNECTED == "connected"
        assert TransportState.DISCONNECTING == "disconnecting"
        assert TransportState.ERROR == "error"


class TestMCPTransportABC:
    def test_cannot_instantiate(self):
        cfg = ServerConfig(name="test", transport=TransportType.HTTP, url="https://localhost")
        with pytest.raises(TypeError, match="abstract"):
            MCPTransport(cfg)  # type: ignore[abstract]

    def test_initial_state(self):
        """Verify initial state through a minimal concrete subclass."""

        class DummyTransport(MCPTransport):
            async def connect(self, context=None):
                pass

            async def disconnect(self):
                pass

        cfg = ServerConfig(name="test", transport=TransportType.HTTP, url="https://localhost")
        t = DummyTransport(cfg)
        assert t.state == TransportState.DISCONNECTED
        assert t.config is cfg

    def test_session_raises_when_disconnected(self):
        class DummyTransport(MCPTransport):
            async def connect(self, context=None):
                pass

            async def disconnect(self):
                pass

        cfg = ServerConfig(name="test", transport=TransportType.HTTP, url="https://localhost")
        t = DummyTransport(cfg)
        with pytest.raises(TransportClosedError, match="not connected"):
            _ = t.session

    @pytest.mark.asyncio
    async def test_context_manager(self):
        connected = False
        disconnected = False

        class DummyTransport(MCPTransport):
            async def connect(self, context=None):
                nonlocal connected
                connected = True

            async def disconnect(self):
                nonlocal disconnected
                disconnected = True

        cfg = ServerConfig(name="test", transport=TransportType.HTTP, url="https://localhost")
        async with DummyTransport(cfg) as t:
            assert connected
            assert isinstance(t, DummyTransport)
        assert disconnected

    @pytest.mark.asyncio
    async def test_context_manager_disconnect_on_error(self):
        disconnected = False

        class DummyTransport(MCPTransport):
            async def connect(self, context=None):
                pass

            async def disconnect(self):
                nonlocal disconnected
                disconnected = True

        cfg = ServerConfig(name="test", transport=TransportType.HTTP, url="https://localhost")
        with pytest.raises(RuntimeError):
            async with DummyTransport(cfg):
                raise RuntimeError("boom")
        assert disconnected
