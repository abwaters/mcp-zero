"""Factory for creating transport instances from configuration."""

from __future__ import annotations

from mcp_zero.transport.base import MCPTransport
from mcp_zero.transport.config import ServerConfig, TransportType
from mcp_zero.transport.http import StreamableHTTPTransport
from mcp_zero.transport.stdio import StdioTransport


class TransportFactory:
    """Creates transport instances based on server configuration."""

    _registry: dict[TransportType, type[MCPTransport]] = {
        TransportType.HTTP: StreamableHTTPTransport,
        TransportType.STDIO: StdioTransport,
    }

    @classmethod
    def create(cls, config: ServerConfig) -> MCPTransport:
        """Return an unconnected transport for the given config."""
        transport_cls = cls._registry.get(config.transport)
        if transport_cls is None:
            raise ValueError(f"No transport registered for type '{config.transport}'")
        return transport_cls(config)

    @classmethod
    def register(cls, transport_type: TransportType, transport_cls: type[MCPTransport]) -> None:
        """Register a custom transport class for a transport type."""
        cls._registry[transport_type] = transport_cls
