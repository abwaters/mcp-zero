"""stdio transport for locally-spawned MCP servers."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_zero.context import RequestContext
from mcp_zero.transport.base import MCPTransport, TransportState
from mcp_zero.transport.errors import ProcessError, SessionError, TransportConnectionError

logger = logging.getLogger(__name__)


class StdioTransport(MCPTransport):
    """Wraps the MCP SDK's ``stdio_client`` context manager.

    The connection lifecycle (including cancel scopes created by the SDK's
    internal task groups) is owned by a dedicated background task so that
    callers' cancel-scope stacks stay clean.  Without this isolation,
    entering ``stdio_client`` or ``ClientSession`` inside an MCP request
    handler corrupts the handler's cancel-scope stack and crashes the
    gateway session.

    Provides health checking and reconnection support for the
    ``StdioProcessManager`` lifecycle layer.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._last_context: RequestContext | None = None
        self._bg_task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None

    async def connect(
        self, context: RequestContext | None = None, *, auth_token: str | None = None
    ) -> None:
        if self._state == TransportState.CONNECTED:
            return

        # Clean up any leftover background task from a previous failed attempt.
        await self._cleanup_bg_task()

        if context is not None:
            self._last_context = context
        cid = context.correlation_id if context else ""
        self._state = TransportState.CONNECTING

        ready = asyncio.Event()
        connect_error: list[BaseException | None] = [None]
        self._stop_event = asyncio.Event()
        stop_event = self._stop_event  # capture for closure

        # Build env and params before spawning the background task so that
        # parameter-validation errors surface synchronously.
        env = dict(self._config.env) if self._config.env else None
        if context and env is not None:
            env["MCP_CORRELATION_ID"] = context.correlation_id
            if context.trace_id is not None:
                env["MCP_TRACE_ID"] = context.trace_id
        elif context:
            env = {"MCP_CORRELATION_ID": context.correlation_id}
            if context.trace_id is not None:
                env["MCP_TRACE_ID"] = context.trace_id

        params = StdioServerParameters(
            command=self._config.command,  # type: ignore[arg-type]
            args=list(self._config.args),
            env=env,
        )

        async def _connection_owner() -> None:
            """Background task that owns context-manager lifetimes.

            Cancel scopes from ``stdio_client`` and ``ClientSession`` live on
            *this* task's cancel-scope stack, keeping the caller's stack clean
            and avoiding AnyIO cancel-scope ordering violations.
            """
            stack: AsyncExitStack | None = None
            try:
                stack = AsyncExitStack()
                read_stream, write_stream = await stack.enter_async_context(
                    stdio_client(params)
                )
                session = await stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
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
                        logger.debug("Error closing stdio transport stack", exc_info=True)

        try:
            self._bg_task = asyncio.create_task(_connection_owner())
            await ready.wait()

            if connect_error[0] is not None:
                await self._cleanup_bg_task()
                exc = connect_error[0]
                if isinstance(exc, (FileNotFoundError, PermissionError)):
                    raise ProcessError(
                        f"Failed to spawn '{self._config.command}' "
                        f"for '{self._config.name}': {exc}",
                        server_name=self._config.name,
                        correlation_id=cid,
                    ) from exc
                if isinstance(exc, (TransportConnectionError, ProcessError)):
                    raise exc
                if isinstance(exc, OSError):
                    raise TransportConnectionError(
                        f"Failed to connect to '{self._config.name}': {exc}",
                        server_name=self._config.name,
                        correlation_id=cid,
                    ) from exc
                raise SessionError(
                    f"Session error for '{self._config.name}': {exc}",
                    server_name=self._config.name,
                    correlation_id=cid,
                ) from exc
        except (TransportConnectionError, ProcessError, SessionError):
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

    def is_healthy(self) -> bool:
        """Fast state check — no I/O."""
        return self._state == TransportState.CONNECTED and self._session is not None

    async def reconnect(self, context: RequestContext | None = None) -> None:
        """Disconnect then connect, reusing the stored context if none is provided."""
        await self.disconnect()
        await self.connect(context=context or self._last_context)
