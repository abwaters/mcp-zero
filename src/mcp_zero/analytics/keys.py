"""Redis key builder for analytics namespacing."""

from __future__ import annotations

import time


class KeyBuilder:
    """Generates namespaced Redis keys for analytics data.

    All keys follow the pattern ``{prefix}:{environment}:{gateway_id}:...``
    so multiple gateways can safely share a Redis cluster.
    """

    def __init__(self, prefix: str, environment: str, gateway_id: str) -> None:
        self._prefix = prefix
        self._env = environment
        self._gw = gateway_id
        self._base = f"{prefix}:{environment}:{gateway_id}"

    @property
    def base(self) -> str:
        """The base key prefix for this gateway instance."""
        return self._base

    def bucket_id(self, bucket_seconds: int, epoch: float | None = None) -> int:
        """Compute the bucket ID for the given (or current) epoch time."""
        ts = epoch if epoch is not None else time.time()
        return int(ts) // bucket_seconds

    def bucket_key(self, metric: str, bid: int) -> str:
        """Key for a time-bucketed hash counter.

        Example: ``mcpgw:production:gw1:b:12345:tool_calls``
        """
        return f"{self._base}:b:{bid}:{metric}"

    def registry_key(self) -> str:
        """Sorted set key for gateway discovery.

        Example: ``mcpgw:gateways``
        """
        return f"{self._prefix}:gateways"

    def info_key(self) -> str:
        """Hash key for this gateway's metadata.

        Example: ``mcpgw:gw:production:gw1:info``
        """
        return f"{self._prefix}:gw:{self._env}:{self._gw}:info"
