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
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route


def _build_server() -> Server:
    server = Server("echo-test-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="echo",
                description="Returns the input text unchanged.",
                inputSchema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            ),
            Tool(
                name="greet",
                description="Returns a greeting for the given name.",
                inputSchema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            ),
            Tool(
                name="get_secret_data",
                description="Returns text containing PII for masking tests.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="reverse",
                description="Returns the input text reversed.",
                inputSchema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
        arguments = arguments or {}

        if name == "echo":
            text = arguments.get("text", "")
            return [TextContent(type="text", text=text)]

        if name == "greet":
            person_name = arguments.get("name", "World")
            return [TextContent(type="text", text=f"Hello, {person_name}!")]

        if name == "get_secret_data":
            return [
                TextContent(
                    type="text",
                    text="Contact John Smith at john.smith@example.com or call 555-123-4567.",
                )
            ]

        if name == "reverse":
            text = arguments.get("text", "")
            return [TextContent(type="text", text=text[::-1])]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return server


def create_sse_app() -> Starlette:
    """Build a Starlette ASGI app that serves the echo server over SSE."""
    server = _build_server()
    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> None:
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    async def handle_messages(request: Request) -> None:
        await sse_transport.handle_post_message(request.scope, request.receive, request._send)

    async def health(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    return Starlette(
        routes=[
            Route("/health", endpoint=health),
            Route("/sse", endpoint=handle_sse),
            Route("/messages/", endpoint=handle_messages, methods=["POST"]),
        ],
    )


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9090
    app = create_sse_app()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
