"""Minimal MCP server over SSE for integration testing.

Exposes the same tools as ``echo_server.py`` but over the SSE transport
(GET ``/sse`` + POST ``/messages/``).

Run directly:  python tests/fixtures/echo_server_sse.py
"""

from __future__ import annotations

import sys

import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.sse import SseServerTransport
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route


async def _list_tools(ctx, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(
        tools=[
            Tool(
                name="echo",
                description="Returns the input text unchanged.",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            ),
            Tool(
                name="greet",
                description="Returns a greeting for the given name.",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            ),
            Tool(
                name="get_secret_data",
                description="Returns text containing PII for masking tests.",
                input_schema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="reverse",
                description="Returns the input text reversed.",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            ),
        ]
    )


async def _call_tool(ctx, params: CallToolRequestParams) -> CallToolResult:
    name = params.name
    arguments = params.arguments or {}

    if name == "echo":
        text = arguments.get("text", "")
        content = [TextContent(type="text", text=text)]
    elif name == "greet":
        person_name = arguments.get("name", "World")
        content = [TextContent(type="text", text=f"Hello, {person_name}!")]
    elif name == "get_secret_data":
        content = [
            TextContent(
                type="text",
                text="Contact John Smith at john.smith@example.com or call 555-123-4567.",
            )
        ]
    elif name == "reverse":
        text = arguments.get("text", "")
        content = [TextContent(type="text", text=text[::-1])]
    else:
        content = [TextContent(type="text", text=f"Unknown tool: {name}")]

    return CallToolResult(content=content, is_error=False)


def _build_server() -> Server:
    return Server("echo-test-server", on_list_tools=_list_tools, on_call_tool=_call_tool)


def create_sse_app() -> Starlette:
    """Build a Starlette ASGI app that serves the echo server over SSE."""
    server = _build_server()
    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> None:
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    async def health(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    return Starlette(
        routes=[
            Route("/health", endpoint=health),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages", app=sse_transport.handle_post_message),
        ],
    )


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9090
    app = create_sse_app()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
