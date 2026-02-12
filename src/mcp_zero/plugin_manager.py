"""Plugin manager — discovery, loading, and lifecycle management."""

from __future__ import annotations

import importlib.metadata
import logging

from mcp_zero.governance.config import PluginDeclaration
from mcp_zero.pipeline.registry import HookRegistry
from mcp_zero.plugin import Plugin

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "mcp_zero.plugins"


class PluginLoadError(Exception):
    """Raised when a plugin cannot be discovered, loaded, or configured."""


class PluginManager:
    """Discovers, loads, and manages the lifecycle of mcp-zero plugins.

    Plugins are discovered from the ``mcp_zero.plugins`` entry-point group
    at construction time.  They are activated only when explicitly listed in
    the policy file's ``plugins:`` section.
    """

    def __init__(self) -> None:
        self._available: dict[str, importlib.metadata.EntryPoint] = {}
        self._plugins: list[Plugin] = []
        self._discover()

    def _discover(self) -> None:
        """Scan installed entry points for the ``mcp_zero.plugins`` group."""
        eps = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
        for ep in eps:
            self._available[ep.name] = ep
        if self._available:
            logger.info(
                "Discovered %d plugin entry point(s): %s",
                len(self._available),
                ", ".join(sorted(self._available)),
            )

    def available_plugins(self) -> list[str]:
        """Return sorted list of discovered entry-point names."""
        return sorted(self._available)

    def load_plugins(self, declarations: list[PluginDeclaration], registry: HookRegistry) -> None:
        """Load, configure, and register plugins from policy declarations.

        Args:
            declarations: Plugin declarations from the policy file.
            registry: Hook registry for plugins to register their hooks.

        Raises:
            PluginLoadError: If any plugin fails to load or configure.
        """
        for decl in declarations:
            plugin = self._load_one(decl.name, decl.package, decl.config)
            plugin.register(registry)
            self._plugins.append(plugin)
            logger.info("Plugin '%s' loaded and registered", decl.name)

    def _load_one(self, name: str, package: str, config: dict) -> Plugin:
        """Resolve entry point, instantiate, validate, and configure a plugin."""
        ep_name = package or name
        if ep_name not in self._available:
            raise PluginLoadError(
                f"Plugin '{name}' (package '{ep_name}') not found in "
                f"'{ENTRY_POINT_GROUP}' entry points. "
                f"Available: {', '.join(sorted(self._available)) or '(none)'}"
            )

        ep = self._available[ep_name]
        try:
            factory = ep.load()
        except Exception as exc:
            raise PluginLoadError(f"Failed to load entry point for plugin '{name}': {exc}") from exc

        try:
            plugin = factory()
        except Exception as exc:
            raise PluginLoadError(f"Factory for plugin '{name}' raised: {exc}") from exc

        if not isinstance(plugin, Plugin):
            raise PluginLoadError(
                f"Plugin '{name}' does not satisfy the Plugin protocol "
                f"(got {type(plugin).__name__})"
            )

        try:
            plugin.configure(config)
        except Exception as exc:
            raise PluginLoadError(f"Plugin '{name}' configure() failed: {exc}") from exc

        return plugin

    def teardown_all(self) -> None:
        """Tear down all loaded plugins in reverse order (best-effort)."""
        for plugin in reversed(self._plugins):
            try:
                plugin.teardown()
                logger.info("Plugin '%s' torn down", plugin.name)
            except Exception:
                logger.exception("Error tearing down plugin '%s'", plugin.name)

    @property
    def loaded_plugins(self) -> list[Plugin]:
        """Return list of loaded plugin instances."""
        return list(self._plugins)
