"""Tests for stdio process lifecycle manager."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_zero.transport.base import TransportState
from mcp_zero.transport.config import ServerConfig, TransportType
from mcp_zero.transport.process_manager import StdioProcessManager
from mcp_zero.transport.stdio import StdioTransport


def _make_transport(name: str = "test", max_restarts: int = 3, restart_delay: float = 0.0):
    """Create a StdioTransport with mocked internals."""
    cfg = ServerConfig(
        name=name,
        transport=TransportType.STDIO,
        command="echo",
        max_restarts=max_restarts,
        restart_delay=restart_delay,
    )
    t = StdioTransport(cfg)
    t.connect = AsyncMock()  # type: ignore[method-assign]
    t.disconnect = AsyncMock()  # type: ignore[method-assign]
    t.reconnect = AsyncMock()  # type: ignore[method-assign]
    return t


class TestRegistration:
    def test_register(self):
        mgr = StdioProcessManager()
        t = _make_transport("srv")
        mgr.register(t)
        assert "srv" in mgr.managed_servers

    def test_register_duplicate_raises(self):
        mgr = StdioProcessManager()
        t = _make_transport("srv")
        mgr.register(t)
        with pytest.raises(ValueError, match="already registered"):
            mgr.register(t)

    def test_unregister(self):
        mgr = StdioProcessManager()
        t = _make_transport("srv")
        mgr.register(t)
        mgr.unregister("srv")
        assert "srv" not in mgr.managed_servers

    def test_unregister_nonexistent_is_noop(self):
        mgr = StdioProcessManager()
        mgr.unregister("nope")  # should not raise

    def test_get_status(self):
        mgr = StdioProcessManager()
        t = _make_transport("srv")
        mgr.register(t)
        status = mgr.get_status("srv")
        assert status is not None
        assert status.transport is t
        assert status.consecutive_failures == 0

    def test_get_status_missing(self):
        mgr = StdioProcessManager()
        assert mgr.get_status("nope") is None

    def test_get_transport(self):
        mgr = StdioProcessManager()
        t = _make_transport("srv")
        mgr.register(t)
        assert mgr.get_transport("srv") is t

    def test_get_transport_missing(self):
        mgr = StdioProcessManager()
        assert mgr.get_transport("nope") is None


class TestStartAll:
    @pytest.mark.asyncio
    async def test_connects_all(self):
        mgr = StdioProcessManager()
        t1 = _make_transport("a")
        t2 = _make_transport("b")
        mgr.register(t1)
        mgr.register(t2)

        await mgr.start_all()

        t1.connect.assert_awaited_once()
        t2.connect.assert_awaited_once()
        assert mgr.is_running is True

        await mgr.shutdown()

    @pytest.mark.asyncio
    async def test_records_initial_failure(self):
        mgr = StdioProcessManager()
        t = _make_transport("fail")
        t.connect.side_effect = RuntimeError("boom")
        mgr.register(t)

        await mgr.start_all()

        status = mgr.get_status("fail")
        assert status is not None
        assert status.consecutive_failures == 1

        await mgr.shutdown()


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy_not_restarted(self):
        mgr = StdioProcessManager(health_interval=0.05)
        t = _make_transport("ok")
        t.is_healthy = MagicMock(return_value=True)  # type: ignore[method-assign]
        mgr.register(t)

        await mgr.start_all()
        await asyncio.sleep(0.15)  # let health loop run a couple times
        await mgr.shutdown()

        t.reconnect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unhealthy_triggers_restart(self):
        mgr = StdioProcessManager(health_interval=0.05)
        t = _make_transport("bad", restart_delay=0.0)
        t.is_healthy = MagicMock(return_value=False)  # type: ignore[method-assign]
        mgr.register(t)

        await mgr.start_all()
        await asyncio.sleep(0.2)
        await mgr.shutdown()

        t.reconnect.assert_awaited()

    @pytest.mark.asyncio
    async def test_max_restarts_permanently_fails(self):
        mgr = StdioProcessManager(health_interval=0.05)
        t = _make_transport("doomed", max_restarts=2, restart_delay=0.0)
        t.is_healthy = MagicMock(return_value=False)  # type: ignore[method-assign]
        t.reconnect.side_effect = RuntimeError("still broken")
        mgr.register(t)

        await mgr.start_all()
        # Let health loop detect and exhaust restarts
        await asyncio.sleep(0.5)
        await mgr.shutdown()

        status = mgr.get_status("doomed")
        assert status is not None
        assert status.permanently_failed is True

    @pytest.mark.asyncio
    async def test_success_resets_counter(self):
        mgr = StdioProcessManager(health_interval=0.05)
        t = _make_transport("flaky", max_restarts=3, restart_delay=0.0)

        call_count = 0

        def flaky_health():
            nonlocal call_count
            call_count += 1
            # Unhealthy on first check, healthy after reconnect
            return call_count > 1

        t.is_healthy = MagicMock(side_effect=flaky_health)  # type: ignore[method-assign]
        mgr.register(t)

        await mgr.start_all()
        await asyncio.sleep(0.2)
        await mgr.shutdown()

        status = mgr.get_status("flaky")
        assert status is not None
        assert status.consecutive_failures == 0
        assert status.permanently_failed is False


class TestShutdown:
    @pytest.mark.asyncio
    async def test_disconnects_all(self):
        mgr = StdioProcessManager()
        t1 = _make_transport("a")
        t2 = _make_transport("b")
        mgr.register(t1)
        mgr.register(t2)

        await mgr.start_all()
        await mgr.shutdown()

        t1.disconnect.assert_awaited_once()
        t2.disconnect.assert_awaited_once()
        assert mgr.is_running is False

    @pytest.mark.asyncio
    async def test_tolerates_disconnect_errors(self):
        mgr = StdioProcessManager()
        t = _make_transport("err")
        t.disconnect.side_effect = RuntimeError("cleanup failed")
        mgr.register(t)

        await mgr.start_all()
        await mgr.shutdown()  # should not raise

    @pytest.mark.asyncio
    async def test_cancels_health_task(self):
        mgr = StdioProcessManager(health_interval=0.05)
        t = _make_transport("srv")
        t.is_healthy = MagicMock(return_value=True)  # type: ignore[method-assign]
        mgr.register(t)

        await mgr.start_all()
        assert mgr.is_running is True

        await mgr.shutdown()
        assert mgr.is_running is False


class TestContextManager:
    @pytest.mark.asyncio
    async def test_cleanup_on_normal_exit(self):
        mgr = StdioProcessManager()
        t = _make_transport("srv")
        t.is_healthy = MagicMock(return_value=True)  # type: ignore[method-assign]
        mgr.register(t)

        async with mgr:
            await mgr.start_all()
            assert mgr.is_running is True

        t.disconnect.assert_awaited_once()
        assert mgr.is_running is False

    @pytest.mark.asyncio
    async def test_cleanup_on_exception(self):
        mgr = StdioProcessManager()
        t = _make_transport("srv")
        t.is_healthy = MagicMock(return_value=True)  # type: ignore[method-assign]
        mgr.register(t)

        with pytest.raises(RuntimeError, match="oops"):
            async with mgr:
                await mgr.start_all()
                raise RuntimeError("oops")

        t.disconnect.assert_awaited_once()
        assert mgr.is_running is False


class TestSignalHandling:
    @pytest.mark.asyncio
    async def test_sync_handler_sets_shutdown_event(self):
        mgr = StdioProcessManager()
        assert not mgr._shutdown_event.is_set()
        mgr._sync_signal_handler(2, None)
        assert mgr._shutdown_event.is_set()

    @pytest.mark.asyncio
    @patch("mcp_zero.transport.process_manager.platform")
    async def test_install_unix_handlers(self, mock_platform):
        mock_platform.system.return_value = "Linux"
        mgr = StdioProcessManager()

        loop = asyncio.get_running_loop()
        with patch.object(loop, "add_signal_handler") as mock_add:
            mgr.install_signal_handlers()
            assert mock_add.call_count == 2

    @pytest.mark.asyncio
    @patch("mcp_zero.transport.process_manager.platform")
    @patch("mcp_zero.transport.process_manager.signal")
    async def test_install_windows_handlers(self, mock_signal, mock_platform):
        mock_platform.system.return_value = "Windows"
        mock_signal.SIGINT = 2
        mock_signal.SIGTERM = 15
        mgr = StdioProcessManager()

        mgr.install_signal_handlers()
        assert mock_signal.signal.call_count == 2


class TestFailClosed:
    @pytest.mark.asyncio
    async def test_permanently_failed_blocks_session(self):
        mgr = StdioProcessManager()
        t = _make_transport("dead")
        mgr.register(t)

        status = mgr.get_status("dead")
        assert status is not None
        status.permanently_failed = True

        # Transport in ERROR state should raise TransportClosedError on session access
        t._state = TransportState.ERROR
        from mcp_zero.transport.errors import TransportClosedError

        with pytest.raises(TransportClosedError):
            _ = t.session
