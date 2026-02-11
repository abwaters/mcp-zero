"""Tests for stdio transport."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_zero.context import RequestContext
from mcp_zero.transport.base import TransportState
from mcp_zero.transport.config import ServerConfig, TransportType
from mcp_zero.transport.errors import ProcessError, SessionError, TransportClosedError
from mcp_zero.transport.stdio import StdioTransport


def make_stdio_config(name="test-stdio", command="python", args=None, env=None):
    return ServerConfig(
        name=name,
        transport=TransportType.STDIO,
        command=command,
        args=args or [],
        env=env or {},
    )


@pytest.fixture
def mock_sdk(monkeypatch):
    """Mock the MCP SDK's stdio_client and ClientSession."""
    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()

    read_stream = MagicMock()
    write_stream = MagicMock()

    mock_stdio_cm = AsyncMock()
    mock_stdio_cm.__aenter__ = AsyncMock(return_value=(read_stream, write_stream))
    mock_stdio_cm.__aexit__ = AsyncMock(return_value=False)

    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "mcp_zero.transport.stdio.stdio_client",
            return_value=mock_stdio_cm,
        ) as mock_client,
        patch(
            "mcp_zero.transport.stdio.ClientSession",
            return_value=mock_session_cm,
        ) as mock_session_cls,
    ):
        yield {
            "client": mock_client,
            "session_cls": mock_session_cls,
            "session": mock_session,
        }


class TestStdioTransport:
    @pytest.mark.asyncio
    async def test_connect_success(self, mock_sdk):
        cfg = make_stdio_config()
        t = StdioTransport(cfg)

        await t.connect()

        assert t.state == TransportState.CONNECTED
        assert t.session is mock_sdk["session"]
        mock_sdk["session"].initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_passes_params(self, mock_sdk):
        cfg = make_stdio_config(command="node", args=["server.js"], env={"DEBUG": "1"})
        t = StdioTransport(cfg)

        await t.connect()

        call_args = mock_sdk["client"].call_args[0][0]
        assert call_args.command == "node"
        assert call_args.args == ["server.js"]
        assert call_args.env["DEBUG"] == "1"

    @pytest.mark.asyncio
    async def test_connect_injects_correlation_id(self, mock_sdk):
        cfg = make_stdio_config()
        ctx = RequestContext(correlation_id="test-123")
        t = StdioTransport(cfg)

        await t.connect(context=ctx)

        call_args = mock_sdk["client"].call_args[0][0]
        assert call_args.env["MCP_CORRELATION_ID"] == "test-123"

    @pytest.mark.asyncio
    async def test_connect_injects_trace_id(self, mock_sdk):
        cfg = make_stdio_config()
        ctx = RequestContext(correlation_id="c-1", trace_id="t-1")
        t = StdioTransport(cfg)

        await t.connect(context=ctx)

        call_args = mock_sdk["client"].call_args[0][0]
        assert call_args.env["MCP_TRACE_ID"] == "t-1"

    @pytest.mark.asyncio
    async def test_connect_no_trace_id_omits_env_var(self, mock_sdk):
        cfg = make_stdio_config()
        ctx = RequestContext(correlation_id="c-1")  # trace_id defaults to None
        t = StdioTransport(cfg)

        await t.connect(context=ctx)

        call_args = mock_sdk["client"].call_args[0][0]
        assert call_args.env["MCP_CORRELATION_ID"] == "c-1"
        assert "MCP_TRACE_ID" not in call_args.env

    @pytest.mark.asyncio
    async def test_connect_no_trace_id_omits_env_var_with_existing_env(self, mock_sdk):
        cfg = make_stdio_config(env={"EXISTING": "value"})
        ctx = RequestContext(correlation_id="c-1")  # trace_id defaults to None
        t = StdioTransport(cfg)

        await t.connect(context=ctx)

        call_args = mock_sdk["client"].call_args[0][0]
        assert call_args.env["EXISTING"] == "value"
        assert call_args.env["MCP_CORRELATION_ID"] == "c-1"
        assert "MCP_TRACE_ID" not in call_args.env

    @pytest.mark.asyncio
    async def test_connect_merges_env_with_correlation(self, mock_sdk):
        cfg = make_stdio_config(env={"EXISTING": "value"})
        ctx = RequestContext(correlation_id="corr-456", trace_id="trace-789")
        t = StdioTransport(cfg)

        await t.connect(context=ctx)

        call_args = mock_sdk["client"].call_args[0][0]
        assert call_args.env["EXISTING"] == "value"
        assert call_args.env["MCP_CORRELATION_ID"] == "corr-456"
        assert call_args.env["MCP_TRACE_ID"] == "trace-789"

    @pytest.mark.asyncio
    async def test_connect_idempotent(self, mock_sdk):
        cfg = make_stdio_config()
        t = StdioTransport(cfg)

        await t.connect()
        await t.connect()

        mock_sdk["client"].assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect(self, mock_sdk):
        cfg = make_stdio_config()
        t = StdioTransport(cfg)

        await t.connect()
        await t.disconnect()

        assert t.state == TransportState.DISCONNECTED
        with pytest.raises(TransportClosedError):
            _ = t.session


    @pytest.mark.asyncio
    async def test_disconnect_from_different_task_skips_exit_stack_close(self, mock_sdk):
        cfg = make_stdio_config()
        t = StdioTransport(cfg)
        await t.connect()

        mock_exit_stack = AsyncMock()
        t._exit_stack = mock_exit_stack
        t._owner_task_id = 12345

        with patch("mcp_zero.transport.stdio.anyio.get_current_task", return_value=object()):
            await t.disconnect()

        mock_exit_stack.aclose.assert_not_awaited()
        assert t.state == TransportState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_disconnect_idempotent(self, mock_sdk):
        cfg = make_stdio_config()
        t = StdioTransport(cfg)
        await t.disconnect()
        assert t.state == TransportState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_connect_file_not_found(self, mock_sdk):
        mock_sdk["client"].return_value.__aenter__.side_effect = FileNotFoundError("no such cmd")
        cfg = make_stdio_config(command="nonexistent")
        t = StdioTransport(cfg)

        with pytest.raises(ProcessError, match="nonexistent"):
            await t.connect()
        assert t.state == TransportState.ERROR

    @pytest.mark.asyncio
    async def test_connect_permission_error(self, mock_sdk):
        mock_sdk["client"].return_value.__aenter__.side_effect = PermissionError("denied")
        cfg = make_stdio_config()
        t = StdioTransport(cfg)

        with pytest.raises(ProcessError, match="denied"):
            await t.connect()
        assert t.state == TransportState.ERROR

    @pytest.mark.asyncio
    async def test_connect_session_error(self, mock_sdk):
        mock_sdk["session"].initialize.side_effect = RuntimeError("bad handshake")
        cfg = make_stdio_config()
        t = StdioTransport(cfg)

        with pytest.raises(SessionError, match="bad handshake"):
            await t.connect()
        assert t.state == TransportState.ERROR

    @pytest.mark.asyncio
    async def test_error_carries_correlation_id(self, mock_sdk):
        mock_sdk["client"].return_value.__aenter__.side_effect = FileNotFoundError("gone")
        cfg = make_stdio_config()
        ctx = RequestContext(correlation_id="err-cid")
        t = StdioTransport(cfg)

        with pytest.raises(ProcessError) as exc_info:
            await t.connect(context=ctx)
        assert exc_info.value.correlation_id == "err-cid"

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_sdk):
        cfg = make_stdio_config()
        async with StdioTransport(cfg) as t:
            assert t.state == TransportState.CONNECTED
        assert t.state == TransportState.DISCONNECTED


