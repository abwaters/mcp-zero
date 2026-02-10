"""Tests for output masking (MaskingHook.on_post_masking)."""

from __future__ import annotations

from unittest.mock import AsyncMock

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


def _make_ctx(response_payload: dict | None = None) -> HookContext:
    return HookContext(
        request=RequestContext(),
        response_payload=response_payload or {},
    )


class TestOutputMaskingBasic:
    @pytest.mark.asyncio
    async def test_masks_text_in_response_content(self):
        """Standard MCP response with text content gets masked."""
        engine = AsyncMock()

        async def mock_mask(text, entities, direction):
            if "John Doe" in text:
                return MaskingResult(
                    masked_text=text.replace("John Doe", "<PERSON>"),
                    events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
                    has_masked=True,
                )
            return MaskingResult(masked_text=text, events=[], has_masked=False)

        engine.mask_text.side_effect = mock_mask

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(
            response_payload={
                "content": [{"type": "text", "text": "User John Doe has 3 issues"}],
                "isError": False,
            }
        )
        result = await hook.on_post_masking(ctx)

        assert result.output_masking_applied is True
        assert result.response_payload["content"][0]["text"] == "User <PERSON> has 3 issues"
        assert "content[0].text" in result.output_masked_fields

    @pytest.mark.asyncio
    async def test_masks_multiple_content_items(self):
        engine = AsyncMock()

        async def mock_mask(text, entities, direction):
            if "john@" in text:
                return MaskingResult(
                    masked_text="<EMAIL_ADDRESS>",
                    events=[MaskingEvent(entity_type="EMAIL_ADDRESS", count=1, status="masked")],
                    has_masked=True,
                )
            if "Jane" in text:
                return MaskingResult(
                    masked_text="<PERSON>",
                    events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
                    has_masked=True,
                )
            return MaskingResult(masked_text=text, events=[], has_masked=False)

        engine.mask_text.side_effect = mock_mask

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(
            response_payload={
                "content": [
                    {"type": "text", "text": "john@example.com"},
                    {"type": "text", "text": "Jane Smith"},
                ],
                "isError": False,
            }
        )
        result = await hook.on_post_masking(ctx)

        assert result.output_masking_applied is True
        assert result.response_payload["content"][0]["text"] == "<EMAIL_ADDRESS>"
        assert result.response_payload["content"][1]["text"] == "<PERSON>"

    @pytest.mark.asyncio
    async def test_no_masking_when_nothing_detected(self):
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="safe text", events=[], has_masked=False
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(
            response_payload={
                "content": [{"type": "text", "text": "safe text"}],
                "isError": False,
            }
        )
        result = await hook.on_post_masking(ctx)

        assert result.output_masking_applied is False
        assert result.output_masked_fields == []

    @pytest.mark.asyncio
    async def test_uses_response_direction(self):
        """Masking engine receives direction='response'."""
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="text", events=[], has_masked=False
        )

        hook = MaskingHook(engine, _make_config(entities=["PERSON"]))
        ctx = _make_ctx(response_payload={"message": "hello"})
        await hook.on_post_masking(ctx)

        engine.mask_text.assert_called_once_with(
            text="hello",
            entities=["PERSON"],
            direction="response",
        )


