"""Tests for main module."""

from unittest.mock import patch

import pytest
import yaml

from mcp_zero.governance.config import CorsConfig, PluginDeclaration, PolicyConfig
from mcp_zero.governance.errors import PolicyFileError
from mcp_zero.identity.config import IdentityConfig
from mcp_zero.main import (
    _build_cors_config,
    _build_obo_provider,
    _build_pipeline,
    _is_insecure_allowed,
    _load_policy_and_configs,
    _load_server_configs,
    run,
)
from mcp_zero.pipeline import Pipeline
from mcp_zero.plugin import BasePlugin
from mcp_zero.plugin_manager import PluginLoadError, PluginManager
from mcp_zero.proxy.middleware import AuthHeaderMiddleware
from mcp_zero.transport.config import ServerConfig, TransportType


class TestIsInsecureAllowed:
    def test_not_set(self, monkeypatch):
        monkeypatch.delenv("MCP_ALLOW_INSECURE", raising=False)
        assert _is_insecure_allowed() is False

    def test_empty(self, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_INSECURE", "")
        assert _is_insecure_allowed() is False

    def test_truthy_1(self, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_INSECURE", "1")
        assert _is_insecure_allowed() is True

    def test_truthy_true(self, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_INSECURE", "true")
        assert _is_insecure_allowed() is True

    def test_truthy_yes(self, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_INSECURE", "yes")
        assert _is_insecure_allowed() is True

    def test_truthy_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_INSECURE", "TRUE")
        assert _is_insecure_allowed() is True

    def test_falsy_value(self, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_INSECURE", "0")
        assert _is_insecure_allowed() is False


class TestLoadServerConfigs:
    def test_no_env_returns_empty(self, monkeypatch):
        monkeypatch.delenv("MCP_UPSTREAM_URL", raising=False)
        assert _load_server_configs() == []

    def test_with_env_returns_config(self, monkeypatch):
        monkeypatch.setenv("MCP_UPSTREAM_URL", "https://upstream:9090")
        configs = _load_server_configs()
        assert len(configs) == 1
        assert configs[0].name == "default"
        assert configs[0].url == "https://upstream:9090"

    def test_http_url_rejected_without_allow_insecure(self, monkeypatch):
        monkeypatch.setenv("MCP_UPSTREAM_URL", "http://upstream:9090")
        monkeypatch.delenv("MCP_ALLOW_INSECURE", raising=False)
        with pytest.raises(ValueError, match="must use https://"):
            _load_server_configs()

    def test_http_url_allowed_with_allow_insecure(self, monkeypatch):
        monkeypatch.setenv("MCP_UPSTREAM_URL", "http://upstream:9090")
        monkeypatch.setenv("MCP_ALLOW_INSECURE", "1")
        configs = _load_server_configs()
        assert len(configs) == 1
        assert configs[0].url == "http://upstream:9090"


class TestLoadPolicyAndConfigs:
    def test_no_policy_file_falls_back_to_legacy(self, monkeypatch):
        monkeypatch.delenv("MCP_POLICY_FILE", raising=False)
        monkeypatch.setenv("MCP_UPSTREAM_URL", "https://upstream:9090")
        configs, identity, policy_config = _load_policy_and_configs()
        assert len(configs) == 1
        assert configs[0].name == "default"
        assert identity is None
        assert policy_config is None

    def test_no_policy_file_no_upstream(self, monkeypatch):
        monkeypatch.delenv("MCP_POLICY_FILE", raising=False)
        monkeypatch.delenv("MCP_UPSTREAM_URL", raising=False)
        configs, identity, policy_config = _load_policy_and_configs()
        assert configs == []
        assert identity is None
        assert policy_config is None

    def test_policy_file_loads_configs(self, monkeypatch, tmp_path):
        policy = {
            "version": 1,
            "default": "deny",
            "servers": [
                {"name": "api", "transport": "http", "url": "https://localhost:9000"},
            ],
            "policies": [],
        }
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(policy))
        monkeypatch.setenv("MCP_POLICY_FILE", str(path))

        configs, identity, policy_config = _load_policy_and_configs()
        assert len(configs) == 1
        assert configs[0].name == "api"
        assert identity is None
        assert policy_config is not None

    def test_policy_file_loads_identity(self, monkeypatch, tmp_path):
        policy = {
            "version": 1,
            "default": "deny",
            "identity": {
                "provider": "okta",
                "issuer": "https://example.okta.com",
                "audience": "my-app",
            },
            "servers": [],
            "policies": [],
        }
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(policy))
        monkeypatch.setenv("MCP_POLICY_FILE", str(path))

        configs, identity, policy_config = _load_policy_and_configs()
        assert configs == []
        assert isinstance(identity, IdentityConfig)
        assert identity.issuer == "https://example.okta.com"
        assert identity.audience == "my-app"
        assert policy_config is not None

    def test_invalid_policy_file_raises(self, monkeypatch, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("version: 2\n")
        monkeypatch.setenv("MCP_POLICY_FILE", str(path))
        with pytest.raises(Exception):
            _load_policy_and_configs()

    def test_missing_policy_file_raises(self, monkeypatch):
        monkeypatch.setenv("MCP_POLICY_FILE", "/nonexistent/policy.yaml")
        with pytest.raises(PolicyFileError):
            _load_policy_and_configs()


class TestBuildIdentityPipeline:
    def test_no_issuer_returns_none(self, monkeypatch):
        monkeypatch.delenv("OKTA_ISSUER", raising=False)
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)
        pipeline, plugin_manager = _build_pipeline()
        assert pipeline is None
        assert isinstance(plugin_manager, PluginManager)

    def test_issuer_without_audience_returns_none(self, monkeypatch):
        monkeypatch.setenv("OKTA_ISSUER", "https://okta.example.com")
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)
        pipeline, plugin_manager = _build_pipeline()
        assert pipeline is None
        assert isinstance(plugin_manager, PluginManager)

    def test_with_issuer_and_audience_returns_pipeline(self, monkeypatch):
        monkeypatch.setenv("OKTA_ISSUER", "https://okta.example.com")
        monkeypatch.setenv("OKTA_AUDIENCE", "my-app")
        pipeline, plugin_manager = _build_pipeline()
        assert isinstance(pipeline, Pipeline)
        assert isinstance(plugin_manager, PluginManager)

    def test_with_identity_config_returns_pipeline(self):
        config = IdentityConfig(issuer="https://okta.example.com", audience="my-app")
        pipeline, plugin_manager = _build_pipeline(identity_config=config)
        assert isinstance(pipeline, Pipeline)
        assert isinstance(plugin_manager, PluginManager)

    def test_identity_config_skips_env_vars(self, monkeypatch):
        """When identity_config is provided, env vars are not needed."""
        monkeypatch.delenv("OKTA_ISSUER", raising=False)
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)
        config = IdentityConfig(issuer="https://okta.example.com", audience="my-app")
        pipeline, plugin_manager = _build_pipeline(identity_config=config)
        assert isinstance(pipeline, Pipeline)
        assert isinstance(plugin_manager, PluginManager)


class TestBuildPipelinePlugins:
    def test_no_plugins_in_policy(self, monkeypatch):
        monkeypatch.delenv("OKTA_ISSUER", raising=False)
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)
        policy = PolicyConfig(version=1)
        pipeline, plugin_manager = _build_pipeline(policy_config=policy)
        assert plugin_manager.loaded_plugins == []

    def test_plugins_loaded_when_declared(self, monkeypatch):
        monkeypatch.delenv("OKTA_ISSUER", raising=False)
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)

        # Set up a fake entry point
        ep = type("EP", (), {"name": "test-plugin", "load": lambda self: BasePlugin})()
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [ep],
        )

        policy = PolicyConfig(
            version=1,
            plugins=[PluginDeclaration(name="test-plugin", package="test-plugin")],
        )
        pipeline, plugin_manager = _build_pipeline(policy_config=policy)
        assert len(plugin_manager.loaded_plugins) == 1

    def test_missing_plugin_raises(self, monkeypatch):
        monkeypatch.delenv("OKTA_ISSUER", raising=False)
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)
        monkeypatch.setattr(
            "mcp_zero.plugin_manager.importlib.metadata.entry_points",
            lambda group: [],
        )

        policy = PolicyConfig(
            version=1,
            plugins=[PluginDeclaration(name="nonexistent", package="nonexistent")],
        )
        with pytest.raises(PluginLoadError, match="not found"):
            _build_pipeline(policy_config=policy)


