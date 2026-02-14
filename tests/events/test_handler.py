"""Tests for EventHandler protocol and BaseEventHandler."""

import pytest

from mcp_zero.audit.event import AuditEvent, AuditEventType
from mcp_zero.events.handler import BaseEventHandler, EventHandler


class TestEventHandlerProtocol:
    def test_base_event_handler_satisfies_protocol(self):
        handler = BaseEventHandler()
        assert isinstance(handler, EventHandler)

    def test_plain_class_satisfies_protocol(self):
        class MyHandler:
            @property
            def name(self) -> str:
                return "my-handler"

            async def handle_event(self, event):
                pass

        assert isinstance(MyHandler(), EventHandler)

    def test_missing_handle_event_fails_protocol(self):
        class Incomplete:
            @property
            def name(self) -> str:
                return "incomplete"

        assert not isinstance(Incomplete(), EventHandler)

    def test_missing_name_property_fails_protocol(self):
        class NoName:
            async def handle_event(self, event):
                pass

        assert not isinstance(NoName(), EventHandler)


class TestBaseEventHandler:
    def test_name_defaults_to_class_name(self):
        handler = BaseEventHandler()
        assert handler.name == "BaseEventHandler"

    def test_subclass_name_defaults_to_subclass_name(self):
        class MyCustomHandler(BaseEventHandler):
            pass

        handler = MyCustomHandler()
        assert handler.name == "MyCustomHandler"

    @pytest.mark.asyncio
    async def test_handle_event_is_noop(self):
        handler = BaseEventHandler()
        event = AuditEvent(event_type=AuditEventType.TOOL_INVOCATION)
        await handler.handle_event(event)  # should not raise
