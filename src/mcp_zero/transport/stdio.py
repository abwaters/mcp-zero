"""stdio transport for locally-spawned MCP servers."""

from __future__ import annotations

from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_zero.context import RequestContext
from mcp_zero.transport.base import MCPTransport, TransportState
from mcp_zero.transport.errors import ProcessError, SessionError, TransportConnectionError


class StdioTransport(MCPTransport):
    """Wraps the MCP SDK's ``stdio_client`` context manager.

    Story #9 will add health monitoring and restart logic.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._exit_stack: AsyncExitStack | None = None

    async def connect(self, context: RequestContext | None = None) -> None:
        if self._state == TransportState.CONNECTED:
            return

        self._state = TransportState.CONNECTING
        try:
            env = dict(self._config.env) if self._config.env else None
            if context and env is not None:
                env["MCP_CORRELATION_ID"] = context.correlation_id
            elif context:
                env = {"MCP_CORRELATION_ID": context.correlation_id}

            params = StdioServerParameters(
                command=self._config.command,  # type: ignore[arg-type]
                args=list(self._config.args),
                env=env,
            )

            stack = AsyncExitStack()
            read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()

            self._exit_stack = stack
            self._session = session
            self._state = TransportState.CONNECTED
        except (FileNotFoundError, PermissionError) as exc:
            self._state = TransportState.ERROR
            raise ProcessError(
                f"Failed to spawn '{self._config.command}' for '{self._config.name}': {exc}",
                server_name=self._config.name,
            ) from exc
        except (TransportConnectionError, ProcessError):
            self._state = TransportState.ERROR
            raise
        except OSError as exc:
            self._state = TransportState.ERROR
            raise TransportConnectionError(
                f"Failed to connect to '{self._config.name}': {exc}",
                server_name=self._config.name,
            ) from exc
        except Exception as exc:
            self._state = TransportState.ERROR
            raise SessionError(
                f"Session error for '{self._config.name}': {exc}",
                server_name=self._config.name,
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