class TestBuildPipelinePostureLogging:
    def test_policy_without_identity_logs_warning(self, monkeypatch, caplog):
        """Policy loaded without identity should produce a WARNING-level log."""
        monkeypatch.delenv("OKTA_ISSUER", raising=False)
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)
        policy = PolicyConfig(version=1)

        import logging

        with caplog.at_level(logging.WARNING):
            _build_pipeline(policy_config=policy)

        assert any("SECURITY POSTURE" in r.message for r in caplog.records)
        assert any("anonymous" in r.message for r in caplog.records)

    def test_issuer_without_audience_with_policy_logs_warning(self, monkeypatch, caplog):
        """OKTA_ISSUER without OKTA_AUDIENCE + policy should warn about misconfiguration."""
        monkeypatch.setenv("OKTA_ISSUER", "https://okta.example.com")
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)
        policy = PolicyConfig(version=1)

        import logging

        with caplog.at_level(logging.WARNING):
            _build_pipeline(policy_config=policy)

        assert any("OKTA_AUDIENCE" in r.message for r in caplog.records)
        assert any("SECURITY POSTURE" in r.message for r in caplog.records)

    def test_no_config_logs_pipeline_disabled_at_warning(self, monkeypatch, caplog):
        """Pipeline disabled message should be logged at WARNING level."""
        monkeypatch.delenv("OKTA_ISSUER", raising=False)
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)

        import logging

        with caplog.at_level(logging.WARNING):
            pipeline, _ = _build_pipeline()

        assert pipeline is None
        assert any(
            "pipeline disabled" in r.message and r.levelno == logging.WARNING
            for r in caplog.records
        )


