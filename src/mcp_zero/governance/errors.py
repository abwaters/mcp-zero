"""Governance error hierarchy."""

from __future__ import annotations


class GovernanceError(Exception):
    """Base error for all governance operations."""


class PolicyFileError(GovernanceError):
    """Failed to read or parse a policy file.

    Args:
        message: Error description.
        file_path: Path to the policy file that failed.
    """

    def __init__(self, message: str, *, file_path: str = "") -> None:
        self.file_path = file_path
        super().__init__(message)


class PolicyValidationError(GovernanceError):
    """Policy schema or type validation failed.

    Args:
        message: Error description.
        field: The field that failed validation.
    """

    def __init__(self, message: str, *, field: str = "") -> None:
        self.field = field
        super().__init__(message)


class PolicyReferenceError(PolicyValidationError):
    """Cross-reference between policy sections is invalid.

    Args:
        message: Error description.
        field: The field containing the invalid reference.
        reference: The referenced value that could not be resolved.
    """

    def __init__(self, message: str, *, field: str = "", reference: str = "") -> None:
        self.reference = reference
        super().__init__(message, field=field)
