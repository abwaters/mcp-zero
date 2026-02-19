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
        cfg = ServerConfig(
            name="remote", transport=TransportType.HTTP, url="https://localhost:8080"
        )
        assert cfg.name == "remote"
        assert cfg.transport == TransportType.HTTP
        assert cfg.url == "https://localhost:8080"

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
        cfg = ServerConfig(
            name="remote", transport=TransportType.HTTP, url="https://localhost:8080"
        )
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
            url="https://localhost:8080",
            max_restarts=10,
            restart_delay=5.0,
        )
        assert cfg.max_restarts == 10
        assert cfg.restart_delay == 5.0

    def test_timeout_retry_defaults(self):
        cfg = ServerConfig(
            name="remote", transport=TransportType.HTTP, url="https://localhost:8080"
        )
        assert cfg.timeout_seconds == 30.0
        assert cfg.max_retries == 2
        assert cfg.retry_delay_seconds == 1.0

    def test_timeout_retry_custom(self):
        cfg = ServerConfig(
            name="remote",
            transport=TransportType.HTTP,
            url="https://localhost:8080",
            timeout_seconds=60.0,
            max_retries=5,
            retry_delay_seconds=2.0,
        )
        assert cfg.timeout_seconds == 60.0
        assert cfg.max_retries == 5
        assert cfg.retry_delay_seconds == 2.0

    def test_token_exchange_defaults(self):
        cfg = ServerConfig(
            name="remote", transport=TransportType.HTTP, url="https://localhost:8080"
        )
        assert cfg.token_exchange is False
        assert cfg.target_audience is None
        assert cfg.required_scopes == []

    def test_token_exchange_valid(self):
        cfg = ServerConfig(
            name="remote",
            transport=TransportType.HTTP,
            url="https://localhost:8080",
            token_exchange=True,
            target_audience="api://mcp-server",
            required_scopes=["read", "write"],
        )
        assert cfg.token_exchange is True
        assert cfg.target_audience == "api://mcp-server"
        assert cfg.required_scopes == ["read", "write"]

    def test_token_exchange_stdio_rejected(self):
        with pytest.raises(ValueError, match="not supported for stdio"):
            ServerConfig(
                name="local",
                transport=TransportType.STDIO,
                command="python",
                token_exchange=True,
                target_audience="api://mcp-server",
            )

    def test_token_exchange_missing_audience(self):
        with pytest.raises(ValueError, match="requires 'target_audience'"):
            ServerConfig(
                name="remote",
                transport=TransportType.HTTP,
                url="https://localhost:8080",
                token_exchange=True,
            )

    def test_http_rejects_insecure_url(self):
        with pytest.raises(ValueError, match="must use https://"):
            ServerConfig(name="remote", transport=TransportType.HTTP, url="http://localhost:8080")

    def test_http_allows_insecure_with_flag(self):
        cfg = ServerConfig(
            name="remote",
            transport=TransportType.HTTP,
            url="http://localhost:8080",
            allow_insecure=True,
        )
        assert cfg.url == "http://localhost:8080"

    def test_stdio_unaffected_by_https_check(self):
        cfg = ServerConfig(name="local", transport=TransportType.STDIO, command="python")
        assert cfg.allow_insecure is False

    def test_headers_default_empty(self):
        cfg = ServerConfig(
            name="remote", transport=TransportType.HTTP, url="https://localhost:8080"
        )
        assert cfg.headers == {}

    def test_headers_accepted_for_http(self):
        cfg = ServerConfig(
            name="remote",
            transport=TransportType.HTTP,
            url="https://localhost:8080",
            headers={"Authorization": "Bearer token123", "X-Api-Key": "key456"},
        )
        assert cfg.headers == {"Authorization": "Bearer token123", "X-Api-Key": "key456"}

    def test_headers_accepted_for_sse(self):
        cfg = ServerConfig(
            name="remote",
            transport=TransportType.SSE,
            url="https://localhost:8080/sse",
            headers={"Authorization": "Bearer tok"},
        )
        assert cfg.headers == {"Authorization": "Bearer tok"}

    def test_headers_rejected_for_stdio(self):
        with pytest.raises(ValueError, match="headers are not supported for stdio"):
            ServerConfig(
                name="local",
                transport=TransportType.STDIO,
                command="python",
                headers={"X-Api-Key": "secret"},
            )

    def test_headers_env_var_expansion(self, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "expanded-value")
        cfg = ServerConfig(
            name="remote",
            transport=TransportType.HTTP,
            url="https://localhost:8080",
            headers={"Authorization": "Bearer ${MY_TOKEN}"},
        )
        assert cfg.headers["Authorization"] == "Bearer expanded-value"

    def test_headers_env_var_missing_expands_to_empty(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        cfg = ServerConfig(
            name="remote",
            transport=TransportType.HTTP,
            url="https://localhost:8080",
            headers={"Authorization": "Bearer ${NONEXISTENT_VAR}"},
        )
        assert cfg.headers["Authorization"] == "Bearer "

    def test_headers_multiple_env_vars(self, monkeypatch):
        monkeypatch.setenv("TOKEN_TYPE", "Bearer")
        monkeypatch.setenv("TOKEN_VALUE", "abc123")
        cfg = ServerConfig(
            name="remote",
            transport=TransportType.HTTP,
            url="https://localhost:8080",
            headers={"Authorization": "${TOKEN_TYPE} ${TOKEN_VALUE}"},
        )
        assert cfg.headers["Authorization"] == "Bearer abc123"

    def test_headers_no_env_var_syntax_unchanged(self):
        cfg = ServerConfig(
            name="remote",
            transport=TransportType.HTTP,
            url="https://localhost:8080",
            headers={"X-Static": "plain-value"},
        )
        assert cfg.headers["X-Static"] == "plain-value"
