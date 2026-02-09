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
    async def test_connect_merges_env_with_correlation(self, mock_sdk):
        cfg = make_stdio_config(env={"EXISTING": "value"})
        ctx = RequestContext(correlation_id="corr-456")
        t = StdioTransport(cfg)

        await t.connect(context=ctx)

        call_args = mock_sdk["client"].call_args[0][0]
        assert call_args.env["EXISTING"] == "value"
        assert call_args.env["MCP_CORRELATION_ID"] == "corr-456"

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
    async def test_context_manager(self, mock_sdk):
        cfg = make_stdio_config()
        async with StdioTransport(cfg) as t:
            assert t.state == TransportState.CONNECTED
        assert t.state == TransportState.DISCONNECTED
