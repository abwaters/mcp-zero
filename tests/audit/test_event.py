"""Tests for audit event dataclasses."""

from __future__ import annotations

import dataclasses

import pytest

from mcp_zero.audit.event import AuditEvent, AuditEventType, MaskingSummary


class TestAuditEventType:
    def test_values(self):
        assert AuditEventType.REQUEST == "request"
        assert AuditEventType.RESPONSE == "response"
        assert AuditEventType.ERROR == "error"

    def test_from_string(self):
        assert AuditEventType("request") is AuditEventType.REQUEST
        assert AuditEventType("response") is AuditEventType.RESPONSE
        assert AuditEventType("error") is AuditEventType.ERROR

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            AuditEventType("invalid")


class TestMaskingSummary:
    def test_defaults(self):
        summary = MaskingSummary()
        assert summary.applied is False
        assert summary.entity_types == []
        assert summary.entity_counts == {}
        assert summary.masked_field_count == 0
        assert summary.masked_fields == []
        assert summary.failure_count == 0
        assert summary.masking_stage_completed is False

    def test_frozen(self):
        summary = MaskingSummary()
        with pytest.raises(AttributeError):
            summary.applied = True  # type: ignore[misc]

    def test_custom_values(self):
        summary = MaskingSummary(
            applied=True,
            entity_types=["PERSON", "EMAIL_ADDRESS"],
            entity_counts={"PERSON": 2, "EMAIL_ADDRESS": 1},
            masked_field_count=3,
            masked_fields=["name", "email", "bio"],
            failure_count=0,
            masking_stage_completed=True,
        )
        assert summary.applied is True
        assert summary.entity_types == ["PERSON", "EMAIL_ADDRESS"]
        assert summary.entity_counts["PERSON"] == 2
        assert summary.masked_field_count == 3
        assert summary.masking_stage_completed is True


class TestAuditEvent:
    def test_defaults(self):
        event = AuditEvent(event_type=AuditEventType.REQUEST)
        assert event.event_type == AuditEventType.REQUEST
        assert event.correlation_id == ""
        assert event.trace_id == ""
        assert event.user_id == ""
        assert event.server_name == ""
        assert event.tool_name == ""
        assert event.policy_decision == ""
        assert event.policy_rule_id == ""
        assert event.short_circuited is False
        assert event.short_circuit_reason == ""
        assert isinstance(event.input_masking, MaskingSummary)
        assert isinstance(event.output_masking, MaskingSummary)
        assert event.duration_ms == 0.0
        assert event.error_type == ""
        assert event.error_message == ""

    def test_frozen(self):
        event = AuditEvent(event_type=AuditEventType.REQUEST)
        with pytest.raises(AttributeError):
            event.correlation_id = "changed"  # type: ignore[misc]

    def test_no_payload_fields_structural_guarantee(self):
        """Tripwire: if anyone adds a field containing 'payload', this fails."""
        field_names = [f.name for f in dataclasses.fields(AuditEvent)]
        for name in field_names:
            assert "payload" not in name, (
                f"AuditEvent field '{name}' contains 'payload' — "
                f"audit events must remain payload-free"
            )

    def test_custom_values(self):
        masking = MaskingSummary(applied=True, entity_types=["PERSON"])
        event = AuditEvent(
            event_type=AuditEventType.ERROR,
            correlation_id="abc-123",
            trace_id="trace-1",
            user_id="user@example.com",
            server_name="my-server",
            tool_name="search",
            policy_decision="allow",
            policy_rule_id="rule-1",
            short_circuited=True,
            short_circuit_reason="denied",
            input_masking=masking,
            duration_ms=42.5,
            error_type="ShortCircuitError",
            error_message="denied by policy",
        )
        assert event.event_type == AuditEventType.ERROR
        assert event.correlation_id == "abc-123"
        assert event.user_id == "user@example.com"
        assert event.input_masking.applied is True
        assert event.error_type == "ShortCircuitError"
