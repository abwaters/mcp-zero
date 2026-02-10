"""Tests for the MaskingHook lifecycle hook."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_zero.context import HookContext, RequestContext
from mcp_zero.governance.config import PresidioConfig
from mcp_zero.masking.engine import MaskingEvent, MaskingResult
from mcp_zero.masking.errors import MaskingEngineError
from mcp_zero.masking.hook import MaskingHook
from mcp_zero.pipeline.errors import ShortCircuitError


def _make_config(
    enabled: bool = True,
    entities: list[str] | None = None,
) -> PresidioConfig:
    return PresidioConfig(
        enabled=enabled,
        entities=entities or ["PERSON", "EMAIL_ADDRESS"],
    )


def _make_ctx(payload: dict | None = None) -> HookContext:
    return HookContext(
        request=RequestContext(),
        request_payload=payload or {},
    )


def _mask_side_effect(replacements: dict[str, tuple[str, list[MaskingEvent]]]):
    """Build a mask_text side-effect that replaces known values."""

    async def _side_effect(text, entities, direction):
        for pattern, (masked, events) in replacements.items():
            if pattern in text:
                return MaskingResult(masked_text=masked, events=events, has_masked=True)
        return MaskingResult(masked_text=text, events=[], has_masked=False)

    return _side_effect


# ---------------------------------------------------------------------------
# Top-level string field masking (backwards-compatible)
# ---------------------------------------------------------------------------


class TestMaskingHookMasksPayload:
    @pytest.mark.asyncio
    async def test_masks_text_fields(self):
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="Hello <PERSON>",
            events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
            has_masked=True,
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={"message": "Hello John Smith"})
        result = await hook.on_pre_masking(ctx)

        assert result.masking_applied is True
        assert result.masked_fields == ["message"]
        assert result.request_payload["message"] == "Hello <PERSON>"

    @pytest.mark.asyncio
    async def test_masks_multiple_text_fields(self):
        engine = AsyncMock()
        engine.mask_text.side_effect = _mask_side_effect(
            {
                "John": (
                    "<PERSON>",
                    [MaskingEvent(entity_type="PERSON", count=1, status="masked")],
                ),
                "alice@": (
                    "<EMAIL_ADDRESS>",
                    [MaskingEvent(entity_type="EMAIL_ADDRESS", count=1, status="masked")],
                ),
            }
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={"name": "John", "email": "alice@example.com", "count": "5"})
        result = await hook.on_pre_masking(ctx)

        assert result.masking_applied is True
        assert "name" in result.masked_fields
        assert "email" in result.masked_fields
        assert result.request_payload["name"] == "<PERSON>"
        assert result.request_payload["email"] == "<EMAIL_ADDRESS>"

    @pytest.mark.asyncio
    async def test_skips_non_string_fields(self):
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="masked", events=[], has_masked=False
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={"count": 42, "flag": True, "nothing": None})
        result = await hook.on_pre_masking(ctx)

        engine.mask_text.assert_not_called()
        assert result.masking_applied is False

    @pytest.mark.asyncio
    async def test_no_masking_when_nothing_detected(self):
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="safe text", events=[], has_masked=False
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={"message": "safe text"})
        result = await hook.on_pre_masking(ctx)

        assert result.masking_applied is False
        assert result.masked_fields == []


# ---------------------------------------------------------------------------
# Recursive (nested) masking
# ---------------------------------------------------------------------------


class TestMaskingHookRecursive:
    @pytest.mark.asyncio
    async def test_masks_nested_dict_values(self):
        """Issue #20: nested dict values must be scanned and masked."""
        engine = AsyncMock()
        engine.mask_text.side_effect = _mask_side_effect(
            {
                "john.doe@company.com": (
                    "Find <EMAIL_ADDRESS>",
                    [MaskingEvent(entity_type="EMAIL_ADDRESS", count=1, status="masked")],
                ),
            }
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(
            payload={
                "arguments": {
                    "query": "Find john.doe@company.com",
                    "filters": {"department": "engineering"},
                }
            }
        )
        result = await hook.on_pre_masking(ctx)

        assert result.masking_applied is True
        assert "arguments.query" in result.masked_fields
        assert result.request_payload["arguments"]["query"] == "Find <EMAIL_ADDRESS>"
        # Structure preserved — keys untouched
        assert "arguments" in result.request_payload
        assert "filters" in result.request_payload["arguments"]
        assert result.request_payload["arguments"]["filters"]["department"] == "engineering"

    @pytest.mark.asyncio
    async def test_masks_deeply_nested_values(self):
        """Three levels deep."""
        engine = AsyncMock()
        engine.mask_text.side_effect = _mask_side_effect(
            {
                "secret-api-key": (
                    "<API_KEY>",
                    [MaskingEvent(entity_type="API_KEY", count=1, status="masked")],
                ),
            }
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(
            payload={
                "level1": {
                    "level2": {
                        "level3": "secret-api-key",
                    }
                }
            }
        )
        result = await hook.on_pre_masking(ctx)

        assert result.masking_applied is True
        assert "level1.level2.level3" in result.masked_fields
        assert result.request_payload["level1"]["level2"]["level3"] == "<API_KEY>"

    @pytest.mark.asyncio
    async def test_masks_strings_in_lists(self):
        """Strings inside lists must be scanned."""
        engine = AsyncMock()
        engine.mask_text.side_effect = _mask_side_effect(
            {
                "Jane": (
                    "<PERSON>",
                    [MaskingEvent(entity_type="PERSON", count=1, status="masked")],
                ),
            }
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={"names": ["Jane Doe", "safe-text"]})
        result = await hook.on_pre_masking(ctx)

        assert result.masking_applied is True
        assert "names[0]" in result.masked_fields
        assert result.request_payload["names"][0] == "<PERSON>"
        assert result.request_payload["names"][1] == "safe-text"

    @pytest.mark.asyncio
    async def test_masks_dicts_inside_lists(self):
        """Dicts nested inside lists."""
        engine = AsyncMock()
        engine.mask_text.side_effect = _mask_side_effect(
            {
                "bob@": (
                    "<EMAIL_ADDRESS>",
                    [MaskingEvent(entity_type="EMAIL_ADDRESS", count=1, status="masked")],
                ),
            }
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(
            payload={
                "users": [
                    {"email": "bob@corp.com", "role": "admin"},
                    {"email": "safe", "role": "user"},
                ]
            }
        )
        result = await hook.on_pre_masking(ctx)

        assert result.masking_applied is True
        assert "users[0].email" in result.masked_fields
        assert result.request_payload["users"][0]["email"] == "<EMAIL_ADDRESS>"
        assert result.request_payload["users"][0]["role"] == "admin"
        assert result.request_payload["users"][1]["email"] == "safe"

    @pytest.mark.asyncio
    async def test_non_string_values_in_nested_structures_unchanged(self):
        """Numbers, booleans, None inside nested structures pass through."""
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="text", events=[], has_masked=False
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(
            payload={
                "arguments": {
                    "count": 42,
                    "enabled": True,
                    "value": None,
                    "rate": 3.14,
                    "label": "safe text",
                }
            }
        )
        result = await hook.on_pre_masking(ctx)

        assert result.request_payload["arguments"]["count"] == 42
        assert result.request_payload["arguments"]["enabled"] is True
        assert result.request_payload["arguments"]["value"] is None
        assert result.request_payload["arguments"]["rate"] == 3.14
        # Only the string field should have been sent to the engine
        engine.mask_text.assert_called_once_with(
            text="safe text", entities=["PERSON", "EMAIL_ADDRESS"], direction="request"
        )

    @pytest.mark.asyncio
    async def test_preserves_request_structure_keys_untouched(self):
        """Keys are never modified, only values."""
        engine = AsyncMock()
        engine.mask_text.side_effect = _mask_side_effect(
            {
                "secret": (
                    "<MASKED>",
                    [MaskingEvent(entity_type="PASSWORD", count=1, status="masked")],
                ),
            }
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(
            payload={
                "method": "tools/call",
                "params": {
                    "name": "search_users",
                    "arguments": {"password": "secret123"},
                },
            }
        )
        result = await hook.on_pre_masking(ctx)

        # All original keys preserved
        assert "method" in result.request_payload
        assert "params" in result.request_payload
        assert "name" in result.request_payload["params"]
        assert "arguments" in result.request_payload["params"]
        assert "password" in result.request_payload["params"]["arguments"]

    @pytest.mark.asyncio
    async def test_mixed_nested_structure(self):
        """Real-world MCP tool call shape from issue #20."""
        engine = AsyncMock()
        engine.mask_text.side_effect = _mask_side_effect(
            {
                "john.doe@company.com": (
                    "Find <EMAIL_ADDRESS>",
                    [MaskingEvent(entity_type="EMAIL_ADDRESS", count=1, status="masked")],
                ),
            }
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(
            payload={
                "arguments": {
                    "query": "Find john.doe@company.com",
                    "filters": {"department": "engineering"},
                    "limit": 10,
                }
            }
        )
        result = await hook.on_pre_masking(ctx)

        assert result.masking_applied is True
        assert result.request_payload["arguments"]["query"] == "Find <EMAIL_ADDRESS>"
        assert result.request_payload["arguments"]["filters"]["department"] == "engineering"
        assert result.request_payload["arguments"]["limit"] == 10


# ---------------------------------------------------------------------------
# Disabled config
# ---------------------------------------------------------------------------


class TestMaskingHookDisabled:
    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        engine = AsyncMock()
        config = _make_config(enabled=False)

        hook = MaskingHook(engine, config)
        ctx = _make_ctx(payload={"message": "John Smith"})
        result = await hook.on_pre_masking(ctx)

        engine.mask_text.assert_not_called()
        assert result.masking_applied is False

    @pytest.mark.asyncio
    async def test_returns_ctx_unchanged_when_disabled(self):
        engine = AsyncMock()
        config = _make_config(enabled=False)

        hook = MaskingHook(engine, config)
        ctx = _make_ctx(payload={"data": "sensitive"})
        result = await hook.on_pre_masking(ctx)

        assert result is ctx


# ---------------------------------------------------------------------------
# Error handling — fail-closed
# ---------------------------------------------------------------------------


class TestMaskingHookFailClosed:
    @pytest.mark.asyncio
    async def test_engine_error_raises_short_circuit(self):
        """Issue #20: masking failure must deny request (fail closed)."""
        engine = AsyncMock()
        engine.mask_text.side_effect = MaskingEngineError("engine failed", engine="presidio")

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={"message": "John Smith"})

        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_pre_masking(ctx)

        assert exc_info.value.deny is True
        assert "Masking failure" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_engine_error_on_nested_field_raises_short_circuit(self):
        """Fail-closed applies even when error occurs deep in a nested structure."""
        engine = AsyncMock()

        call_count = 0

        async def _fail_on_second(text, entities, direction):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MaskingResult(masked_text=text, events=[], has_masked=False)
            raise MaskingEngineError("engine crashed", engine="presidio")

        engine.mask_text.side_effect = _fail_on_second

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={"safe": "hello", "nested": {"dangerous": "trigger error"}})

        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_pre_masking(ctx)

        assert exc_info.value.deny is True

    @pytest.mark.asyncio
    async def test_empty_payload_returns_unchanged(self):
        engine = AsyncMock()

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={})
        result = await hook.on_pre_masking(ctx)

        engine.mask_text.assert_not_called()
        assert result.masking_applied is False
        assert result.masking_stage_completed is True


# ---------------------------------------------------------------------------
# Masking events in context (for audit)
# ---------------------------------------------------------------------------


class TestMaskingHookEvents:
    @pytest.mark.asyncio
    async def test_masking_events_stored_in_context(self):
        """Issue #20: masking events must be recorded in context for audit."""
        events = [
            MaskingEvent(entity_type="PERSON", count=1, status="masked"),
            MaskingEvent(entity_type="EMAIL_ADDRESS", count=2, status="masked"),
        ]
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="<PERSON> emailed <EMAIL_ADDRESS> and <EMAIL_ADDRESS>",
            events=events,
            has_masked=True,
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={"text": "John emailed alice@x.com and bob@x.com"})
        result = await hook.on_pre_masking(ctx)

        assert len(result.masking_events) == 2
        assert result.masking_events[0].entity_type == "PERSON"
        assert result.masking_events[1].entity_type == "EMAIL_ADDRESS"

    @pytest.mark.asyncio
    async def test_masking_events_aggregated_across_fields(self):
        """Events from multiple fields should all be collected."""
        engine = AsyncMock()

        async def _mock(text, entities, direction):
            if "John" in text:
                return MaskingResult(
                    masked_text="<PERSON>",
                    events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
                    has_masked=True,
                )
            if "alice@" in text:
                return MaskingResult(
                    masked_text="<EMAIL_ADDRESS>",
                    events=[MaskingEvent(entity_type="EMAIL_ADDRESS", count=1, status="masked")],
                    has_masked=True,
                )
            return MaskingResult(masked_text=text, events=[], has_masked=False)

        engine.mask_text.side_effect = _mock

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(
            payload={
                "name": "John",
                "contact": {"email": "alice@example.com"},
            }
        )
        result = await hook.on_pre_masking(ctx)

        assert len(result.masking_events) == 2
        entity_types = {e.entity_type for e in result.masking_events}
        assert entity_types == {"PERSON", "EMAIL_ADDRESS"}

    @pytest.mark.asyncio
    async def test_no_masking_events_when_nothing_detected(self):
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="safe", events=[], has_masked=False
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={"text": "safe"})
        result = await hook.on_pre_masking(ctx)

        assert result.masking_events == []


