"""Audit lifecycle hook — emits payload-free audit events."""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from mcp_zero.audit.event import AuditEvent, AuditEventType, MaskingSummary
from mcp_zero.context import HookContext
from mcp_zero.pipeline.hooks import LifecycleHook

logger = logging.getLogger(__name__)


class AuditHook(LifecycleHook):
    """Emits payload-free audit events at PRE_AUDIT and on errors.

    **Critical guarantee**: this hook never reads ``ctx.request_payload``
    or ``ctx.response_payload``.  Audit events contain only metadata and
    masking summaries (entity types, counts, field paths).

    Registered at priority 150 so it runs after all masking hooks.
    """

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    @property
    def events(self) -> list[AuditEvent]:
        """Recorded events — primarily for testing."""
        return list(self._events)

    async def on_pre_audit(self, ctx: HookContext) -> HookContext:
        event_type = AuditEventType.RESPONSE if ctx.response_payload else AuditEventType.REQUEST
        event = self._build_event(ctx, event_type)
        self._emit(event)
        return ctx

    async def on_error(self, ctx: HookContext, error: Exception) -> None:
        event = self._build_event(ctx, AuditEventType.ERROR)
        event = AuditEvent(
            event_type=event.event_type,
            correlation_id=event.correlation_id,
            trace_id=event.trace_id,
            user_id=event.user_id,
            server_name=event.server_name,
            tool_name=event.tool_name,
            policy_decision=event.policy_decision,
            policy_rule_id=event.policy_rule_id,
            short_circuited=event.short_circuited,
            short_circuit_reason=event.short_circuit_reason,
            input_masking=event.input_masking,
            output_masking=event.output_masking,
            duration_ms=event.duration_ms,
            error_type=type(error).__name__,
            error_message=str(error),
        )
        self._emit(event)

    def _build_event(self, ctx: HookContext, event_type: AuditEventType) -> AuditEvent:
        """Extract only metadata and masking summaries from context."""
        duration_ms = (time.monotonic() - ctx.started_at) * 1000

        input_masking = self._build_masking_summary(
            applied=ctx.masking_applied,
            masked_fields=ctx.masked_fields,
            masking_events=ctx.masking_events,
            masking_stage_completed=ctx.masking_stage_completed,
        )

        output_masking = self._build_masking_summary(
            applied=ctx.output_masking_applied,
            masked_fields=ctx.output_masked_fields,
            masking_events=[],  # output masking events not stored separately on ctx
            masking_stage_completed=ctx.masking_stage_completed,
        )

        user_id = ""
        if ctx.request.identity:
            user_id = ctx.request.identity.user_id

        return AuditEvent(
            event_type=event_type,
            correlation_id=ctx.request.correlation_id,
            trace_id=ctx.request.trace_id,
            user_id=user_id,
            server_name=ctx.server_name,
            tool_name=ctx.tool_name,
            policy_decision=ctx.policy_decision.value,
            policy_rule_id=ctx.policy_rule_id,
            short_circuited=ctx.short_circuited,
            short_circuit_reason=ctx.short_circuit_reason,
            input_masking=input_masking,
            output_masking=output_masking,
            duration_ms=duration_ms,
        )

    @staticmethod
    def _build_masking_summary(
        *,
        applied: bool,
        masked_fields: list[str],
        masking_events: list,
        masking_stage_completed: bool,
    ) -> MaskingSummary:
        entity_counts: dict[str, int] = defaultdict(int)
        entity_types: list[str] = []
        failure_count = 0

        for event in masking_events:
            entity_counts[event.entity_type] += event.count
            if event.entity_type not in entity_types:
                entity_types.append(event.entity_type)
            if event.status == "failed":
                failure_count += 1

        return MaskingSummary(
            applied=applied,
            entity_types=entity_types,
            entity_counts=dict(entity_counts),
            masked_field_count=len(masked_fields),
            masked_fields=list(masked_fields),
            failure_count=failure_count,
            masking_stage_completed=masking_stage_completed,
        )

    def _emit(self, event: AuditEvent) -> None:
        self._events.append(event)
        logger.info(
            "AuditEvent type=%s correlation_id=%s user=%s server=%s tool=%s "
            "policy=%s masking_completed=%s",
            event.event_type.value,
            event.correlation_id,
            event.user_id,
            event.server_name,
            event.tool_name,
            event.policy_decision,
            event.input_masking.masking_stage_completed,
        )
