"""Proxy error hierarchy."""

from __future__ import annotations


class ProxyError(Exception):
    """Base error for all proxy operations."""

    def __init__(self, message: str, *, server_name: str = "", correlation_id: str = "") -> None:
        self.server_name = server_name
        self.correlation_id = correlation_id
        super().__init__(message)


class RoutingError(ProxyError):
    """Tool could not be routed to any upstream server."""


class UpstreamError(ProxyError):
    """Upstream MCP server returned an error."""


class ProxyTimeoutError(ProxyError):
    """Upstream call exceeded timeout."""