class TestStdioTransportHealth:
    @pytest.mark.asyncio
    async def test_healthy_when_connected(self, mock_sdk):
        cfg = make_stdio_config()
        t = StdioTransport(cfg)
        await t.connect()
        assert t.is_healthy() is True

    def test_unhealthy_when_disconnected(self):
        cfg = make_stdio_config()
        t = StdioTransport(cfg)
        assert t.is_healthy() is False

    @pytest.mark.asyncio
    async def test_unhealthy_after_disconnect(self, mock_sdk):
        cfg = make_stdio_config()
        t = StdioTransport(cfg)
        await t.connect()
        await t.disconnect()
        assert t.is_healthy() is False

    @pytest.mark.asyncio
    async def test_unhealthy_in_error_state(self, mock_sdk):
        mock_sdk["session"].initialize.side_effect = RuntimeError("fail")
        cfg = make_stdio_config()
        t = StdioTransport(cfg)
        with pytest.raises(Exception):
            await t.connect()
        assert t.state == TransportState.ERROR
        assert t.is_healthy() is False

    @pytest.mark.asyncio
    async def test_reconnect_success(self, mock_sdk):
        cfg = make_stdio_config()
        t = StdioTransport(cfg)
        await t.connect()
        assert t.is_healthy() is True

        await t.reconnect()
        assert t.is_healthy() is True
        assert t.state == TransportState.CONNECTED

    @pytest.mark.asyncio
    async def test_reconnect_reuses_stored_context(self, mock_sdk):
        cfg = make_stdio_config()
        ctx = RequestContext(correlation_id="stored-ctx")
        t = StdioTransport(cfg)
        await t.connect(context=ctx)

        await t.reconnect()

        # Second connect call should use stored context
        call_args = mock_sdk["client"].call_args[0][0]
        assert call_args.env["MCP_CORRELATION_ID"] == "stored-ctx"

    @pytest.mark.asyncio
    async def test_reconnect_with_new_context(self, mock_sdk):
        cfg = make_stdio_config()
        ctx1 = RequestContext(correlation_id="old-ctx")
        ctx2 = RequestContext(correlation_id="new-ctx")
        t = StdioTransport(cfg)
        await t.connect(context=ctx1)

        await t.reconnect(context=ctx2)

        call_args = mock_sdk["client"].call_args[0][0]
        assert call_args.env["MCP_CORRELATION_ID"] == "new-ctx"

    @pytest.mark.asyncio
    async def test_reconnect_from_error_state(self, mock_sdk):
        cfg = make_stdio_config()
        t = StdioTransport(cfg)
        await t.connect()

        # Force error state
        t._state = TransportState.ERROR
        await t.reconnect()
        assert t.is_healthy() is True
