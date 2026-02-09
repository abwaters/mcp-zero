"""Tests for Pipeline orchestration, chaining, short-circuit, and error handling."""

import pytest

from mcp_zero.context import HookContext, PolicyDecision
from mcp_zero.pipeline.errors import HookError, ShortCircuitError
from mcp_zero.pipeline.hooks import HookPoint, LifecycleHook
from mcp_zero.pipeline.pipeline import Pipeline
from mcp_zero.pipeline.registry import HookRegistry

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _TrackingHook(LifecycleHook):
    """Records which hook points were called and in what order."""

    def __init__(self, label: str = "") -> None:
        self._label = label
        self.calls: list[str] = []

    @property
    def name(self) -> str:
        return self._label or super().name

    async def on_pre_validation(self, ctx: HookContext) -> HookContext:
        self.calls.append("pre_validation")
        return ctx

    async def on_post_validation(self, ctx: HookContext) -> HookContext:
        self.calls.append("post_validation")
        return ctx

    async def on_pre_masking(self, ctx: HookContext) -> HookContext:
        self.calls.append("pre_masking")
        return ctx

    async def on_post_masking(self, ctx: HookContext) -> HookContext:
        self.calls.append("post_masking")
        return ctx

    async def on_pre_audit(self, ctx: HookContext) -> HookContext:
        self.calls.append("pre_audit")
        return ctx

    async def on_error(self, ctx: HookContext, error: Exception) -> None:
        self.calls.append("on_error")


def _build_pipeline(*hooks: tuple[LifecycleHook, int]) -> Pipeline:
    reg = HookRegistry()
    for hook, priority in hooks:
        reg.register(hook, priority=priority)
    reg.build()
    return Pipeline(reg)


# ---------------------------------------------------------------------------
# Execution order tests
# ---------------------------------------------------------------------------


class TestPipelineExecution:
    @pytest.mark.asyncio
    async def test_all_hook_points_fire_in_order(self):
        hook = _TrackingHook("tracker")
        pipeline = _build_pipeline((hook, 100))
        ctx = HookContext()
        result = await pipeline.execute(ctx)
        assert result.success is True
        assert hook.calls == [
            "pre_validation",
            "post_validation",
            "pre_masking",
            "post_masking",
            "pre_audit",
        ]

    @pytest.mark.asyncio
    async def test_empty_pipeline_succeeds(self):
        reg = HookRegistry()
        reg.build()
        pipeline = Pipeline(reg)
        result = await pipeline.execute(HookContext())
        assert result.success is True
        assert result.hooks_executed == []

    @pytest.mark.asyncio
    async def test_duration_is_positive(self):
        reg = HookRegistry()
        reg.build()
        pipeline = Pipeline(reg)
        result = await pipeline.execute(HookContext())
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_hooks_executed_list(self):
        hook = _TrackingHook("H1")
        pipeline = _build_pipeline((hook, 100))
        result = await pipeline.execute(HookContext())
        assert "H1.on_pre_validation" in result.hooks_executed
        assert "H1.on_pre_audit" in result.hooks_executed
        assert len(result.hooks_executed) == 5

    @pytest.mark.asyncio
    async def test_hook_execution_order_multiple_hooks(self):
        """Multiple hooks execute in priority order at each hook point."""
        order: list[str] = []

        class OrderHook(LifecycleHook):
            def __init__(self, label: str) -> None:
                self._label = label

            @property
            def name(self) -> str:
                return self._label

            async def on_pre_validation(self, ctx: HookContext) -> HookContext:
                order.append(f"{self._label}.pre_validation")
                return ctx

            async def on_post_validation(self, ctx: HookContext) -> HookContext:
                order.append(f"{self._label}.post_validation")
                return ctx

        early = OrderHook("early")
        late = OrderHook("late")
        pipeline = _build_pipeline((late, 200), (early, 10))
        await pipeline.execute(HookContext())
        assert order == [
            "early.pre_validation",
            "late.pre_validation",
            "early.post_validation",
            "late.post_validation",
        ]