# ---------------------------------------------------------------------------
# Context preservation
# ---------------------------------------------------------------------------


class TestMaskingHookContext:
    @pytest.mark.asyncio
    async def test_correlation_id_preserved(self):
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="<PERSON>",
            events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
            has_masked=True,
        )

        hook = MaskingHook(engine, _make_config())
        original_request = RequestContext()
        ctx = HookContext(
            request=original_request,
            request_payload={"name": "John Smith"},
        )
        result = await hook.on_pre_masking(ctx)

        assert result.request.correlation_id == original_request.correlation_id

    @pytest.mark.asyncio
    async def test_passes_configured_entities(self):
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="text", events=[], has_masked=False
        )

        config = _make_config(entities=["CREDIT_CARD", "PHONE_NUMBER"])
        hook = MaskingHook(engine, config)
        ctx = _make_ctx(payload={"data": "some text"})
        await hook.on_pre_masking(ctx)

        engine.mask_text.assert_called_once_with(
            text="some text",
            entities=["CREDIT_CARD", "PHONE_NUMBER"],
            direction="request",
        )

    @pytest.mark.asyncio
    async def test_correlation_id_preserved_through_nested_masking(self):
        """Correlation ID must survive recursive masking."""
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="<PERSON>",
            events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
            has_masked=True,
        )

        hook = MaskingHook(engine, _make_config())
        original_request = RequestContext()
        ctx = HookContext(
            request=original_request,
            request_payload={"nested": {"name": "John Smith"}},
        )
        result = await hook.on_pre_masking(ctx)

        assert result.request.correlation_id == original_request.correlation_id


