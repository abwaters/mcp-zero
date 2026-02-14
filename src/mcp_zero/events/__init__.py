"""Event plugin architecture — optional event dispatch for logging, alerting, etc."""

from mcp_zero.events.bus import EventBus
from mcp_zero.events.handler import BaseEventHandler, EventHandler

__all__ = ["EventBus", "EventHandler", "BaseEventHandler"]
