"""Hook registry with priority ordering and freeze-on-build."""

from __future__ import annotations

from mcp_zero.pipeline.errors import PipelineError
from mcp_zero.pipeline.hooks import LifecycleHook


class HookRegistry:
    """Collects lifecycle hooks and freezes them in priority order via build().

    Priority integers control execution order (lower = earlier):
      0-49   early  (identity / auth)
      50-99  middle (governance)
      100-149 standard (default)
      150+   late   (audit / logging)

    Equal priorities maintain insertion order (stable sort).
    """

    def __init__(self) -> None:
        self._entries: list[tuple[int, int, LifecycleHook]] = []
        self._frozen = False
        self._insert_counter = 0

    def register(self, hook: LifecycleHook, *, priority: int = 100) -> None:
        """Add a hook with the given priority.

        Raises PipelineError if the registry has been frozen via build().
        """
        if self._frozen:
            raise PipelineError("Cannot register hooks after build()")
        self._entries.append((priority, self._insert_counter, hook))
        self._insert_counter += 1

    def build(self) -> HookRegistry:
        """Freeze the registry and sort hooks by priority (stable).

        Returns self for chaining.
        """
        self._entries.sort(key=lambda e: (e[0], e[1]))
        self._frozen = True
        return self

    def get_hooks(self) -> list[LifecycleHook]:
        """Return hooks in priority order.

        Raises PipelineError if build() has not been called.
        """
        if not self._frozen:
            raise PipelineError("Registry must be built before use — call build()")
        return [hook for _, _, hook in self._entries]
