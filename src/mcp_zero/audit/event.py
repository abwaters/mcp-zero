"""Audit event dataclasses — deliberately payload-free."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class AuditEventType(StrEnum):
    """Type of audit event emitted by the pipeline."""

    REQUEST = "request"
    RESPONSE = "response"
    ERROR = "error"


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
    trace_id: str = ""
    user_id: str = ""
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
