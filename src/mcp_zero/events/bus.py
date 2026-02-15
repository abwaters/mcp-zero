"""EventBus — dispatches audit events to registered handlers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mcp_zero.events.handler import EventHandler

if TYPE_CHECKING:
    from mcp_zero.audit.event import AuditEvent

logger = logging.getLogger(__name__)


class EventBus:
    """Collects event handlers and dispatches audit events to all of them.

    Handlers are called in registration order.  If a handler raises an
    exception it is logged and swallowed — one failing handler never
    prevents other handlers from receiving the event or breaks the
    pipeline.
    """

    def __init__(self) -> None:
        self._handlers: list[EventHandler] = []

    def register(self, handler: EventHandler) -> None:
        """Register an event handler.

        Raises:
            TypeError: If *handler* does not satisfy the EventHandler protocol.
        """
        if not isinstance(handler, EventHandler):
            raise TypeError(
                f"Expected an EventHandler, got {type(handler).__name__}. "
                f"Event handlers must have a 'name' property and an async 'handle_event' method."
            )
        self._handlers.append(handler)
        logger.info("Event handler '%s' registered", handler.name)

    async def emit(self, event: AuditEvent) -> None:
        """Dispatch *event* to every registered handler.

        Exceptions from individual handlers are logged and suppressed.
        """
        for handler in self._handlers:
            try:
                await handler.handle_event(event)
            except Exception:
                logger.exception(
                    "Event handler '%s' failed for event %s", handler.name, event.event_type.value
                )

    @property
    def handlers(self) -> list[EventHandler]:
        """Return a copy of the registered handler list."""
        return list(self._handlers)

    @property
    def handler_count(self) -> int:
        """Return the number of registered handlers."""
        return len(self._handlers)
