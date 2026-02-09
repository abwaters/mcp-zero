"""Transport error hierarchy."""

from __future__ import annotations


class TransportError(Exception):
    """Base error for all transport operations."""

    def __init__(self, message: str, *, server_name: str = "", correlation_id: str = "") -> None:
        self.server_name = server_name
        self.correlation_id = correlation_id
        super().__init__(message)


class TransportConnectionError(TransportError):
    """Failed to establish connection to an MCP server."""


class TransportTimeoutError(TransportError):
    """Operation timed out."""


class SessionError(TransportError):
    """MCP session or protocol-level error."""


class TransportClosedError(TransportError):
    """Operation attempted on a closed or disconnected transport."""


class ProcessError(TransportError):
    """stdio process lifecycle error (spawn failure, unexpected exit)."""
