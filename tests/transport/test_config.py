"""Tests for transport configuration."""

import pytest

from mcp_zero.transport.config import ServerConfig, TransportType


class TestTransportType:
    def test_http_value(self):
        assert TransportType.HTTP == "http"

    def test_stdio_value(self):
        assert TransportType.STDIO == "stdio"

    def test_from_string(self):
        assert TransportType("http") is TransportType.HTTP
        assert TransportType("stdio") is TransportType.STDIO


class TestServerConfig:
    def test_http_config_valid(self):
        cfg = ServerConfig(name="remote", transport=TransportType.HTTP, url="http://localhost:8080")
        assert cfg.name == "remote"
        assert cfg.transport == TransportType.HTTP
        assert cfg.url == "http://localhost:8080"

    def test_http_config_missing_url(self):
        with pytest.raises(ValueError, match="requires 'url'"):
            ServerConfig(name="remote", transport=TransportType.HTTP)

    def test_stdio_config_valid(self):
        cfg = ServerConfig(
            name="local",
            transport=TransportType.STDIO,
            command="node",
            args=["server.js"],
            env={"DEBUG": "1"},
        )
        assert cfg.command == "node"
        assert cfg.args == ["server.js"]
        assert cfg.env == {"DEBUG": "1"}

    def test_stdio_config_missing_command(self):
        with pytest.raises(ValueError, match="requires 'command'"):
            ServerConfig(name="local", transport=TransportType.STDIO)

    def test_frozen(self):
        cfg = ServerConfig(name="remote", transport=TransportType.HTTP, url="http://localhost:8080")
        with pytest.raises(AttributeError):
            cfg.name = "other"  # type: ignore[misc]

    def test_defaults(self):
        cfg = ServerConfig(name="local", transport=TransportType.STDIO, command="python")
        assert cfg.args == []
        assert cfg.env == {}
        assert cfg.url is None

    def test_lifecycle_defaults(self):
        cfg = ServerConfig(name="local", transport=TransportType.STDIO, command="python")
        assert cfg.max_restarts == 3
        assert cfg.restart_delay == 1.0

    def test_lifecycle_custom_values(self):
        cfg = ServerConfig(
            name="local",
            transport=TransportType.STDIO,
            command="python",
            max_restarts=5,
            restart_delay=2.5,
        )
        assert cfg.max_restarts == 5
        assert cfg.restart_delay == 2.5

    def test_http_config_ignores_lifecycle(self):
        cfg = ServerConfig(
            name="remote",
            transport=TransportType.HTTP,
            url="http://localhost:8080",
            max_restarts=10,
            restart_delay=5.0,
        )
        assert cfg.max_restarts == 10
        assert cfg.restart_delay == 5.0

    def test_timeout_retry_defaults(self):
        cfg = ServerConfig(name="remote", transport=TransportType.HTTP, url="http://localhost:8080")
        assert cfg.timeout_seconds == 30.0
        assert cfg.max_retries == 2
        assert cfg.retry_delay_seconds == 1.0

    def test_timeout_retry_custom(self):
        cfg = ServerConfig(
            name="remote",
            transport=TransportType.HTTP,
            url="http://localhost:8080",
            timeout_seconds=60.0,
            max_retries=5,
            retry_delay_seconds=2.0,
        )
        assert cfg.timeout_seconds == 60.0
        assert cfg.max_retries == 5
        assert cfg.retry_delay_seconds == 2.0
