"""stdio process lifecycle management — health monitoring, restart, and shutdown."""

from __future__ import annotations

import asyncio
import logging
import platform
import signal
from dataclasses import dataclass, field
from typing import Self

from mcp_zero.transport.stdio import StdioTransport

logger = logging.getLogger(__name__)

_DEFAULT_HEALTH_INTERVAL = 5.0  # seconds between health checks
_MAX_BACKOFF = 60.0  # cap for exponential backoff


@dataclass
class ProcessStatus:
    """Mutable status tracker for a managed stdio transport."""

    transport: StdioTransport
    consecutive_failures: int = 0
    permanently_failed: bool = False
    restart_in_progress: bool = False
    total_restarts: int = field(default=0, init=False)


class StdioProcessManager:
    """Lifecycle manager for stdio transports.

    Monitors health, restarts on failure with exponential backoff,
    and ensures graceful cleanup on shutdown.
    """

    def __init__(self, health_interval: float = _DEFAULT_HEALTH_INTERVAL) -> None:
        self._transports: dict[str, ProcessStatus] = {}
        self._health_interval = health_interval
        self._health_task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()
        self._signal_handlers_installed = False

    # -- Registration --

    def register(self, transport: StdioTransport) -> None:
        """Register a transport for lifecycle management."""
        name = transport.config.name
        if name in self._transports:
            raise ValueError(f"Transport '{name}' is already registered")
        self._transports[name] = ProcessStatus(transport=transport)

    def unregister(self, name: str) -> None:
        """Remove a transport from management."""
        self._transports.pop(name, None)

    # -- Query API --

    @property
    def managed_servers(self) -> list[str]:
        """Names of all managed transports."""
        return list(self._transports.keys())

    @property
    def is_running(self) -> bool:
        """True if the health monitor is active."""
        return self._health_task is not None and not self._health_task.done()

    def get_status(self, name: str) -> ProcessStatus | None:
        """Get the status tracker for a named transport."""
        return self._transports.get(name)

    def get_transport(self, name: str) -> StdioTransport | None:
        """Get the transport instance by server name."""
        status = self._transports.get(name)
        return status.transport if status else None

    # -- Startup --

    async def start_all(self) -> None:
        """Connect all registered transports and start the health monitor."""
        for name, status in self._transports.items():
            try:
                await status.transport.connect()
                logger.info("Connected transport '%s'", name)
            except Exception:
                status.consecutive_failures = 1
                logger.exception("Initial connect failed for '%s'", name)

        self._shutdown_event.clear()
        self._health_task = asyncio.create_task(self._health_loop())

    # -- Health monitoring --

    async def _health_loop(self) -> None:
        """Periodically check transport health and restart as needed."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=self._health_interval)
                break  # shutdown signalled
            except asyncio.TimeoutError:
                pass  # interval elapsed, run checks

            for name, status in list(self._transports.items()):
                if status.permanently_failed or status.restart_in_progress:
                    continue
                if not status.transport.is_healthy():
                    await self._try_restart(name, status)

    async def _try_restart(self, name: str, status: ProcessStatus) -> None:
        """Attempt to restart a transport with exponential backoff."""
        max_restarts = status.transport.config.max_restarts
        base_delay = status.transport.config.restart_delay

        if status.consecutive_failures >= max_restarts:
            status.permanently_failed = True
            logger.error(
                "Transport '%s' permanently failed after %d restarts",
                name,
                max_restarts,
            )
            return

        status.restart_in_progress = True
        delay = min(base_delay * (2**status.consecutive_failures), _MAX_BACKOFF)
        logger.info(
            "Restarting '%s' (attempt %d/%d, delay %.1fs)",
            name,
            status.consecutive_failures + 1,
            max_restarts,
            delay,
        )

        await asyncio.sleep(delay)

        try:
            await status.transport.reconnect()
            status.consecutive_failures = 0
            status.total_restarts += 1
            logger.info("Restart succeeded for '%s'", name)
        except Exception:
            status.consecutive_failures += 1
            logger.exception(
                "Restart failed for '%s' (failures: %d/%d)",
                name,
                status.consecutive_failures,
                max_restarts,
            )
        finally:
            status.restart_in_progress = False

    # -- Shutdown --

    async def shutdown(self) -> None:
        """Gracefully shut down all transports and stop health monitoring."""
        self._shutdown_event.set()

        if self._health_task is not None:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None

        async def _safe_disconnect(name: str, status: ProcessStatus) -> None:
            try:
                await status.transport.disconnect()
            except Exception:
                logger.exception("Error disconnecting '%s' during shutdown", name)

        await asyncio.gather(*(_safe_disconnect(n, s) for n, s in self._transports.items()))

    # -- Signal handling --

    def install_signal_handlers(self) -> None:
        """Install OS signal handlers that trigger graceful shutdown."""
        if platform.system() != "Windows":
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, self._shutdown_event.set)
        else:
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, self._sync_signal_handler)
        self._signal_handlers_installed = True

    def _remove_signal_handlers(self) -> None:
        """Remove previously installed signal handlers."""
        if not self._signal_handlers_installed:
            return
        if platform.system() != "Windows":
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(sig)
        else:
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, signal.SIG_DFL)
        self._signal_handlers_installed = False

    def _sync_signal_handler(self, signum: int, frame: object) -> None:
        """Windows-compatible signal handler that sets the shutdown event."""
        self._shutdown_event.set()

    # -- Context manager --

    async def __aenter__(self) -> Self:
        self.install_signal_handlers()
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self._remove_signal_handlers()
        await self.shutdown()
