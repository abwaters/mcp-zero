"""Tests for proxy server."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from mcp_zero.context import HookContext, PolicyDecision, RequestContext, UserIdentity
from mcp_zero.identity.errors import TokenExchangeError
from mcp_zero.pipeline import Pipeline, PipelineResult
from mcp_zero.proxy.auth import AuthProvider
from mcp_zero.proxy.errors import RoutingError, UpstreamError
from mcp_zero.proxy.proxy_server import ProxyServer
from mcp_zero.proxy.server_manager import ServerManager
from mcp_zero.transport.config import ServerConfig, TransportType
from mcp_zero.transport.errors import TransportConnectionError


def make_configs():
    return [
        ServerConfig(
            name="weather",
            transport=TransportType.HTTP,
            url="http://weather:8080",
            max_retries=1,
            retry_delay_seconds=0.01,
            timeout_seconds=5.0,
            allow_insecure=True,
        ),
        ServerConfig(
            name="db",
            transport=TransportType.HTTP,
            url="http://db:8080",
            allow_insecure=True,
        ),
    ]


def make_tool(name="get_weather", description="Get weather"):
    return Tool(name=name, description=description, inputSchema={"type": "object"})


def make_call_result(text="result"):
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        isError=False,
    )


class TestProxyServerListTools:
    @pytest.mark.asyncio
    async def test_aggregates_tools_from_all_servers(self):
        mgr = ServerManager(make_configs())

        mock_session_w = AsyncMock()
        mock_session_w.list_tools = AsyncMock(
            return_value=ListToolsResult(tools=[make_tool("get_weather")])
        )
        mock_session_d = AsyncMock()
        mock_session_d.list_tools = AsyncMock(
            return_value=ListToolsResult(tools=[make_tool("query")])
        )

        sessions = {"weather": mock_session_w, "db": mock_session_d}

        async def fake_get_session(name, ctx=None, **kwargs):
            return sessions[name]

        mgr.get_session = AsyncMock(side_effect=fake_get_session)

        proxy = ProxyServer(mgr)
        tools = await proxy._list_tools()

        assert len(tools) == 2
        names = {t.name for t in tools}
        assert "weather__get_weather" in names
        assert "db__query" in names

    @pytest.mark.asyncio
    async def test_skips_failed_server(self):
        mgr = ServerManager(make_configs())

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(
            return_value=ListToolsResult(tools=[make_tool("query")])
        )

        async def fake_get_session(name, ctx=None, **kwargs):
            if name == "weather":
                raise ConnectionError("down")
            return mock_session

        mgr.get_session = AsyncMock(side_effect=fake_get_session)

        proxy = ProxyServer(mgr)
        tools = await proxy._list_tools()

        assert len(tools) == 1
        assert tools[0].name == "db__query"

    @pytest.mark.asyncio
    async def test_timeout_skips_slow_server(self):
        configs = [
            ServerConfig(
                name="fast",
                transport=TransportType.HTTP,
                url="http://fast:8080",
                timeout_seconds=0.05,
                allow_insecure=True,
            ),
            ServerConfig(
                name="slow",
                transport=TransportType.HTTP,
                url="http://slow:8080",
                timeout_seconds=0.05,
                allow_insecure=True,
            ),
        ]
        mgr = ServerManager(configs)

        mock_fast = AsyncMock()
        mock_fast.list_tools = AsyncMock(
            return_value=ListToolsResult(tools=[make_tool("ping")])
        )
        mock_slow = AsyncMock()

        async def slow_list_tools():
            await asyncio.sleep(10)
            return ListToolsResult(tools=[make_tool("nope")])

        mock_slow.list_tools = AsyncMock(side_effect=slow_list_tools)

        sessions = {"fast": mock_fast, "slow": mock_slow}

        async def fake_get_session(name, ctx=None, **kwargs):
            return sessions[name]

        mgr.get_session = AsyncMock(side_effect=fake_get_session)

        proxy = ProxyServer(mgr)
        tools = await proxy._list_tools()

        assert len(tools) == 1
        assert tools[0].name == "fast__ping"

    @pytest.mark.asyncio
    async def test_queries_servers_concurrently(self):
        """Verify servers are queried in parallel, not sequentially."""
        configs = [
            ServerConfig(
                name="a",
                transport=TransportType.HTTP,
                url="http://a:8080",
                timeout_seconds=5.0,
                allow_insecure=True,
            ),
            ServerConfig(
                name="b",
                transport=TransportType.HTTP,
                url="http://b:8080",
                timeout_seconds=5.0,
                allow_insecure=True,
            ),
        ]
        mgr = ServerManager(configs)

        async def delayed_list_a():
            await asyncio.sleep(0.1)
            return ListToolsResult(tools=[make_tool("tool_a")])

        async def delayed_list_b():
            await asyncio.sleep(0.1)
            return ListToolsResult(tools=[make_tool("tool_b")])

        mock_a = AsyncMock()
        mock_a.list_tools = delayed_list_a
        mock_b = AsyncMock()
        mock_b.list_tools = delayed_list_b

        sessions = {"a": mock_a, "b": mock_b}

        async def fake_get_session(name, ctx=None, **kwargs):
            return sessions[name]

        mgr.get_session = AsyncMock(side_effect=fake_get_session)

        proxy = ProxyServer(mgr)

        import time

        start = time.monotonic()
        tools = await proxy._list_tools()
        elapsed = time.monotonic() - start

        assert len(tools) == 2
        # If sequential, would take ~0.2s; parallel should be ~0.1s
        assert elapsed < 0.18, f"Took {elapsed:.3f}s — servers queried sequentially?"


class TestProxyServerCallTool:
    @pytest.mark.asyncio
    async def test_routes_to_correct_upstream(self):
        mgr = ServerManager(make_configs())

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=make_call_result("sunny"))

        mgr.get_session = AsyncMock(return_value=mock_session)

        proxy = ProxyServer(mgr)
        result = await proxy._call_tool("weather__get_weather", {"city": "NYC"})

        assert len(result) == 1
        assert result[0].text == "sunny"
        mock_session.call_tool.assert_awaited_once_with("get_weather", {"city": "NYC"})

    @pytest.mark.asyncio
    async def test_invalid_tool_name_raises(self):
        mgr = ServerManager(make_configs())
        proxy = ProxyServer(mgr)

        with pytest.raises(RoutingError):
            await proxy._call_tool("badname", {})

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self):
        configs = [
            ServerConfig(
                name="weather",
                transport=TransportType.HTTP,
                url="http://weather:8080",
                max_retries=1,
                retry_delay_seconds=0.01,
                timeout_seconds=5.0,
                allow_insecure=True,
            ),
        ]
        mgr = ServerManager(configs)

        mock_session = AsyncMock()
        call_count = {"n": 0}

        async def fake_call_tool(name, args):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise TransportConnectionError("conn reset", server_name="weather")
            return make_call_result("ok")

        mock_session.call_tool = AsyncMock(side_effect=fake_call_tool)
        mgr.get_session = AsyncMock(return_value=mock_session)
        mgr.disconnect = AsyncMock()

        proxy = ProxyServer(mgr)
        result = await proxy._call_tool("weather__get_weather", {})

        assert result[0].text == "ok"
        assert call_count["n"] == 2
        mgr.disconnect.assert_awaited_once_with("weather")

    @pytest.mark.asyncio
    async def test_exhausted_retries_raises_upstream_error(self):
        configs = [
            ServerConfig(
                name="weather",
                transport=TransportType.HTTP,
                url="http://weather:8080",
                max_retries=1,
                retry_delay_seconds=0.01,
                timeout_seconds=5.0,
                allow_insecure=True,
            ),
        ]
        mgr = ServerManager(configs)

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(
            side_effect=TransportConnectionError("down", server_name="weather")
        )
        mgr.get_session = AsyncMock(return_value=mock_session)
        mgr.disconnect = AsyncMock()

        proxy = ProxyServer(mgr)
        with pytest.raises(UpstreamError, match="failed after 2 attempts"):
            await proxy._call_tool("weather__get_weather", {})

    @pytest.mark.asyncio
    async def test_timeout_raises_upstream_error(self):
        configs = [
            ServerConfig(
                name="weather",
                transport=TransportType.HTTP,
                url="http://weather:8080",
                max_retries=0,
                timeout_seconds=0.01,
                allow_insecure=True,
            ),
        ]
        mgr = ServerManager(configs)

        mock_session = AsyncMock()

        async def slow_call(name, args):
            await asyncio.sleep(10)

        mock_session.call_tool = AsyncMock(side_effect=slow_call)
        mgr.get_session = AsyncMock(return_value=mock_session)

        proxy = ProxyServer(mgr)
        with pytest.raises(UpstreamError, match="failed after 1 attempts"):
            await proxy._call_tool("weather__get_weather", {})


class TestProxyServerWithPipeline:
    @pytest.mark.asyncio
    async def test_denied_by_pipeline(self):
        mgr = ServerManager(make_configs())

        mock_pipeline = AsyncMock(spec=Pipeline)
        deny_request = RequestContext()
        deny_ctx = HookContext(
            request=deny_request,
            policy_decision=PolicyDecision.DENY,
            short_circuit_reason="blocked by policy",
        )
        mock_pipeline.execute = AsyncMock(
            return_value=PipelineResult(context=deny_ctx, success=False)
        )

        proxy = ProxyServer(mgr, pipeline=mock_pipeline)
        result = await proxy._call_tool("weather__get_weather", {})

        assert len(result) == 1
        assert "Access denied" in result[0].text
        assert deny_request.correlation_id in result[0].text
        # Policy internals must NOT leak to the client
        assert "blocked by policy" not in result[0].text

    @pytest.mark.asyncio
    async def test_deny_response_includes_correlation_id(self):
        mgr = ServerManager(make_configs())

        mock_pipeline = AsyncMock(spec=Pipeline)
        deny_request = RequestContext()
        deny_ctx = HookContext(
            request=deny_request,
            policy_decision=PolicyDecision.DENY,
            short_circuit_reason="internal reason",
        )
        mock_pipeline.execute = AsyncMock(
            return_value=PipelineResult(context=deny_ctx, success=False)
        )

        proxy = ProxyServer(mgr, pipeline=mock_pipeline)
        result = await proxy._call_tool("weather__get_weather", {})

        expected = f"Access denied (correlation_id={deny_request.correlation_id})"
        assert result[0].text == expected

    @pytest.mark.asyncio
    async def test_pipeline_runs_post_hooks(self):
        mgr = ServerManager(make_configs())

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=make_call_result("ok"))
        mgr.get_session = AsyncMock(return_value=mock_session)

        mock_pipeline = AsyncMock(spec=Pipeline)

        async def passthrough_execute(ctx):
            return PipelineResult(context=ctx, success=True)

        mock_pipeline.execute = AsyncMock(side_effect=passthrough_execute)

        proxy = ProxyServer(mgr, pipeline=mock_pipeline)
        result = await proxy._call_tool("weather__get_weather", {})

        assert result[0].text == "ok"
        # execute called twice: pre and post pipeline
        assert mock_pipeline.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_post_pipeline_failure_blocks_response(self):
        """When post-pipeline fails (e.g. output masking error), client gets error."""
        mgr = ServerManager(make_configs())

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=make_call_result("sensitive"))
        mgr.get_session = AsyncMock(return_value=mock_session)

        call_count = {"n": 0}

        async def execute_side_effect(ctx):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Pre-pipeline succeeds
                return PipelineResult(context=ctx, success=True)
            # Post-pipeline fails (masking failure)
            return PipelineResult(
                context=ctx.evolve(short_circuited=True),
                success=False,
            )

        mock_pipeline = AsyncMock(spec=Pipeline)
        mock_pipeline.execute = AsyncMock(side_effect=execute_side_effect)

        proxy = ProxyServer(mgr, pipeline=mock_pipeline)
        result = await proxy._call_tool("weather__get_weather", {})

        assert len(result) == 1
        assert "Response blocked" in result[0].text
        # Client must NOT receive the original sensitive data
        assert "sensitive" not in result[0].text

    @pytest.mark.asyncio
    async def test_post_pipeline_returns_masked_content(self):
        """Post-pipeline masked response_payload is used to rebuild content."""
        mgr = ServerManager(make_configs())

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(
            return_value=make_call_result("Hello John Doe at john@example.com")
        )
        mgr.get_session = AsyncMock(return_value=mock_session)

        call_count = {"n": 0}

        async def execute_side_effect(ctx):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return PipelineResult(context=ctx, success=True)
            # Post-pipeline masks the response
            masked_payload = {
                "content": [{"type": "text", "text": "Hello <PERSON> at <EMAIL_ADDRESS>"}],
                "isError": False,
            }
            return PipelineResult(
                context=ctx.evolve(
                    response_payload=masked_payload,
                    output_masking_applied=True,
                ),
                success=True,
            )

        mock_pipeline = AsyncMock(spec=Pipeline)
        mock_pipeline.execute = AsyncMock(side_effect=execute_side_effect)

        proxy = ProxyServer(mgr, pipeline=mock_pipeline)
        result = await proxy._call_tool("weather__get_weather", {})

        assert len(result) == 1
        assert result[0].text == "Hello <PERSON> at <EMAIL_ADDRESS>"


class TestProxyServerWithAuth:
    @pytest.mark.asyncio
    async def test_injects_auth_token(self):
        mgr = ServerManager(make_configs())

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=make_call_result("authed"))
        mgr.get_session = AsyncMock(return_value=mock_session)

        mock_auth = AsyncMock(spec=AuthProvider)
        mock_auth.get_token = AsyncMock(return_value="obo-token-123")

        proxy = ProxyServer(mgr, auth_provider=mock_auth)
        result = await proxy._call_tool("weather__get_weather", {})

        assert result[0].text == "authed"
        # Verify auth token was passed to get_session
        call_kwargs = mgr.get_session.call_args[1]
        assert call_kwargs["auth_token"] == "obo-token-123"

    @pytest.mark.asyncio
    async def test_uses_enriched_context_from_pipeline(self):
        """Auth provider receives the pipeline-enriched context, not the original."""
        mgr = ServerManager(make_configs())

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=make_call_result("ok"))
        mgr.get_session = AsyncMock(return_value=mock_session)

        # Pipeline enriches context with identity and raw_token
        enriched_request = RequestContext(
            identity=UserIdentity(user_id="user-1"),
            raw_token="enriched-jwt",
        )
        enriched_ctx = HookContext(
            request=enriched_request,
            policy_decision=PolicyDecision.PENDING,
        )
        mock_pipeline = AsyncMock(spec=Pipeline)
        mock_pipeline.execute = AsyncMock(
            return_value=PipelineResult(context=enriched_ctx, success=True)
        )

        captured_context = {}

        async def capture_get_token(server_name, context):
            captured_context["ctx"] = context
            return None

        mock_auth = AsyncMock(spec=AuthProvider)
        mock_auth.get_token = AsyncMock(side_effect=capture_get_token)

        proxy = ProxyServer(mgr, pipeline=mock_pipeline, auth_provider=mock_auth)
        await proxy._call_tool("weather__get_weather", {})

        # Auth provider should have received the enriched context
        assert captured_context["ctx"].raw_token == "enriched-jwt"
        assert captured_context["ctx"].identity is not None
        assert captured_context["ctx"].identity.user_id == "user-1"

    @pytest.mark.asyncio
    async def test_token_exchange_error_returns_denial(self):
        mgr = ServerManager(make_configs())

        mock_auth = AsyncMock(spec=AuthProvider)
        mock_auth.get_token = AsyncMock(
            side_effect=TokenExchangeError("exchange failed", audience="api://weather")
        )

        proxy = ProxyServer(mgr, auth_provider=mock_auth)
        result = await proxy._call_tool("weather__get_weather", {})

        assert len(result) == 1
        assert "denied" in result[0].text.lower()
        assert "exchange failed" in result[0].text
