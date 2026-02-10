"""Tests for the MaskingHook lifecycle hook."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_zero.context import HookContext, RequestContext
from mcp_zero.governance.config import PresidioConfig
from mcp_zero.masking.engine import MaskingEvent, MaskingResult
from mcp_zero.masking.errors import MaskingEngineError
from mcp_zero.masking.hook import MaskingHook


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
        call_count = 0

        async def mock_mask_text(text, entities, direction):
            nonlocal call_count
            call_count += 1
            if "John" in text:
                return MaskingResult(
                    masked_text="<PERSON>",
                    events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
                    has_masked=True,
                )
            if "alice@" in text:
                return MaskingResult(
                    masked_text="<EMAIL_ADDRESS>",
                    events=[
                        MaskingEvent(entity_type="EMAIL_ADDRESS", count=1, status="masked")
                    ],
                    has_masked=True,
                )
            return MaskingResult(masked_text=text, events=[], has_masked=False)

        engine = AsyncMock()
        engine.mask_text.side_effect = mock_mask_text

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
        ctx = _make_ctx(payload={"count": 42, "items": ["a", "b"]})
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


class TestMaskingHookErrorHandling:
    @pytest.mark.asyncio
    async def test_engine_error_continues_gracefully(self):
        engine = AsyncMock()
        engine.mask_text.side_effect = MaskingEngineError(
            "engine failed", engine="presidio"
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={"message": "John Smith"})
        result = await hook.on_pre_masking(ctx)

        # Should not crash; masking not applied
        assert result.masking_applied is False
        assert result.masked_fields == []

    @pytest.mark.asyncio
    async def test_empty_payload_returns_unchanged(self):
        engine = AsyncMock()

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(payload={})
        result = await hook.on_pre_masking(ctx)

        engine.mask_text.assert_not_called()
        assert result is ctx


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


class TestMaskingHookProperties:
    def test_hook_name(self):
        engine = MagicMock()
        hook = MaskingHook(engine, _make_config())
        assert hook.name == "MaskingHook"
