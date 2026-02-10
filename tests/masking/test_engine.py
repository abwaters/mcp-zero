"""Tests for the abstract MaskingEngine interface and result types."""

from __future__ import annotations

import pytest

from mcp_zero.masking.engine import MaskingEngine, MaskingEvent, MaskingResult


class StubEngine(MaskingEngine):
    """Concrete stub for testing the ABC contract."""

    async def mask_text(self, text: str, entities: list[str], direction: str) -> MaskingResult:
        return MaskingResult(masked_text=text, events=[], has_masked=False)

    def validate_config(self) -> bool:
        return True


class TestMaskingEvent:
    def test_fields(self):
        event = MaskingEvent(entity_type="PERSON", count=2, status="masked")
        assert event.entity_type == "PERSON"
        assert event.count == 2
        assert event.status == "masked"

    def test_frozen(self):
        event = MaskingEvent(entity_type="EMAIL_ADDRESS", count=1, status="masked")
        with pytest.raises(AttributeError):
            event.count = 5  # type: ignore[misc]


class TestMaskingResult:
    def test_no_masking(self):
        result = MaskingResult(masked_text="hello", events=[], has_masked=False)
        assert result.masked_text == "hello"
        assert result.events == []
        assert result.has_masked is False

    def test_with_events(self):
        events = [MaskingEvent(entity_type="PERSON", count=1, status="masked")]
        result = MaskingResult(masked_text="<PERSON>", events=events, has_masked=True)
        assert result.has_masked is True
        assert len(result.events) == 1

    def test_frozen(self):
        result = MaskingResult(masked_text="hi")
        with pytest.raises(AttributeError):
            result.masked_text = "bye"  # type: ignore[misc]

    def test_defaults(self):
        result = MaskingResult(masked_text="text")
        assert result.events == []
        assert result.has_masked is False


class TestMaskingEngineABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            MaskingEngine()  # type: ignore[abstract]

    @pytest.mark.asyncio
    async def test_stub_mask_text(self):
        engine = StubEngine()
        result = await engine.mask_text("hello", ["PERSON"], "request")
        assert result.masked_text == "hello"
        assert result.has_masked is False

    def test_stub_validate_config(self):
        engine = StubEngine()
        assert engine.validate_config() is True
