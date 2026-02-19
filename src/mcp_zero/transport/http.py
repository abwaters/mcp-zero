"""Streamable HTTP transport for remote MCP servers."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from mcp_zero.context import RequestContext
from mcp_zero.transport.base import MCPTransport, TransportState
from mcp_zero.transport.errors import SessionError, TransportConnectionError

logger = logging.getLogger(__name__)


class StreamableHTTPTransport(MCPTransport):
    """Wraps the MCP SDK's ``streamable_http_client`` context manager.

    The connection lifecycle (including cancel scopes created by the SDK's
    internal task groups) is owned by a dedicated background task so that
    callers' cancel-scope stacks stay clean.  Without this isolation,
    entering ``streamable_http_client`` or ``ClientSession`` inside an MCP
    request handler corrupts the handler's cancel-scope stack and crashes
    the gateway session.
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

        ready = asyncio.Event()
        connect_error: list[BaseException | None] = [None]
        self._stop_event = asyncio.Event()
        stop_event = self._stop_event  # capture for closure

        async def _connection_owner() -> None:
            """Background task that owns context-manager lifetimes.

            Cancel scopes from ``streamable_http_client`` and ``ClientSession``
            live on *this* task's cancel-scope stack, keeping the caller's
            stack clean and avoiding AnyIO cancel-scope ordering violations.
            """
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

                http_client: httpx.AsyncClient | None = None
                if headers:
                    http_client = await stack.enter_async_context(
                        httpx.AsyncClient(
                            headers=headers,
                            timeout=httpx.Timeout(self._config.timeout_seconds),
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
                        logger.debug("Error closing HTTP transport stack", exc_info=True)

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
