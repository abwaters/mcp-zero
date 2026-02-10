"""Tests for the PresidioMaskingEngine."""

from __future__ import annotations

import pytest

from mcp_zero.governance.config import PresidioConfig
from mcp_zero.masking.errors import MaskingConfigError, MaskingEngineError
from mcp_zero.masking.presidio import PresidioMaskingEngine


def _make_engine(
    entities: list[str] | None = None,
    enabled: bool = True,
) -> PresidioMaskingEngine:
    if entities is None:
        entities = ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"]
    config = PresidioConfig(
        enabled=enabled,
        entities=entities,
    )
    return PresidioMaskingEngine(config)


class TestPresidioDetection:
    @pytest.mark.asyncio
    async def test_detect_person(self):
        engine = _make_engine(entities=["PERSON"])
        result = await engine.mask_text("Call John Smith tomorrow", ["PERSON"], "request")
        assert result.has_masked is True
        assert "<PERSON>" in result.masked_text
        assert "John Smith" not in result.masked_text

    @pytest.mark.asyncio
    async def test_detect_email(self):
        engine = _make_engine(entities=["EMAIL_ADDRESS"])
        result = await engine.mask_text(
            "Email me at alice@example.com", ["EMAIL_ADDRESS"], "request"
        )
        assert result.has_masked is True
        assert "<EMAIL_ADDRESS>" in result.masked_text
        assert "alice@example.com" not in result.masked_text

    @pytest.mark.asyncio
    async def test_detect_phone(self):
        engine = _make_engine(entities=["PHONE_NUMBER"])
        result = await engine.mask_text("Call me at 555-123-4567", ["PHONE_NUMBER"], "request")
        assert result.has_masked is True
        assert "<PHONE_NUMBER>" in result.masked_text
        assert "555-123-4567" not in result.masked_text

    @pytest.mark.asyncio
    async def test_detect_credit_card(self):
        engine = _make_engine(entities=["CREDIT_CARD"])
        result = await engine.mask_text(
            "Card number: 4111 1111 1111 1111", ["CREDIT_CARD"], "request"
        )
        assert result.has_masked is True
        assert "<CREDIT_CARD>" in result.masked_text
        assert "4111" not in result.masked_text


class TestPresidioCustomRecognizers:
    @pytest.mark.asyncio
    async def test_detect_api_key(self):
        engine = _make_engine(entities=["API_KEY"])
        result = await engine.mask_text(
            "api_key: AKIAIOSFODNN7EXAMPLE1234567890",
            ["API_KEY"],
            "request",
        )
        assert result.has_masked is True
        assert "<API_KEY>" in result.masked_text

    @pytest.mark.asyncio
    async def test_detect_password(self):
        engine = _make_engine(entities=["PASSWORD"])
        result = await engine.mask_text("password: SuperSecret123!", ["PASSWORD"], "request")
        assert result.has_masked is True
        assert "<PASSWORD>" in result.masked_text
        assert "SuperSecret123!" not in result.masked_text


class TestPresidioMultipleEntities:
    @pytest.mark.asyncio
    async def test_multiple_same_entity(self):
        engine = _make_engine(entities=["PERSON"])
        result = await engine.mask_text(
            "John Smith met Jane Doe at the park",
            ["PERSON"],
            "request",
        )
        assert result.has_masked is True
        # Should mask at least one person
        assert "<PERSON>" in result.masked_text

    @pytest.mark.asyncio
    async def test_mixed_entity_types(self):
        engine = _make_engine(entities=["PERSON", "EMAIL_ADDRESS"])
        result = await engine.mask_text(
            "Contact John Smith at john@example.com",
            ["PERSON", "EMAIL_ADDRESS"],
            "request",
        )
        assert result.has_masked is True
        assert "<PERSON>" in result.masked_text or "<EMAIL_ADDRESS>" in result.masked_text
        # At least one entity detected
        assert len(result.events) >= 1


class TestPresidioMaskingEvents:
    @pytest.mark.asyncio
    async def test_events_populated(self):
        engine = _make_engine(entities=["EMAIL_ADDRESS"])
        result = await engine.mask_text(
            "Email alice@example.com or bob@example.com",
            ["EMAIL_ADDRESS"],
            "request",
        )
        assert result.has_masked is True
        assert len(result.events) >= 1
        email_events = [e for e in result.events if e.entity_type == "EMAIL_ADDRESS"]
        assert len(email_events) == 1
        assert email_events[0].count >= 1
        assert email_events[0].status == "masked"

    @pytest.mark.asyncio
    async def test_events_sorted_by_entity_type(self):
        engine = _make_engine(entities=["PERSON", "EMAIL_ADDRESS"])
        result = await engine.mask_text(
            "Contact Alice at alice@example.com",
            ["PERSON", "EMAIL_ADDRESS"],
            "request",
        )
        if len(result.events) >= 2:
            types = [e.entity_type for e in result.events]
            assert types == sorted(types)


class TestPresidioEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_text(self):
        engine = _make_engine()
        result = await engine.mask_text("", ["PERSON"], "request")
        assert result.masked_text == ""
        assert result.has_masked is False
        assert result.events == []

    @pytest.mark.asyncio
    async def test_no_entities_found(self):
        engine = _make_engine(entities=["CREDIT_CARD"])
        result = await engine.mask_text("The weather is nice today", ["CREDIT_CARD"], "request")
        assert result.has_masked is False
        assert result.masked_text == "The weather is nice today"
        assert result.events == []

    @pytest.mark.asyncio
    async def test_direction_parameter_accepted(self):
        engine = _make_engine(entities=["PERSON"])
        # Both directions should work without error
        result_req = await engine.mask_text("John Smith", ["PERSON"], "request")
        result_resp = await engine.mask_text("John Smith", ["PERSON"], "response")
        assert result_req.has_masked is True
        assert result_resp.has_masked is True


class TestPresidioValidateConfig:
    def test_valid_config(self):
        engine = _make_engine()
        assert engine.validate_config() is True

    def test_empty_entities_raises(self):
        engine = _make_engine(entities=[])
        with pytest.raises(MaskingConfigError) as exc_info:
            engine.validate_config()
        assert "entities" in str(exc_info.value)

    def test_import_error_raises_engine_error(self, monkeypatch):
        """If presidio is not importable, validate_config raises MaskingEngineError."""
        engine = _make_engine()

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if "presidio" in name:
                raise ImportError("no presidio")
            return real_import(name, *args, **kwargs)

        # Reset the lazy-initialized engines so _ensure_initialized runs again
        engine._analyzer = None
        engine._anonymizer = None

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(MaskingEngineError):
            engine.validate_config()
