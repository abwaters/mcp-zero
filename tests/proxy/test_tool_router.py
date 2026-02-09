"""Tests for tool router."""

import pytest
from mcp.types import Tool

from mcp_zero.proxy.errors import RoutingError
from mcp_zero.proxy.tool_router import namespace_tool, namespace_tools, parse_tool


class TestNamespaceTool:
    def test_basic(self):
        assert namespace_tool("weather", "get_forecast") == "weather__get_forecast"

    def test_server_with_hyphens(self):
        assert namespace_tool("my-server", "do_thing") == "my-server__do_thing"


class TestParseTool:
    def test_basic(self):
        server, tool = parse_tool("weather__get_forecast")
        assert server == "weather"
        assert tool == "get_forecast"

    def test_tool_with_underscores(self):
        server, tool = parse_tool("srv__get_the_weather")
        assert server == "srv"
        assert tool == "get_the_weather"

    def test_no_separator_raises(self):
        with pytest.raises(RoutingError, match="Invalid namespaced tool name"):
            parse_tool("no_separator_here")

    def test_empty_server_raises(self):
        with pytest.raises(RoutingError, match="Invalid namespaced tool name"):
            parse_tool("__tool")

    def test_empty_tool_raises(self):
        with pytest.raises(RoutingError, match="Invalid namespaced tool name"):
            parse_tool("server__")

    def test_roundtrip(self):
        name = namespace_tool("srv", "fn")
        server, tool = parse_tool(name)
        assert server == "srv"
        assert tool == "fn"


class TestNamespaceTools:
    def test_prefixes_all_tools(self):
        tools = [
            Tool(name="get_weather", description="Get weather", inputSchema={"type": "object"}),
            Tool(name="get_time", description="Get time", inputSchema={"type": "object"}),
        ]
        result = namespace_tools("weather-srv", tools)
        assert len(result) == 2
        assert result[0].name == "weather-srv__get_weather"
        assert result[1].name == "weather-srv__get_time"

    def test_preserves_description_and_schema(self):
        schema = {"type": "object", "properties": {"city": {"type": "string"}}}
        tools = [Tool(name="get", description="desc", inputSchema=schema)]
        result = namespace_tools("srv", tools)
        assert result[0].description == "desc"
        assert result[0].inputSchema == schema

    def test_empty_list(self):
        assert namespace_tools("srv", []) == []
