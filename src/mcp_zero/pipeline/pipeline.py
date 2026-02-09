"""Pipeline orchestrator — runs hooks through the request/response lifecycle."""

from __future__ import annotations

import time

from mcp_zero.context import HookContext, PolicyDecision
from mcp_zero.pipeline.errors import HookError, ShortCircuitError
from mcp_zero.pipeline.hooks import HookPoint
from mcp_zero.pipeline.registry import HookRegistry
from mcp_zero.pipeline.result import PipelineResult

# Mapping from HookPoint to the LifecycleHook method name.
_HOOK_METHOD: dict[HookPoint, str] = {
    HookPoint.PRE_VALIDATION: "on_pre_validation",
    HookPoint.POST_VALIDATION: "on_post_validation",
    HookPoint.PRE_MASKING: "on_pre_masking",
    HookPoint.POST_MASKING: "on_post_masking",
    HookPoint.PRE_AUDIT: "on_pre_audit",
}


class Pipeline:
    """Executes registered hooks through an ordered sequence of hook points.

    On ShortCircuitError the pipeline stops, marks the context, fires on_error
    hooks, and returns a failure result.  Unexpected exceptions are wrapped in
    HookError and handled the same way.  Error hooks never break the pipeline.
    """

    HOOK_SEQUENCE: list[HookPoint] = [
        HookPoint.PRE_VALIDATION,
        HookPoint.POST_VALIDATION,
        HookPoint.PRE_MASKING,
        HookPoint.POST_MASKING,
        HookPoint.PRE_AUDIT,
    ]

    def __init__(self, registry: HookRegistry) -> None:
        self._hooks = registry.get_hooks()

    async def execute(self, ctx: HookContext) -> PipelineResult:
        """Run *ctx* through every hook point in sequence."""
        start = time.monotonic()
        hooks_executed: list[str] = []

        try:
            for point in self.HOOK_SEQUENCE:
                ctx = await self._execute_hook_point(point, ctx, hooks_executed)
        except ShortCircuitError as exc:
            ctx = ctx.evolve(
                short_circuited=True,
                short_circuit_reason=exc.reason,
                **({"policy_decision": PolicyDecision.DENY} if exc.deny else {}),
            )
            await self._fire_error_hooks(ctx, exc)
            return PipelineResult(
                context=ctx,
                success=False,
                error=exc,
                duration_ms=(time.monotonic() - start) * 1000,
                hooks_executed=hooks_executed,
            )
        except HookError as exc:
            await self._fire_error_hooks(ctx, exc)
            return PipelineResult(
                context=ctx,
                success=False,
                error=exc,
                duration_ms=(time.monotonic() - start) * 1000,
                hooks_executed=hooks_executed,
            )

        return PipelineResult(
            context=ctx,
            success=True,
            duration_ms=(time.monotonic() - start) * 1000,
            hooks_executed=hooks_executed,
        )

    async def execute_hook_point(self, point: HookPoint, ctx: HookContext) -> HookContext:
        """Run a single hook point across all hooks (public API)."""
        return await self._execute_hook_point(point, ctx, [])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _execute_hook_point(
        self,
        point: HookPoint,
        ctx: HookContext,
        hooks_executed: list[str],
    ) -> HookContext:
        method_name = _HOOK_METHOD[point]
        for hook in self._hooks:
            try:
                ctx = await getattr(hook, method_name)(ctx)
                hooks_executed.append(f"{hook.name}.{method_name}")
            except ShortCircuitError:
                hooks_executed.append(f"{hook.name}.{method_name}")
                raise
            except Exception as exc:
                hooks_executed.append(f"{hook.name}.{method_name}")
                raise HookError(
                    str(exc),
                    hook_name=hook.name,
                    hook_point=point.value,
                ) from exc
        return ctx

    async def _fire_error_hooks(self, ctx: HookContext, error: Exception) -> None:
        """Call on_error on every hook; suppress any exceptions."""
        for hook in self._hooks:
            try:
                await hook.on_error(ctx, error)
            except Exception:  # noqa: BLE001
                pass
