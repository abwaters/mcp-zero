"""Integration tests — EventBus wired through AuditHook and PluginManager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcp_zero.audit.event import AuditEvent, AuditEventType
from mcp_zero.audit.hook import AuditHook
from mcp_zero.context import HookContext, PolicyDecision, RequestContext, UserIdentity
from mcp_zero.events.bus import EventBus
from mcp_zero.events.handler import BaseEventHandler
from mcp_zero.governance.config import PluginDeclaration
from mcp_zero.masking.engine import MaskingEvent
from mcp_zero.pipeline.errors import ShortCircuitError
from mcp_zero.pipeline.registry import HookRegistry
from mcp_zero.plugin import BasePlugin
from mcp_zero.plugin_manager import PluginManager


def _make_ctx(**kwargs) -> HookContext:
    """Build a HookContext with sensible defaults."""
    defaults = {
        "request": RequestContext(
            identity=UserIdentity(user_id="test-user", email="test@example.com", groups=["dev"]),
        ),
        "server_name": "test-server",
        "tool_name": "test-tool",
        "policy_decision": PolicyDecision.ALLOW,
        "policy_rule_id": "rule-1",
    }
    defaults.update(kwargs)
    return HookContext(**defaults)


class _RecordingHandler(BaseEventHandler):
    """Handler that records all received events."""

    def __init__(self) -> None:
        self.received: list[AuditEvent] = []

    @property
    def name(self) -> str:
        return "recording-handler"

    async def handle_event(self, event: AuditEvent) -> None:
        self.received.append(event)


# ---------------------------------------------------------------------------
# AuditHook + EventBus integration
# ---------------------------------------------------------------------------


class TestAuditHookEventBus:
    @pytest.mark.asyncio
    async def test_events_dispatched_on_pre_audit(self):
        bus = EventBus()
        handler = _RecordingHandler()
        bus.register(handler)

        hook = AuditHook(event_bus=bus)
        ctx = _make_ctx()
        await hook.on_pre_audit(ctx)

        assert len(handler.received) == 1
        assert handler.received[0].event_type == AuditEventType.TOOL_INVOCATION

    @pytest.mark.asyncio
    async def test_masking_event_dispatched(self):
        bus = EventBus()
        handler = _RecordingHandler()
        bus.register(handler)

        hook = AuditHook(event_bus=bus)
        ctx = _make_ctx(
            masking_applied=True,
            masked_fields=["name"],
            masking_events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
            masking_stage_completed=True,
        )
        await hook.on_pre_audit(ctx)

        assert len(handler.received) == 2
        assert handler.received[0].event_type == AuditEventType.TOOL_INVOCATION
        assert handler.received[1].event_type == AuditEventType.MASKING_EVENT

    @pytest.mark.asyncio
    async def test_error_event_dispatched(self):
        bus = EventBus()
        handler = _RecordingHandler()
        bus.register(handler)

        hook = AuditHook(event_bus=bus)
        ctx = _make_ctx(short_circuited=True, short_circuit_reason="denied")
        error = ShortCircuitError("denied by policy", deny=True)
        await hook.on_error(ctx, error)

        assert len(handler.received) == 1
        assert handler.received[0].event_type == AuditEventType.POLICY_DECISION
        assert handler.received[0].error_type == "ShortCircuitError"

    @pytest.mark.asyncio
    async def test_generic_error_dispatched(self):
        bus = EventBus()
        handler = _RecordingHandler()
        bus.register(handler)

        hook = AuditHook(event_bus=bus)
        ctx = _make_ctx()
        await hook.on_error(ctx, RuntimeError("boom"))

        assert len(handler.received) == 1
        assert handler.received[0].event_type == AuditEventType.ERROR

    @pytest.mark.asyncio
    async def test_no_event_bus_works(self):
        """AuditHook without event_bus still works normally."""
        hook = AuditHook()
        ctx = _make_ctx()
        result = await hook.on_pre_audit(ctx)
        assert result is ctx
        assert len(hook.events) == 1

    @pytest.mark.asyncio
    async def test_event_metadata_matches(self):
        bus = EventBus()
        handler = _RecordingHandler()
        bus.register(handler)

        hook = AuditHook(event_bus=bus)
        ctx = _make_ctx(transport="http")
        await hook.on_pre_audit(ctx)

        event = handler.received[0]
        assert event.correlation_id == ctx.request.correlation_id
        assert event.user_id == "test-user"
        assert event.server_name == "test-server"
        assert event.tool_name == "test-tool"
        assert event.transport == "http"

    @pytest.mark.asyncio
    async def test_handler_error_does_not_break_audit(self):
        """A failing event handler must not break the audit hook."""

        class FailHandler(BaseEventHandler):
            @property
            def name(self) -> str:
                return "fail"

            async def handle_event(self, event: AuditEvent) -> None:
                raise RuntimeError("handler crash")

        bus = EventBus()
        bus.register(FailHandler())

        hook = AuditHook(event_bus=bus)
        ctx = _make_ctx()
        result = await hook.on_pre_audit(ctx)

        # Hook still succeeds and records the event
        assert result is ctx
        assert len(hook.events) == 1


# ---------------------------------------------------------------------------
# PluginManager + EventBus integration
# ---------------------------------------------------------------------------


def _make_entry_point(name: str, factory=None):
    ep = MagicMock()
    ep.name = name
    if factory is not None:
        ep.load.return_value = factory
    return ep


class TestPluginManagerEventBus:
    def test_plugin_register_event_handlers_called(self, monkeypatch):
        """Plugins with register_event_handlers get the event bus."""
        bus_received = []

        class EventPlugin(BasePlugin):
            @property
            def name(self):
                return "event-plugin"

            def register_event_handlers(self, bus):
                bus_received.append(bus)

        ep = _make_entry_point("event-plugin", EventPlugin)
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep],
        )

        mgr = PluginManager()
        registry = HookRegistry()
        event_bus = EventBus()
        decl = PluginDeclaration(name="event-plugin", package="event-plugin")
        mgr.load_plugins([decl], registry, event_bus=event_bus)

        assert bus_received == [event_bus]

    def test_plugin_without_register_event_handlers(self, monkeypatch):
        """Plugins without register_event_handlers still load fine."""

        class PlainPlugin:
            @property
            def name(self):
                return "plain"

            def configure(self, config):
                pass

            def register(self, registry):
                pass

            def teardown(self):
                pass

        ep = _make_entry_point("plain", PlainPlugin)
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep],
        )

        mgr = PluginManager()
        registry = HookRegistry()
        event_bus = EventBus()
        decl = PluginDeclaration(name="plain", package="plain")
        mgr.load_plugins([decl], registry, event_bus=event_bus)

        assert len(mgr.loaded_plugins) == 1

    def test_no_event_bus_backward_compatible(self, monkeypatch):
        """load_plugins without event_bus still works (backward compatible)."""

        class SimplePlugin(BasePlugin):
            @property
            def name(self):
                return "simple"

        ep = _make_entry_point("simple", SimplePlugin)
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep],
        )

        mgr = PluginManager()
        registry = HookRegistry()
        decl = PluginDeclaration(name="simple", package="simple")
        mgr.load_plugins([decl], registry)  # no event_bus arg

        assert len(mgr.loaded_plugins) == 1

    def test_plugin_registers_handler_on_bus(self, monkeypatch):
        """A plugin can register an event handler during register_event_handlers."""

        class EventPlugin(BasePlugin):
            @property
            def name(self):
                return "registering-plugin"

            def register_event_handlers(self, bus):
                bus.register(_RecordingHandler())

        ep = _make_entry_point("registering-plugin", EventPlugin)
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep],
        )

        mgr = PluginManager()
        registry = HookRegistry()
        event_bus = EventBus()
        decl = PluginDeclaration(name="registering-plugin", package="registering-plugin")
        mgr.load_plugins([decl], registry, event_bus=event_bus)

        assert event_bus.handler_count == 1