class TestOutputMaskingRecursive:
    @pytest.mark.asyncio
    async def test_masks_nested_dict_values(self):
        engine = AsyncMock()

        async def mock_mask(text, entities, direction):
            if "secret" in text:
                return MaskingResult(
                    masked_text="<PASSWORD>",
                    events=[MaskingEvent(entity_type="PASSWORD", count=1, status="masked")],
                    has_masked=True,
                )
            return MaskingResult(masked_text=text, events=[], has_masked=False)

        engine.mask_text.side_effect = mock_mask

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(response_payload={"result": {"data": {"password": "secret123"}}})
        result = await hook.on_post_masking(ctx)

        assert result.output_masking_applied is True
        assert result.response_payload["result"]["data"]["password"] == "<PASSWORD>"
        assert "result.data.password" in result.output_masked_fields

    @pytest.mark.asyncio
    async def test_masks_strings_in_lists(self):
        engine = AsyncMock()

        async def mock_mask(text, entities, direction):
            if "John" in text:
                return MaskingResult(
                    masked_text="<PERSON>",
                    events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
                    has_masked=True,
                )
            return MaskingResult(masked_text=text, events=[], has_masked=False)

        engine.mask_text.side_effect = mock_mask

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(response_payload={"names": ["John Doe", "safe name", "John Smith"]})
        result = await hook.on_post_masking(ctx)

        assert result.output_masking_applied is True
        assert result.response_payload["names"][0] == "<PERSON>"
        assert result.response_payload["names"][1] == "safe name"
        assert result.response_payload["names"][2] == "<PERSON>"

    @pytest.mark.asyncio
    async def test_deeply_nested_structure(self):
        """Handles MCP response with nested content arrays."""
        engine = AsyncMock()

        async def mock_mask(text, entities, direction):
            if "PII" in text:
                return MaskingResult(
                    masked_text="<MASKED>",
                    events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
                    has_masked=True,
                )
            return MaskingResult(masked_text=text, events=[], has_masked=False)

        engine.mask_text.side_effect = mock_mask

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(
            response_payload={
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Contains PII data",
                            "annotations": {
                                "source": "Also PII here",
                            },
                        }
                    ]
                }
            }
        )
        result = await hook.on_post_masking(ctx)

        assert result.output_masking_applied is True
        content = result.response_payload["result"]["content"][0]
        assert content["text"] == "<MASKED>"
        assert content["annotations"]["source"] == "<MASKED>"

    @pytest.mark.asyncio
    async def test_preserves_non_string_values(self):
        """Non-string values (ints, bools, None) pass through unchanged."""
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="text", events=[], has_masked=False
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(
            response_payload={
                "count": 42,
                "active": True,
                "data": None,
                "message": "text",
            }
        )
        result = await hook.on_post_masking(ctx)

        assert result.response_payload["count"] == 42
        assert result.response_payload["active"] is True
        assert result.response_payload["data"] is None

    @pytest.mark.asyncio
    async def test_preserves_dict_keys(self):
        """Dict keys are never modified, even if they contain PII."""
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="safe", events=[], has_masked=False
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(response_payload={"john@example.com": "some value"})
        result = await hook.on_post_masking(ctx)

        assert "john@example.com" in result.response_payload


class TestOutputMaskingDisabled:
    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        engine = AsyncMock()
        config = _make_config(enabled=False)

        hook = MaskingHook(engine, config)
        ctx = _make_ctx(response_payload={"content": [{"type": "text", "text": "John Smith"}]})
        result = await hook.on_post_masking(ctx)

        engine.mask_text.assert_not_called()
        assert result.output_masking_applied is False

    @pytest.mark.asyncio
    async def test_returns_ctx_unchanged_when_disabled(self):
        engine = AsyncMock()
        config = _make_config(enabled=False)

        hook = MaskingHook(engine, config)
        ctx = _make_ctx(response_payload={"data": "sensitive"})
        result = await hook.on_post_masking(ctx)

        assert result is ctx

    @pytest.mark.asyncio
    async def test_empty_payload_returns_unchanged(self):
        engine = AsyncMock()

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(response_payload={})
        result = await hook.on_post_masking(ctx)

        engine.mask_text.assert_not_called()
        assert result.output_masking_applied is False
        assert result.masking_stage_completed is True


class TestOutputMaskingFailClosed:
    @pytest.mark.asyncio
    async def test_engine_error_raises_short_circuit(self):
        """Output masking failure blocks response (fail-closed)."""
        engine = AsyncMock()
        engine.mask_text.side_effect = MaskingEngineError("engine crashed", engine="presidio")

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(response_payload={"content": [{"type": "text", "text": "John Smith"}]})

        with pytest.raises(ShortCircuitError, match="Output masking failed"):
            await hook.on_post_masking(ctx)

    @pytest.mark.asyncio
    async def test_engine_error_sets_deny(self):
        """ShortCircuitError from output masking sets deny=True."""
        engine = AsyncMock()
        engine.mask_text.side_effect = MaskingEngineError("engine crashed", engine="presidio")

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(response_payload={"message": "John Smith"})

        with pytest.raises(ShortCircuitError) as exc_info:
            await hook.on_post_masking(ctx)

        assert exc_info.value.deny is True

    @pytest.mark.asyncio
    async def test_engine_error_in_nested_structure_blocks_response(self):
        """Engine error deep in a nested structure still triggers fail-closed."""
        call_count = {"n": 0}

        async def mock_mask(text, entities, direction):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return MaskingResult(masked_text="safe", events=[], has_masked=False)
            raise MaskingEngineError("engine crashed", engine="presidio")

        engine = AsyncMock()
        engine.mask_text.side_effect = mock_mask

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(
            response_payload={
                "content": [
                    {"type": "text", "text": "safe text"},
                    {"type": "text", "text": "triggers error"},
                ]
            }
        )

        with pytest.raises(ShortCircuitError, match="Output masking failed"):
            await hook.on_post_masking(ctx)


