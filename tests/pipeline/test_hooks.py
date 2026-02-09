"""Tests for HookPoint enum and LifecycleHook ABC."""

from abc import ABC

import pytest

from mcp_zero.context import HookContext
from mcp_zero.pipeline.hooks import HookPoint, LifecycleHook


class TestHookPoint:
    def test_values(self):
        assert HookPoint.PRE_VALIDATION == "pre_validation"
        assert HookPoint.POST_VALIDATION == "post_validation"
        assert HookPoint.PRE_MASKING == "pre_masking"
        assert HookPoint.POST_MASKING == "post_masking"
        assert HookPoint.PRE_AUDIT == "pre_audit"
        assert HookPoint.ON_ERROR == "on_error"

    def test_from_string(self):
        assert HookPoint("pre_validation") is HookPoint.PRE_VALIDATION

    def test_count(self):
        assert len(HookPoint) == 6


class TestLifecycleHook:
    def test_is_abstract_base(self):
        """LifecycleHook inherits from ABC as a design marker.

        Because all methods have default implementations (no @abstractmethod),
        direct instantiation is technically possible but discouraged.
        """
        assert issubclass(LifecycleHook, ABC)

    def test_subclass_name(self):
        class MyHook(LifecycleHook):
            pass

        hook = MyHook()
        assert hook.name == "MyHook"

    @pytest.mark.asyncio
    async def test_default_on_pre_validation_is_passthrough(self):
        class NoopHook(LifecycleHook):
            pass

        hook = NoopHook()
        ctx = HookContext()
        result = await hook.on_pre_validation(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_default_on_post_validation_is_passthrough(self):
        class NoopHook(LifecycleHook):
            pass

        hook = NoopHook()
        ctx = HookContext()
        result = await hook.on_post_validation(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_default_on_pre_masking_is_passthrough(self):
        class NoopHook(LifecycleHook):
            pass

        hook = NoopHook()
        ctx = HookContext()
        result = await hook.on_pre_masking(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_default_on_post_masking_is_passthrough(self):
        class NoopHook(LifecycleHook):
            pass

        hook = NoopHook()
        ctx = HookContext()
        result = await hook.on_post_masking(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_default_on_pre_audit_is_passthrough(self):
        class NoopHook(LifecycleHook):
            pass

        hook = NoopHook()
        ctx = HookContext()
        result = await hook.on_pre_audit(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_default_on_error_is_noop(self):
        class NoopHook(LifecycleHook):
            pass

        hook = NoopHook()
        ctx = HookContext()
        result = await hook.on_error(ctx, RuntimeError("test"))
        assert result is None

    @pytest.mark.asyncio
    async def test_override_single_method(self):
        class AuthHook(LifecycleHook):
            async def on_pre_validation(self, ctx: HookContext) -> HookContext:
                return ctx.evolve(extras={"auth": True})

        hook = AuthHook()
        ctx = HookContext()
        result = await hook.on_pre_validation(ctx)
        assert result.extras["auth"] is True
        # Other methods still passthrough
        assert (await hook.on_post_validation(ctx)) is ctx
