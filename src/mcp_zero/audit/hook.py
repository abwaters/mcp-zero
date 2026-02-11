"""Audit lifecycle hook — emits structured JSON audit events."""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

from mcp_zero.audit.event import AuditEvent, AuditEventType, MaskingEventSummary, MaskingSummary
from mcp_zero.context import HookContext
from mcp_zero.pipeline.hooks import LifecycleHook

logger = logging.getLogger(__name__)


class AuditHook(LifecycleHook):
    """Emits structured JSON audit events at PRE_AUDIT and on errors.

    **Critical guarantee**: this hook never reads ``ctx.request_payload``
    or ``ctx.response_payload``.  Audit events contain only metadata and
    masking summaries (entity types, counts, field paths).

    Registered at priority 150 so it runs after all masking hooks.

    In-memory event retention is bounded to ``max_events`` (default 1000)
    to prevent unbounded memory growth in long-lived processes.  Oldest
    events are evicted first.  Set ``max_events=0`` to disable in-memory
    retention entirely (events are still logged as JSON).
    """

    _DEFAULT_MAX_EVENTS = 1000

    def __init__(
        self,
        logging_config: object | None = None,
        *,
        max_events: int = _DEFAULT_MAX_EVENTS,
    ) -> None:
        self._events: deque[AuditEvent] = deque(maxlen=max_events or None)
        self._include: list[str] | None = None
        if logging_config is not None and hasattr(logging_config, "include"):
            inc = logging_config.include
            if inc:
                self._include = list(inc)

    @property
    def events(self) -> list[AuditEvent]:
        """Recorded events — primarily for testing."""
        return list(self._events)

    async def on_pre_audit(self, ctx: HookContext) -> HookContext:
        event = self._build_event(ctx, AuditEventType.TOOL_INVOCATION)
        self._emit(event)

        # Emit supplementary masking event when masking was applied
        if ctx.masking_applied or ctx.output_masking_applied:
            masking_event = self._build_event(ctx, AuditEventType.MASKING_EVENT)
            self._emit(masking_event)

        return ctx

    async def on_error(self, ctx: HookContext, error: Exception) -> None:
        from mcp_zero.pipeline.errors import ShortCircuitError

        # Policy deny → POLICY_DECISION, other errors → ERROR
        if isinstance(error, ShortCircuitError) and error.deny:
            event_type = AuditEventType.POLICY_DECISION
        else:
            event_type = AuditEventType.ERROR

        event = self._build_event(ctx, event_type)
        event = AuditEvent(
            event_type=event.event_type,
            correlation_id=event.correlation_id,
            trace_id=event.trace_id,
            user_id=event.user_id,
            user_groups=event.user_groups,
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
            timestamp=event.timestamp,
            transport=event.transport,
            masking_events=event.masking_events,
            request_size_bytes=event.request_size_bytes,
            response_size_bytes=event.response_size_bytes,
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
        user_groups: list[str] = []
        if ctx.request.identity:
            user_id = ctx.request.identity.user_id
            user_groups = list(ctx.request.identity.groups)

        masking_event_summaries = self._build_masking_event_summaries(ctx.masking_events)

        request_size = self._measure_size(ctx.request_payload)
        response_size = self._measure_size(ctx.response_payload)

        return AuditEvent(
            event_type=event_type,
            correlation_id=ctx.request.correlation_id,
            trace_id=ctx.request.trace_id,
            user_id=user_id,
            user_groups=user_groups,
            server_name=ctx.server_name,
            tool_name=ctx.tool_name,
            policy_decision=ctx.policy_decision.value,
            policy_rule_id=ctx.policy_rule_id,
            short_circuited=ctx.short_circuited,
            short_circuit_reason=ctx.short_circuit_reason,
            input_masking=input_masking,
            output_masking=output_masking,
            duration_ms=duration_ms,
            timestamp=datetime.now(UTC).isoformat(),
            transport=ctx.transport,
            masking_events=masking_event_summaries,
            request_size_bytes=request_size,
            response_size_bytes=response_size,
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

    @staticmethod
    def _build_masking_event_summaries(masking_events: list) -> list[MaskingEventSummary]:
        """Convert raw masking events to MaskingEventSummary instances."""
        summaries: list[MaskingEventSummary] = []
        for event in masking_events:
            status = "success" if event.status != "failed" else "failed"
            summaries.append(
                MaskingEventSummary(
                    entity_type=event.entity_type,
                    count=event.count,
                    status=status,
                )
            )
        return summaries

    @staticmethod
    def _measure_size(payload: dict) -> int:
        """Measure payload size in bytes without storing content."""
        if not payload:
            return 0
        return len(json.dumps(payload).encode())

    def _emit(self, event: AuditEvent) -> None:
        self._events.append(event)
        json_dict = event.to_json_dict(include=self._include or None)
        logger.info(json.dumps(json_dict, default=str))
