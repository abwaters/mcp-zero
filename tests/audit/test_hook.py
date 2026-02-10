"""Tests for AuditHook — structured JSON audit event emission."""

from __future__ import annotations

import dataclasses
import json
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
            identity=UserIdentity(user_id="test-user", email="test@example.com", groups=["dev"]),
        ),
        "server_name": "test-server",
        "tool_name": "test-tool",
        "policy_decision": PolicyDecision.ALLOW,
        "policy_rule_id": "rule-1",
    }
    defaults.update(kwargs)
    return HookContext(**defaults)


# ---------------------------------------------------------------------------
# Normal flow — TOOL_INVOCATION events
# ---------------------------------------------------------------------------


class TestAuditHookNormalFlow:
    @pytest.mark.asyncio
    async def test_emits_tool_invocation_event(self):
        hook = AuditHook()
        ctx = _make_ctx(request_payload={"message": "hello"})
        await hook.on_pre_audit(ctx)

        assert len(hook.events) == 1
        event = hook.events[0]
        assert event.event_type == AuditEventType.TOOL_INVOCATION

    @pytest.mark.asyncio
    async def test_emits_tool_invocation_with_response(self):
        hook = AuditHook()
        ctx = _make_ctx(response_payload={"result": "ok"})
        await hook.on_pre_audit(ctx)

        assert len(hook.events) == 1
        assert hook.events[0].event_type == AuditEventType.TOOL_INVOCATION

    @pytest.mark.asyncio
    async def test_tool_invocation_when_no_payloads(self):
        hook = AuditHook()
        ctx = _make_ctx()
        await hook.on_pre_audit(ctx)

        assert hook.events[0].event_type == AuditEventType.TOOL_INVOCATION

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

    @pytest.mark.asyncio
    async def test_timestamp_populated(self):
        hook = AuditHook()
        ctx = _make_ctx()
        await hook.on_pre_audit(ctx)

        assert hook.events[0].timestamp != ""
        assert "T" in hook.events[0].timestamp  # ISO-8601 format

    @pytest.mark.asyncio
    async def test_transport_populated(self):
        hook = AuditHook()
        ctx = _make_ctx(transport="http")
        await hook.on_pre_audit(ctx)

        assert hook.events[0].transport == "http"

    @pytest.mark.asyncio
    async def test_user_groups_populated(self):
        hook = AuditHook()
        ctx = _make_ctx(
            request=RequestContext(
                identity=UserIdentity(user_id="u1", groups=["admin", "dev"]),
            ),
        )
        await hook.on_pre_audit(ctx)

        assert hook.events[0].user_groups == ["admin", "dev"]

    @pytest.mark.asyncio
    async def test_request_size_bytes(self):
        hook = AuditHook()
        payload = {"message": "hello world"}
        ctx = _make_ctx(request_payload=payload)
        await hook.on_pre_audit(ctx)

        expected_size = len(json.dumps(payload).encode())
        assert hook.events[0].request_size_bytes == expected_size

    @pytest.mark.asyncio
    async def test_response_size_bytes(self):
        hook = AuditHook()
        payload = {"result": "ok"}
        ctx = _make_ctx(response_payload=payload)
        await hook.on_pre_audit(ctx)

        expected_size = len(json.dumps(payload).encode())
        assert hook.events[0].response_size_bytes == expected_size

    @pytest.mark.asyncio
    async def test_empty_payload_zero_size(self):
        hook = AuditHook()
        ctx = _make_ctx()
        await hook.on_pre_audit(ctx)

        assert hook.events[0].request_size_bytes == 0
        assert hook.events[0].response_size_bytes == 0


# ---------------------------------------------------------------------------
# Supplementary MASKING_EVENT emission
# ---------------------------------------------------------------------------


