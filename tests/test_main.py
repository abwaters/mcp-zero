"""Tests for main module."""

from unittest.mock import patch

import pytest
import yaml

from mcp_zero.governance.errors import PolicyFileError
from mcp_zero.identity.config import IdentityConfig
from mcp_zero.main import (
    _build_identity_pipeline,
    _load_policy_and_configs,
    _load_server_configs,
    run,
)
from mcp_zero.pipeline import Pipeline
from mcp_zero.proxy.middleware import AuthHeaderMiddleware


class TestLoadServerConfigs:
    def test_no_env_returns_empty(self, monkeypatch):
        monkeypatch.delenv("MCP_UPSTREAM_URL", raising=False)
        assert _load_server_configs() == []

    def test_with_env_returns_config(self, monkeypatch):
        monkeypatch.setenv("MCP_UPSTREAM_URL", "http://upstream:9090")
        configs = _load_server_configs()
        assert len(configs) == 1
        assert configs[0].name == "default"
        assert configs[0].url == "http://upstream:9090"


class TestLoadPolicyAndConfigs:
    def test_no_policy_file_falls_back_to_legacy(self, monkeypatch):
        monkeypatch.delenv("MCP_POLICY_FILE", raising=False)
        monkeypatch.setenv("MCP_UPSTREAM_URL", "http://upstream:9090")
        configs, identity = _load_policy_and_configs()
        assert len(configs) == 1
        assert configs[0].name == "default"
        assert identity is None

    def test_no_policy_file_no_upstream(self, monkeypatch):
        monkeypatch.delenv("MCP_POLICY_FILE", raising=False)
        monkeypatch.delenv("MCP_UPSTREAM_URL", raising=False)
        configs, identity = _load_policy_and_configs()
        assert configs == []
        assert identity is None

    def test_policy_file_loads_configs(self, monkeypatch, tmp_path):
        policy = {
            "version": 1,
            "default": "deny",
            "servers": [
                {"name": "api", "transport": "http", "url": "http://localhost:9000"},
            ],
            "policies": [],
        }
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(policy))
        monkeypatch.setenv("MCP_POLICY_FILE", str(path))

        configs, identity = _load_policy_and_configs()
        assert len(configs) == 1
        assert configs[0].name == "api"
        assert identity is None

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

        configs, identity = _load_policy_and_configs()
        assert configs == []
        assert isinstance(identity, IdentityConfig)
        assert identity.issuer == "https://example.okta.com"
        assert identity.audience == "my-app"

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
        assert _build_identity_pipeline() is None

    def test_issuer_without_audience_returns_none(self, monkeypatch):
        monkeypatch.setenv("OKTA_ISSUER", "https://okta.example.com")
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)
        assert _build_identity_pipeline() is None

    def test_with_issuer_and_audience_returns_pipeline(self, monkeypatch):
        monkeypatch.setenv("OKTA_ISSUER", "https://okta.example.com")
        monkeypatch.setenv("OKTA_AUDIENCE", "my-app")
        result = _build_identity_pipeline()
        assert isinstance(result, Pipeline)

    def test_with_identity_config_returns_pipeline(self):
        config = IdentityConfig(issuer="https://okta.example.com", audience="my-app")
        result = _build_identity_pipeline(identity_config=config)
        assert isinstance(result, Pipeline)

    def test_identity_config_skips_env_vars(self, monkeypatch):
        """When identity_config is provided, env vars are not needed."""
        monkeypatch.delenv("OKTA_ISSUER", raising=False)
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)
        config = IdentityConfig(issuer="https://okta.example.com", audience="my-app")
        result = _build_identity_pipeline(identity_config=config)
        assert isinstance(result, Pipeline)


class TestRun:
    @patch("mcp_zero.main.uvicorn")
    def test_starts_uvicorn(self, mock_uvicorn, monkeypatch):
        monkeypatch.delenv("MCP_UPSTREAM_URL", raising=False)
        monkeypatch.delenv("MCP_POLICY_FILE", raising=False)
        monkeypatch.delenv("OKTA_ISSUER", raising=False)
        monkeypatch.delenv("OKTA_AUDIENCE", raising=False)
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
                {"name": "api", "transport": "http", "url": "http://localhost:9000"},
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