class TestRun:
    def test_refuses_startup_without_config(self, monkeypatch):
        """Gateway refuses to start without identity/policy config (fail-closed)."""
        monkeypatch.delenv("MCP_UPSTREAM_URL", raising=False)
        monkeypatch.delenv("MCP_POLICY_FILE", raising=False)
        monkeypatch.delenv("OKTA_ISSUER", raising=False)
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)
        monkeypatch.delenv("MCP_ALLOW_INSECURE", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            run()
        assert exc_info.value.code == 78

    def test_refuses_startup_with_partial_identity_config(self, monkeypatch, tmp_path):
        """Gateway refuses when OKTA_ISSUER is set without OKTA_AUDIENCE + policy file."""
        policy = {
            "version": 1,
            "default": "deny",
            "servers": [
                {"name": "api", "transport": "http", "url": "https://localhost:9000"},
            ],
            "policies": [],
        }
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(policy))

        monkeypatch.setenv("MCP_POLICY_FILE", str(path))
        monkeypatch.setenv("OKTA_ISSUER", "https://okta.example.com")
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)
        monkeypatch.delenv("MCP_ALLOW_INSECURE", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            run()
        assert exc_info.value.code == 78

    @patch("mcp_zero.main.uvicorn")
    def test_partial_identity_allowed_with_allow_insecure(
        self, mock_uvicorn, monkeypatch, tmp_path
    ):
        """Partial identity config starts when MCP_ALLOW_INSECURE is set."""
        policy = {
            "version": 1,
            "default": "deny",
            "servers": [
                {"name": "api", "transport": "http", "url": "https://localhost:9000"},
            ],
            "policies": [],
        }
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(policy))

        monkeypatch.setenv("MCP_POLICY_FILE", str(path))
        monkeypatch.setenv("OKTA_ISSUER", "https://okta.example.com")
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)
        monkeypatch.setenv("MCP_ALLOW_INSECURE", "true")
        monkeypatch.setenv("MCP_HOST", "127.0.0.1")
        monkeypatch.setenv("MCP_PORT", "9999")

        run()

        mock_uvicorn.run.assert_called_once()

    @patch("mcp_zero.main.uvicorn")
    def test_starts_insecure_with_allow_insecure(self, mock_uvicorn, monkeypatch):
        """Gateway starts without config when MCP_ALLOW_INSECURE is set."""
        monkeypatch.delenv("MCP_UPSTREAM_URL", raising=False)
        monkeypatch.delenv("MCP_POLICY_FILE", raising=False)
        monkeypatch.delenv("OKTA_ISSUER", raising=False)
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)
        monkeypatch.setenv("MCP_ALLOW_INSECURE", "true")
        monkeypatch.setenv("MCP_HOST", "127.0.0.1")
        monkeypatch.setenv("MCP_PORT", "9999")

        run()

        mock_uvicorn.run.assert_called_once()
        call_args = mock_uvicorn.run.call_args
        assert isinstance(call_args[0][0], AuthHeaderMiddleware)
        assert call_args[1]["host"] == "127.0.0.1"
        assert call_args[1]["port"] == 9999

    @patch("mcp_zero.main.uvicorn")
    def test_starts_with_policy_file(self, mock_uvicorn, monkeypatch, tmp_path):
        policy = {
            "version": 1,
            "default": "deny",
            "servers": [
                {"name": "api", "transport": "http", "url": "https://localhost:9000"},
            ],
            "policies": [],
        }
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(policy))

        monkeypatch.setenv("MCP_POLICY_FILE", str(path))
        monkeypatch.delenv("OKTA_ISSUER", raising=False)
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)
        monkeypatch.setenv("MCP_HOST", "127.0.0.1")
        monkeypatch.setenv("MCP_PORT", "9999")

        run()

        mock_uvicorn.run.assert_called_once()


