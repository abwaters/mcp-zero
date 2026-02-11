"""Redis client abstraction for analytics — supports standalone and cluster."""

from __future__ import annotations

import logging
from typing import Any

from mcp_zero.analytics.config import RedisConfig

logger = logging.getLogger(__name__)


class RedisAnalyticsClient:
    """Thin async wrapper around ``redis.asyncio`` for analytics writes.

    Supports both standalone Redis and Redis Cluster via the ``cluster``
    config flag.  All public methods are fire-and-forget: they log errors
    but never raise into the caller.
    """

    def __init__(self, config: RedisConfig) -> None:
        self._config = config
        self._client: Any = None

    async def connect(self) -> None:
        """Establish the Redis connection."""
        import redis.asyncio as aioredis

        kwargs: dict[str, Any] = {
            "socket_timeout": self._config.socket_timeout,
            "retry_on_timeout": self._config.retry_on_timeout,
            "decode_responses": True,
        }
        if self._config.password:
            kwargs["password"] = self._config.password

        try:
            if self._config.cluster:
                from redis.asyncio.cluster import RedisCluster

                self._client = RedisCluster.from_url(
                    self._config.url,
                    **kwargs,
                )
            else:
                self._client = aioredis.from_url(
                    self._config.url,
                    **kwargs,
                )
            # Verify connectivity
            await self._client.ping()
            logger.info(
                "Analytics Redis connected: %s (cluster=%s)",
                self._config.url,
                self._config.cluster,
            )
        except Exception:
            logger.warning("Failed to connect to analytics Redis", exc_info=True)
            self._client = None

    async def disconnect(self) -> None:
        """Close the Redis connection."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                logger.debug("Error closing analytics Redis connection", exc_info=True)
            finally:
                self._client = None

    @property
    def connected(self) -> bool:
        """Whether the client has an active connection."""
        return self._client is not None

    async def execute_pipeline(self, operations: list[tuple[str, list[Any]]]) -> None:
        """Execute a batch of Redis commands in a pipeline.

        Each operation is a tuple of ``(command_name, [args...])``.
        Supported commands: ``HINCRBY``, ``EXPIRE``, ``ZADD``, ``HSET``.

        Args:
            operations: List of (command, args) tuples.
        """
        if not self._client or not operations:
            return

        try:
            pipe = self._client.pipeline(transaction=False)
            for cmd, args in operations:
                cmd_lower = cmd.lower()
                if cmd_lower == "hincrby":
                    pipe.hincrby(*args)
                elif cmd_lower == "expire":
                    pipe.expire(*args)
                elif cmd_lower == "zadd":
                    pipe.zadd(*args)
                elif cmd_lower == "hset":
                    pipe.hset(*args)
                elif cmd_lower == "incr":
                    pipe.incr(*args)
                else:
                    logger.warning("Unknown pipeline command: %s", cmd)
            await pipe.execute()
        except Exception:
            logger.warning("Analytics Redis pipeline failed", exc_info=True)
            # Attempt reconnect on next flush
            await self._try_reconnect()

    async def _try_reconnect(self) -> None:
        """Attempt to re-establish the Redis connection."""
        try:
            await self.disconnect()
            await self.connect()
        except Exception:
            logger.debug("Analytics Redis reconnect failed", exc_info=True)
