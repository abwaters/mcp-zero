"""Pipeline error hierarchy."""

from __future__ import annotations


class PipelineError(Exception):
    """Base error for all pipeline operations."""


class ShortCircuitError(PipelineError):
    """Raised by a hook to halt pipeline execution early.

    Args:
        reason: Human-readable explanation for the short-circuit.
        deny: If True, the short-circuit represents a policy denial.
    """

    def __init__(self, reason: str, *, deny: bool = False) -> None:
        self.reason = reason
        self.deny = deny
        super().__init__(reason)


class HookError(PipelineError):
    """Wraps unexpected exceptions raised inside a hook.

    Args:
        message: Error description.
        hook_name: Name of the hook that failed.
        hook_point: Hook point where the failure occurred.
    """

    def __init__(self, message: str, *, hook_name: str = "", hook_point: str = "") -> None:
        self.hook_name = hook_name
        self.hook_point = hook_point
        super().__init__(message)
