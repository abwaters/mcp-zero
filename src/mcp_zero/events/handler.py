"""EventHandler protocol and base class for event plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from mcp_zero.audit.event import AuditEvent


@runtime_checkable
class EventHandler(Protocol):
    """Protocol that event handlers must satisfy.

    Event handlers receive all core audit events emitted by the gateway
    pipeline.  Implementations can use these for external logging,
    alerting, metrics collection, or any other observability need.

    Handlers are called in registration order.  Exceptions in one
    handler do not prevent subsequent handlers from receiving the event.
    """

    @property
    def name(self) -> str: ...

    async def handle_event(self, event: AuditEvent) -> None: ...


class BaseEventHandler:
    """Convenience base class with no-op defaults for EventHandler.

    Subclasses only need to override ``handle_event``.
    The ``name`` property defaults to the class name.
    """

    @property
    def name(self) -> str:
        return type(self).__name__

    async def handle_event(self, event: AuditEvent) -> None:
        pass