# ---------------------------------------------------------------------------
# Context chaining tests
# ---------------------------------------------------------------------------


class TestPipelineChaining:
    @pytest.mark.asyncio
    async def test_context_flows_through_hooks(self):
        """Each hook receives the context returned by the previous hook."""

        class AddTagHook(LifecycleHook):
            def __init__(self, tag: str) -> None:
                self._tag = tag

            async def on_pre_validation(self, ctx: HookContext) -> HookContext:
                tags = list(ctx.extras.get("tags", []))
                tags.append(self._tag)
                return ctx.evolve(extras={**ctx.extras, "tags": tags})

        h1 = AddTagHook("first")
        h2 = AddTagHook("second")
        pipeline = _build_pipeline((h1, 10), (h2, 20))
        result = await pipeline.execute(HookContext())
        assert result.context.extras["tags"] == ["first", "second"]

    @pytest.mark.asyncio
    async def test_context_flows_across_hook_points(self):
        """Context modifications persist across different hook points."""

        class ModifyHook(LifecycleHook):
            async def on_pre_validation(self, ctx: HookContext) -> HookContext:
                return ctx.evolve(server_name="set-in-pre-validation")

            async def on_pre_audit(self, ctx: HookContext) -> HookContext:
                return ctx.evolve(
                    extras={"server_from_earlier": ctx.server_name},
                )

        hook = ModifyHook()
        pipeline = _build_pipeline((hook, 100))
        result = await pipeline.execute(HookContext())
        assert result.context.server_name == "set-in-pre-validation"
        assert result.context.extras["server_from_earlier"] == "set-in-pre-validation"


# ---------------------------------------------------------------------------
# Short-circuit tests
# ---------------------------------------------------------------------------