class TestBuildCorsConfig:
    def test_no_config_returns_none(self, monkeypatch):
        monkeypatch.delenv("MCP_CORS_ORIGINS", raising=False)
        result = _build_cors_config(None)
        assert result is None

    def test_policy_only(self, monkeypatch):
        monkeypatch.delenv("MCP_CORS_ORIGINS", raising=False)
        monkeypatch.delenv("MCP_CORS_ALLOW_CREDENTIALS", raising=False)
        monkeypatch.delenv("MCP_CORS_MAX_AGE", raising=False)
        policy = PolicyConfig(
            version=1,
            cors=CorsConfig(allow_origins=["https://app.example.com"]),
        )
        result = _build_cors_config(policy)
        assert result is not None
        assert result.allow_origins == ["https://app.example.com"]
        assert result.allow_credentials is False
        assert result.max_age == 600

    def test_env_only(self, monkeypatch):
        monkeypatch.setenv("MCP_CORS_ORIGINS", "https://a.com, https://b.com")
        monkeypatch.delenv("MCP_CORS_ALLOW_CREDENTIALS", raising=False)
        monkeypatch.delenv("MCP_CORS_MAX_AGE", raising=False)
        result = _build_cors_config(None)
        assert result is not None
        assert result.allow_origins == ["https://a.com", "https://b.com"]

    def test_env_overrides_policy(self, monkeypatch):
        monkeypatch.setenv("MCP_CORS_ORIGINS", "https://override.com")
        monkeypatch.setenv("MCP_CORS_ALLOW_CREDENTIALS", "true")
        monkeypatch.setenv("MCP_CORS_MAX_AGE", "1200")
        policy = PolicyConfig(
            version=1,
            cors=CorsConfig(
                allow_origins=["https://original.com"],
                allow_credentials=False,
                max_age=300,
            ),
        )
        result = _build_cors_config(policy)
        assert result.allow_origins == ["https://override.com"]
        assert result.allow_credentials is True
        assert result.max_age == 1200

    def test_empty_env_not_treated_as_set(self, monkeypatch):
        monkeypatch.setenv("MCP_CORS_ORIGINS", "")
        result = _build_cors_config(None)
        assert result is None

    def test_policy_with_credential_env_override(self, monkeypatch):
        monkeypatch.delenv("MCP_CORS_ORIGINS", raising=False)
        monkeypatch.setenv("MCP_CORS_ALLOW_CREDENTIALS", "true")
        monkeypatch.delenv("MCP_CORS_MAX_AGE", raising=False)
        policy = PolicyConfig(
            version=1,
            cors=CorsConfig(
                allow_origins=["https://app.com"],
                allow_credentials=False,
            ),
        )
        result = _build_cors_config(policy)
        assert result.allow_origins == ["https://app.com"]
        assert result.allow_credentials is True


