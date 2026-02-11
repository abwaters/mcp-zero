"""Tests for AnalyticsHook — lifecycle hook recording."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from mcp_zero.analytics.collector import AnalyticsCollector, AnalyticsEvent
from mcp_zero.analytics.config import AnalyticsConfig, RedisConfig
from mcp_zero.analytics.hook import AnalyticsHook
from mcp_zero.context import HookContext, PolicyDecision, RequestContext, UserIdentity
from mcp_zero.pipeline.errors import ShortCircuitError


@dataclass(frozen=True)
class _FakeMaskingEvent:
    """Minimal stand-in for MaskingEvent to avoid deep import chains."""

    entity_type: str
    count: int
    status: str


class FakeRedisClient:
    """Stub Redis client for testing."""

    connected = True

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def execute_pipeline(self, operations):
        pass


def _make_collector() -> AnalyticsCollector:
    config = AnalyticsConfig(
        redis=RedisConfig(url="redis://localhost:6379"),
        environment="test",
        gateway_id="test-gw",
        queue_size=100,
    )
    return AnalyticsCollector(config, FakeRedisClient())


def _make_ctx(**kwargs) -> HookContext:
    defaults = {
        "request": RequestContext(
            identity=UserIdentity(user_id="test-user", groups=["dev"]),
        ),
        "server_name": "test-server",
        "tool_name": "test-tool",
        "policy_decision": PolicyDecision.ALLOW,
        "policy_rule_id": "rule-1",
    }
    defaults.update(kwargs)
    return HookContext(**defaults)


class TestAnalyticsHookPreAudit:
    @pytest.mark.asyncio
    async def test_records_tool_call(self):
        collector = _make_collector()
        hook = AnalyticsHook(collector)

        ctx = _make_ctx(request_payload={"arguments": {"path": "/tmp"}})
        await hook.on_pre_audit(ctx)

        assert collector._queue.qsize() >= 1
        event = collector._queue.get_nowait()
        assert event.event_type == "tool_call"
        assert event.server == "test-server"
        assert event.tool == "test-tool"
        assert event.user_id == "test-user"

    @pytest.mark.asyncio
    async def test_records_tool_call_without_identity(self):
        collector = _make_collector()
        hook = AnalyticsHook(collector)

        ctx = _make_ctx(request=RequestContext())
        await hook.on_pre_audit(ctx)

        event = collector._queue.get_nowait()
        assert event.user_id == ""

    @pytest.mark.asyncio
    async def test_records_redactions_from_masking_events(self):
        collector = _make_collector()
        hook = AnalyticsHook(collector)

        masking_events = [
            _FakeMaskingEvent(entity_type="EMAIL_ADDRESS", count=2, status="success"),
            _FakeMaskingEvent(entity_type="PHONE_NUMBER", count=1, status="success"),
        ]
        ctx = _make_ctx(masking_events=masking_events)
        await hook.on_pre_audit(ctx)

        # 1 tool_call + 2 redaction events
        assert collector._queue.qsize() == 3

        events: list[AnalyticsEvent] = []
        while not collector._queue.empty():
            events.append(collector._queue.get_nowait())

        tool_calls = [e for e in events if e.event_type == "tool_call"]
        redactions = [e for e in events if e.event_type == "redaction"]

        assert len(tool_calls) == 1
        assert len(redactions) == 2
        assert redactions[0].entity_type == "EMAIL_ADDRESS"
        assert redactions[0].count == 2
        assert redactions[1].entity_type == "PHONE_NUMBER"
        assert redactions[1].count == 1

    @pytest.mark.asyncio
    async def test_measures_payload_sizes(self):
        collector = _make_collector()
        hook = AnalyticsHook(collector)

        ctx = _make_ctx(
            request_payload={"arguments": {"data": "hello"}},
            response_payload={"content": [{"type": "text", "text": "world"}]},
        )
        await hook.on_pre_audit(ctx)

        event = collector._queue.get_nowait()
        assert event.request_bytes > 0
        assert event.response_bytes > 0


class TestAnalyticsHookOnError:
    @pytest.mark.asyncio
    async def test_records_denial_on_short_circuit(self):
        collector = _make_collector()
        hook = AnalyticsHook(collector)

        ctx = _make_ctx(policy_rule_id="deny-rule")
        error = ShortCircuitError("Access denied", deny=True)
        await hook.on_error(ctx, error)

        event = collector._queue.get_nowait()
        assert event.event_type == "denial"
        assert event.server == "test-server"
        assert event.tool == "test-tool"
        assert event.user_id == "test-user"
        assert event.rule_id == "deny-rule"

    @pytest.mark.asyncio
    async def test_records_error_on_other_exception(self):
        collector = _make_collector()
        hook = AnalyticsHook(collector)

        ctx = _make_ctx()
        error = RuntimeError("Something broke")
        await hook.on_error(ctx, error)

        event = collector._queue.get_nowait()
        assert event.event_type == "error"
        assert event.server == "test-server"
        assert event.tool == "test-tool"

    @pytest.mark.asyncio
    async def test_denial_without_identity(self):
        collector = _make_collector()
        hook = AnalyticsHook(collector)

        ctx = _make_ctx(request=RequestContext())
        error = ShortCircuitError("No auth", deny=True)
        await hook.on_error(ctx, error)

        event = collector._queue.get_nowait()
        assert event.user_id == ""
