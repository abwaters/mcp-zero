"""Tests for AuditHook — payload-free audit event emission."""

from __future__ import annotations

import dataclasses
import logging

import pytest

from mcp_zero.audit.event import AuditEvent, AuditEventType
from mcp_zero.audit.hook import AuditHook
from mcp_zero.context import HookContext, PolicyDecision, RequestContext, UserIdentity
from mcp_zero.masking.engine import MaskingEvent
from mcp_zero.pipeline.errors import ShortCircuitError


def _make_ctx(**kwargs) -> HookContext:
    """Build a HookContext with sensible defaults."""
    defaults = {
        "request": RequestContext(
            identity=UserIdentity(user_id="test-user", email="test@example.com"),
        ),
        "server_name": "test-server",
        "tool_name": "test-tool",
        "policy_decision": PolicyDecision.ALLOW,
        "policy_rule_id": "rule-1",
    }
    defaults.update(kwargs)
    return HookContext(**defaults)


# ---------------------------------------------------------------------------
# Normal flow — REQUEST and RESPONSE events
# ---------------------------------------------------------------------------


class TestAuditHookNormalFlow:
    @pytest.mark.asyncio
    async def test_emits_request_event(self):
        hook = AuditHook()
        ctx = _make_ctx(request_payload={"message": "hello"})
        await hook.on_pre_audit(ctx)

        assert len(hook.events) == 1
        event = hook.events[0]
        assert event.event_type == AuditEventType.REQUEST

    @pytest.mark.asyncio
    async def test_emits_response_event_when_response_present(self):
        hook = AuditHook()
        ctx = _make_ctx(response_payload={"result": "ok"})
        await hook.on_pre_audit(ctx)

        assert len(hook.events) == 1
        assert hook.events[0].event_type == AuditEventType.RESPONSE

    @pytest.mark.asyncio
    async def test_request_event_when_no_payloads(self):
        hook = AuditHook()
        ctx = _make_ctx()
        await hook.on_pre_audit(ctx)

        assert hook.events[0].event_type == AuditEventType.REQUEST

    @pytest.mark.asyncio
    async def test_metadata_populated(self):
        hook = AuditHook()
        ctx = _make_ctx()
        await hook.on_pre_audit(ctx)

        event = hook.events[0]
        assert event.correlation_id == ctx.request.correlation_id
        assert event.trace_id == ctx.request.trace_id
        assert event.user_id == "test-user"
        assert event.server_name == "test-server"
        assert event.tool_name == "test-tool"
        assert event.policy_decision == "allow"
        assert event.policy_rule_id == "rule-1"

    @pytest.mark.asyncio
    async def test_no_identity_sets_empty_user_id(self):
        hook = AuditHook()
        ctx = _make_ctx(request=RequestContext())
        await hook.on_pre_audit(ctx)

        assert hook.events[0].user_id == ""

    @pytest.mark.asyncio
    async def test_returns_ctx_unchanged(self):
        hook = AuditHook()
        ctx = _make_ctx()
        result = await hook.on_pre_audit(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_duration_ms_positive(self):
        hook = AuditHook()
        ctx = _make_ctx()
        await hook.on_pre_audit(ctx)

        assert hook.events[0].duration_ms >= 0


# ---------------------------------------------------------------------------
# Masking metadata in audit events
# ---------------------------------------------------------------------------


class TestAuditHookMaskingMetadata:
    @pytest.mark.asyncio
    async def test_input_masking_summary(self):
        masking_events = [
            MaskingEvent(entity_type="PERSON", count=2, status="masked"),
            MaskingEvent(entity_type="EMAIL_ADDRESS", count=1, status="masked"),
        ]
        hook = AuditHook()
        ctx = _make_ctx(
            masking_applied=True,
            masked_fields=["name", "contact.email"],
            masking_events=masking_events,
            masking_stage_completed=True,
        )
        await hook.on_pre_audit(ctx)

        summary = hook.events[0].input_masking
        assert summary.applied is True
        assert summary.entity_types == ["PERSON", "EMAIL_ADDRESS"]
        assert summary.entity_counts == {"PERSON": 2, "EMAIL_ADDRESS": 1}
        assert summary.masked_field_count == 2
        assert summary.masked_fields == ["name", "contact.email"]
        assert summary.masking_stage_completed is True

    @pytest.mark.asyncio
    async def test_output_masking_summary(self):
        hook = AuditHook()
        ctx = _make_ctx(
            output_masking_applied=True,
            output_masked_fields=["content[0].text"],
            masking_stage_completed=True,
            response_payload={"content": [{"text": "<PERSON>"}]},
        )
        await hook.on_pre_audit(ctx)

        summary = hook.events[0].output_masking
        assert summary.applied is True
        assert summary.masked_field_count == 1
        assert summary.masked_fields == ["content[0].text"]
        assert summary.masking_stage_completed is True

    @pytest.mark.asyncio
    async def test_failure_count_tracked(self):
        masking_events = [
            MaskingEvent(entity_type="PERSON", count=1, status="masked"),
            MaskingEvent(entity_type="SSN", count=1, status="failed"),
        ]
        hook = AuditHook()
        ctx = _make_ctx(
            masking_applied=True,
            masked_fields=["data"],
            masking_events=masking_events,
            masking_stage_completed=True,
        )
        await hook.on_pre_audit(ctx)

        summary = hook.events[0].input_masking
        assert summary.failure_count == 1

    @pytest.mark.asyncio
    async def test_masking_stage_completed_propagated(self):
        hook = AuditHook()
        ctx = _make_ctx(masking_stage_completed=True)
        await hook.on_pre_audit(ctx)

        assert hook.events[0].input_masking.masking_stage_completed is True

    @pytest.mark.asyncio
    async def test_masking_not_completed_by_default(self):
        hook = AuditHook()
        ctx = _make_ctx()
        await hook.on_pre_audit(ctx)

        assert hook.events[0].input_masking.masking_stage_completed is False


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------


class TestAuditHookErrorPath:
    @pytest.mark.asyncio
    async def test_emits_error_event(self):
        hook = AuditHook()
        ctx = _make_ctx(short_circuited=True, short_circuit_reason="denied")
        error = ShortCircuitError("denied by policy", deny=True)
        await hook.on_error(ctx, error)

        assert len(hook.events) == 1
        event = hook.events[0]
        assert event.event_type == AuditEventType.ERROR
        assert event.error_type == "ShortCircuitError"
        assert event.error_message == "denied by policy"

    @pytest.mark.asyncio
    async def test_error_event_has_metadata(self):
        hook = AuditHook()
        ctx = _make_ctx(short_circuited=True, short_circuit_reason="denied")
        error = ShortCircuitError("denied", deny=True)
        await hook.on_error(ctx, error)

        event = hook.events[0]
        assert event.correlation_id == ctx.request.correlation_id
        assert event.user_id == "test-user"
        assert event.server_name == "test-server"

    @pytest.mark.asyncio
    async def test_error_event_generic_exception(self):
        hook = AuditHook()
        ctx = _make_ctx()
        error = RuntimeError("something broke")
        await hook.on_error(ctx, error)

        event = hook.events[0]
        assert event.error_type == "RuntimeError"
        assert event.error_message == "something broke"


# ---------------------------------------------------------------------------
# Payload exclusion (critical security tests)
# ---------------------------------------------------------------------------


class TestAuditHookPayloadExclusion:
    PII_STRING = "John Smith lives at 123 Secret St, SSN 123-45-6789"

    @pytest.mark.asyncio
    async def test_request_payload_not_in_event_repr(self):
        """PII in request_payload must never appear in audit event."""
        hook = AuditHook()
        ctx = _make_ctx(request_payload={"message": self.PII_STRING})
        await hook.on_pre_audit(ctx)

        event_repr = repr(hook.events[0])
        assert self.PII_STRING not in event_repr
        assert "123-45-6789" not in event_repr
        assert "Secret St" not in event_repr

    @pytest.mark.asyncio
    async def test_response_payload_not_in_event_repr(self):
        """PII in response_payload must never appear in audit event."""
        hook = AuditHook()
        ctx = _make_ctx(response_payload={"result": self.PII_STRING})
        await hook.on_pre_audit(ctx)

        event_repr = repr(hook.events[0])
        assert self.PII_STRING not in event_repr

    @pytest.mark.asyncio
    async def test_error_path_payload_not_in_event(self):
        """PII in payloads must not leak through error audit events."""
        hook = AuditHook()
        ctx = _make_ctx(
            request_payload={"data": self.PII_STRING},
            response_payload={"result": self.PII_STRING},
        )
        error = ShortCircuitError("denied", deny=True)
        await hook.on_error(ctx, error)

        event_repr = repr(hook.events[0])
        assert self.PII_STRING not in event_repr

    def test_audit_event_has_no_payload_field(self):
        """Structural guarantee: no field named *payload* on AuditEvent."""
        field_names = [f.name for f in dataclasses.fields(AuditEvent)]
        for name in field_names:
            assert "payload" not in name


# ---------------------------------------------------------------------------
# Debug logging safety
# ---------------------------------------------------------------------------


class TestAuditHookLoggingSafety:
    PII_STRING = "Jane Doe, SSN 987-65-4321, jane@secret.com"

    @pytest.mark.asyncio
    async def test_pii_not_in_log_records(self, caplog):
        """PII from payloads must never appear in log output."""
        hook = AuditHook()
        ctx = _make_ctx(
            request_payload={"message": self.PII_STRING},
            response_payload={"result": self.PII_STRING},
        )
        with caplog.at_level(logging.DEBUG, logger="mcp_zero.audit.hook"):
            await hook.on_pre_audit(ctx)

        full_log = caplog.text
        assert self.PII_STRING not in full_log
        assert "987-65-4321" not in full_log
        assert "jane@secret.com" not in full_log

    @pytest.mark.asyncio
    async def test_error_pii_not_in_log_records(self, caplog):
        hook = AuditHook()
        ctx = _make_ctx(request_payload={"data": self.PII_STRING})
        error = ShortCircuitError("denied", deny=True)

        with caplog.at_level(logging.DEBUG, logger="mcp_zero.audit.hook"):
            await hook.on_error(ctx, error)

        full_log = caplog.text
        assert self.PII_STRING not in full_log
        assert "987-65-4321" not in full_log
