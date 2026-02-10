"""Tests for audit event dataclasses."""

from __future__ import annotations

import dataclasses
import json

import pytest

from mcp_zero.audit.event import (
    AuditEvent,
    AuditEventType,
    MaskingEventSummary,
    MaskingSummary,
)


class TestAuditEventType:
    def test_values(self):
        assert AuditEventType.TOOL_INVOCATION == "mcp_tool_invocation"
        assert AuditEventType.POLICY_DECISION == "policy_decision"
        assert AuditEventType.MASKING_EVENT == "masking_event"
        assert AuditEventType.ERROR == "error"

    def test_from_string(self):
        assert AuditEventType("mcp_tool_invocation") is AuditEventType.TOOL_INVOCATION
        assert AuditEventType("policy_decision") is AuditEventType.POLICY_DECISION
        assert AuditEventType("masking_event") is AuditEventType.MASKING_EVENT
        assert AuditEventType("error") is AuditEventType.ERROR

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            AuditEventType("invalid")


class TestMaskingEventSummary:
    def test_defaults(self):
        summary = MaskingEventSummary()
        assert summary.entity_type == ""
        assert summary.count == 0
        assert summary.status == ""

    def test_custom_values(self):
        summary = MaskingEventSummary(entity_type="PERSON", count=3, status="success")
        assert summary.entity_type == "PERSON"
        assert summary.count == 3
        assert summary.status == "success"

    def test_frozen(self):
        summary = MaskingEventSummary()
        with pytest.raises(AttributeError):
            summary.count = 5  # type: ignore[misc]


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
        event = AuditEvent(event_type=AuditEventType.TOOL_INVOCATION)
        assert event.event_type == AuditEventType.TOOL_INVOCATION
        assert event.correlation_id == ""
        assert event.trace_id == ""
        assert event.user_id == ""
        assert event.user_groups == []
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
        assert event.timestamp == ""
        assert event.transport == ""
        assert event.masking_events == []
        assert event.request_size_bytes == 0
        assert event.response_size_bytes == 0

    def test_frozen(self):
        event = AuditEvent(event_type=AuditEventType.TOOL_INVOCATION)
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
        masking_events = [
            MaskingEventSummary(entity_type="PERSON", count=2, status="success"),
        ]
        event = AuditEvent(
            event_type=AuditEventType.ERROR,
            correlation_id="abc-123",
            trace_id="trace-1",
            user_id="user@example.com",
            user_groups=["admin", "dev"],
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
            timestamp="2025-01-01T00:00:00+00:00",
            transport="http",
            masking_events=masking_events,
            request_size_bytes=128,
            response_size_bytes=256,
        )
        assert event.event_type == AuditEventType.ERROR
        assert event.correlation_id == "abc-123"
        assert event.user_id == "user@example.com"
        assert event.user_groups == ["admin", "dev"]
        assert event.input_masking.applied is True
        assert event.error_type == "ShortCircuitError"
        assert event.timestamp == "2025-01-01T00:00:00+00:00"
        assert event.transport == "http"
        assert len(event.masking_events) == 1
        assert event.masking_events[0].entity_type == "PERSON"
        assert event.request_size_bytes == 128
        assert event.response_size_bytes == 256


class TestAuditEventToJsonDict:
    def test_basic_serialization(self):
        event = AuditEvent(
            event_type=AuditEventType.TOOL_INVOCATION,
            correlation_id="abc-123",
            timestamp="2025-01-01T00:00:00+00:00",
            user_id="user@example.com",
            user_groups=["admin"],
            server_name="my-server",
            tool_name="search",
            transport="http",
        )
        d = event.to_json_dict()
        assert d["event_type"] == "mcp_tool_invocation"
        assert d["correlation_id"] == "abc-123"
        assert d["timestamp"] == "2025-01-01T00:00:00+00:00"
        assert d["user"]["user_id"] == "user@example.com"
        assert d["user"]["groups"] == ["admin"]
        assert d["server_name"] == "my-server"
        assert d["transport"] == "http"

    def test_include_filters_fields(self):
        event = AuditEvent(
            event_type=AuditEventType.TOOL_INVOCATION,
            correlation_id="abc-123",
            timestamp="2025-01-01T00:00:00+00:00",
            server_name="my-server",
            tool_name="search",
            transport="http",
        )
        d = event.to_json_dict(include=["server_name", "tool_name"])
        # Always-included fields
        assert "event_type" in d
        assert "timestamp" in d
        assert "correlation_id" in d
        # Explicitly included
        assert "server_name" in d
        assert "tool_name" in d
        # Filtered out
        assert "transport" not in d
        assert "user" not in d
        assert "duration_ms" not in d

    def test_always_included_fields_present(self):
        event = AuditEvent(
            event_type=AuditEventType.ERROR,
            correlation_id="x",
            timestamp="t",
        )
        d = event.to_json_dict(include=["error_type"])
        assert "event_type" in d
        assert "timestamp" in d
        assert "correlation_id" in d
        assert "error_type" in d

    def test_valid_json(self):
        event = AuditEvent(
            event_type=AuditEventType.TOOL_INVOCATION,
            correlation_id="test-123",
            timestamp="2025-01-01T00:00:00+00:00",
            masking_events=[
                MaskingEventSummary(entity_type="PERSON", count=2, status="success"),
            ],
        )
        d = event.to_json_dict()
        json_str = json.dumps(d, default=str)
        parsed = json.loads(json_str)
        assert parsed["event_type"] == "mcp_tool_invocation"
        assert len(parsed["masking_events"]) == 1
        assert parsed["masking_events"][0]["entity_type"] == "PERSON"

    def test_masking_events_serialization(self):
        event = AuditEvent(
            event_type=AuditEventType.MASKING_EVENT,
            masking_events=[
                MaskingEventSummary(entity_type="PERSON", count=2, status="success"),
                MaskingEventSummary(entity_type="SSN", count=1, status="failed"),
            ],
        )
        d = event.to_json_dict()
        assert len(d["masking_events"]) == 2
        assert d["masking_events"][0] == {"entity_type": "PERSON", "count": 2, "status": "success"}
        assert d["masking_events"][1] == {"entity_type": "SSN", "count": 1, "status": "failed"}

    def test_no_include_returns_all_fields(self):
        event = AuditEvent(
            event_type=AuditEventType.TOOL_INVOCATION,
            correlation_id="test",
            timestamp="t",
            transport="http",
            request_size_bytes=100,
            response_size_bytes=200,
        )
        d = event.to_json_dict()
        assert "transport" in d
        assert "request_size_bytes" in d
        assert "response_size_bytes" in d
        assert "user" in d
        assert "masking_events" in d
