"""Auth provider interface for OBO token exchange."""

from __future__ import annotations

from abc import ABC, abstractmethod

from mcp_zero.context import RequestContext


class AuthProvider(ABC):
    """Abstract base for obtaining auth tokens for upstream MCP servers.

    Epic 2 will supply a concrete OBO implementation.
    """

    @abstractmethod
    async def get_token(self, server_name: str, context: RequestContext) -> str | None:
        """Return a bearer token for the given upstream server, or None."""


class NoAuthProvider(AuthProvider):
    """Default no-op provider — returns no token."""

    async def get_token(self, server_name: str, context: RequestContext) -> str | None:
        return None