class TestBuildOBOProviderValidation:
    def _obo_server_config(self, name="weather"):
        return ServerConfig(
            name=name,
            transport=TransportType.HTTP,
            url="https://weather:8080",
            token_exchange=True,
            target_audience="api://weather",
        )

    def test_refuses_obo_without_identity(self, monkeypatch):
        """OBO servers without identity pipeline should fail-closed."""
        monkeypatch.delenv("MCP_ALLOW_INSECURE", raising=False)
        monkeypatch.setenv("OKTA_TOKEN_ENDPOINT", "https://okta/token")
        monkeypatch.setenv("OKTA_CLIENT_ID", "client-id")
        monkeypatch.setenv("OKTA_CLIENT_SECRET", "secret")

        with pytest.raises(SystemExit) as exc_info:
            _build_obo_provider([self._obo_server_config()], identity_enabled=False)
        assert exc_info.value.code == 78

    def test_allows_obo_without_identity_when_insecure(self, monkeypatch):
        """OBO servers without identity allowed when MCP_ALLOW_INSECURE is set."""
        monkeypatch.setenv("MCP_ALLOW_INSECURE", "true")
        monkeypatch.setenv("OKTA_TOKEN_ENDPOINT", "https://okta/token")
        monkeypatch.setenv("OKTA_CLIENT_ID", "client-id")
        monkeypatch.setenv("OKTA_CLIENT_SECRET", "secret")

        # Should not raise — returns the provider
        result = _build_obo_provider([self._obo_server_config()], identity_enabled=False)
        assert result is not None

    def test_obo_with_identity_enabled(self, monkeypatch):
        """OBO servers with identity pipeline should work normally."""
        monkeypatch.delenv("MCP_ALLOW_INSECURE", raising=False)
        monkeypatch.setenv("OKTA_TOKEN_ENDPOINT", "https://okta/token")
        monkeypatch.setenv("OKTA_CLIENT_ID", "client-id")
        monkeypatch.setenv("OKTA_CLIENT_SECRET", "secret")

        result = _build_obo_provider([self._obo_server_config()], identity_enabled=True)
        assert result is not None

    def test_no_obo_servers_skips_validation(self, monkeypatch):
        """Non-OBO servers should not trigger identity validation."""
        monkeypatch.delenv("MCP_ALLOW_INSECURE", raising=False)
        config = ServerConfig(
            name="api",
            transport=TransportType.HTTP,
            url="https://api:8080",
        )
        result = _build_obo_provider([config], identity_enabled=False)
        assert result is None
