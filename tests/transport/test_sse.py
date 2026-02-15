"""Tests for SSE transport."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_zero.context import RequestContext
from mcp_zero.transport.base import TransportState
from mcp_zero.transport.config import ServerConfig, TransportType
from mcp_zero.transport.errors import SessionError, TransportClosedError, TransportConnectionError
from mcp_zero.transport.sse import SSETransport


def make_sse_config(name="test-sse", url="https://localhost:8080/sse"):
    return ServerConfig(name=name, transport=TransportType.SSE, url=url)


@pytest.fixture
def mock_sdk(monkeypatch):
    """Mock the MCP SDK's sse_client and ClientSession."""
    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()

    read_stream = MagicMock()
    write_stream = MagicMock()

    # sse_client yields (read, write)
    mock_sse_cm = AsyncMock()
    mock_sse_cm.__aenter__ = AsyncMock(return_value=(read_stream, write_stream))
    mock_sse_cm.__aexit__ = AsyncMock(return_value=False)

    # ClientSession context manager
    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "mcp_zero.transport.sse.sse_client",
            return_value=mock_sse_cm,
        ) as mock_client,
        patch(
            "mcp_zero.transport.sse.ClientSession",
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


class TestSSETransport:
    @pytest.mark.asyncio
    async def test_connect_success(self, mock_sdk):
        cfg = make_sse_config()
        t = SSETransport(cfg)

        await t.connect()

        assert t.state == TransportState.CONNECTED
        assert t.session is mock_sdk["session"]
        mock_sdk["client"].assert_called_once_with(
            cfg.url,
            headers={},
            sse_read_timeout=cfg.timeout_seconds,
        )
        mock_sdk["session"].initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_idempotent(self, mock_sdk):
        cfg = make_sse_config()
        t = SSETransport(cfg)

        await t.connect()
        await t.connect()  # second call should be a no-op

        mock_sdk["client"].assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect(self, mock_sdk):
        cfg = make_sse_config()
        t = SSETransport(cfg)

        await t.connect()
        await t.disconnect()

        assert t.state == TransportState.DISCONNECTED
        with pytest.raises(TransportClosedError):
            _ = t.session

    @pytest.mark.asyncio
    async def test_disconnect_idempotent(self, mock_sdk):
        cfg = make_sse_config()
        t = SSETransport(cfg)
        # disconnecting when already disconnected is a no-op
        await t.disconnect()
        assert t.state == TransportState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_connect_os_error(self, mock_sdk):
        mock_sdk["client"].return_value.__aenter__.side_effect = OSError("refused")
        cfg = make_sse_config()
        t = SSETransport(cfg)

        with pytest.raises(TransportConnectionError, match="refused"):
            await t.connect()
        assert t.state == TransportState.ERROR

    @pytest.mark.asyncio
    async def test_connect_session_error(self, mock_sdk):
        mock_sdk["session"].initialize.side_effect = RuntimeError("protocol mismatch")
        cfg = make_sse_config()
        t = SSETransport(cfg)

        with pytest.raises(SessionError, match="protocol mismatch"):
            await t.connect()
        assert t.state == TransportState.ERROR

    @pytest.mark.asyncio
    async def test_connect_with_context_passes_headers(self, mock_sdk):
        cfg = make_sse_config()
        ctx = RequestContext(correlation_id="c-1", trace_id="t-1")
        t = SSETransport(cfg)

        await t.connect(context=ctx)

        call_kwargs = mock_sdk["client"].call_args[1]
        assert call_kwargs["headers"]["X-Correlation-ID"] == "c-1"
        assert call_kwargs["headers"]["X-Trace-ID"] == "t-1"

    @pytest.mark.asyncio
    async def test_connect_with_context_no_trace_id_omits_header(self, mock_sdk):
        cfg = make_sse_config()
        ctx = RequestContext(correlation_id="c-1")  # trace_id defaults to None
        t = SSETransport(cfg)

        await t.connect(context=ctx)

        call_kwargs = mock_sdk["client"].call_args[1]
        assert call_kwargs["headers"]["X-Correlation-ID"] == "c-1"
        assert "X-Trace-ID" not in call_kwargs["headers"]

    @pytest.mark.asyncio
    async def test_connect_without_context_empty_headers(self, mock_sdk):
        cfg = make_sse_config()
        t = SSETransport(cfg)

        await t.connect()

        call_kwargs = mock_sdk["client"].call_args[1]
        assert call_kwargs["headers"] == {}

    @pytest.mark.asyncio
    async def test_connect_with_auth_token(self, mock_sdk):
        cfg = make_sse_config()
        t = SSETransport(cfg)

        await t.connect(auth_token="my-obo-token")

        call_kwargs = mock_sdk["client"].call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer my-obo-token"

    @pytest.mark.asyncio
    async def test_connect_with_context_and_auth_token(self, mock_sdk):
        cfg = make_sse_config()
        ctx = RequestContext(correlation_id="c-1", trace_id="t-1")
        t = SSETransport(cfg)

        await t.connect(context=ctx, auth_token="tok")

        call_kwargs = mock_sdk["client"].call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer tok"
        assert call_kwargs["headers"]["X-Correlation-ID"] == "c-1"

    @pytest.mark.asyncio
    async def test_connect_applies_sse_read_timeout(self, mock_sdk):
        cfg = ServerConfig(
            name="test-sse",
            transport=TransportType.SSE,
            url="https://localhost:8080/sse",
            timeout_seconds=60.0,
        )
        t = SSETransport(cfg)

        await t.connect()

        call_kwargs = mock_sdk["client"].call_args[1]
        assert call_kwargs["sse_read_timeout"] == 60.0

    @pytest.mark.asyncio
    async def test_error_carries_correlation_id(self, mock_sdk):
        mock_sdk["client"].return_value.__aenter__.side_effect = OSError("refused")
        cfg = make_sse_config()
        ctx = RequestContext(correlation_id="err-cid")
        t = SSETransport(cfg)

        with pytest.raises(TransportConnectionError) as exc_info:
            await t.connect(context=ctx)
        assert exc_info.value.correlation_id == "err-cid"

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_sdk):
        cfg = make_sse_config()
        async with SSETransport(cfg) as t:
            assert t.state == TransportState.CONNECTED
        assert t.state == TransportState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_reconnect_after_disconnect(self, mock_sdk):
        cfg = make_sse_config()
        t = SSETransport(cfg)

        await t.connect()
        assert t.state == TransportState.CONNECTED

        await t.disconnect()
        assert t.state == TransportState.DISCONNECTED

        await t.connect()
        assert t.state == TransportState.CONNECTED
        assert mock_sdk["client"].call_count == 2


class TestSSEServerConfig:
    def test_sse_config_requires_url(self):
        with pytest.raises(ValueError, match="requires 'url'"):
            ServerConfig(name="no-url", transport=TransportType.SSE)

    def test_sse_config_requires_https(self):
        with pytest.raises(ValueError):
            ServerConfig(name="insecure", transport=TransportType.SSE, url="http://example.com/sse")

    def test_sse_config_allows_insecure(self):
        cfg = ServerConfig(
            name="insecure",
            transport=TransportType.SSE,
            url="http://example.com/sse",
            allow_insecure=True,
        )
        assert cfg.url == "http://example.com/sse"

    def test_sse_config_valid(self):
        cfg = ServerConfig(
            name="valid-sse",
            transport=TransportType.SSE,
            url="https://example.com/sse",
        )
        assert cfg.transport == TransportType.SSE
        assert cfg.url == "https://example.com/sse"

    def test_sse_config_supports_token_exchange(self):
        cfg = ServerConfig(
            name="sse-obo",
            transport=TransportType.SSE,
            url="https://example.com/sse",
            token_exchange=True,
            target_audience="https://api.example.com",
        )
        assert cfg.token_exchange is True
