"""Tests for PipelineResult."""

import pytest

from mcp_zero.context import HookContext
from mcp_zero.pipeline.result import PipelineResult


class TestPipelineResult:
    def test_success_result(self):
        ctx = HookContext()
        result = PipelineResult(context=ctx, success=True, duration_ms=1.5)
        assert result.success is True
        assert result.error is None
        assert result.duration_ms == 1.5
        assert result.hooks_executed == []

    def test_failure_result(self):
        ctx = HookContext()
        err = RuntimeError("boom")
        result = PipelineResult(
            context=ctx,
            success=False,
            error=err,
            hooks_executed=["AuthHook.on_pre_validation"],
        )
        assert result.success is False
        assert result.error is err
        assert result.hooks_executed == ["AuthHook.on_pre_validation"]

    def test_frozen(self):
        ctx = HookContext()
        result = PipelineResult(context=ctx, success=True)
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]

    def test_defaults(self):
        ctx = HookContext()
        result = PipelineResult(context=ctx, success=True)
        assert result.error is None
        assert result.duration_ms == 0.0
        assert result.hooks_executed == []
