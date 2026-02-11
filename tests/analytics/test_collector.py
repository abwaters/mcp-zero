"""Tests for AnalyticsCollector — event queueing and Redis batch writes."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mcp_zero.analytics.collector import AnalyticsCollector, AnalyticsEvent, EventType
from mcp_zero.analytics.config import AnalyticsConfig, RedisConfig


def _make_config(**overrides) -> AnalyticsConfig:
    """Build an AnalyticsConfig with test defaults."""
    defaults = {
        "redis": RedisConfig(url="redis://localhost:6379"),
        "environment": "test",
        "gateway_id": "test-gw",
        "bucket_seconds": 60,
        "retention_seconds": 300,
        "heartbeat_seconds": 30,
        "queue_size": 100,
        "flush_interval": 0.1,
    }
    defaults.update(overrides)
    return AnalyticsConfig(**defaults)


class FakeRedisClient:
    """In-memory Redis client mock for testing."""

    def __init__(self):
        self.operations: list[list[tuple[str, list[Any]]]] = []
        self.connected = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def execute_pipeline(self, operations: list[tuple[str, list[Any]]]) -> None:
        self.operations.append(operations)


class TestAnalyticsCollectorEnqueue:
    def test_record_tool_call_enqueues(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        collector.record_tool_call(server="s1", tool="t1", user_id="alice")
        assert collector._queue.qsize() == 1

    def test_record_denial_enqueues(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        collector.record_denial(
            server="s1", tool="t1", user_id="alice", rule_id="r1"
        )
        assert collector._queue.qsize() == 1

    def test_record_redaction_enqueues(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        collector.record_redaction(
            server="s1", tool="t1", entity_type="EMAIL", count=3
        )
        assert collector._queue.qsize() == 1

    def test_record_output_redaction_enqueues(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        collector.record_output_redaction(
            server="s1", tool="t1", entity_type="PERSON", count=2
        )
        assert collector._queue.qsize() == 1

    def test_record_masking_failure_enqueues(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        collector.record_masking_failure(
            server="s1", tool="t1", direction="input"
        )
        assert collector._queue.qsize() == 1

    def test_record_error_enqueues(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        collector.record_error(server="s1", tool="t1")
        assert collector._queue.qsize() == 1

    def test_queue_full_drops_events(self):
        config = _make_config(queue_size=2)
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        collector.record_tool_call(server="s1", tool="t1")
        collector.record_tool_call(server="s1", tool="t2")
        collector.record_tool_call(server="s1", tool="t3")  # dropped

        assert collector._queue.qsize() == 2
        assert collector._drop_count == 1


class TestAnalyticsCollectorBuildOperations:
    def test_tool_call_generates_hierarchical_keys(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        event = AnalyticsEvent(
            event_type=EventType.TOOL_CALL,
            server="myserver",
            tool="mytool",
            user_id="alice",
            duration_ms=150.0,
            request_bytes=100,
            response_bytes=200,
            transport="http",
            timestamp=60000.0,
        )

        ops = collector._build_operations([event])

        commands = [op[0] for op in ops]
        assert "HINCRBY" in commands
        assert "EXPIRE" in commands

        hincrby_keys = [op[1][0] for op in ops if op[0] == "HINCRBY"]
        # Verify hierarchical key pattern: ...:{category}:{dimension}
        assert any(":calls:tool" in k for k in hincrby_keys)
        assert any(":calls:server" in k for k in hincrby_keys)
        assert any(":calls:user" in k for k in hincrby_keys)
        assert any(":calls:transport" in k for k in hincrby_keys)
        assert any(":latency:sum" in k for k in hincrby_keys)
        assert any(":latency:count" in k for k in hincrby_keys)
        assert any(":sizes:request" in k for k in hincrby_keys)
        assert any(":sizes:response" in k for k in hincrby_keys)

        # Verify gw: prefix in key path
        assert all(":gw:" in k for k in hincrby_keys)

    def test_tool_call_records_transport(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        event = AnalyticsEvent(
            event_type=EventType.TOOL_CALL,
            server="s1",
            tool="t1",
            transport="stdio",
            timestamp=60000.0,
        )

        ops = collector._build_operations([event])
        transport_ops = [
            op for op in ops
            if op[0] == "HINCRBY" and ":calls:transport" in op[1][0]
        ]
        assert len(transport_ops) == 1
        assert transport_ops[0][1][1] == "stdio"

    def test_tool_call_tracks_latency_max(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        events = [
            AnalyticsEvent(
                event_type=EventType.TOOL_CALL, server="s1", tool="t1",
                duration_ms=100.0, timestamp=60000.0,
            ),
            AnalyticsEvent(
                event_type=EventType.TOOL_CALL, server="s1", tool="t1",
                duration_ms=250.0, timestamp=60000.0,
            ),
        ]

        ops = collector._build_operations(events)
        hset_ops = [
            op for op in ops
            if op[0] == "HSET" and ":latency:max" in op[1][0]
        ]
        assert len(hset_ops) == 1
        # Should be the max of 100 and 250
        assert hset_ops[0][1][2] == "250"

    def test_denial_generates_hierarchical_keys(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        event = AnalyticsEvent(
            event_type=EventType.DENIAL,
            server="s1",
            tool="t1",
            user_id="bob",
            rule_id="deny-all",
            reason="policy_deny",
            timestamp=60000.0,
        )

        ops = collector._build_operations([event])
        hincrby_keys = [op[1][0] for op in ops if op[0] == "HINCRBY"]

        assert any(":denials:tool" in k for k in hincrby_keys)
        assert any(":denials:rule" in k for k in hincrby_keys)
        assert any(":denials:user" in k for k in hincrby_keys)
        assert any(":denials:reason" in k for k in hincrby_keys)

    def test_denial_records_reason(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        event = AnalyticsEvent(
            event_type=EventType.DENIAL,
            server="s1",
            tool="t1",
            reason="no_identity",
            timestamp=60000.0,
        )

        ops = collector._build_operations([event])
        reason_ops = [
            op for op in ops
            if op[0] == "HINCRBY" and ":denials:reason" in op[1][0]
        ]
        assert len(reason_ops) == 1
        assert reason_ops[0][1][1] == "no_identity"

    def test_redaction_uses_input_key(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        event = AnalyticsEvent(
            event_type=EventType.REDACTION,
            server="s1",
            tool="t1",
            entity_type="EMAIL_ADDRESS",
            count=5,
            timestamp=60000.0,
        )

        ops = collector._build_operations([event])
        hincrby_keys = [op[1][0] for op in ops if op[0] == "HINCRBY"]

        assert any(":redactions:input" in k for k in hincrby_keys)
        assert any(":redactions:tool" in k for k in hincrby_keys)
        # Verify entity_type as field name
        input_ops = [
            op for op in ops
            if op[0] == "HINCRBY" and ":redactions:input" in op[1][0]
        ]
        assert input_ops[0][1][1] == "EMAIL_ADDRESS"
        assert input_ops[0][1][2] == 5

    def test_output_redaction_uses_output_key(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        event = AnalyticsEvent(
            event_type=EventType.OUTPUT_REDACTION,
            server="s1",
            tool="t1",
            entity_type="PERSON",
            count=2,
            timestamp=60000.0,
        )

        ops = collector._build_operations([event])
        hincrby_keys = [op[1][0] for op in ops if op[0] == "HINCRBY"]

        assert any(":redactions:output" in k for k in hincrby_keys)
        assert any(":redactions:tool" in k for k in hincrby_keys)

    def test_masking_failure_uses_fail_key(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        event = AnalyticsEvent(
            event_type=EventType.MASKING_FAILURE,
            server="s1",
            tool="t1",
            direction="output",
            timestamp=60000.0,
        )

        ops = collector._build_operations([event])
        fail_ops = [
            op for op in ops
            if op[0] == "HINCRBY" and ":redactions:fail" in op[1][0]
        ]
        assert len(fail_ops) == 1
        assert fail_ops[0][1][1] == "output"

    def test_error_generates_hierarchical_key(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        event = AnalyticsEvent(
            event_type=EventType.ERROR,
            server="s1",
            tool="t1",
            timestamp=60000.0,
        )

        ops = collector._build_operations([event])
        hincrby_keys = [op[1][0] for op in ops if op[0] == "HINCRBY"]
        assert any(":errors:tool" in k for k in hincrby_keys)

    def test_expire_only_once_per_key(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        events = [
            AnalyticsEvent(
                event_type=EventType.TOOL_CALL, server="s1", tool="t1",
                timestamp=60000.0,
            ),
            AnalyticsEvent(
                event_type=EventType.TOOL_CALL, server="s1", tool="t2",
                timestamp=60000.0,
            ),
        ]

        ops = collector._build_operations(events)

        expire_keys = [op[1][0] for op in ops if op[0] == "EXPIRE"]
        calls_tool_expires = [k for k in expire_keys if ":calls:tool" in k]
        assert len(calls_tool_expires) == 1


class TestAnalyticsCollectorFlush:
    @pytest.mark.asyncio
    async def test_flush_drains_queue(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        collector.record_tool_call(server="s1", tool="t1")
        collector.record_tool_call(server="s1", tool="t2")

        await collector._flush()

        assert collector._queue.qsize() == 0
        assert len(client.operations) == 1

    @pytest.mark.asyncio
    async def test_flush_noop_when_empty(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        await collector._flush()

        assert len(client.operations) == 0


class TestAnalyticsCollectorHeartbeat:
    @pytest.mark.asyncio
    async def test_heartbeat_writes_indexes(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        await collector._write_heartbeat()

        assert len(client.operations) == 1
        ops = client.operations[0]
        commands = [op[0] for op in ops]

        assert "ZADD" in commands
        assert "HSET" in commands
        assert "EXPIRE" in commands
        assert "SADD" in commands

        # Verify SADD writes to idx keys
        sadd_ops = [op for op in ops if op[0] == "SADD"]
        sadd_keys = [op[1][0] for op in sadd_ops]
        assert any(":idx:envs" in k for k in sadd_keys)
        assert any(":idx:gw:" in k for k in sadd_keys)


class TestAnalyticsCollectorLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        await collector.start()
        assert collector._running is True
        assert client.connected is True

        collector.record_tool_call(server="s1", tool="t1")
        await asyncio.sleep(0.2)

        await collector.stop()
        assert collector._running is False

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        await collector.start()
        await collector.start()
        assert collector._running is True

        await collector.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        await collector.stop()
