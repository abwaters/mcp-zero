"""Tests for main module."""

from unittest.mock import patch

from starlette.applications import Starlette

from mcp_zero.main import _load_server_configs, run


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


class TestRun:
    @patch("mcp_zero.main.uvicorn")
    def test_starts_uvicorn(self, mock_uvicorn, monkeypatch):
        monkeypatch.delenv("MCP_UPSTREAM_URL", raising=False)
        monkeypatch.setenv("MCP_HOST", "127.0.0.1")
        monkeypatch.setenv("MCP_PORT", "9999")

        run()

        mock_uvicorn.run.assert_called_once()
        call_args = mock_uvicorn.run.call_args
        assert isinstance(call_args[0][0], Starlette)
        assert call_args[1]["host"] == "127.0.0.1"
        assert call_args[1]["port"] == 9999
