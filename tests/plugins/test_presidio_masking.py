"""Tests for the Presidio masking plugin."""

import pytest

from mcp_zero.pipeline.registry import HookRegistry
from mcp_zero.plugin import Plugin
from mcp_zero.plugins.presidio_masking import PresidioMaskingPlugin


class TestPresidioMaskingPlugin:
    def test_satisfies_plugin_protocol(self):
        plugin = PresidioMaskingPlugin()
        assert isinstance(plugin, Plugin)

    def test_name(self):
        plugin = PresidioMaskingPlugin()
        assert plugin.name == "presidio-masking"

    def test_configure_stores_entities(self):
        plugin = PresidioMaskingPlugin()
        plugin.configure({"entities": ["PERSON", "EMAIL_ADDRESS"]})
        assert plugin._entities == ["PERSON", "EMAIL_ADDRESS"]

    def test_configure_empty_entities_raises(self):
        plugin = PresidioMaskingPlugin()
        with pytest.raises(ValueError, match="non-empty 'entities' list"):
            plugin.configure({"entities": []})

    def test_configure_missing_entities_raises(self):
        plugin = PresidioMaskingPlugin()
        with pytest.raises(ValueError, match="non-empty 'entities' list"):
            plugin.configure({})

    def test_configure_custom_priority(self):
        plugin = PresidioMaskingPlugin()
        plugin.configure({"entities": ["PERSON"], "priority": 90})
        assert plugin._priority == 90

    def test_register_adds_hook_to_registry(self):
        plugin = PresidioMaskingPlugin()
        plugin.configure({"entities": ["PERSON", "EMAIL_ADDRESS"]})
        registry = HookRegistry()
        plugin.register(registry)
        # Registry should have one entry (the MaskingHook)
        registry.build()
        hooks = registry.get_hooks()
        assert len(hooks) == 1
        from mcp_zero.masking.hook import MaskingHook

        assert isinstance(hooks[0], MaskingHook)


class TestPresidioMaskingPluginEntryPoint:
    def test_discoverable_via_entry_points(self):
        """The plugin is registered as an entry point and discoverable."""
        from mcp_zero.plugin_manager import PluginManager

        mgr = PluginManager()
        assert "presidio-masking" in mgr.available_plugins()

    def test_end_to_end_load(self):
        """Load the plugin through PluginManager using the entry point."""
        from mcp_zero.governance.config import PluginDeclaration
        from mcp_zero.plugin_manager import PluginManager

        mgr = PluginManager()
        registry = HookRegistry()
        decl = PluginDeclaration(
            name="presidio-masking",
            package="presidio-masking",
            config={"entities": ["PERSON", "EMAIL_ADDRESS"]},
        )
        mgr.load_plugins([decl], registry)
        assert len(mgr.loaded_plugins) == 1
        assert mgr.loaded_plugins[0].name == "presidio-masking"

        # Verify the hook was registered
        registry.build()
        hooks = registry.get_hooks()
        assert len(hooks) == 1