class TestAuditHookMaskingEvent:
    @pytest.mark.asyncio
    async def test_emits_masking_event_when_input_masking_applied(self):
        hook = AuditHook()
        ctx = _make_ctx(
            masking_applied=True,
            masked_fields=["name"],
            masking_events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
            masking_stage_completed=True,
        )
        await hook.on_pre_audit(ctx)

        assert len(hook.events) == 2
        assert hook.events[0].event_type == AuditEventType.TOOL_INVOCATION
        assert hook.events[1].event_type == AuditEventType.MASKING_EVENT

    @pytest.mark.asyncio
    async def test_emits_masking_event_when_output_masking_applied(self):
        hook = AuditHook()
        ctx = _make_ctx(
            output_masking_applied=True,
            output_masked_fields=["content[0].text"],
            masking_stage_completed=True,
        )
        await hook.on_pre_audit(ctx)

        assert len(hook.events) == 2
        assert hook.events[1].event_type == AuditEventType.MASKING_EVENT

    @pytest.mark.asyncio
    async def test_no_masking_event_when_no_masking(self):
        hook = AuditHook()
        ctx = _make_ctx()
        await hook.on_pre_audit(ctx)

        assert len(hook.events) == 1
        assert hook.events[0].event_type == AuditEventType.TOOL_INVOCATION

    @pytest.mark.asyncio
    async def test_masking_event_summaries_populated(self):
        masking_events = [
            MaskingEvent(entity_type="PERSON", count=2, status="masked"),
            MaskingEvent(entity_type="SSN", count=1, status="failed"),
        ]
        hook = AuditHook()
        ctx = _make_ctx(
            masking_applied=True,
            masked_fields=["name", "ssn"],
            masking_events=masking_events,
            masking_stage_completed=True,
        )
        await hook.on_pre_audit(ctx)

        event = hook.events[0]  # TOOL_INVOCATION
        assert len(event.masking_events) == 2
        assert event.masking_events[0].entity_type == "PERSON"
        assert event.masking_events[0].count == 2
        assert event.masking_events[0].status == "success"
        assert event.masking_events[1].entity_type == "SSN"
        assert event.masking_events[1].status == "failed"


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
    async def test_emits_policy_decision_on_deny(self):
        hook = AuditHook()
        ctx = _make_ctx(short_circuited=True, short_circuit_reason="denied")
        error = ShortCircuitError("denied by policy", deny=True)
        await hook.on_error(ctx, error)

        assert len(hook.events) == 1
        event = hook.events[0]
        assert event.event_type == AuditEventType.POLICY_DECISION
        assert event.error_type == "ShortCircuitError"
        assert event.error_message == "denied by policy"

    @pytest.mark.asyncio
    async def test_emits_error_for_non_policy_errors(self):
        hook = AuditHook()
        ctx = _make_ctx()
        error = RuntimeError("something broke")
        await hook.on_error(ctx, error)

        event = hook.events[0]
        assert event.event_type == AuditEventType.ERROR
        assert event.error_type == "RuntimeError"
        assert event.error_message == "something broke"

    @pytest.mark.asyncio
    async def test_emits_error_for_non_deny_short_circuit(self):
        hook = AuditHook()
        ctx = _make_ctx()
        error = ShortCircuitError("not a deny", deny=False)
        await hook.on_error(ctx, error)

        assert hook.events[0].event_type == AuditEventType.ERROR

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
    async def test_error_event_has_timestamp(self):
        hook = AuditHook()
        ctx = _make_ctx()
        error = RuntimeError("fail")
        await hook.on_error(ctx, error)

        assert hook.events[0].timestamp != ""

    @pytest.mark.asyncio
    async def test_error_event_has_transport(self):
        hook = AuditHook()
        ctx = _make_ctx(transport="stdio")
        error = RuntimeError("fail")
        await hook.on_error(ctx, error)

        assert hook.events[0].transport == "stdio"

    @pytest.mark.asyncio
    async def test_error_event_has_user_groups(self):
        hook = AuditHook()
        ctx = _make_ctx()
        error = RuntimeError("fail")
        await hook.on_error(ctx, error)

        assert hook.events[0].user_groups == ["dev"]


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
# JSON logging output
# ---------------------------------------------------------------------------


class TestAuditHookJsonOutput:
    @pytest.mark.asyncio
    async def test_logs_valid_json(self, caplog):
        hook = AuditHook()
        ctx = _make_ctx()
        with caplog.at_level(logging.INFO, logger="mcp_zero.audit.hook"):
            await hook.on_pre_audit(ctx)

        assert len(caplog.records) >= 1
        parsed = json.loads(caplog.records[0].message)
        assert parsed["event_type"] == "mcp_tool_invocation"
        assert "correlation_id" in parsed

    @pytest.mark.asyncio
    async def test_json_has_user_nested(self, caplog):
        hook = AuditHook()
        ctx = _make_ctx()
        with caplog.at_level(logging.INFO, logger="mcp_zero.audit.hook"):
            await hook.on_pre_audit(ctx)

        parsed = json.loads(caplog.records[0].message)
        assert "user" in parsed
        assert parsed["user"]["user_id"] == "test-user"
        assert parsed["user"]["groups"] == ["dev"]


# ---------------------------------------------------------------------------
# Field filtering via LoggingConfig
# ---------------------------------------------------------------------------


class _FakeLoggingConfig:
    def __init__(self, include: list[str]):
        self.include = include


class TestAuditHookFieldFiltering:
    @pytest.mark.asyncio
    async def test_include_filters_json_output(self, caplog):
        config = _FakeLoggingConfig(include=["server_name", "tool_name"])
        hook = AuditHook(logging_config=config)
        ctx = _make_ctx()
        with caplog.at_level(logging.INFO, logger="mcp_zero.audit.hook"):
            await hook.on_pre_audit(ctx)

        parsed = json.loads(caplog.records[0].message)
        # Always included
        assert "event_type" in parsed
        assert "timestamp" in parsed
        assert "correlation_id" in parsed
        # Explicitly included
        assert "server_name" in parsed
        assert "tool_name" in parsed
        # Filtered out
        assert "transport" not in parsed
        assert "user" not in parsed

    @pytest.mark.asyncio
    async def test_empty_include_no_filtering(self, caplog):
        config = _FakeLoggingConfig(include=[])
        hook = AuditHook(logging_config=config)
        ctx = _make_ctx()
        with caplog.at_level(logging.INFO, logger="mcp_zero.audit.hook"):
            await hook.on_pre_audit(ctx)

        parsed = json.loads(caplog.records[0].message)
        # All fields present when include is empty
        assert "transport" in parsed
        assert "user" in parsed

    @pytest.mark.asyncio
    async def test_no_config_no_filtering(self, caplog):
        hook = AuditHook()
        ctx = _make_ctx()
        with caplog.at_level(logging.INFO, logger="mcp_zero.audit.hook"):
            await hook.on_pre_audit(ctx)

        parsed = json.loads(caplog.records[0].message)
        assert "transport" in parsed
        assert "user" in parsed


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

    @pytest.mark.asyncio
    async def test_json_output_no_pii(self, caplog):
        """JSON log output must not contain PII from payloads."""
        hook = AuditHook()
        ctx = _make_ctx(
            request_payload={"message": self.PII_STRING},
        )
        with caplog.at_level(logging.INFO, logger="mcp_zero.audit.hook"):
            await hook.on_pre_audit(ctx)

        for record in caplog.records:
            assert self.PII_STRING not in record.message
            assert "987-65-4321" not in record.message
