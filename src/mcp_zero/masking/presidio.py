"""Presidio-based masking engine implementation."""

from __future__ import annotations

import logging
from collections import Counter

from mcp_zero.governance.config import PresidioConfig
from mcp_zero.masking.engine import MaskingEngine, MaskingEvent, MaskingResult
from mcp_zero.masking.errors import MaskingConfigError, MaskingEngineError

logger = logging.getLogger(__name__)


class PresidioMaskingEngine(MaskingEngine):
    """Masking engine backed by Microsoft Presidio.

    Lazy-initialises the Presidio analyzer and anonymizer on first use so that
    the (relatively heavy) NLP model load only happens when masking is actually
    invoked.

    Args:
        config: Presidio configuration from the policy file.
    """

    def __init__(self, config: PresidioConfig) -> None:
        self._config = config
        self._analyzer: object | None = None
        self._anonymizer: object | None = None

    def _ensure_initialized(self) -> None:
        """Lazy-init analyzer and anonymizer engines."""
        if self._analyzer is not None:
            return

        try:
            from presidio_analyzer import (
                AnalyzerEngine,
                Pattern,
                PatternRecognizer,
            )
            from presidio_anonymizer import AnonymizerEngine
        except ImportError as exc:
            raise MaskingEngineError(
                "presidio-analyzer and presidio-anonymizer must be installed",
                engine="presidio",
            ) from exc

        try:
            analyzer = AnalyzerEngine()

            # Register custom recognizers for API keys and passwords
            api_key_recognizer = PatternRecognizer(
                supported_entity="API_KEY",
                patterns=[
                    Pattern(
                        name="api_key_generic",
                        regex=r"(?i)(?:api[_-]?key|apikey|access[_-]?key)\s*[:=]\s*['\"]?([A-Za-z0-9\-_]{20,})['\"]?",
                        score=0.8,
                    ),
                    Pattern(
                        name="bearer_token",
                        regex=r"(?i)bearer\s+[A-Za-z0-9\-_.~+/]+=*",
                        score=0.7,
                    ),
                ],
            )

            password_recognizer = PatternRecognizer(
                supported_entity="PASSWORD",
                patterns=[
                    Pattern(
                        name="password_field",
                        regex=r"(?i)(?:password|passwd|pwd)\s*[:=]\s*['\"]?(\S+)['\"]?",
                        score=0.8,
                    ),
                ],
            )

            analyzer.registry.add_recognizer(api_key_recognizer)
            analyzer.registry.add_recognizer(password_recognizer)

            self._analyzer = analyzer
            self._anonymizer = AnonymizerEngine()
        except Exception as exc:
            raise MaskingEngineError(
                f"Failed to initialise Presidio engines: {exc}",
                engine="presidio",
            ) from exc

    async def mask_text(self, text: str, entities: list[str], direction: str) -> MaskingResult:
        """Detect and mask entities using Presidio.

        Args:
            text: Input text to scan and mask.
            entities: Entity types to detect.
            direction: "request" or "response".

        Returns:
            MaskingResult with masked text and per-entity events.
        """
        if not text:
            return MaskingResult(masked_text=text, events=[], has_masked=False)

        self._ensure_initialized()

        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
        from presidio_anonymizer.entities import OperatorConfig

        analyzer: AnalyzerEngine = self._analyzer  # type: ignore[assignment]
        anonymizer: AnonymizerEngine = self._anonymizer  # type: ignore[assignment]

        # Analyze text for entities
        results = analyzer.analyze(
            text=text,
            entities=entities,
            language="en",
        )

        if not results:
            return MaskingResult(masked_text=text, events=[], has_masked=False)

        # Count detections per entity type
        counts: Counter[str] = Counter()
        for r in results:
            counts[r.entity_type] += 1

        # Anonymize — replace with <ENTITY_TYPE> placeholders
        operators = {
            "DEFAULT": OperatorConfig("replace", {"new_value": "<MASKED>"}),
        }
        for entity_type in counts:
            operators[entity_type] = OperatorConfig("replace", {"new_value": f"<{entity_type}>"})

        anonymized = anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators=operators,
        )

        events = [
            MaskingEvent(entity_type=et, count=c, status="masked")
            for et, c in sorted(counts.items())
        ]

        return MaskingResult(
            masked_text=anonymized.text,
            events=events,
            has_masked=True,
        )

    def validate_config(self) -> bool:
        """Check that Presidio packages are importable and engines initialise.

        Returns:
            True if everything is ready.

        Raises:
            MaskingConfigError: If entity list is empty.
            MaskingEngineError: If Presidio cannot initialise.
        """
        if not self._config.entities:
            raise MaskingConfigError(
                "presidio.entities must not be empty when enabled",
                field="masking.presidio.entities",
            )

        self._ensure_initialized()
        return True
