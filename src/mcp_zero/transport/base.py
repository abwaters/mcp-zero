"""Abstract transport interface for MCP server communication."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Self

from mcp import ClientSession

from mcp_zero.context import RequestContext
from mcp_zero.transport.config import ServerConfig
from mcp_zero.transport.errors import TransportClosedError


class TransportState(StrEnum):
    """Lifecycle state of a transport connection."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    ERROR = "error"


class MCPTransport(ABC):
    """Abstract base for MCP server transports.

    Business logic accesses the SDK's ClientSession via ``transport.session``
    and never imports transport-specific code.
    """

    def __init__(self, config: ServerConfig) -> None:
        self._config = config
        self._state = TransportState.DISCONNECTED
        self._session: ClientSession | None = None

    @property
    def config(self) -> ServerConfig:
        return self._config

    @property
    def state(self) -> TransportState:
        return self._state

    @property
    def session(self) -> ClientSession:
        """Return the active MCP session.

        Raises TransportClosedError if not connected.
        """
        if self._state != TransportState.CONNECTED or self._session is None:
            raise TransportClosedError(
                f"Transport to '{self._config.name}' is not connected (state={self._state})",
                server_name=self._config.name,
            )
        return self._session

    @abstractmethod
    async def connect(
        self, context: RequestContext | None = None, *, auth_token: str | None = None
    ) -> None:
        """Establish connection and initialize the MCP session."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection and release resources."""

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.disconnect()