# ---------------------------------------------------------------------------
# masking_stage_completed flag
# ---------------------------------------------------------------------------


class TestMaskingStageCompleted:
    @pytest.mark.asyncio
    async def test_set_true_when_pii_found(self):
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="<PERSON>",
            events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
            has_masked=True,
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={"name": "John Smith"})
        result = await hook.on_pre_masking(ctx)

        assert result.masking_stage_completed is True

    @pytest.mark.asyncio
    async def test_set_true_when_no_pii_found(self):
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="safe text", events=[], has_masked=False
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={"message": "safe text"})
        result = await hook.on_pre_masking(ctx)

        assert result.masking_stage_completed is True

    @pytest.mark.asyncio
    async def test_set_true_when_empty_payload(self):
        engine = AsyncMock()

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={})
        result = await hook.on_pre_masking(ctx)

        assert result.masking_stage_completed is True

    @pytest.mark.asyncio
    async def test_stays_false_when_disabled(self):
        engine = AsyncMock()

        hook = MaskingHook(engine, _make_config(enabled=False))
        ctx = _make_ctx(payload={"name": "John"})
        result = await hook.on_pre_masking(ctx)

        assert result.masking_stage_completed is False

    @pytest.mark.asyncio
    async def test_stays_false_on_engine_failure(self):
        engine = AsyncMock()
        engine.mask_text.side_effect = MaskingEngineError("engine failed", engine="presidio")

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={"name": "John"})

        with pytest.raises(ShortCircuitError):
            await hook.on_pre_masking(ctx)

        # ctx was not evolved — masking_stage_completed stays False
        assert ctx.masking_stage_completed is False


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestMaskingHookProperties:
    def test_hook_name(self):
        engine = MagicMock()
        hook = MaskingHook(engine, _make_config())
        assert hook.name == "MaskingHook"
