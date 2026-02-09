"""Request context for correlation and user attribution."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class RequestContext:
    """Per-request context carrying correlation ID and user identity.

    Stories #11/#12 will extend this with full identity propagation.
    """

    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str | None = None
    user_email: str | None = None
    user_groups: list[str] = field(default_factory=list)


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
    short_circuited: bool = False
    short_circuit_reason: str = ""
    started_at: float = field(default_factory=time.monotonic)
    extras: dict[str, Any] = field(default_factory=dict)

    def evolve(self, **changes: Any) -> HookContext:
        """Return a new HookContext with the given fields replaced."""
        return replace(self, **changes)
