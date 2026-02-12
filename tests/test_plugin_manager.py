"""Tests for PluginManager."""

from unittest.mock import MagicMock

import pytest

from mcp_zero.governance.config import PluginDeclaration
from mcp_zero.pipeline.registry import HookRegistry
from mcp_zero.plugin import BasePlugin
from mcp_zero.plugin_manager import PluginLoadError, PluginManager


def _make_entry_point(name: str, factory=None):
    """Create a mock entry point."""
    ep = MagicMock()
    ep.name = name
    if factory is not None:
        ep.load.return_value = factory
    return ep


class TestDiscovery:
    def test_discovers_entry_points(self, monkeypatch):
        ep1 = _make_entry_point("plugin-a")
        ep2 = _make_entry_point("plugin-b")
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep1, ep2],
        )
        mgr = PluginManager()
        assert mgr.available_plugins() == ["plugin-a", "plugin-b"]

    def test_no_entry_points(self, monkeypatch):
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [],
        )
        mgr = PluginManager()
        assert mgr.available_plugins() == []


class TestLoadSuccess:
    def test_load_valid_plugin(self, monkeypatch):
        class GoodPlugin(BasePlugin):
            @property
            def name(self):
                return "good"

        factory = GoodPlugin
        ep = _make_entry_point("good", factory)
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep],
        )

        mgr = PluginManager()
        registry = HookRegistry()
        decl = PluginDeclaration(name="good", package="good", config={"k": "v"})
        mgr.load_plugins([decl], registry)

        assert len(mgr.loaded_plugins) == 1
        assert mgr.loaded_plugins[0].name == "good"

    def test_configure_called_with_config(self, monkeypatch):
        configure_args = []

        class TrackPlugin(BasePlugin):
            def configure(self, config):
                configure_args.append(config)

        ep = _make_entry_point("track", TrackPlugin)
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep],
        )

        mgr = PluginManager()
        registry = HookRegistry()
        decl = PluginDeclaration(name="track", package="track", config={"a": 1})
        mgr.load_plugins([decl], registry)
        assert configure_args == [{"a": 1}]

    def test_register_called_with_registry(self, monkeypatch):
        register_calls = []

        class RegPlugin(BasePlugin):
            def register(self, registry):
                register_calls.append(registry)

        ep = _make_entry_point("reg", RegPlugin)
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep],
        )

        mgr = PluginManager()
        registry = HookRegistry()
        mgr.load_plugins([PluginDeclaration(name="reg", package="reg")], registry)
        assert register_calls == [registry]


class TestLoadErrors:
    def test_missing_package_raises(self, monkeypatch):
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [],
        )
        mgr = PluginManager()
        registry = HookRegistry()
        decl = PluginDeclaration(name="missing", package="missing")
        with pytest.raises(PluginLoadError, match="not found"):
            mgr.load_plugins([decl], registry)

    def test_factory_raises(self, monkeypatch):
        ep = _make_entry_point("bad-factory")
        ep.load.return_value = MagicMock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep],
        )
        mgr = PluginManager()
        registry = HookRegistry()
        decl = PluginDeclaration(name="bad-factory", package="bad-factory")
        with pytest.raises(PluginLoadError, match="Factory.*raised"):
            mgr.load_plugins([decl], registry)

    def test_entry_point_load_raises(self, monkeypatch):
        ep = _make_entry_point("broken")
        ep.load.side_effect = ImportError("no module")
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep],
        )
        mgr = PluginManager()
        registry = HookRegistry()
        decl = PluginDeclaration(name="broken", package="broken")
        with pytest.raises(PluginLoadError, match="Failed to load entry point"):
            mgr.load_plugins([decl], registry)

    def test_bad_protocol_raises(self, monkeypatch):
        class NotAPlugin:
            pass

        ep = _make_entry_point("bad-proto", NotAPlugin)
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep],
        )
        mgr = PluginManager()
        registry = HookRegistry()
        decl = PluginDeclaration(name="bad-proto", package="bad-proto")
        with pytest.raises(PluginLoadError, match="does not satisfy the Plugin protocol"):
            mgr.load_plugins([decl], registry)

    def test_configure_raises(self, monkeypatch):
        class BadConfigure(BasePlugin):
            def configure(self, config):
                raise ValueError("bad config")

        ep = _make_entry_point("bad-cfg", BadConfigure)
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep],
        )
        mgr = PluginManager()
        registry = HookRegistry()
        decl = PluginDeclaration(name="bad-cfg", package="bad-cfg")
        with pytest.raises(PluginLoadError, match="configure\\(\\) failed"):
            mgr.load_plugins([decl], registry)


class TestTeardown:
    def test_teardown_reverse_order(self, monkeypatch):
        teardown_order = []

        class PluginA(BasePlugin):
            @property
            def name(self):
                return "A"

            def teardown(self):
                teardown_order.append("A")

        class PluginB(BasePlugin):
            @property
            def name(self):
                return "B"

            def teardown(self):
                teardown_order.append("B")

        ep_a = _make_entry_point("a", PluginA)
        ep_b = _make_entry_point("b", PluginB)
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep_a, ep_b],
        )

        mgr = PluginManager()
        registry = HookRegistry()
        mgr.load_plugins(
            [
                PluginDeclaration(name="a", package="a"),
                PluginDeclaration(name="b", package="b"),
            ],
            registry,
        )
        mgr.teardown_all()
        assert teardown_order == ["B", "A"]

    def test_teardown_resilience(self, monkeypatch):
        teardown_calls = []

        class FailPlugin(BasePlugin):
            @property
            def name(self):
                return "fail"

            def teardown(self):
                teardown_calls.append("fail")
                raise RuntimeError("teardown error")

        class GoodPlugin(BasePlugin):
            @property
            def name(self):
                return "good"

            def teardown(self):
                teardown_calls.append("good")

        ep_good = _make_entry_point("good", GoodPlugin)
        ep_fail = _make_entry_point("fail", FailPlugin)
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep_good, ep_fail],
        )

        mgr = PluginManager()
        registry = HookRegistry()
        mgr.load_plugins(
            [
                PluginDeclaration(name="good", package="good"),
                PluginDeclaration(name="fail", package="fail"),
            ],
            registry,
        )
        mgr.teardown_all()
        # Reversed order: fail first, then good — both called despite error
        assert teardown_calls == ["fail", "good"]


class TestPackageResolution:
    def test_package_defaults_to_name(self, monkeypatch):
        ep = _make_entry_point("my-plugin", BasePlugin)
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep],
        )
        mgr = PluginManager()
        registry = HookRegistry()
        # package="" means it should fall back to name
        decl = PluginDeclaration(name="my-plugin", package="")
        mgr.load_plugins([decl], registry)
        assert len(mgr.loaded_plugins) == 1
