"""Masking error hierarchy."""

from __future__ import annotations


class MaskingError(Exception):
    """Base error for all masking operations."""


class MaskingEngineError(MaskingError):
    """Engine initialization or runtime failure.

    Args:
        message: Error description.
        engine: Name of the engine that failed.
    """

    def __init__(self, message: str, *, engine: str = "") -> None:
        self.engine = engine
        super().__init__(message)


class MaskingConfigError(MaskingError):
    """Configuration validation failure.

    Args:
        message: Error description.
        field: The config field that failed validation.
    """

    def __init__(self, message: str, *, field: str = "") -> None:
        self.field = field
        super().__init__(message)
