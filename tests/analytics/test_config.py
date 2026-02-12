"""Tests for analytics configuration dataclasses."""

from __future__ import annotations

from mcp_zero.analytics.config import AnalyticsConfig, RedisConfig


class TestRedisConfig:
    def test_defaults(self):
        config = RedisConfig()
        assert config.url == ""
        assert config.cluster is False
        assert config.tls is False
        assert config.password is None
        assert config.socket_timeout == 5.0
        assert config.retry_on_timeout is True

    def test_custom_values(self):
        config = RedisConfig(
            url="redis://myhost:6380/2",
            cluster=True,
            tls=True,
            password="secret",
            socket_timeout=10.0,
            retry_on_timeout=False,
        )
        assert config.url == "redis://myhost:6380/2"
        assert config.cluster is True
        assert config.tls is True
        assert config.password == "secret"
        assert config.socket_timeout == 10.0
        assert config.retry_on_timeout is False


class TestAnalyticsConfig:
    def test_defaults(self):
        config = AnalyticsConfig()
        assert config.environment == "default"
        assert config.key_prefix == "mcpgw"
        assert config.bucket_seconds == 60
        assert config.retention_seconds == 3600
        assert config.heartbeat_seconds == 30
        assert config.queue_size == 10000
        assert config.flush_interval == 1.0

    def test_auto_generates_gateway_id(self):
        config = AnalyticsConfig()
        assert len(config.gateway_id) == 8
        # Each call generates a different ID
        config2 = AnalyticsConfig()
        assert config.gateway_id != config2.gateway_id

    def test_preserves_explicit_gateway_id(self):
        config = AnalyticsConfig(gateway_id="my-gw")
        assert config.gateway_id == "my-gw"

    def test_enabled_when_redis_url_set(self):
        config = AnalyticsConfig(redis=RedisConfig(url="redis://localhost:6379"))
        assert config.enabled is True

    def test_disabled_when_no_redis_url(self):
        config = AnalyticsConfig()
        assert config.enabled is False

    def test_disabled_when_empty_redis_url(self):
        config = AnalyticsConfig(redis=RedisConfig(url=""))
        assert config.enabled is False
