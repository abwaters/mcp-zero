"""Minimal MCP server over stdio for integration testing.

Provides tools designed to exercise each gateway capability:

- ``echo``: Returns whatever text is sent (baseline happy path).
- ``greet``: Returns a greeting containing a person's name (output PII testing).
- ``get_secret_data``: Returns text with PII entities (output masking validation).
- ``reverse``: Returns reversed text (multi-tool / session-reuse testing).

Run directly:  python tests/fixtures/echo_server.py
"""

from __future__ import annotations

import asyncio

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


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
            # Deliberately returns text containing PII entities.
            return [
                TextContent(
                    type="text",
                    text=("Contact John Smith at john.smith@example.com or call 555-123-4567."),
                )
            ]

        if name == "reverse":
            text = arguments.get("text", "")
            return [TextContent(type="text", text=text[::-1])]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return server


async def main() -> None:
    server = _build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
