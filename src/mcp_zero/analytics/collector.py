"""Analytics collector — queues events and flushes to Redis in the background."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from mcp_zero.analytics.client import RedisAnalyticsClient
from mcp_zero.analytics.config import AnalyticsConfig
from mcp_zero.analytics.keys import KeyBuilder

logger = logging.getLogger(__name__)


class EventType:
    """Event type constants."""

    TOOL_CALL = "tool_call"
    DENIAL = "denial"
    REDACTION = "redaction"
    OUTPUT_REDACTION = "output_redaction"
    MASKING_FAILURE = "masking_failure"
    ERROR = "error"


@dataclass
class AnalyticsEvent:
    """Lightweight event for the analytics queue."""

    event_type: str
    server: str = ""
    tool: str = ""
    user_id: str = ""
    rule_id: str = ""
    entity_type: str = ""
    count: int = 1
    duration_ms: float = 0.0
    request_bytes: int = 0
    response_bytes: int = 0
    transport: str = ""
    reason: str = ""
    direction: str = ""  # "input" | "output" for masking failures
    timestamp: float = field(default_factory=time.time)


class AnalyticsCollector:
    """Accepts analytics events, queues them, and writes to Redis in batches.

    The collector runs two background tasks:

    1. **Flush task** — drains the event queue every ``flush_interval`` seconds
       and writes aggregated counters to Redis via pipeline.
    2. **Heartbeat task** — writes gateway presence to the registry sorted set
       every ``heartbeat_seconds`` seconds, and maintains navigation index sets.

    If Redis is unavailable, events are silently dropped.  The queue is bounded
    to prevent memory growth.
    """

    def __init__(self, config: AnalyticsConfig, client: RedisAnalyticsClient) -> None:
        self._config = config
        self._client = client
        self._keys = KeyBuilder(config.key_prefix, config.environment, config.gateway_id)
        self._queue: asyncio.Queue[AnalyticsEvent] = asyncio.Queue(maxsize=config.queue_size)
        self._flush_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._started_at = time.time()
        self._drop_count = 0
        self._running = False

    async def start(self) -> None:
        """Start background flush and heartbeat tasks."""
        if self._running:
            return
        self._running = True
        self._started_at = time.time()
        await self._client.connect()
        self._flush_task = asyncio.create_task(self._flush_loop(), name="analytics-flush")
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name="analytics-heartbeat"
        )
        logger.info(
            "Analytics collector started: env=%s, gw=%s, bucket=%ds, retention=%ds",
            self._config.environment,
            self._config.gateway_id,
            self._config.bucket_seconds,
            self._config.retention_seconds,
        )

    async def stop(self) -> None:
        """Stop background tasks and flush remaining events."""
        if not self._running:
            return
        self._running = False

        for task in (self._flush_task, self._heartbeat_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Final flush
        await self._flush()
        await self._client.disconnect()
        logger.info("Analytics collector stopped")

    # -- Public recording methods (non-blocking) --------------------------------

    def record_tool_call(
        self,
        *,
        server: str,
        tool: str,
        user_id: str = "",
        duration_ms: float = 0.0,
        request_bytes: int = 0,
        response_bytes: int = 0,
        transport: str = "",
    ) -> None:
        """Enqueue a tool call event."""
        self._enqueue(
            AnalyticsEvent(
                event_type=EventType.TOOL_CALL,
                server=server,
                tool=tool,
                user_id=user_id,
                duration_ms=duration_ms,
                request_bytes=request_bytes,
                response_bytes=response_bytes,
                transport=transport,
            )
        )

    def record_denial(
        self,
        *,
        server: str,
        tool: str,
        user_id: str = "",
        rule_id: str = "",
        reason: str = "",
    ) -> None:
        """Enqueue a policy denial event."""
        self._enqueue(
            AnalyticsEvent(
                event_type=EventType.DENIAL,
                server=server,
                tool=tool,
                user_id=user_id,
                rule_id=rule_id,
                reason=reason,
            )
        )

    def record_redaction(
        self,
        *,
        server: str,
        tool: str,
        entity_type: str,
        count: int = 1,
    ) -> None:
        """Enqueue an input redaction event."""
        self._enqueue(
            AnalyticsEvent(
                event_type=EventType.REDACTION,
                server=server,
                tool=tool,
                entity_type=entity_type,
                count=count,
            )
        )

    def record_output_redaction(
        self,
        *,
        server: str,
        tool: str,
        entity_type: str,
        count: int = 1,
    ) -> None:
        """Enqueue an output redaction event."""
        self._enqueue(
            AnalyticsEvent(
                event_type=EventType.OUTPUT_REDACTION,
                server=server,
                tool=tool,
                entity_type=entity_type,
                count=count,
            )
        )

    def record_masking_failure(self, *, server: str, tool: str, direction: str) -> None:
        """Enqueue a masking failure event.

        Args:
            direction: ``"input"`` or ``"output"``.
        """
        self._enqueue(
            AnalyticsEvent(
                event_type=EventType.MASKING_FAILURE,
                server=server,
                tool=tool,
                direction=direction,
            )
        )

    def record_error(self, *, server: str, tool: str) -> None:
        """Enqueue an error event."""
        self._enqueue(
            AnalyticsEvent(
                event_type=EventType.ERROR,
                server=server,
                tool=tool,
            )
        )

    # -- Internal ---------------------------------------------------------------

    def _enqueue(self, event: AnalyticsEvent) -> None:
        """Put an event on the queue, dropping if full."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._drop_count += 1
            if self._drop_count % 1000 == 1:
                logger.warning(
                    "Analytics queue full — dropped %d events total",
                    self._drop_count,
                )

    async def _flush_loop(self) -> None:
        """Background loop that periodically flushes queued events to Redis."""
        while self._running:
            try:
                await asyncio.sleep(self._config.flush_interval)
                await self._flush()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("Analytics flush error", exc_info=True)

    async def _flush(self) -> None:
        """Drain the queue and write aggregated counters to Redis."""
        events: list[AnalyticsEvent] = []
        while not self._queue.empty():
            try:
                events.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if not events:
            return

        operations = self._build_operations(events)
        await self._client.execute_pipeline(operations)

    def _build_operations(self, events: list[AnalyticsEvent]) -> list[tuple[str, list[Any]]]:
        """Convert a batch of events into Redis pipeline operations."""
        ops: list[tuple[str, list[Any]]] = []
        ttl = self._config.retention_seconds
        keys_seen: set[str] = set()
        # Track per-bucket max latencies: (bucket_key, field) → max_ms
        latency_maxes: dict[tuple[str, str], int] = {}

        for event in events:
            bid = self._keys.bucket_id(self._config.bucket_seconds, event.timestamp)
            tool_field = f"{event.server}::{event.tool}"

            if event.event_type == EventType.TOOL_CALL:
                self._hincrby(ops, keys_seen, "calls", "tool", bid, tool_field, 1, ttl)
                self._hincrby(ops, keys_seen, "calls", "server", bid, event.server, 1, ttl)
                if event.user_id:
                    self._hincrby(ops, keys_seen, "calls", "user", bid, event.user_id, 1, ttl)
                if event.transport:
                    self._hincrby(
                        ops,
                        keys_seen,
                        "calls",
                        "transport",
                        bid,
                        event.transport,
                        1,
                        ttl,
                    )
                if event.duration_ms > 0:
                    duration_int = int(event.duration_ms)
                    self._hincrby(
                        ops,
                        keys_seen,
                        "latency",
                        "sum",
                        bid,
                        tool_field,
                        duration_int,
                        ttl,
                    )
                    self._hincrby(
                        ops,
                        keys_seen,
                        "latency",
                        "count",
                        bid,
                        tool_field,
                        1,
                        ttl,
                    )
                    # Track max for deferred HSET
                    max_key = self._keys.bucket_key("latency", "max", bid)
                    existing = latency_maxes.get((max_key, tool_field), 0)
                    if duration_int > existing:
                        latency_maxes[(max_key, tool_field)] = duration_int
                if event.request_bytes > 0:
                    self._hincrby(
                        ops,
                        keys_seen,
                        "sizes",
                        "request",
                        bid,
                        tool_field,
                        event.request_bytes,
                        ttl,
                    )
                if event.response_bytes > 0:
                    self._hincrby(
                        ops,
                        keys_seen,
                        "sizes",
                        "response",
                        bid,
                        tool_field,
                        event.response_bytes,
                        ttl,
                    )

            elif event.event_type == EventType.DENIAL:
                self._hincrby(ops, keys_seen, "denials", "tool", bid, tool_field, 1, ttl)
                if event.rule_id:
                    self._hincrby(
                        ops,
                        keys_seen,
                        "denials",
                        "rule",
                        bid,
                        event.rule_id,
                        1,
                        ttl,
                    )
                if event.user_id:
                    self._hincrby(
                        ops,
                        keys_seen,
                        "denials",
                        "user",
                        bid,
                        event.user_id,
                        1,
                        ttl,
                    )
                if event.reason:
                    self._hincrby(
                        ops,
                        keys_seen,
                        "denials",
                        "reason",
                        bid,
                        event.reason,
                        1,
                        ttl,
                    )

            elif event.event_type == EventType.REDACTION:
                self._hincrby(
                    ops,
                    keys_seen,
                    "redactions",
                    "input",
                    bid,
                    event.entity_type,
                    event.count,
                    ttl,
                )
                self._hincrby(
                    ops,
                    keys_seen,
                    "redactions",
                    "tool",
                    bid,
                    tool_field,
                    event.count,
                    ttl,
                )

            elif event.event_type == EventType.OUTPUT_REDACTION:
                self._hincrby(
                    ops,
                    keys_seen,
                    "redactions",
                    "output",
                    bid,
                    event.entity_type,
                    event.count,
                    ttl,
                )
                self._hincrby(
                    ops,
                    keys_seen,
                    "redactions",
                    "tool",
                    bid,
                    tool_field,
                    event.count,
                    ttl,
                )

            elif event.event_type == EventType.MASKING_FAILURE:
                self._hincrby(
                    ops,
                    keys_seen,
                    "redactions",
                    "fail",
                    bid,
                    event.direction,
                    1,
                    ttl,
                )

            elif event.event_type == EventType.ERROR:
                self._hincrby(ops, keys_seen, "errors", "tool", bid, tool_field, 1, ttl)

        # Emit HSET for latency max values (not HINCRBY — we want max, not sum).
        # This is approximate when multiple flushes compete, but good enough for
        # a dashboard snapshot.
        for (max_key, field_name), max_val in latency_maxes.items():
            ops.append(("HSET", [max_key, field_name, str(max_val)]))
            if max_key not in keys_seen:
                keys_seen.add(max_key)
                ops.append(("EXPIRE", [max_key, ttl]))

        return ops

    def _hincrby(
        self,
        ops: list[tuple[str, list[Any]]],
        keys_seen: set[str],
        category: str,
        dimension: str,
        bid: int,
        field_name: str,
        increment: int,
        ttl: int,
    ) -> None:
        """Add HINCRBY + EXPIRE (once per key) to the operations list."""
        key = self._keys.bucket_key(category, dimension, bid)
        ops.append(("HINCRBY", [key, field_name, increment]))
        if key not in keys_seen:
            keys_seen.add(key)
            ops.append(("EXPIRE", [key, ttl]))

    # -- Heartbeat & index maintenance ------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Background loop that writes gateway presence to the registry."""
        while self._running:
            try:
                await self._write_heartbeat()
                await asyncio.sleep(self._config.heartbeat_seconds)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("Analytics heartbeat error", exc_info=True)

    async def _write_heartbeat(self) -> None:
        """Write gateway presence and maintain navigation indexes."""
        now = time.time()
        registry_key = self._keys.registry_key()
        info_key = self._keys.info_key()
        member = self._keys.registry_member
        info_ttl = self._config.heartbeat_seconds * 3

        host = os.environ.get("MCP_HOST", "0.0.0.0")
        port = os.environ.get("MCP_PORT", "8080")

        ops: list[tuple[str, list[Any]]] = [
            # Registry sorted set
            ("ZADD", [registry_key, {member: now}]),
            # Gateway info hash
            (
                "HSET",
                [
                    info_key,
                    "host",
                    host,
                    "port",
                    port,
                    "environment",
                    self._config.environment,
                    "gateway_id",
                    self._config.gateway_id,
                    "started_at",
                    str(int(self._started_at)),
                    "last_heartbeat",
                    str(int(now)),
                    "key_prefix",
                    self._config.key_prefix,
                ],
            ),
            ("EXPIRE", [info_key, info_ttl]),
            # Navigation indexes
            ("SADD", [self._keys.idx_envs_key(), self._config.environment]),
            ("SADD", [self._keys.idx_gateways_key(), self._config.gateway_id]),
        ]
        await self._client.execute_pipeline(ops)
