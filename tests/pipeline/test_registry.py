"""Tests for HookRegistry ordering and freeze semantics."""

import pytest

from mcp_zero.pipeline.errors import PipelineError
from mcp_zero.pipeline.hooks import LifecycleHook
from mcp_zero.pipeline.registry import HookRegistry


class _StubHook(LifecycleHook):
    """Concrete hook for testing."""

    def __init__(self, label: str = "") -> None:
        self._label = label

    @property
    def name(self) -> str:
        return self._label or super().name


class TestHookRegistry:
    def test_build_returns_self(self):
        reg = HookRegistry()
        assert reg.build() is reg

    def test_get_hooks_before_build_raises(self):
        reg = HookRegistry()
        reg.register(_StubHook("a"))
        with pytest.raises(PipelineError, match="must be built"):
            reg.get_hooks()

    def test_register_after_build_raises(self):
        reg = HookRegistry()
        reg.build()
        with pytest.raises(PipelineError, match="Cannot register"):
            reg.register(_StubHook("a"))

    def test_empty_registry(self):
        reg = HookRegistry()
        reg.build()
        assert reg.get_hooks() == []

    def test_single_hook(self):
        reg = HookRegistry()
        hook = _StubHook("only")
        reg.register(hook)
        reg.build()
        assert reg.get_hooks() == [hook]

    def test_priority_ordering(self):
        reg = HookRegistry()
        late = _StubHook("late")
        early = _StubHook("early")
        middle = _StubHook("middle")
        reg.register(late, priority=200)
        reg.register(early, priority=10)
        reg.register(middle, priority=100)
        reg.build()
        names = [h.name for h in reg.get_hooks()]
        assert names == ["early", "middle", "late"]

    def test_stable_sort_equal_priority(self):
        reg = HookRegistry()
        a = _StubHook("a")
        b = _StubHook("b")
        c = _StubHook("c")
        reg.register(a, priority=100)
        reg.register(b, priority=100)
        reg.register(c, priority=100)
        reg.build()
        names = [h.name for h in reg.get_hooks()]
        assert names == ["a", "b", "c"]

    def test_mixed_priorities_and_insertion_order(self):
        reg = HookRegistry()
        hooks = [
            ("audit", 150),
            ("auth", 10),
            ("governance", 50),
            ("masking", 100),
            ("logging", 150),
        ]
        for label, prio in hooks:
            reg.register(_StubHook(label), priority=prio)
        reg.build()
        names = [h.name for h in reg.get_hooks()]
        assert names == ["auth", "governance", "masking", "audit", "logging"]

    def test_default_priority_is_100(self):
        reg = HookRegistry()
        early = _StubHook("early")
        default = _StubHook("default")
        reg.register(early, priority=50)
        reg.register(default)  # default priority=100
        reg.build()
        names = [h.name for h in reg.get_hooks()]
        assert names == ["early", "default"]
