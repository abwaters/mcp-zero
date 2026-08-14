"""Tool routing via server__tool namespacing."""

from __future__ import annotations

from mcp.types import Tool

from mcp_zero.proxy.errors import RoutingError

SEPARATOR = "__"


def namespace_tool(server_name: str, tool_name: str) -> str:
    """Return a namespaced tool name: ``{server_name}__{tool_name}``."""
    return f"{server_name}{SEPARATOR}{tool_name}"


def parse_tool(namespaced_name: str) -> tuple[str, str]:
    """Parse a namespaced tool name into ``(server_name, tool_name)``.

    Raises RoutingError if the name does not contain the separator.
    """
    parts = namespaced_name.split(SEPARATOR, maxsplit=1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise RoutingError(
            f"Invalid namespaced tool name: '{namespaced_name}' (expected 'server{SEPARATOR}tool')",
        )
    return parts[0], parts[1]


def namespace_tools(server_name: str, tools: list[Tool]) -> list[Tool]:
    """Return copies of *tools* with their names prefixed by *server_name*."""
    # model_copy preserves all fields (input_schema, annotations, output_schema,
    # etc.) while only rewriting the name.
    return [
        tool.model_copy(update={"name": namespace_tool(server_name, tool.name)}) for tool in tools
    ]
