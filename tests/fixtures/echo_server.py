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
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)


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
        # Deliberately returns text containing PII entities.
        content = [
            TextContent(
                type="text",
                text=("Contact John Smith at john.smith@example.com or call 555-123-4567."),
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


async def main() -> None:
    server = _build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
