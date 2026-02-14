"""Tests for EventBus — event dispatch to registered handlers."""

from __future__ import annotations

import pytest

from mcp_zero.audit.event import AuditEvent, AuditEventType
from mcp_zero.events.bus import EventBus
from mcp_zero.events.handler import BaseEventHandler


def _make_event(**kwargs) -> AuditEvent:
    """Build an AuditEvent with sensible defaults."""
    defaults = {
        "event_type": AuditEventType.TOOL_INVOCATION,
        "correlation_id": "test-corr-id",
        "server_name": "test-server",
        "tool_name": "test-tool",
    }
    defaults.update(kwargs)
    return AuditEvent(**defaults)


class _RecordingHandler(BaseEventHandler):
    """Handler that records all received events."""

    def __init__(self, name: str = "recorder") -> None:
        self._name = name
        self.received: list[AuditEvent] = []

    @property
    def name(self) -> str:
        return self._name

    async def handle_event(self, event: AuditEvent) -> None:
        self.received.append(event)


class _FailingHandler(BaseEventHandler):
    """Handler that raises on every event."""

    @property
    def name(self) -> str:
        return "failing-handler"

    async def handle_event(self, event: AuditEvent) -> None:
        raise RuntimeError("handler exploded")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestEventBusRegistration:
    def test_register_handler(self):
        bus = EventBus()
        handler = _RecordingHandler()
        bus.register(handler)

        assert bus.handler_count == 1
        assert bus.handlers == [handler]

    def test_register_multiple_handlers(self):
        bus = EventBus()
        h1 = _RecordingHandler("h1")
        h2 = _RecordingHandler("h2")
        bus.register(h1)
        bus.register(h2)

        assert bus.handler_count == 2
        assert bus.handlers == [h1, h2]

    def test_register_rejects_non_handler(self):
        bus = EventBus()
        with pytest.raises(TypeError, match="Expected an EventHandler"):
            bus.register("not a handler")  # type: ignore[arg-type]

    def test_register_rejects_incomplete_handler(self):
        class Incomplete:
            @property
            def name(self) -> str:
                return "incomplete"

        bus = EventBus()
        with pytest.raises(TypeError, match="Expected an EventHandler"):
            bus.register(Incomplete())  # type: ignore[arg-type]

    def test_handlers_returns_copy(self):
        bus = EventBus()
        handler = _RecordingHandler()
        bus.register(handler)

        handlers = bus.handlers
        handlers.clear()
        assert bus.handler_count == 1  # original unaffected

    def test_empty_bus(self):
        bus = EventBus()
        assert bus.handler_count == 0
        assert bus.handlers == []


# ---------------------------------------------------------------------------
# Event dispatch
# ---------------------------------------------------------------------------


class TestEventBusEmit:
    @pytest.mark.asyncio
    async def test_emit_dispatches_to_handler(self):
        bus = EventBus()
        handler = _RecordingHandler()
        bus.register(handler)

        event = _make_event()
        await bus.emit(event)

        assert len(handler.received) == 1
        assert handler.received[0] is event

    @pytest.mark.asyncio
    async def test_emit_dispatches_to_all_handlers(self):
        bus = EventBus()
        h1 = _RecordingHandler("h1")
        h2 = _RecordingHandler("h2")
        bus.register(h1)
        bus.register(h2)

        event = _make_event()
        await bus.emit(event)

        assert len(h1.received) == 1
        assert len(h2.received) == 1

    @pytest.mark.asyncio
    async def test_emit_preserves_order(self):
        order: list[str] = []

        class OrderTracker(BaseEventHandler):
            def __init__(self, label: str):
                self._label = label

            @property
            def name(self) -> str:
                return self._label

            async def handle_event(self, event: AuditEvent) -> None:
                order.append(self._label)

        bus = EventBus()
        bus.register(OrderTracker("first"))
        bus.register(OrderTracker("second"))
        bus.register(OrderTracker("third"))

        await bus.emit(_make_event())
        assert order == ["first", "second", "third"]

    @pytest.mark.asyncio
    async def test_emit_multiple_events(self):
        bus = EventBus()
        handler = _RecordingHandler()
        bus.register(handler)

        e1 = _make_event(correlation_id="c1")
        e2 = _make_event(correlation_id="c2")
        await bus.emit(e1)
        await bus.emit(e2)

        assert len(handler.received) == 2
        assert handler.received[0].correlation_id == "c1"
        assert handler.received[1].correlation_id == "c2"

    @pytest.mark.asyncio
    async def test_emit_no_handlers_is_noop(self):
        bus = EventBus()
        event = _make_event()
        await bus.emit(event)  # should not raise


# ---------------------------------------------------------------------------
# Error resilience
# ---------------------------------------------------------------------------


class TestEventBusErrorResilience:
    @pytest.mark.asyncio
    async def test_failing_handler_does_not_block_others(self):
        bus = EventBus()
        recorder = _RecordingHandler()
        bus.register(_FailingHandler())
        bus.register(recorder)

        event = _make_event()
        await bus.emit(event)  # should not raise

        # The second handler still received the event
        assert len(recorder.received) == 1

    @pytest.mark.asyncio
    async def test_failing_handler_logged(self, caplog):
        import logging

        bus = EventBus()
        bus.register(_FailingHandler())

        with caplog.at_level(logging.ERROR, logger="mcp_zero.events.bus"):
            await bus.emit(_make_event())

        assert any("failing-handler" in r.message for r in caplog.records)
        assert any("handler exploded" in (r.exc_text or "") for r in caplog.records)

    @pytest.mark.asyncio
    async def test_multiple_failing_handlers(self):
        bus = EventBus()
        recorder = _RecordingHandler()
        bus.register(_FailingHandler())
        bus.register(_FailingHandler())
        bus.register(recorder)

        await bus.emit(_make_event())

        # Despite two failures, the recording handler still gets the event
        assert len(recorder.received) == 1
