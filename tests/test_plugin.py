"""Tests for Plugin protocol and BasePlugin."""

from mcp_zero.events.bus import EventBus
from mcp_zero.pipeline.registry import HookRegistry
from mcp_zero.plugin import BasePlugin, Plugin


class TestPluginProtocol:
    def test_base_plugin_satisfies_protocol(self):
        plugin = BasePlugin()
        assert isinstance(plugin, Plugin)

    def test_plain_class_satisfies_protocol(self):
        class MyPlugin:
            @property
            def name(self) -> str:
                return "my-plugin"

            def configure(self, config):
                pass

            def register(self, registry):
                pass

            def teardown(self):
                pass

        assert isinstance(MyPlugin(), Plugin)

    def test_missing_method_fails_protocol(self):
        class Incomplete:
            @property
            def name(self) -> str:
                return "incomplete"

            def configure(self, config):
                pass

            # missing register and teardown

        assert not isinstance(Incomplete(), Plugin)

    def test_missing_name_property_fails_protocol(self):
        class NoName:
            def configure(self, config):
                pass

            def register(self, registry):
                pass

            def teardown(self):
                pass

        assert not isinstance(NoName(), Plugin)


class TestBasePlugin:
    def test_name_defaults_to_class_name(self):
        plugin = BasePlugin()
        assert plugin.name == "BasePlugin"

    def test_subclass_name_defaults_to_subclass_name(self):
        class MyCustomPlugin(BasePlugin):
            pass

        plugin = MyCustomPlugin()
        assert plugin.name == "MyCustomPlugin"

    def test_configure_is_noop(self):
        plugin = BasePlugin()
        plugin.configure({"key": "value"})  # should not raise

    def test_register_is_noop(self):
        plugin = BasePlugin()
        registry = HookRegistry()
        plugin.register(registry)  # should not raise

    def test_register_event_handlers_is_noop(self):
        plugin = BasePlugin()
        bus = EventBus()
        plugin.register_event_handlers(bus)  # should not raise
        assert bus.handler_count == 0

    def test_teardown_is_noop(self):
        plugin = BasePlugin()
        plugin.teardown()  # should not raise