class TestPipelineShortCircuit:
    @pytest.mark.asyncio
    async def test_short_circuit_stops_pipeline(self):
        class DenyHook(LifecycleHook):
            async def on_post_validation(self, ctx: HookContext) -> HookContext:
                raise ShortCircuitError("blocked by policy", deny=True)

        tracker = _TrackingHook("tracker")
        deny = DenyHook()
        pipeline = _build_pipeline((deny, 50), (tracker, 100))
        result = await pipeline.execute(HookContext())
        assert result.success is False
        assert result.context.short_circuited is True
        assert result.context.short_circuit_reason == "blocked by policy"
        assert result.context.policy_decision == PolicyDecision.DENY
        # Tracker should have run pre_validation (before the deny hook point)
        # but not pre_masking or later (those come after post_validation)
        assert "pre_masking" not in tracker.calls

    @pytest.mark.asyncio
    async def test_short_circuit_without_deny(self):
        class StopHook(LifecycleHook):
            async def on_pre_masking(self, ctx: HookContext) -> HookContext:
                raise ShortCircuitError("early exit")

        hook = StopHook()
        pipeline = _build_pipeline((hook, 100))
        result = await pipeline.execute(HookContext())
        assert result.success is False
        assert result.context.short_circuited is True
        assert result.context.policy_decision == PolicyDecision.PENDING  # not changed

    @pytest.mark.asyncio
    async def test_short_circuit_error_in_result(self):
        class StopHook(LifecycleHook):
            async def on_pre_validation(self, ctx: HookContext) -> HookContext:
                raise ShortCircuitError("nope")

        hook = StopHook()
        pipeline = _build_pipeline((hook, 100))
        result = await pipeline.execute(HookContext())
        assert isinstance(result.error, ShortCircuitError)


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestPipelineErrors:
    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped_in_hook_error(self):
        class BrokenHook(LifecycleHook):
            async def on_pre_validation(self, ctx: HookContext) -> HookContext:
                raise ValueError("something went wrong")

        hook = BrokenHook()
        pipeline = _build_pipeline((hook, 100))
        result = await pipeline.execute(HookContext())
        assert result.success is False
        assert isinstance(result.error, HookError)
        assert result.error.hook_name == "BrokenHook"
        assert result.error.hook_point == "pre_validation"

    @pytest.mark.asyncio
    async def test_error_hooks_fire_on_failure(self):
        error_calls: list[tuple[str, Exception]] = []

        class ErrorObserver(LifecycleHook):
            def __init__(self, label: str) -> None:
                self._label = label

            @property
            def name(self) -> str:
                return self._label

            async def on_error(self, ctx: HookContext, error: Exception) -> None:
                error_calls.append((self._label, error))

        class BrokenHook(ErrorObserver):
            async def on_pre_validation(self, ctx: HookContext) -> HookContext:
                raise RuntimeError("fail")

        broken = BrokenHook("broken")
        observer = ErrorObserver("observer")
        pipeline = _build_pipeline((broken, 50), (observer, 100))
        await pipeline.execute(HookContext())
        # Both hooks receive on_error
        assert len(error_calls) == 2
        assert error_calls[0][0] == "broken"
        assert error_calls[1][0] == "observer"
        assert all(isinstance(e, HookError) for _, e in error_calls)

    @pytest.mark.asyncio
    async def test_error_hooks_fire_on_short_circuit(self):
        error_calls: list[tuple[str, Exception]] = []

        class ErrorObserver(LifecycleHook):
            def __init__(self, label: str) -> None:
                self._label = label

            @property
            def name(self) -> str:
                return self._label

            async def on_error(self, ctx: HookContext, error: Exception) -> None:
                error_calls.append((self._label, error))

        class DenyHook(ErrorObserver):
            async def on_pre_validation(self, ctx: HookContext) -> HookContext:
                raise ShortCircuitError("denied")

        deny = DenyHook("deny")
        observer = ErrorObserver("observer")
        pipeline = _build_pipeline((deny, 50), (observer, 100))
        await pipeline.execute(HookContext())
        # Both hooks receive on_error
        assert len(error_calls) == 2
        assert error_calls[0][0] == "deny"
        assert error_calls[1][0] == "observer"
        assert all(isinstance(e, ShortCircuitError) for _, e in error_calls)

    @pytest.mark.asyncio
    async def test_error_hook_exception_is_suppressed(self):
        """Error hooks that raise should not break the pipeline."""

        class BadErrorHook(LifecycleHook):
            async def on_error(self, ctx: HookContext, error: Exception) -> None:
                raise RuntimeError("error hook blew up")

        class BrokenHook(LifecycleHook):
            async def on_pre_validation(self, ctx: HookContext) -> HookContext:
                raise ValueError("original error")

        bad = BadErrorHook()
        broken = BrokenHook()
        pipeline = _build_pipeline((broken, 50), (bad, 100))
        result = await pipeline.execute(HookContext())
        # Pipeline still returns a result — error hook exception was suppressed
        assert result.success is False
        assert isinstance(result.error, HookError)


# ---------------------------------------------------------------------------
# execute_hook_point (public single-point API)
# ---------------------------------------------------------------------------


class TestExecuteHookPoint:
    @pytest.mark.asyncio
    async def test_single_hook_point(self):
        class TagHook(LifecycleHook):
            async def on_pre_validation(self, ctx: HookContext) -> HookContext:
                return ctx.evolve(extras={"tagged": True})

        hook = TagHook()
        pipeline = _build_pipeline((hook, 100))
        ctx = HookContext()
        result = await pipeline.execute_hook_point(HookPoint.PRE_VALIDATION, ctx)
        assert result.extras["tagged"] is True


# ---------------------------------------------------------------------------
# Transport-agnostic verification
# ---------------------------------------------------------------------------


class TestTransportAgnostic:
    def test_no_transport_imports(self):
        """Pipeline module should have zero transport imports."""
        import mcp_zero.pipeline.pipeline as mod

        source = open(mod.__file__).read()
        assert "transport" not in source
