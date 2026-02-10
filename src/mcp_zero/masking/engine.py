"""Abstract masking engine interface and result types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MaskingEvent:
    """A single masking event for audit/logging.

    Args:
        entity_type: The type of entity detected (e.g. PERSON, EMAIL_ADDRESS).
        count: Number of occurrences masked.
        status: Outcome — "masked" or "failed".
    """

    entity_type: str
    count: int
    status: str  # "masked" | "failed"


@dataclass(frozen=True)
class MaskingResult:
    """Result of a masking operation.

    Args:
        masked_text: The text after masking.
        events: Per-entity-type masking events.
        has_masked: Whether any masking was applied.
    """

    masked_text: str
    events: list[MaskingEvent] = field(default_factory=list)
    has_masked: bool = False


class MaskingEngine(ABC):
    """Abstract base class for masking engines.

    Implementations detect and replace sensitive data in text.
    """

    @abstractmethod
    async def mask_text(
        self, text: str, entities: list[str], direction: str
    ) -> MaskingResult:
        """Detect and mask sensitive entities in *text*.

        Args:
            text: The input text to scan.
            entities: Entity types to detect (e.g. ["PERSON", "EMAIL_ADDRESS"]).
            direction: "request" or "response" — allows engines to vary behaviour.

        Returns:
            A MaskingResult with the masked text and per-entity events.
        """

    @abstractmethod
    def validate_config(self) -> bool:
        """Check that the engine is properly configured and operational.

        Returns:
            True if the engine is ready.

        Raises:
            MaskingConfigError: If the configuration is invalid.
            MaskingEngineError: If the engine cannot initialise.
        """
