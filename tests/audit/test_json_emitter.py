"""End-to-end JSON emission tests for the audit subsystem."""

from __future__ import annotations

import json
import logging

import pytest

from mcp_zero.audit.hook import AuditHook
from mcp_zero.context import HookContext, PolicyDecision, RequestContext, UserIdentity
from mcp_zero.masking.engine import MaskingEvent
from mcp_zero.pipeline.errors import ShortCircuitError


def _make_ctx(**kwargs) -> HookContext:
    """Build a HookContext with sensible defaults."""
    defaults = {
        "request": RequestContext(
            identity=UserIdentity(
                user_id="test-user", email="test@example.com", groups=["admin", "dev"]
            ),
        ),
        "server_name": "test-server",
        "tool_name": "test-tool",
        "policy_decision": PolicyDecision.ALLOW,
        "policy_rule_id": "rule-1",
        "transport": "http",
    }
    defaults.update(kwargs)
    return HookContext(**defaults)


class TestJsonEmission:
    """End-to-end tests verifying JSON structure matches issue #23 schema."""

    @pytest.mark.asyncio
    async def test_tool_invocation_json_structure(self, caplog):
        hook = AuditHook()
        ctx = _make_ctx(request_payload={"arguments": {"query": "test"}})

        with caplog.at_level(logging.INFO, logger="mcp_zero.audit.hook"):
            await hook.on_pre_audit(ctx)

        parsed = json.loads(caplog.records[0].message)

        assert parsed["event_type"] == "mcp_tool_invocation"
        assert parsed["correlation_id"] == ctx.request.correlation_id
        assert parsed["timestamp"]  # non-empty
        assert parsed["user"]["user_id"] == "test-user"
        assert parsed["user"]["groups"] == ["admin", "dev"]
        assert parsed["server_name"] == "test-server"
        assert parsed["tool_name"] == "test-tool"
        assert parsed["transport"] == "http"
        assert parsed["policy_decision"] == "allow"
        assert parsed["request_size_bytes"] > 0
        assert isinstance(parsed["masking_events"], list)

    @pytest.mark.asyncio
    async def test_policy_decision_json_structure(self, caplog):
        hook = AuditHook()
        ctx = _make_ctx(short_circuited=True, short_circuit_reason="Access denied")
        error = ShortCircuitError("Access denied", deny=True)

        with caplog.at_level(logging.INFO, logger="mcp_zero.audit.hook"):
            await hook.on_error(ctx, error)

        parsed = json.loads(caplog.records[0].message)
        assert parsed["event_type"] == "policy_decision"
        assert parsed["error_type"] == "ShortCircuitError"
        assert parsed["short_circuited"] is True

    @pytest.mark.asyncio
    async def test_masking_events_in_json(self, caplog):
        masking_events = [
            MaskingEvent(entity_type="PERSON", count=2, status="masked"),
            MaskingEvent(entity_type="EMAIL_ADDRESS", count=1, status="masked"),
        ]
        hook = AuditHook()
        ctx = _make_ctx(
            masking_applied=True,
            masked_fields=["name", "email"],
            masking_events=masking_events,
            masking_stage_completed=True,
        )

        with caplog.at_level(logging.INFO, logger="mcp_zero.audit.hook"):
            await hook.on_pre_audit(ctx)

        # First record is TOOL_INVOCATION
        parsed = json.loads(caplog.records[0].message)
        assert len(parsed["masking_events"]) == 2
        assert parsed["masking_events"][0]["entity_type"] == "PERSON"
        assert parsed["masking_events"][0]["count"] == 2
        assert parsed["masking_events"][0]["status"] == "success"

        # Second record is MASKING_EVENT
        parsed2 = json.loads(caplog.records[1].message)
        assert parsed2["event_type"] == "masking_event"

    @pytest.mark.asyncio
    async def test_sizes_in_json(self, caplog):
        hook = AuditHook()
        req_payload = {"arguments": {"query": "hello"}}
        resp_payload = {"content": [{"text": "world"}]}
        ctx = _make_ctx(request_payload=req_payload, response_payload=resp_payload)

        with caplog.at_level(logging.INFO, logger="mcp_zero.audit.hook"):
            await hook.on_pre_audit(ctx)

        parsed = json.loads(caplog.records[0].message)
        assert parsed["request_size_bytes"] == len(json.dumps(req_payload).encode())
        assert parsed["response_size_bytes"] == len(json.dumps(resp_payload).encode())


class TestJsonTraceIdEmission:
    """Tests verifying trace_id is null for top-level and set for child contexts."""

    @pytest.mark.asyncio
    async def test_top_level_emits_trace_id_null(self, caplog):
        hook = AuditHook()
        ctx = _make_ctx()  # top-level request, trace_id is None

        with caplog.at_level(logging.INFO, logger="mcp_zero.audit.hook"):
            await hook.on_pre_audit(ctx)

        parsed = json.loads(caplog.records[0].message)
        assert parsed["trace_id"] is None

    @pytest.mark.asyncio
    async def test_child_context_emits_parent_correlation_id_as_trace_id(self, caplog):
        hook = AuditHook()
        parent_request = RequestContext(
            identity=UserIdentity(
                user_id="test-user", email="test@example.com", groups=["admin", "dev"]
            ),
        )
        child_request = parent_request.child_context()
        ctx = _make_ctx(request=child_request)

        with caplog.at_level(logging.INFO, logger="mcp_zero.audit.hook"):
            await hook.on_pre_audit(ctx)

        parsed = json.loads(caplog.records[0].message)
        assert parsed["trace_id"] == parent_request.correlation_id


class TestJsonFieldFiltering:
    """Tests for field filtering via logging.include."""

    @pytest.mark.asyncio
    async def test_include_filters_to_specified_fields(self, caplog):

        class _Config:
            include = ["server_name", "tool_name", "transport"]

        hook = AuditHook(logging_config=_Config())
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
        assert "transport" in parsed
        # Filtered out
        assert "user" not in parsed
        assert "duration_ms" not in parsed
        assert "masking_events" not in parsed

    @pytest.mark.asyncio
    async def test_include_user_field(self, caplog):

        class _Config:
            include = ["user"]

        hook = AuditHook(logging_config=_Config())
        ctx = _make_ctx()

        with caplog.at_level(logging.INFO, logger="mcp_zero.audit.hook"):
            await hook.on_pre_audit(ctx)

        parsed = json.loads(caplog.records[0].message)
        assert "user" in parsed
        assert parsed["user"]["user_id"] == "test-user"
        assert "server_name" not in parsed

    @pytest.mark.asyncio
    async def test_all_records_filtered(self, caplog):
        """When include is set, all emitted records are filtered."""

        class _Config:
            include = ["server_name"]

        hook = AuditHook(logging_config=_Config())
        ctx = _make_ctx(
            masking_applied=True,
            masked_fields=["name"],
            masking_events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
        )

        with caplog.at_level(logging.INFO, logger="mcp_zero.audit.hook"):
            await hook.on_pre_audit(ctx)

        # Both TOOL_INVOCATION and MASKING_EVENT should be filtered
        assert len(caplog.records) == 2
        for record in caplog.records:
            parsed = json.loads(record.message)
            assert "server_name" in parsed
            assert "user" not in parsed
