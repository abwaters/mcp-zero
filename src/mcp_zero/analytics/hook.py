"""Analytics lifecycle hook — records metrics at PRE_AUDIT."""

from __future__ import annotations

import json
import logging
import time

from mcp_zero.analytics.collector import AnalyticsCollector
from mcp_zero.context import HookContext
from mcp_zero.pipeline.hooks import LifecycleHook

logger = logging.getLogger(__name__)


class AnalyticsHook(LifecycleHook):
    """Records analytics events from the pipeline context.

    Registered at priority 145 so it runs just before AuditHook (150).
    All recording is non-blocking — events are enqueued to the collector
    which flushes to Redis in the background.
    """

    def __init__(self, collector: AnalyticsCollector) -> None:
        self._collector = collector

    async def on_pre_audit(self, ctx: HookContext) -> HookContext:
        user_id = ""
        if ctx.request.identity:
            user_id = ctx.request.identity.user_id

        duration_ms = (time.monotonic() - ctx.started_at) * 1000
        request_bytes = self._measure_size(ctx.request_payload)
        response_bytes = self._measure_size(ctx.response_payload)

        # Record the tool call
        self._collector.record_tool_call(
            server=ctx.server_name,
            tool=ctx.tool_name,
            user_id=user_id,
            duration_ms=duration_ms,
            request_bytes=request_bytes,
            response_bytes=response_bytes,
            transport=ctx.transport,
        )

        # Record input redactions
        for event in ctx.masking_events:
            if hasattr(event, "entity_type") and hasattr(event, "count"):
                if hasattr(event, "status") and event.status == "failed":
                    self._collector.record_masking_failure(
                        server=ctx.server_name,
                        tool=ctx.tool_name,
                        direction="input",
                    )
                else:
                    self._collector.record_redaction(
                        server=ctx.server_name,
                        tool=ctx.tool_name,
                        entity_type=event.entity_type,
                        count=event.count,
                    )

        # Record output redactions
        if ctx.output_masking_applied:
            # Output masking events are on the same masking_events list after
            # the post-pipeline runs.  We detect output masking via the flag.
            # For entity-level detail we'd need a separate output_masking_events
            # field; for now record a tool-level output redaction indicator.
            self._collector.record_output_redaction(
                server=ctx.server_name,
                tool=ctx.tool_name,
                entity_type="_aggregate",
                count=len(ctx.output_masked_fields),
            )

        return ctx

    async def on_error(self, ctx: HookContext, error: Exception) -> None:
        from mcp_zero.pipeline.errors import ShortCircuitError

        user_id = ""
        if ctx.request.identity:
            user_id = ctx.request.identity.user_id

        if isinstance(error, ShortCircuitError) and error.deny:
            # Categorize the denial reason
            reason = self._categorize_denial(ctx, error)
            self._collector.record_denial(
                server=ctx.server_name,
                tool=ctx.tool_name,
                user_id=user_id,
                rule_id=ctx.policy_rule_id,
                reason=reason,
            )
        else:
            self._collector.record_error(
                server=ctx.server_name,
                tool=ctx.tool_name,
            )

    @staticmethod
    def _categorize_denial(ctx: HookContext, error: Exception) -> str:
        """Map a denial to a reason category for the denials:reason hash."""
        reason_text = ctx.short_circuit_reason or str(error)
        lower = reason_text.lower()

        if "identity" in lower or "token" in lower or "authen" in lower:
            return "no_identity"
        if "mask" in lower:
            return "masking_failed"
        return "policy_deny"

    @staticmethod
    def _measure_size(payload: dict) -> int:
        """Measure payload size in bytes without storing content."""
        if not payload:
            return 0
        return len(json.dumps(payload).encode())
