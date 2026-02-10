"""Audit event dataclasses — deliberately payload-free."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AuditEventType(StrEnum):
    """Type of audit event emitted by the pipeline."""

    TOOL_INVOCATION = "mcp_tool_invocation"
    POLICY_DECISION = "policy_decision"
    MASKING_EVENT = "masking_event"
    ERROR = "error"


@dataclass(frozen=True)
class MaskingEventSummary:
    """Summary of a single masking operation for the JSON audit schema.

    Maps to items in the ``masking_events[]`` array in the issue #23 schema.
    """

    entity_type: str = ""
    count: int = 0
    status: str = ""  # "success" | "failed"


@dataclass(frozen=True)
class MaskingSummary:
    """Summary of masking activity for an audit event.

    Contains only *metadata* — entity types, counts, and field paths.
    Never contains original or masked text values.
    """

    applied: bool = False
    entity_types: list[str] = field(default_factory=list)
    entity_counts: dict[str, int] = field(default_factory=dict)
    masked_field_count: int = 0
    masked_fields: list[str] = field(default_factory=list)
    failure_count: int = 0
    masking_stage_completed: bool = False


@dataclass(frozen=True)
class AuditEvent:
    """A single audit event — payload-free by design.

    Contains only metadata, policy decisions, and masking summaries.
    Request and response payloads are *never* stored here, eliminating
    any risk of unmasked sensitive data reaching audit logs.
    """

    event_type: AuditEventType
    correlation_id: str = ""
    trace_id: str | None = None
    user_id: str = ""
    user_groups: list[str] = field(default_factory=list)
    server_name: str = ""
    tool_name: str = ""
    policy_decision: str = ""
    policy_rule_id: str = ""
    short_circuited: bool = False
    short_circuit_reason: str = ""
    input_masking: MaskingSummary = field(default_factory=MaskingSummary)
    output_masking: MaskingSummary = field(default_factory=MaskingSummary)
    duration_ms: float = 0.0
    error_type: str = ""
    error_message: str = ""
    timestamp: str = ""
    transport: str = ""
    masking_events: list[MaskingEventSummary] = field(default_factory=list)
    request_size_bytes: int = 0
    response_size_bytes: int = 0

    def to_json_dict(self, *, include: list[str] | None = None) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict matching the issue #23 schema.

        Args:
            include: If set, only include these keys (plus always-included keys:
                ``event_type``, ``timestamp``, ``correlation_id``).

        Returns:
            A dict suitable for ``json.dumps()``.
        """
        always_included = {"event_type", "timestamp", "correlation_id"}

        d: dict[str, Any] = {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "trace_id": self.trace_id,
            "user": {
                "user_id": self.user_id,
                "groups": list(self.user_groups),
            },
            "server_name": self.server_name,
            "tool_name": self.tool_name,
            "transport": self.transport,
            "policy_decision": self.policy_decision,
            "policy_rule_id": self.policy_rule_id,
            "short_circuited": self.short_circuited,
            "short_circuit_reason": self.short_circuit_reason,
            "duration_ms": self.duration_ms,
            "request_size_bytes": self.request_size_bytes,
            "response_size_bytes": self.response_size_bytes,
            "masking_events": [
                {"entity_type": m.entity_type, "count": m.count, "status": m.status}
                for m in self.masking_events
            ],
            "error_type": self.error_type,
            "error_message": self.error_message,
        }

        if include is not None:
            allowed = set(include) | always_included
            d = {k: v for k, v in d.items() if k in allowed}

        return d
