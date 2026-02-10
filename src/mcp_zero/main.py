"""Main application module."""

from __future__ import annotations

import logging
import os

import uvicorn

from mcp_zero.identity import IdentityConfig, IdentityHook, JWKSClient, JWTValidator
from mcp_zero.identity.obo import OBOClient, OBOConfig
from mcp_zero.pipeline import HookRegistry, Pipeline
from mcp_zero.proxy.app import create_app
from mcp_zero.proxy.auth import AuthProvider
from mcp_zero.proxy.obo_auth import OBOAuthProvider, ServerOBOSettings
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


def _build_identity_pipeline() -> Pipeline | None:
    """Build a Pipeline with the IdentityHook when Okta env vars are set."""
    issuer = os.environ.get("OKTA_ISSUER", "")
    audience = os.environ.get("OKTA_AUDIENCE", "")

    if not issuer:
        logger.info("OKTA_ISSUER not set — identity validation disabled")
        return None

    if not audience:
        logger.warning("OKTA_ISSUER set but OKTA_AUDIENCE missing — identity validation disabled")
        return None

    config = IdentityConfig(issuer=issuer, audience=audience)
    jwks_client = JWKSClient(config)
    validator = JWTValidator(config, jwks_client)
    hook = IdentityHook(validator)

    registry = HookRegistry()
    registry.register(hook, priority=10)
    registry.build()

    logger.info("Identity validation enabled (issuer=%s)", issuer)
    return Pipeline(registry)


def _build_obo_provider(configs: list[ServerConfig]) -> AuthProvider | None:
    """Build an OBOAuthProvider when Okta OBO env vars are set.

    Reads ``OKTA_TOKEN_ENDPOINT``, ``OKTA_CLIENT_ID``, and ``OKTA_CLIENT_SECRET``.
    Returns ``None`` if any are missing or no servers have ``token_exchange`` enabled.
    """
    token_endpoint = os.environ.get("OKTA_TOKEN_ENDPOINT", "")
    client_id = os.environ.get("OKTA_CLIENT_ID", "")
    client_secret = os.environ.get("OKTA_CLIENT_SECRET", "")

    if not all([token_endpoint, client_id, client_secret]):
        # Check if any server actually needs OBO
        if any(c.token_exchange for c in configs):
            logger.warning(
                "Server(s) have token_exchange enabled but OKTA_TOKEN_ENDPOINT, "
                "OKTA_CLIENT_ID, or OKTA_CLIENT_SECRET not set — OBO disabled"
            )
        return None

    # Build per-server settings from ServerConfig fields
    server_settings: dict[str, ServerOBOSettings] = {}
    for cfg in configs:
        if cfg.token_exchange and cfg.target_audience:
            server_settings[cfg.name] = ServerOBOSettings(
                server_name=cfg.name,
                enabled=True,
                target_audience=cfg.target_audience,
                scopes=list(cfg.required_scopes),
            )

    if not server_settings:
        logger.info("No servers have token_exchange enabled — OBO provider not created")
        return None

    obo_config = OBOConfig(
        token_endpoint=token_endpoint,
        client_id=client_id,
        client_secret=client_secret,
    )
    obo_client = OBOClient(obo_config)
    provider = OBOAuthProvider(obo_client, server_settings)

    logger.info(
        "OBO token exchange enabled for servers: %s",
        ", ".join(server_settings.keys()),
    )
    return provider


def run() -> None:
    """Start the MCP gateway."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    configs = _load_server_configs()
    if not configs:
        logger.info("No upstream servers configured — starting in pass-through mode")

    # Build identity pipeline when Okta is configured
    pipeline = _build_identity_pipeline()

    # Build OBO auth provider when Okta OBO env vars are set
    auth_provider = _build_obo_provider(configs)

    server_manager = ServerManager(configs)
    proxy_server = ProxyServer(server_manager, pipeline=pipeline, auth_provider=auth_provider)
    app = create_app(proxy_server, server_manager)

    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8080"))

    logger.info("Starting mcp-zero gateway on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port)
