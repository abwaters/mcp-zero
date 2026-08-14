"""Tests for HTTP transport."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_zero.context import RequestContext
from mcp_zero.transport.base import TransportState
from mcp_zero.transport.config import ServerConfig, TransportType
from mcp_zero.transport.errors import SessionError, TransportClosedError, TransportConnectionError
from mcp_zero.transport.http import StreamableHTTPTransport


def make_http_config(name="test-http", url="https://localhost:8080"):
    return ServerConfig(name=name, transport=TransportType.HTTP, url=url)


@pytest.fixture
def mock_sdk(monkeypatch):
    """Mock the MCP SDK's streamable_http_client and ClientSession."""
    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()

    read_stream = MagicMock()
    write_stream = MagicMock()

    # mcp v2 streamable_http_client yields (read, write)
    mock_http_cm = AsyncMock()
    mock_http_cm.__aenter__ = AsyncMock(return_value=(read_stream, write_stream))
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
        mock_sdk["client"].assert_called_once_with(cfg.url, http_client=None)
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
    async def test_connect_with_context_passes_http_client(self, mock_sdk):
        cfg = make_http_config()
        ctx = RequestContext(correlation_id="c-1", trace_id="t-1")
        t = StreamableHTTPTransport(cfg)

        with patch("mcp_zero.transport.http.httpx2.AsyncClient") as mock_httpx:
            mock_httpx_inst = AsyncMock()
            mock_httpx_inst.__aenter__ = AsyncMock(return_value=mock_httpx_inst)
            mock_httpx_inst.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_httpx_inst

            await t.connect(context=ctx)

            mock_httpx.assert_called_once()
            call_kwargs = mock_httpx.call_args[1]
            assert call_kwargs["headers"]["X-Correlation-ID"] == "c-1"
            assert call_kwargs["headers"]["X-Trace-ID"] == "t-1"
            # httpx client instance passed to streamable_http_client
            sdk_call_kwargs = mock_sdk["client"].call_args[1]
            assert sdk_call_kwargs["http_client"] is mock_httpx_inst

    @pytest.mark.asyncio
    async def test_connect_with_context_no_trace_id_omits_header(self, mock_sdk):
        cfg = make_http_config()
        ctx = RequestContext(correlation_id="c-1")  # trace_id defaults to None
        t = StreamableHTTPTransport(cfg)

        with patch("mcp_zero.transport.http.httpx2.AsyncClient") as mock_httpx:
            mock_httpx_inst = AsyncMock()
            mock_httpx_inst.__aenter__ = AsyncMock(return_value=mock_httpx_inst)
            mock_httpx_inst.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_httpx_inst

            await t.connect(context=ctx)

            call_kwargs = mock_httpx.call_args[1]
            assert call_kwargs["headers"]["X-Correlation-ID"] == "c-1"
            assert "X-Trace-ID" not in call_kwargs["headers"]

    @pytest.mark.asyncio
    async def test_connect_without_context_no_http_client(self, mock_sdk):
        cfg = make_http_config()
        t = StreamableHTTPTransport(cfg)

        await t.connect()

        call_kwargs = mock_sdk["client"].call_args[1]
        assert call_kwargs["http_client"] is None

    @pytest.mark.asyncio
    async def test_connect_with_auth_token(self, mock_sdk):
        cfg = make_http_config()
        t = StreamableHTTPTransport(cfg)

        with patch("mcp_zero.transport.http.httpx2.AsyncClient") as mock_httpx:
            mock_httpx_inst = AsyncMock()
            mock_httpx_inst.__aenter__ = AsyncMock(return_value=mock_httpx_inst)
            mock_httpx_inst.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_httpx_inst

            await t.connect(auth_token="my-obo-token")

            call_kwargs = mock_httpx.call_args[1]
            assert call_kwargs["headers"]["Authorization"] == "Bearer my-obo-token"

    @pytest.mark.asyncio
    async def test_connect_with_context_and_auth_token(self, mock_sdk):
        cfg = make_http_config()
        ctx = RequestContext(correlation_id="c-1", trace_id="t-1")
        t = StreamableHTTPTransport(cfg)

        with patch("mcp_zero.transport.http.httpx2.AsyncClient") as mock_httpx:
            mock_httpx_inst = AsyncMock()
            mock_httpx_inst.__aenter__ = AsyncMock(return_value=mock_httpx_inst)
            mock_httpx_inst.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_httpx_inst

            await t.connect(context=ctx, auth_token="tok")

            call_kwargs = mock_httpx.call_args[1]
            assert call_kwargs["headers"]["Authorization"] == "Bearer tok"
            assert call_kwargs["headers"]["X-Correlation-ID"] == "c-1"

    @pytest.mark.asyncio
    async def test_connect_applies_timeout(self, mock_sdk):
        cfg = ServerConfig(
            name="test-http",
            transport=TransportType.HTTP,
            url="https://localhost:8080",
            timeout_seconds=60.0,
        )
        ctx = RequestContext()
        t = StreamableHTTPTransport(cfg)

        with patch("mcp_zero.transport.http.httpx2.AsyncClient") as mock_httpx:
            mock_httpx_inst = AsyncMock()
            mock_httpx_inst.__aenter__ = AsyncMock(return_value=mock_httpx_inst)
            mock_httpx_inst.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_httpx_inst

            await t.connect(context=ctx)

            call_kwargs = mock_httpx.call_args[1]
            timeout = call_kwargs["timeout"]
            assert timeout.connect == 60.0

    @pytest.mark.asyncio
    async def test_error_carries_correlation_id(self, mock_sdk):
        mock_sdk["client"].return_value.__aenter__.side_effect = OSError("refused")
        cfg = make_http_config()
        ctx = RequestContext(correlation_id="err-cid")
        t = StreamableHTTPTransport(cfg)

        with pytest.raises(TransportConnectionError) as exc_info:
            await t.connect(context=ctx)
        assert exc_info.value.correlation_id == "err-cid"

    @pytest.mark.asyncio
    async def test_connect_with_config_headers(self, mock_sdk):
        cfg = ServerConfig(
            name="test-http",
            transport=TransportType.HTTP,
            url="https://localhost:8080",
            headers={"X-Api-Key": "secret", "X-Custom": "value"},
        )
        t = StreamableHTTPTransport(cfg)

        with patch("mcp_zero.transport.http.httpx2.AsyncClient") as mock_httpx:
            mock_httpx_inst = AsyncMock()
            mock_httpx_inst.__aenter__ = AsyncMock(return_value=mock_httpx_inst)
            mock_httpx_inst.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_httpx_inst

            await t.connect()

            mock_httpx.assert_called_once()
            call_kwargs = mock_httpx.call_args[1]
            assert call_kwargs["headers"]["X-Api-Key"] == "secret"
            assert call_kwargs["headers"]["X-Custom"] == "value"

    @pytest.mark.asyncio
    async def test_connect_config_headers_merged_with_context(self, mock_sdk):
        cfg = ServerConfig(
            name="test-http",
            transport=TransportType.HTTP,
            url="https://localhost:8080",
            headers={"X-Api-Key": "secret"},
        )
        ctx = RequestContext(correlation_id="c-1", trace_id="t-1")
        t = StreamableHTTPTransport(cfg)

        with patch("mcp_zero.transport.http.httpx2.AsyncClient") as mock_httpx:
            mock_httpx_inst = AsyncMock()
            mock_httpx_inst.__aenter__ = AsyncMock(return_value=mock_httpx_inst)
            mock_httpx_inst.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_httpx_inst

            await t.connect(context=ctx)

            call_kwargs = mock_httpx.call_args[1]
            assert call_kwargs["headers"]["X-Api-Key"] == "secret"
            assert call_kwargs["headers"]["X-Correlation-ID"] == "c-1"
            assert call_kwargs["headers"]["X-Trace-ID"] == "t-1"

    @pytest.mark.asyncio
    async def test_connect_runtime_headers_override_config_headers(self, mock_sdk):
        cfg = ServerConfig(
            name="test-http",
            transport=TransportType.HTTP,
            url="https://localhost:8080",
            headers={"Authorization": "Bearer static-token"},
        )
        t = StreamableHTTPTransport(cfg)

        with patch("mcp_zero.transport.http.httpx2.AsyncClient") as mock_httpx:
            mock_httpx_inst = AsyncMock()
            mock_httpx_inst.__aenter__ = AsyncMock(return_value=mock_httpx_inst)
            mock_httpx_inst.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_httpx_inst

            await t.connect(auth_token="obo-token")

            call_kwargs = mock_httpx.call_args[1]
            # Runtime auth_token should override the static config Authorization
            assert call_kwargs["headers"]["Authorization"] == "Bearer obo-token"

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_sdk):
        cfg = make_http_config()
        async with StreamableHTTPTransport(cfg) as t:
            assert t.state == TransportState.CONNECTED
        assert t.state == TransportState.DISCONNECTED
