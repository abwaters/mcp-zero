"""Plugin protocol and base class for mcp-zero plugins."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from mcp_zero.pipeline.registry import HookRegistry


@runtime_checkable
class Plugin(Protocol):
    """Protocol that all mcp-zero plugins must satisfy.

    Plugins are discovered via ``mcp_zero.plugins`` entry points and activated
    through the policy file's ``plugins:`` section.
    """

    @property
    def name(self) -> str: ...

    def configure(self, config: dict[str, Any]) -> None: ...

    def register(self, registry: HookRegistry) -> None: ...

    def teardown(self) -> None: ...


class BasePlugin:
    """Convenience base class with no-op defaults for all Plugin methods.

    Subclasses only need to override the methods they care about.
    The ``name`` property defaults to the class name.
    """

    @property
    def name(self) -> str:
        return type(self).__name__

    def configure(self, config: dict[str, Any]) -> None:
        pass

    def register(self, registry: HookRegistry) -> None:
        pass

    def teardown(self) -> None:
        pass
