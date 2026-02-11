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

        collector.record_denial(server="s1", tool="t1", user_id="alice", rule_id="r1")
        assert collector._queue.qsize() == 1

    def test_record_redaction_enqueues(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        collector.record_redaction(server="s1", tool="t1", entity_type="EMAIL", count=3)
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
    def test_tool_call_generates_correct_ops(self):
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
            timestamp=60000.0,
        )

        ops = collector._build_operations([event])

        # Extract just the commands
        commands = [op[0] for op in ops]
        assert "HINCRBY" in commands
        assert "EXPIRE" in commands

        # Check that tool_calls, server_calls, user_calls are all present
        hincrby_keys = [op[1][0] for op in ops if op[0] == "HINCRBY"]
        assert any("tool_calls" in k for k in hincrby_keys)
        assert any("server_calls" in k for k in hincrby_keys)
        assert any("user_calls" in k for k in hincrby_keys)
        assert any("latency_sum" in k for k in hincrby_keys)
        assert any("latency_count" in k for k in hincrby_keys)
        assert any("request_bytes" in k for k in hincrby_keys)
        assert any("response_bytes" in k for k in hincrby_keys)

    def test_denial_generates_correct_ops(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        event = AnalyticsEvent(
            event_type=EventType.DENIAL,
            server="s1",
            tool="t1",
            user_id="bob",
            rule_id="deny-all",
            timestamp=60000.0,
        )

        ops = collector._build_operations([event])
        hincrby_keys = [op[1][0] for op in ops if op[0] == "HINCRBY"]

        assert any("denials" in k for k in hincrby_keys)
        assert any("denial_rules" in k for k in hincrby_keys)
        assert any("denial_users" in k for k in hincrby_keys)

    def test_redaction_generates_correct_ops(self):
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
        hincrby_ops = [op for op in ops if op[0] == "HINCRBY"]

        # Should have redactions + redaction_tools
        assert len(hincrby_ops) == 2
        # Check the entity_type field name
        assert any(op[1][1] == "EMAIL_ADDRESS" for op in hincrby_ops)
        # Check count is 5
        assert any(op[1][2] == 5 for op in hincrby_ops)

    def test_error_generates_correct_ops(self):
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
        assert any("errors" in k for k in hincrby_keys)

    def test_expire_only_once_per_key(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        # Two events in the same bucket and same metric
        events = [
            AnalyticsEvent(
                event_type=EventType.TOOL_CALL, server="s1", tool="t1", timestamp=60000.0
            ),
            AnalyticsEvent(
                event_type=EventType.TOOL_CALL, server="s1", tool="t2", timestamp=60000.0
            ),
        ]

        ops = collector._build_operations(events)

        # Count EXPIRE calls for tool_calls keys
        expire_keys = [op[1][0] for op in ops if op[0] == "EXPIRE"]
        tool_calls_expires = [k for k in expire_keys if "tool_calls" in k]
        # Should only be 1 EXPIRE for the tool_calls bucket key
        assert len(tool_calls_expires) == 1


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
        assert len(client.operations) == 1  # One pipeline batch

    @pytest.mark.asyncio
    async def test_flush_noop_when_empty(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        await collector._flush()

        assert len(client.operations) == 0


class TestAnalyticsCollectorLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        await collector.start()
        assert collector._running is True
        assert client.connected is True

        # Enqueue some events and let a flush cycle happen
        collector.record_tool_call(server="s1", tool="t1")
        await asyncio.sleep(0.2)  # Let flush loop run

        await collector.stop()
        assert collector._running is False

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        await collector.start()
        await collector.start()  # Should not error
        assert collector._running is True

        await collector.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        config = _make_config()
        client = FakeRedisClient()
        collector = AnalyticsCollector(config, client)

        await collector.stop()  # Should not error
