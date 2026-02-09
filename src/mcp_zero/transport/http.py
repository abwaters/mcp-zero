"""Streamable HTTP transport for remote MCP servers."""

from __future__ import annotations

from contextlib import AsyncExitStack

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from mcp_zero.context import RequestContext
from mcp_zero.transport.base import MCPTransport, TransportState
from mcp_zero.transport.errors import SessionError, TransportConnectionError


class StreamableHTTPTransport(MCPTransport):
    """Wraps the MCP SDK's ``streamable_http_client`` context manager.

    Story #8 will add OBO token injection and auth headers.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._exit_stack: AsyncExitStack | None = None

    async def connect(self, context: RequestContext | None = None) -> None:
        if self._state == TransportState.CONNECTED:
            return

        cid = context.correlation_id if context else ""
        self._state = TransportState.CONNECTING
        try:
            stack = AsyncExitStack()

            # Inject correlation / trace headers when a context is available.
            http_client: httpx.AsyncClient | None = None
            if context:
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        headers={
                            "X-Correlation-ID": context.correlation_id,
                            "X-Trace-ID": context.trace_id,
                        }
                    )
                )

            read_stream, write_stream, _ = await stack.enter_async_context(
                streamable_http_client(
                    self._config.url,  # type: ignore[arg-type]
                    http_client=http_client,
                )
            )
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()

            self._exit_stack = stack
            self._session = session
            self._state = TransportState.CONNECTED
        except TransportConnectionError:
            self._state = TransportState.ERROR
            raise
        except OSError as exc:
            self._state = TransportState.ERROR
            raise TransportConnectionError(
                f"Failed to connect to '{self._config.name}' at {self._config.url}: {exc}",
                server_name=self._config.name,
                correlation_id=cid,
            ) from exc
        except Exception as exc:
            self._state = TransportState.ERROR
            raise SessionError(
                f"Session error for '{self._config.name}': {exc}",
                server_name=self._config.name,
                correlation_id=cid,
            ) from exc

    async def disconnect(self) -> None:
        if self._state not in (TransportState.CONNECTED, TransportState.ERROR):
            return

        self._state = TransportState.DISCONNECTING
        try:
            if self._exit_stack is not None:
                await self._exit_stack.aclose()
                self._exit_stack = None
            self._session = None
            self._state = TransportState.DISCONNECTED
        except Exception:
            self._state = TransportState.ERROR
            raise
