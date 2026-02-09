"""Request context for correlation and user attribution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RequestContext:
    """Per-request context carrying correlation ID and user identity.

    Stories #11/#12 will extend this with full identity propagation.
    """

    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str | None = None
    user_email: str | None = None
    user_groups: list[str] = field(default_factory=list)
