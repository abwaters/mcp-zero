"""Tests for main module."""

from unittest.mock import patch

from mcp_zero.main import _build_identity_pipeline, _load_server_configs, run
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


class TestRun:
    @patch("mcp_zero.main.uvicorn")
    def test_starts_uvicorn(self, mock_uvicorn, monkeypatch):
        monkeypatch.delenv("MCP_UPSTREAM_URL", raising=False)
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
