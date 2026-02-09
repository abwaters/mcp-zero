"""Tests for HTTP transport."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_zero.transport.base import TransportState
from mcp_zero.transport.config import ServerConfig, TransportType
from mcp_zero.transport.errors import SessionError, TransportClosedError, TransportConnectionError
from mcp_zero.transport.http import StreamableHTTPTransport


def make_http_config(name="test-http", url="http://localhost:8080"):
    return ServerConfig(name=name, transport=TransportType.HTTP, url=url)


@pytest.fixture
def mock_sdk(monkeypatch):
    """Mock the MCP SDK's streamable_http_client and ClientSession."""
    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()

    read_stream = MagicMock()
    write_stream = MagicMock()
    get_session_id = MagicMock(return_value=None)

    # streamable_http_client yields (read, write, get_session_id)
    mock_http_cm = AsyncMock()
    mock_http_cm.__aenter__ = AsyncMock(return_value=(read_stream, write_stream, get_session_id))
    mock_http_cm.__aexit__ = AsyncMock(return_value=False)

    # ClientSession context manager
    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "mcp_zero.transport.http.streamable_http_client",
            return_value=mock_http_cm,
        ) as mock_client,
        patch(
            "mcp_zero.transport.http.ClientSession",
            return_value=mock_session_cm,
        ) as mock_session_cls,
    ):
        yield {
            "client": mock_client,
            "session_cls": mock_session_cls,
            "session": mock_session,
            "read_stream": read_stream,
            "write_stream": write_stream,
        }


class TestStreamableHTTPTransport:
    @pytest.mark.asyncio
    async def test_connect_success(self, mock_sdk):
        cfg = make_http_config()
        t = StreamableHTTPTransport(cfg)

        await t.connect()

        assert t.state == TransportState.CONNECTED
        assert t.session is mock_sdk["session"]
        mock_sdk["client"].assert_called_once_with(cfg.url)
        mock_sdk["session"].initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_idempotent(self, mock_sdk):
        cfg = make_http_config()
        t = StreamableHTTPTransport(cfg)

        await t.connect()
        await t.connect()  # second call should be a no-op

        mock_sdk["client"].assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect(self, mock_sdk):
        cfg = make_http_config()
        t = StreamableHTTPTransport(cfg)

        await t.connect()
        await t.disconnect()

        assert t.state == TransportState.DISCONNECTED
        with pytest.raises(TransportClosedError):
            _ = t.session

    @pytest.mark.asyncio
    async def test_disconnect_idempotent(self, mock_sdk):
        cfg = make_http_config()
        t = StreamableHTTPTransport(cfg)
        # disconnecting when already disconnected is a no-op
        await t.disconnect()
        assert t.state == TransportState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_connect_os_error(self, mock_sdk):
        mock_sdk["client"].return_value.__aenter__.side_effect = OSError("refused")
        cfg = make_http_config()
        t = StreamableHTTPTransport(cfg)

        with pytest.raises(TransportConnectionError, match="refused"):
            await t.connect()
        assert t.state == TransportState.ERROR

    @pytest.mark.asyncio
    async def test_connect_session_error(self, mock_sdk):
        mock_sdk["session"].initialize.side_effect = RuntimeError("protocol mismatch")
        cfg = make_http_config()
        t = StreamableHTTPTransport(cfg)

        with pytest.raises(SessionError, match="protocol mismatch"):
            await t.connect()
        assert t.state == TransportState.ERROR

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_sdk):
        cfg = make_http_config()
        async with StreamableHTTPTransport(cfg) as t:
            assert t.state == TransportState.CONNECTED
        assert t.state == TransportState.DISCONNECTED
