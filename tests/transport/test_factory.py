"""Tests for transport factory."""

import pytest

from mcp_zero.transport.base import MCPTransport
from mcp_zero.transport.config import ServerConfig, TransportType
from mcp_zero.transport.factory import TransportFactory
from mcp_zero.transport.http import StreamableHTTPTransport
from mcp_zero.transport.stdio import StdioTransport


class TestTransportFactory:
    def test_create_http(self):
        cfg = ServerConfig(name="remote", transport=TransportType.HTTP, url="https://localhost:8080")
        transport = TransportFactory.create(cfg)
        assert isinstance(transport, StreamableHTTPTransport)
        assert transport.config is cfg

    def test_create_stdio(self):
        cfg = ServerConfig(name="local", transport=TransportType.STDIO, command="python")
        transport = TransportFactory.create(cfg)
        assert isinstance(transport, StdioTransport)
        assert transport.config is cfg

    def test_unknown_transport_type(self):
        cfg = ServerConfig.__new__(ServerConfig)
        object.__setattr__(cfg, "name", "bad")
        object.__setattr__(cfg, "transport", "grpc")
        with pytest.raises(ValueError, match="No transport registered"):
            TransportFactory.create(cfg)

    def test_register_custom(self):
        class CustomTransport(MCPTransport):
            async def connect(self, context=None):
                pass

            async def disconnect(self):
                pass

        original = dict(TransportFactory._registry)
        try:
            TransportFactory.register(TransportType.HTTP, CustomTransport)
            cfg = ServerConfig(name="custom", transport=TransportType.HTTP, url="https://localhost")
            transport = TransportFactory.create(cfg)
            assert isinstance(transport, CustomTransport)
        finally:
            TransportFactory._registry = original
