"""SSE transport for remote MCP servers using the deprecated SSE protocol."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack

from mcp import ClientSession
from mcp.client.sse import sse_client

from mcp_zero.context import RequestContext
from mcp_zero.transport.base import MCPTransport, TransportState
from mcp_zero.transport.errors import SessionError, TransportConnectionError

logger = logging.getLogger(__name__)


class SSETransport(MCPTransport):
    """Wraps the MCP SDK's ``sse_client`` context manager.

    Uses the same background-task isolation pattern as
    ``StreamableHTTPTransport``: a dedicated asyncio task owns all
    context-manager lifetimes so the caller's cancel-scope stack stays
    clean.

    .. note::

        SSE transport is **deprecated** in MCP protocol version 2025-03-26.
        It is provided for backward compatibility with servers that have not
        yet adopted Streamable HTTP.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._bg_task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None

    async def connect(
        self, context: RequestContext | None = None, *, auth_token: str | None = None
    ) -> None:
        if self._state == TransportState.CONNECTED:
            return

        # Clean up any leftover background task from a previous failed attempt.
        await self._cleanup_bg_task()

        cid = context.correlation_id if context else ""
        self._state = TransportState.CONNECTING

        logger.info(
            "Connecting to SSE server '%s' at %s (deprecated transport)",
            self._config.name,
            self._config.url,
        )

        ready = asyncio.Event()
        connect_error: list[BaseException | None] = [None]
        self._stop_event = asyncio.Event()
        stop_event = self._stop_event  # capture for closure

        async def _connection_owner() -> None:
            """Background task that owns context-manager lifetimes."""
            stack: AsyncExitStack | None = None
            try:
                stack = AsyncExitStack()

                headers: dict[str, str] = {}
                # Static headers from server config (lowest priority)
                if self._config.headers:
                    headers.update(self._config.headers)
                if context:
                    headers["X-Correlation-ID"] = context.correlation_id
                    if context.trace_id is not None:
                        headers["X-Trace-ID"] = context.trace_id
                if auth_token:
                    headers["Authorization"] = f"Bearer {auth_token}"

                read_stream, write_stream = await stack.enter_async_context(
                    sse_client(
                        self._config.url,  # type: ignore[arg-type]
                        headers=headers,
                        sse_read_timeout=self._config.timeout_seconds,
                    )
                )
                session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
                await session.initialize()

                self._session = session
                self._state = TransportState.CONNECTED
                ready.set()

                # Keep context managers alive until disconnect is requested.
                await stop_event.wait()

            except BaseException as exc:
                if not ready.is_set():
                    connect_error[0] = exc
                    self._state = TransportState.ERROR
                    ready.set()
            finally:
                self._session = None
                if stack is not None:
                    try:
                        await stack.aclose()
                    except BaseException:
                        logger.debug("Error closing SSE transport stack", exc_info=True)

        try:
            self._bg_task = asyncio.create_task(_connection_owner())
            await ready.wait()

            if connect_error[0] is not None:
                await self._cleanup_bg_task()
                exc = connect_error[0]
                if isinstance(exc, TransportConnectionError):
                    raise exc
                if isinstance(exc, OSError):
                    raise TransportConnectionError(
                        f"Failed to connect to '{self._config.name}' at {self._config.url}: {exc}",
                        server_name=self._config.name,
                        correlation_id=cid,
                    ) from exc
                raise SessionError(
                    f"Session error for '{self._config.name}': {exc}",
                    server_name=self._config.name,
                    correlation_id=cid,
                ) from exc
        except (TransportConnectionError, SessionError):
            self._state = TransportState.ERROR
            raise

    async def disconnect(self) -> None:
        if self._state not in (TransportState.CONNECTED, TransportState.ERROR):
            return

        self._state = TransportState.DISCONNECTING
        try:
            await self._cleanup_bg_task()
            self._session = None
            self._state = TransportState.DISCONNECTED
        except Exception:
            self._state = TransportState.ERROR
            raise

    async def _cleanup_bg_task(self) -> None:
        """Signal the background task to stop and wait for it to finish."""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._bg_task is not None:
            try:
                await self._bg_task
            except BaseException:
                pass
            self._bg_task = None
        self._stop_event = None
