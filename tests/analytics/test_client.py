"""Tests for RedisAnalyticsClient — connection and pipeline execution."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_zero.analytics.client import RedisAnalyticsClient
from mcp_zero.analytics.config import RedisConfig


class TestRedisAnalyticsClientInit:
    def test_not_connected_initially(self):
        config = RedisConfig(url="redis://localhost:6379")
        client = RedisAnalyticsClient(config)
        assert client.connected is False

    @pytest.mark.asyncio
    async def test_connect_standalone(self):
        config = RedisConfig(url="redis://localhost:6379")
        client = RedisAnalyticsClient(config)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await client.connect()

        assert client.connected is True
        mock_redis.ping.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_cluster(self):
        config = RedisConfig(url="redis://localhost:6379", cluster=True)
        client = RedisAnalyticsClient(config)

        mock_cluster = AsyncMock()
        mock_cluster.ping = AsyncMock()

        with patch("redis.asyncio.cluster.RedisCluster.from_url", return_value=mock_cluster):
            await client.connect()

        assert client.connected is True

    @pytest.mark.asyncio
    async def test_connect_failure_sets_client_none(self):
        config = RedisConfig(url="redis://localhost:6379")
        client = RedisAnalyticsClient(config)

        with patch("redis.asyncio.from_url", side_effect=ConnectionError("refused")):
            await client.connect()

        assert client.connected is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        config = RedisConfig(url="redis://localhost:6379")
        client = RedisAnalyticsClient(config)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await client.connect()

        await client.disconnect()
        assert client.connected is False
        mock_redis.aclose.assert_awaited_once()


class TestRedisAnalyticsClientPipeline:
    @pytest.mark.asyncio
    async def test_execute_pipeline_runs_commands(self):
        config = RedisConfig(url="redis://localhost:6379")
        client = RedisAnalyticsClient(config)

        mock_pipe = MagicMock()
        mock_pipe.hincrby = MagicMock()
        mock_pipe.expire = MagicMock()
        mock_pipe.execute = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await client.connect()

        operations = [
            ("HINCRBY", ["key1", "field1", 1]),
            ("EXPIRE", ["key1", 3600]),
        ]
        await client.execute_pipeline(operations)

        mock_pipe.hincrby.assert_called_once_with("key1", "field1", 1)
        mock_pipe.expire.assert_called_once_with("key1", 3600)
        mock_pipe.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_pipeline_noop_when_not_connected(self):
        config = RedisConfig(url="redis://localhost:6379")
        client = RedisAnalyticsClient(config)

        # Should not raise
        await client.execute_pipeline([("HINCRBY", ["k", "f", 1])])

    @pytest.mark.asyncio
    async def test_execute_pipeline_noop_when_empty(self):
        config = RedisConfig(url="redis://localhost:6379")
        client = RedisAnalyticsClient(config)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await client.connect()

        await client.execute_pipeline([])
        # pipeline() should not be called for empty ops
        mock_redis.pipeline.assert_not_called()
