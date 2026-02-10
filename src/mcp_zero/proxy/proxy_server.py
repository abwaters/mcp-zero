"""Core MCP proxy server — routes tool calls to upstream servers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

from mcp_zero.context import HookContext, PolicyDecision, RequestContext
from mcp_zero.identity.errors import TokenExchangeError
from mcp_zero.pipeline import Pipeline
from mcp_zero.proxy.auth import AuthProvider, NoAuthProvider
from mcp_zero.proxy.errors import ProxyTimeoutError, UpstreamError
from mcp_zero.proxy.middleware import auth_header_var
from mcp_zero.proxy.server_manager import ServerManager
from mcp_zero.proxy.tool_router import namespace_tools, parse_tool
from mcp_zero.transport.errors import TransportConnectionError, TransportTimeoutError

logger = logging.getLogger(__name__)


class ProxyServer:
    """MCP proxy that aggregates tools from upstream servers and routes calls.

    Uses the MCP SDK's low-level Server for full control over handler behavior.
    """

    def __init__(
        self,
        server_manager: ServerManager,
        *,
        pipeline: Pipeline | None = None,
        auth_provider: AuthProvider | None = None,
    ) -> None:
        self._server_manager = server_manager
        self._pipeline = pipeline
        self._auth_provider = auth_provider or NoAuthProvider()

        self._mcp_server = Server("mcp-zero-proxy")
        self._register_handlers()

    @property
    def mcp_server(self) -> Server:
        """Return the underlying MCP Server for wiring into a transport."""
        return self._mcp_server

    def _register_handlers(self) -> None:
        @self._mcp_server.list_tools()
        async def handle_list_tools() -> list[types.Tool]:
            return await self._list_tools()

        @self._mcp_server.call_tool()
        async def handle_call_tool(
            name: str, arguments: dict[str, Any] | None
        ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
            return await self._call_tool(name, arguments)

    async def _list_tools(self) -> list[types.Tool]:
        """Query all upstream servers and aggregate their tools with namespace prefixes."""
        all_tools: list[types.Tool] = []
        for server_name in self._server_manager.server_names:
            try:
                session = await self._server_manager.get_session(server_name)
                result = await session.list_tools()
                all_tools.extend(namespace_tools(server_name, result.tools))
            except Exception:
                logger.warning("Failed to list tools from '%s'", server_name, exc_info=True)
        return all_tools

    async def _call_tool(
        self, namespaced_name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Route a tool call to the correct upstream server."""
        context = RequestContext()
        server_name, tool_name = parse_tool(namespaced_name)
        config = self._server_manager.get_config(server_name)

        # Build hook context and run pre-pipeline
        hook_ctx = HookContext(
            request=context,
            server_name=server_name,
            tool_name=tool_name,
            request_payload={"arguments": arguments or {}},
            extras={"authorization": auth_header_var.get("")},
            transport=config.transport.value,
        )

        if self._pipeline:
            result = await self._pipeline.execute(hook_ctx)
            hook_ctx = result.context
            if hook_ctx.policy_decision == PolicyDecision.DENY:
                correlation_id = hook_ctx.request.correlation_id
                logger.warning(
                    "Request denied: %s (correlation_id=%s, server=%s, tool=%s)",
                    hook_ctx.short_circuit_reason,
                    correlation_id,
                    server_name,
                    tool_name,
                )
                return [
                    types.TextContent(
                        type="text",
                        text=f"Access denied (correlation_id={correlation_id})",
                    )
                ]

        # Use enriched context (has identity + raw_token after pipeline)
        context = hook_ctx.request

        # Get auth token
        try:
            auth_token = await self._auth_provider.get_token(server_name, context)
        except TokenExchangeError as exc:
            logger.warning("Token exchange failed for '%s': %s", server_name, exc)
            return [
                types.TextContent(
                    type="text",
                    text=f"Request denied: token exchange failed "
                    f"(correlation_id={context.correlation_id}): {exc}",
                )
            ]

        # Call upstream with retries
        last_error: Exception | None = None
        for attempt in range(config.max_retries + 1):
            try:
                session = await self._server_manager.get_session(
                    server_name, context, auth_token=auth_token
                )
                upstream_result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments),
                    timeout=config.timeout_seconds,
                )

                # Run post-pipeline (output masking + audit hooks)
                if self._pipeline:
                    response_payload = {
                        "content": [c.model_dump() for c in upstream_result.content],
                        "isError": upstream_result.isError,
                    }
                    post_ctx = hook_ctx.evolve(response_payload=response_payload)
                    post_result = await self._pipeline.execute(post_ctx)

                    if not post_result.success:
                        # Fail-closed: never return unmasked data to client
                        cid = context.correlation_id
                        logger.warning(
                            "Output masking failed — blocking response "
                            "(correlation_id=%s, server=%s, tool=%s)",
                            cid,
                            server_name,
                            tool_name,
                        )
                        return [
                            types.TextContent(
                                type="text",
                                text=f"Response blocked: output processing failed "
                                f"(correlation_id={cid})",
                            )
                        ]

                    # Rebuild content from the (potentially masked) payload
                    return _rebuild_content(post_result.context.response_payload)

                return list(upstream_result.content)

            except asyncio.TimeoutError:
                last_error = ProxyTimeoutError(
                    f"Upstream '{server_name}' timed out after {config.timeout_seconds}s",
                    server_name=server_name,
                    correlation_id=context.correlation_id,
                )
            except (TransportConnectionError, TransportTimeoutError) as exc:
                last_error = exc
                # Disconnect so next attempt gets a fresh transport
                await self._server_manager.disconnect(server_name)

            if attempt < config.max_retries:
                delay = config.retry_delay_seconds * (2**attempt)
                logger.info(
                    "Retrying '%s' (attempt %d/%d) after %.1fs",
                    server_name,
                    attempt + 1,
                    config.max_retries,
                    delay,
                )
                await asyncio.sleep(delay)

        # All retries exhausted
        raise UpstreamError(
            f"Upstream '{server_name}' failed after {config.max_retries + 1} attempts: "
            f"{last_error}",
            server_name=server_name,
            correlation_id=context.correlation_id,
        )


def _rebuild_content(
    payload: dict[str, Any],
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Reconstruct MCP content objects from a (potentially masked) response payload."""
    content_items: list[types.TextContent | types.ImageContent | types.EmbeddedResource] = []
    for item in payload.get("content", []):
        item_type = item.get("type")
        if item_type == "text":
            content_items.append(types.TextContent.model_validate(item))
        elif item_type == "image":
            content_items.append(types.ImageContent.model_validate(item))
        elif item_type == "resource":
            content_items.append(types.EmbeddedResource.model_validate(item))
        else:
            # Unknown content type — pass through as text fallback
            content_items.append(types.TextContent(type="text", text=str(item)))
    return content_items
