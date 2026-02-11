"""Analytics configuration dataclasses."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RedisConfig:
    """Redis connection configuration.

    Args:
        url: Redis URL (e.g. ``redis://localhost:6379/0``).
        cluster: Whether to use RedisCluster client.
        tls: Enable TLS for the connection.
        password: Optional authentication password.
        socket_timeout: Connection/socket timeout in seconds.
        retry_on_timeout: Automatically retry on timeout errors.
    """

    url: str = ""
    cluster: bool = False
    tls: bool = False
    password: str | None = None
    socket_timeout: float = 5.0
    retry_on_timeout: bool = True


@dataclass(frozen=True)
class AnalyticsConfig:
    """Analytics subsystem configuration.

    Analytics is disabled when ``redis.url`` is empty.  Set a Redis URL
    (via policy file or ``ANALYTICS_REDIS_URL`` env var) to enable.

    Args:
        redis: Redis connection settings.
        environment: Key namespace segment (e.g. ``production``, ``staging``).
        gateway_id: Unique gateway instance identifier.  Auto-generated if empty.
        key_prefix: Redis key prefix for all analytics keys.
        bucket_seconds: Width of each time bucket in seconds.
        retention_seconds: TTL applied to all analytics keys.
        heartbeat_seconds: Interval between gateway heartbeat writes.
        queue_size: Maximum depth of the in-memory event queue.
        flush_interval: Seconds between background flush cycles.
    """

    redis: RedisConfig = field(default_factory=RedisConfig)
    environment: str = "default"
    gateway_id: str = ""
    key_prefix: str = "mcpgw"
    bucket_seconds: int = 60
    retention_seconds: int = 3600
    heartbeat_seconds: int = 30
    queue_size: int = 10000
    flush_interval: float = 1.0

    def __post_init__(self) -> None:
        if not self.gateway_id:
            object.__setattr__(self, "gateway_id", uuid.uuid4().hex[:8])

    @property
    def enabled(self) -> bool:
        """Analytics is enabled when a Redis URL is configured."""
        return bool(self.redis.url)
