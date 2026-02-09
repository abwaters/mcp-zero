"""Main application module."""

from __future__ import annotations

import logging
import os

import uvicorn

from mcp_zero.proxy.app import create_app
from mcp_zero.proxy.proxy_server import ProxyServer
from mcp_zero.proxy.server_manager import ServerManager
from mcp_zero.transport.config import ServerConfig, TransportType

logger = logging.getLogger(__name__)


def _load_server_configs() -> list[ServerConfig]:
    """Load upstream server configs.

    Currently reads a single ``MCP_UPSTREAM_URL`` env var.
    Epic 3 will replace this with a YAML/JSON policy file loader.
    """
    url = os.environ.get("MCP_UPSTREAM_URL")
    if not url:
        return []
    return [
        ServerConfig(
            name="default",
            transport=TransportType.HTTP,
            url=url,
        )
    ]


def run() -> None:
    """Start the MCP gateway."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    configs = _load_server_configs()
    if not configs:
        logger.info("No upstream servers configured — starting in pass-through mode")

    server_manager = ServerManager(configs)
    proxy_server = ProxyServer(server_manager)
    app = create_app(proxy_server, server_manager)

    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8080"))

    logger.info("Starting mcp-zero gateway on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port)
