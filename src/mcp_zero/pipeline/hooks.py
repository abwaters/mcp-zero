"""Hook points and lifecycle hook abstract base class."""

from __future__ import annotations

from abc import ABC
from enum import StrEnum

from mcp_zero.context import HookContext


class HookPoint(StrEnum):
    """Ordered points in the request/response lifecycle."""

    PRE_VALIDATION = "pre_validation"
    POST_VALIDATION = "post_validation"
    PRE_MASKING = "pre_masking"
    POST_MASKING = "post_masking"
    PRE_AUDIT = "pre_audit"
    ON_ERROR = "on_error"


class LifecycleHook(ABC):
    """Base class for lifecycle hooks.

    Subclasses override only the hook points they need.
    All methods have default no-op implementations.
    """

    @property
    def name(self) -> str:
        """Return the hook class name for logging and diagnostics."""
        return self.__class__.__name__

    async def on_pre_validation(self, ctx: HookContext) -> HookContext:
        return ctx

    async def on_post_validation(self, ctx: HookContext) -> HookContext:
        return ctx

    async def on_pre_masking(self, ctx: HookContext) -> HookContext:
        return ctx

    async def on_post_masking(self, ctx: HookContext) -> HookContext:
        return ctx

    async def on_pre_audit(self, ctx: HookContext) -> HookContext:
        return ctx

    async def on_error(self, ctx: HookContext, error: Exception) -> None:
        pass
