"""Request context for correlation and user attribution."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class UserIdentity:
    """Resolved user identity from a validated JWT token."""

    user_id: str
    email: str | None = None
    groups: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RequestContext:
    """Per-request context carrying correlation ID and user identity.

    Each request gets a unique ``correlation_id``.  A ``trace_id`` groups
    parent-child calls together — it defaults to the ``correlation_id`` of the
    root request and is inherited by child contexts.
    """

    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = ""
    identity: UserIdentity | None = None
    raw_token: str | None = None

    def __post_init__(self) -> None:
        if not self.trace_id:
            object.__setattr__(self, "trace_id", self.correlation_id)

    def child_context(self) -> RequestContext:
        """Create a child context with a new correlation ID but the same trace."""
        return RequestContext(
            trace_id=self.trace_id,
            identity=self.identity,
            raw_token=self.raw_token,
        )


class PolicyDecision(StrEnum):
    """Governance policy outcome for a request."""

    PENDING = "pending"
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class HookContext:
    """Immutable context threaded through the lifecycle pipeline.

    Each hook returns a new instance via evolve() (dataclasses.replace wrapper).
    """

    request: RequestContext = field(default_factory=RequestContext)
    request_payload: dict[str, Any] = field(default_factory=dict)
    response_payload: dict[str, Any] = field(default_factory=dict)
    server_name: str = ""
    tool_name: str = ""
    policy_decision: PolicyDecision = PolicyDecision.PENDING
    policy_rule_id: str = ""
    masking_applied: bool = False
    masked_fields: list[str] = field(default_factory=list)
    masking_events: list[Any] = field(default_factory=list)
    output_masking_applied: bool = False
    output_masked_fields: list[str] = field(default_factory=list)
    masking_stage_completed: bool = False
    short_circuited: bool = False
    short_circuit_reason: str = ""
    started_at: float = field(default_factory=time.monotonic)
    extras: dict[str, Any] = field(default_factory=dict)

    def evolve(self, **changes: Any) -> HookContext:
        """Return a new HookContext with the given fields replaced."""
        return replace(self, **changes)
