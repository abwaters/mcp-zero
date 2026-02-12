"""Redis key builder for analytics namespacing.

Key hierarchy::

    {prefix}
    ├── idx                                    # Navigation indexes (SETs)
    │   ├── envs                               #   → {"prod", "staging"}
    │   └── gw:{env}                           #   → {"east-1", "west-1"}
    ├── registry                               # Gateway heartbeats (ZSET)
    └── gw:{env}:{gw_id}                       # Per-gateway subtree
        ├── info                               # Metadata (HASH)
        └── b:{bucket_id}                      # Time bucket subtree
            ├── calls:tool                     # HASH: "server::tool" → count
            ├── calls:server                   # HASH: "server" → count
            ├── calls:user                     # HASH: "user_id" → count
            ├── calls:transport                # HASH: "http"|"stdio" → count
            ├── latency:sum                    # HASH: "server::tool" → ms
            ├── latency:count                  # HASH: "server::tool" → N
            ├── latency:max                    # HASH: "server::tool" → max ms
            ├── sizes:request                  # HASH: "server::tool" → bytes
            ├── sizes:response                 # HASH: "server::tool" → bytes
            ├── denials:tool                   # HASH: "server::tool" → count
            ├── denials:rule                   # HASH: "rule_id" → count
            ├── denials:user                   # HASH: "user_id" → count
            ├── denials:reason                 # HASH: reason category → count
            ├── redactions:input               # HASH: "entity_type" → count
            ├── redactions:output              # HASH: "entity_type" → count
            ├── redactions:tool                # HASH: "server::tool" → count
            ├── redactions:fail                # HASH: "input"|"output" → count
            └── errors:tool                    # HASH: "server::tool" → count
"""

from __future__ import annotations

import time


class KeyBuilder:
    """Generates hierarchical, namespaced Redis keys for analytics data.

    All keys use colon-separated segments so Redis tooling (e.g. Redis Insight)
    renders them as a navigable tree.
    """

    def __init__(self, prefix: str, environment: str, gateway_id: str) -> None:
        self._prefix = prefix
        self._env = environment
        self._gw = gateway_id
        self._gw_base = f"{prefix}:gw:{environment}:{gateway_id}"

    @property
    def gateway_base(self) -> str:
        """The base key path for this gateway: ``{prefix}:gw:{env}:{gw}``."""
        return self._gw_base

    def bucket_id(self, bucket_seconds: int, epoch: float | None = None) -> int:
        """Compute the bucket ID for the given (or current) epoch time."""
        ts = epoch if epoch is not None else time.time()
        return int(ts) // bucket_seconds

    def bucket_key(self, category: str, dimension: str, bid: int) -> str:
        """Key for a time-bucketed hash counter.

        Example: ``mcpgw:gw:prod:east-1:b:12345:calls:tool``
        """
        return f"{self._gw_base}:b:{bid}:{category}:{dimension}"

    # -- Registry & discovery --------------------------------------------------

    def registry_key(self) -> str:
        """Sorted set key for gateway heartbeats.

        Example: ``mcpgw:registry``
        """
        return f"{self._prefix}:registry"

    def info_key(self) -> str:
        """Hash key for this gateway's metadata.

        Example: ``mcpgw:gw:prod:east-1:info``
        """
        return f"{self._gw_base}:info"

    def idx_envs_key(self) -> str:
        """Set key listing all known environments.

        Example: ``mcpgw:idx:envs``
        """
        return f"{self._prefix}:idx:envs"

    def idx_gateways_key(self) -> str:
        """Set key listing gateways in this environment.

        Example: ``mcpgw:idx:gw:prod``
        """
        return f"{self._prefix}:idx:gw:{self._env}"

    @property
    def registry_member(self) -> str:
        """The member string used in the registry sorted set."""
        return f"{self._env}:{self._gw}"