class TestOutputMaskingSeparateTracking:
    @pytest.mark.asyncio
    async def test_output_fields_separate_from_input(self):
        """Output masking events are tracked separately from input masking."""
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="<PERSON>",
            events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
            has_masked=True,
        )

        hook = MaskingHook(engine, _make_config())

        # Simulate a context that already has input masking applied
        ctx = HookContext(
            request=RequestContext(),
            request_payload={"name": "<PERSON>"},
            response_payload={"message": "John Smith"},
            masking_applied=True,
            masked_fields=["name"],
        )

        result = await hook.on_post_masking(ctx)

        # Input masking state preserved
        assert result.masking_applied is True
        assert result.masked_fields == ["name"]
        # Output masking tracked separately
        assert result.output_masking_applied is True
        assert "message" in result.output_masked_fields

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
            response_payload={"name": "John Smith"},
        )
        result = await hook.on_post_masking(ctx)

        assert result.request.correlation_id == original_request.correlation_id


class TestOutputMaskingStageCompleted:
    @pytest.mark.asyncio
    async def test_set_true_when_pii_found(self):
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="<PERSON>",
            events=[MaskingEvent(entity_type="PERSON", count=1, status="masked")],
            has_masked=True,
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(response_payload={"name": "John Smith"})
        result = await hook.on_post_masking(ctx)

        assert result.masking_stage_completed is True

    @pytest.mark.asyncio
    async def test_set_true_when_no_pii_found(self):
        engine = AsyncMock()
        engine.mask_text.return_value = MaskingResult(
            masked_text="safe text", events=[], has_masked=False
        )

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(response_payload={"message": "safe text"})
        result = await hook.on_post_masking(ctx)

        assert result.masking_stage_completed is True

    @pytest.mark.asyncio
    async def test_set_true_when_empty_payload(self):
        engine = AsyncMock()

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(response_payload={})
        result = await hook.on_post_masking(ctx)

        assert result.masking_stage_completed is True

    @pytest.mark.asyncio
    async def test_stays_false_when_disabled(self):
        engine = AsyncMock()

        hook = MaskingHook(engine, _make_config(enabled=False))
        ctx = _make_ctx(response_payload={"data": "hello"})
        result = await hook.on_post_masking(ctx)

        assert result.masking_stage_completed is False

    @pytest.mark.asyncio
    async def test_stays_false_on_engine_failure(self):
        engine = AsyncMock()
        engine.mask_text.side_effect = MaskingEngineError("engine crashed", engine="presidio")

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(response_payload={"data": "John Smith"})

        with pytest.raises(ShortCircuitError):
            await hook.on_post_masking(ctx)

        assert ctx.masking_stage_completed is False


class TestOutputMaskingErrorMessages:
    @pytest.mark.asyncio
    async def test_masks_error_response_content(self):
        """Error messages from MCP servers are also masked."""
        engine = AsyncMock()

        async def mock_mask(text, entities, direction):
            if "john@" in text:
                return MaskingResult(
                    masked_text=text.replace("john@example.com", "<EMAIL_ADDRESS>"),
                    events=[MaskingEvent(entity_type="EMAIL_ADDRESS", count=1, status="masked")],
                    has_masked=True,
                )
            return MaskingResult(masked_text=text, events=[], has_masked=False)

        engine.mask_text.side_effect = mock_mask

        hook = MaskingHook(engine, _make_config())
        ctx = _make_ctx(
            response_payload={
                "content": [
                    {
                        "type": "text",
                        "text": "Error: user john@example.com not found",
                    }
                ],
                "isError": True,
            }
        )
        result = await hook.on_post_masking(ctx)

        assert result.output_masking_applied is True
        assert (
            result.response_payload["content"][0]["text"] == "Error: user <EMAIL_ADDRESS> not found"
        )
        # isError flag is preserved (non-string, passes through)
        assert result.response_payload["isError"] is True
