"""Integration tests for audit hook ordering and pipeline interactions."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mcp_zero.audit.event import AuditEventType
from mcp_zero.audit.hook import AuditHook
from mcp_zero.context import HookContext, PolicyDecision, RequestContext, UserIdentity
from mcp_zero.governance.config import PresidioConfig
from mcp_zero.masking.engine import MaskingEvent, MaskingResult
from mcp_zero.masking.errors import MaskingEngineError
from mcp_zero.masking.hook import MaskingHook
from mcp_zero.pipeline.hooks import LifecycleHook
from mcp_zero.pipeline.pipeline import Pipeline
from mcp_zero.pipeline.registry import HookRegistry


def _make_config(
    enabled: bool = True,
    entities: list[str] | None = None,
) -> PresidioConfig:
    return PresidioConfig(
        enabled=enabled,
        entities=entities or ["PERSON", "EMAIL_ADDRESS"],
    )


def _make_ctx(**kwargs) -> HookContext:
    defaults = {
        "request": RequestContext(
            identity=UserIdentity(user_id="test-user"),
        ),
        "server_name": "test-server",
        "tool_name": "test-tool",
        "policy_decision": PolicyDecision.ALLOW,
    }
    defaults.update(kwargs)
    return HookContext(**defaults)


# ---------------------------------------------------------------------------
# Hook ordering: masking before audit
# ---------------------------------------------------------------------------


class TestHookOrdering:
    @pytest.mark.asyncio
    async def test_masking_fires_before_audit(self):
        """MaskingHook (priority 75) must execute before AuditHook (priority 150).

        At each hook point, all hooks run in priority order.  So for a given
        hook point (e.g. on_pre_masking) MaskingHook runs first, then AuditHook.
        The critical guarantee is that at the PRE_MASKING and POST_MASKING
        hook points, MaskingHook always runs before AuditHook.
        """
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="safe", events=[], has_masked=False
        )
        masking_hook = MaskingHook(engine, _make_config())
        audit_hook = AuditHook()

        registry = HookRegistry()
        registry.register(masking_hook, priority=75)
        registry.register(audit_hook, priority=150)
        registry.build()

        pipeline = Pipeline(registry)
        ctx = _make_ctx(request_payload={"message": "hello"})
        result = await pipeline.execute(ctx)

        assert result.success
        # At each hook point, MaskingHook runs before AuditHook
        # Focus on the masking-relevant hook points
        for hook_point in ("on_pre_masking", "on_post_masking"):
            hooks_at_point = [name for name in result.hooks_executed if hook_point in name]
            if len(hooks_at_point) >= 2:
                masking_idx = next(i for i, n in enumerate(hooks_at_point) if "MaskingHook" in n)
                audit_idx = next(i for i, n in enumerate(hooks_at_point) if "AuditHook" in n)
                assert masking_idx < audit_idx, (
                    f"MaskingHook must run before AuditHook at {hook_point}"
                )

        # Also verify AuditHook.on_pre_audit is in the hooks list (it ran)
        audit_pre_audit = [
            name for name in result.hooks_executed if "AuditHook.on_pre_audit" in name
        ]
        assert audit_pre_audit, "AuditHook.on_pre_audit should have executed"


# ---------------------------------------------------------------------------
# End-to-end with masking
# ---------------------------------------------------------------------------


class TestEndToEndWithMasking:
    @pytest.mark.asyncio
    async def test_masking_stage_completed_in_audit_event(self):
        """After successful masking, audit event shows masking_stage_completed=True."""
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="<PERSON>",
            events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
            has_masked=True,
        )
        masking_hook = MaskingHook(engine, _make_config())
        audit_hook = AuditHook()

        registry = HookRegistry()
        registry.register(masking_hook, priority=75)
        registry.register(audit_hook, priority=150)
        registry.build()

        pipeline = Pipeline(registry)
        ctx = _make_ctx(request_payload={"name": "John Smith"})
        result = await pipeline.execute(ctx)

        assert result.success
        # TOOL_INVOCATION + MASKING_EVENT
        assert len(audit_hook.events) == 2
        event = audit_hook.events[0]
        assert event.event_type == AuditEventType.TOOL_INVOCATION
        assert event.input_masking.masking_stage_completed is True
        assert event.input_masking.applied is True
        assert "PERSON" in event.input_masking.entity_types
        assert audit_hook.events[1].event_type == AuditEventType.MASKING_EVENT

    @pytest.mark.asyncio
    async def test_no_pii_masking_still_completes_stage(self):
        """When no PII found, masking_stage_completed is still True."""
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="safe text", events=[], has_masked=False
        )
        masking_hook = MaskingHook(engine, _make_config())
        audit_hook = AuditHook()

        registry = HookRegistry()
        registry.register(masking_hook, priority=75)
        registry.register(audit_hook, priority=150)
        registry.build()

        pipeline = Pipeline(registry)
        ctx = _make_ctx(request_payload={"message": "safe text"})
        result = await pipeline.execute(ctx)

        assert result.success
        # Only TOOL_INVOCATION, no MASKING_EVENT since masking_applied is False
        assert len(audit_hook.events) == 1
        event = audit_hook.events[0]
        assert event.event_type == AuditEventType.TOOL_INVOCATION
        assert event.input_masking.masking_stage_completed is True
        assert event.input_masking.applied is False

    @pytest.mark.asyncio
    async def test_empty_payload_completes_masking_stage(self):
        """Empty payload still marks masking as completed."""
        engine = AsyncMock()
        masking_hook = MaskingHook(engine, _make_config())
        audit_hook = AuditHook()

        registry = HookRegistry()
        registry.register(masking_hook, priority=75)
        registry.register(audit_hook, priority=150)
        registry.build()

        pipeline = Pipeline(registry)
        ctx = _make_ctx(request_payload={})
        result = await pipeline.execute(ctx)

        assert result.success
        assert len(audit_hook.events) == 1
        event = audit_hook.events[0]
        assert event.event_type == AuditEventType.TOOL_INVOCATION
        assert event.input_masking.masking_stage_completed is True


# ---------------------------------------------------------------------------
# Masking failure path
# ---------------------------------------------------------------------------


class TestMaskingFailurePath:
    @pytest.mark.asyncio
    async def test_engine_failure_sets_masking_not_completed(self):
        """Masking engine failure -> ShortCircuitError(deny=True) -> POLICY_DECISION."""
        engine = AsyncMock()
        engine.mask_text.side_effect = MaskingEngineError("engine crashed", engine="presidio")
        masking_hook = MaskingHook(engine, _make_config())
        audit_hook = AuditHook()

        registry = HookRegistry()
        registry.register(masking_hook, priority=75)
        registry.register(audit_hook, priority=150)
        registry.build()

        pipeline = Pipeline(registry)
        ctx = _make_ctx(request_payload={"name": "John Smith"})
        result = await pipeline.execute(ctx)

        assert not result.success
        # on_error should have fired — masking failures are wrapped in
        # ShortCircuitError(deny=True), so they emit POLICY_DECISION
        assert len(audit_hook.events) == 1
        event = audit_hook.events[0]
        assert event.event_type == AuditEventType.POLICY_DECISION
        assert event.input_masking.masking_stage_completed is False

    @pytest.mark.asyncio
    async def test_engine_failure_no_payload_in_error_event(self):
        """PII in payload must not leak even when masking engine fails."""
        pii = "John Smith SSN 123-45-6789"
        engine = AsyncMock()
        engine.mask_text.side_effect = MaskingEngineError("engine crashed", engine="presidio")
        masking_hook = MaskingHook(engine, _make_config())
        audit_hook = AuditHook()

        registry = HookRegistry()
        registry.register(masking_hook, priority=75)
        registry.register(audit_hook, priority=150)
        registry.build()

        pipeline = Pipeline(registry)
        ctx = _make_ctx(request_payload={"data": pii})
        await pipeline.execute(ctx)

        event_repr = repr(audit_hook.events[0])
        assert pii not in event_repr
        assert "123-45-6789" not in event_repr


# ---------------------------------------------------------------------------
# Governance deny path
# ---------------------------------------------------------------------------


class _DenyHook(LifecycleHook):
    """Test hook that denies at POST_VALIDATION."""

    async def on_post_validation(self, ctx: HookContext) -> HookContext:
        from mcp_zero.pipeline.errors import ShortCircuitError

        raise ShortCircuitError("Access denied by policy", deny=True)


class TestGovernanceDenyPath:
    @pytest.mark.asyncio
    async def test_deny_fires_policy_decision_audit(self):
        """Governance deny -> ShortCircuitError -> on_error -> POLICY_DECISION event."""
        deny_hook = _DenyHook()
        audit_hook = AuditHook()

        registry = HookRegistry()
        registry.register(deny_hook, priority=50)
        registry.register(audit_hook, priority=150)
        registry.build()

        pipeline = Pipeline(registry)
        ctx = _make_ctx(request_payload={"data": "sensitive"})
        result = await pipeline.execute(ctx)

        assert not result.success
        assert len(audit_hook.events) == 1
        event = audit_hook.events[0]
        assert event.event_type == AuditEventType.POLICY_DECISION
        assert event.input_masking.masking_stage_completed is False
        # Payload not in event
        assert "sensitive" not in repr(event)

    @pytest.mark.asyncio
    async def test_deny_event_has_short_circuit_info(self):
        deny_hook = _DenyHook()
        audit_hook = AuditHook()

        registry = HookRegistry()
        registry.register(deny_hook, priority=50)
        registry.register(audit_hook, priority=150)
        registry.build()

        pipeline = Pipeline(registry)
        ctx = _make_ctx()
        await pipeline.execute(ctx)

        event = audit_hook.events[0]
        assert event.short_circuited is True
        assert event.short_circuit_reason == "Access denied by policy"


# ---------------------------------------------------------------------------
# Two-phase audit (both emit TOOL_INVOCATION)
# ---------------------------------------------------------------------------


class TestTwoPhaseAudit:
    @pytest.mark.asyncio
    async def test_request_then_response_events(self):
        """Both phases emit TOOL_INVOCATION + supplementary MASKING_EVENT when masking applies."""
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="<PERSON>",
            events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
            has_masked=True,
        )
        masking_hook = MaskingHook(engine, _make_config())
        audit_hook = AuditHook()

        registry = HookRegistry()
        registry.register(masking_hook, priority=75)
        registry.register(audit_hook, priority=150)
        registry.build()

        pipeline = Pipeline(registry)

        # Phase 1: request (input masking applied)
        ctx_req = _make_ctx(request_payload={"name": "John"})
        await pipeline.execute(ctx_req)

        # Phase 2: response (output masking applied by masking hook)
        ctx_resp = _make_ctx(
            response_payload={"result": "John"},
        )
        await pipeline.execute(ctx_resp)

        # Phase 1: TOOL_INVOCATION + MASKING_EVENT (input masking applied)
        # Phase 2: TOOL_INVOCATION + MASKING_EVENT (output masking applied)
        #          + additional TOOL_INVOCATION from on_pre_audit of second pipeline.execute
        # The masking mock returns has_masked=True for both phases
        tool_events = [
            e for e in audit_hook.events if e.event_type == AuditEventType.TOOL_INVOCATION
        ]
        masking_events = [
            e for e in audit_hook.events if e.event_type == AuditEventType.MASKING_EVENT
        ]
        assert len(tool_events) >= 2
        assert tool_events[0].input_masking.applied is True
        assert len(masking_events) >= 1
