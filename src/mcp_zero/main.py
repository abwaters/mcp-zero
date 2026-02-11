"""Main application module."""

from __future__ import annotations

import logging
import os
import sys

import uvicorn

from mcp_zero.audit import AuditHook
from mcp_zero.governance import GovernanceHook, PolicyConfig, PolicyEngine
from mcp_zero.governance.errors import GovernanceError
from mcp_zero.governance.loader import (
    convert_to_identity_config,
    convert_to_server_configs,
    load_policy_file,
)
from mcp_zero.identity import IdentityConfig, IdentityHook, JWKSClient, JWTValidator
from mcp_zero.identity.obo import OBOClient, OBOConfig
from mcp_zero.logging import configure_logging
from mcp_zero.masking import MaskingHook, PresidioMaskingEngine
from mcp_zero.pipeline import HookRegistry, Pipeline
from mcp_zero.proxy.app import create_app
from mcp_zero.proxy.auth import AuthProvider
from mcp_zero.proxy.obo_auth import OBOAuthProvider, ServerOBOSettings
from mcp_zero.proxy.proxy_server import ProxyServer
from mcp_zero.proxy.server_manager import ServerManager
from mcp_zero.transport.config import ServerConfig, TransportType

logger = logging.getLogger(__name__)


def _is_insecure_allowed() -> bool:
    """Return True when ``MCP_ALLOW_INSECURE`` env var is truthy."""
    return os.environ.get("MCP_ALLOW_INSECURE", "").strip().lower() in ("1", "true", "yes")


def _load_server_configs() -> list[ServerConfig]:
    """Load upstream server configs from ``MCP_UPSTREAM_URL`` env var.

    Legacy fallback when no policy file is configured.
    """
    url = os.environ.get("MCP_UPSTREAM_URL")
    if not url:
        return []
    return [
        ServerConfig(
            name="default",
            transport=TransportType.HTTP,
            url=url,
            allow_insecure=_is_insecure_allowed(),
        )
    ]


def _load_policy_and_configs() -> tuple[
    list[ServerConfig], IdentityConfig | None, PolicyConfig | None
]:
    """Load server configs, identity config, and policy config from policy file or env vars.

    Reads ``MCP_POLICY_FILE`` env var for the policy file path.
    If not set, falls back to legacy ``MCP_UPSTREAM_URL`` behavior.

    Returns:
        A 3-tuple of (server_configs, identity_config, policy_config).
        identity_config and policy_config are None when no policy file is
        configured or when using legacy env vars.

    Raises:
        GovernanceError: If the policy file is invalid (fail-fast at startup).
    """
    policy_file = os.environ.get("MCP_POLICY_FILE")

    if not policy_file:
        logger.info("MCP_POLICY_FILE not set — using legacy env var configuration")
        return _load_server_configs(), None, None

    try:
        policy = load_policy_file(policy_file)
    except GovernanceError:
        logger.error("Failed to load policy file: %s", policy_file)
        raise

    configs = convert_to_server_configs(policy)
    identity_config = convert_to_identity_config(policy)
    return configs, identity_config, policy


def _build_pipeline(
    identity_config: IdentityConfig | None = None,
    policy_config: PolicyConfig | None = None,
) -> Pipeline | None:
    """Build a Pipeline with identity, governance, masking, and audit hooks.

    Identity and governance hooks are only registered when their configuration
    is present.  Masking and audit hooks are registered whenever a policy file
    is loaded, even without identity — so data protection works in local/demo
    setups that don't use OAuth2.

    If *identity_config* is provided (from a policy file), it is used directly.
    Otherwise falls back to ``OKTA_ISSUER`` / ``OKTA_AUDIENCE`` env vars.
    """
    registry = HookRegistry()
    identity_enabled = False

    # --- Identity hook (optional) ---
    if identity_config is None:
        issuer = os.environ.get("OKTA_ISSUER", "")
        audience = os.environ.get("OKTA_AUDIENCE", "")

        if issuer and audience:
            identity_config = IdentityConfig(
                issuer=issuer, audience=audience, allow_insecure=_is_insecure_allowed()
            )
        elif issuer and not audience:
            logger.warning(
                "OKTA_ISSUER set but OKTA_AUDIENCE missing — identity validation disabled"
            )

    if identity_config is not None:
        jwks_client = JWKSClient(identity_config)
        validator = JWTValidator(identity_config, jwks_client)
        identity_hook = IdentityHook(validator)
        registry.register(identity_hook, priority=10)
        identity_enabled = True
        logger.info("Identity validation enabled (issuer=%s)", identity_config.issuer)
    else:
        logger.info("Identity validation disabled — no identity configuration found")

    # --- Governance hook (requires policy file) ---
    if policy_config is not None:
        engine = PolicyEngine(policy_config)
        governance_hook = GovernanceHook(engine, identity_required=identity_enabled)
        registry.register(governance_hook, priority=50)
        logger.info("Governance policy enforcement enabled (%d rules)", len(policy_config.policies))

    # --- Masking hook (requires policy file with presidio enabled) ---
    if policy_config is not None and policy_config.masking.presidio.enabled:
        masking_engine = PresidioMaskingEngine(policy_config.masking.presidio)
        masking_hook = MaskingHook(masking_engine, policy_config.masking.presidio)
        registry.register(masking_hook, priority=75)
        logger.info(
            "Presidio masking enabled (entities=%s)",
            ", ".join(policy_config.masking.presidio.entities),
        )

    # --- Audit hook (always registered when pipeline exists) ---
    logging_config = policy_config.logging if policy_config else None
    audit_hook = AuditHook(logging_config=logging_config)
    registry.register(audit_hook, priority=150)

    # Only build the pipeline if at least one functional hook was registered
    if not identity_enabled and policy_config is None:
        logger.info("No identity or policy configuration — pipeline disabled")
        return None

    registry.build()
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
        allow_insecure=_is_insecure_allowed(),
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
    configure_logging(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        fmt=os.environ.get("LOG_FORMAT", "json").strip().lower(),
    )

    if _is_insecure_allowed():
        logger.warning("MCP_ALLOW_INSECURE is set — HTTPS enforcement disabled (dev only)")

    configs, identity_config, policy_config = _load_policy_and_configs()

    # If policy specifies logging overrides, apply them
    if policy_config and policy_config.logging:
        logging.getLogger().setLevel(policy_config.logging.level.upper())
        if policy_config.logging.format != "json":
            configure_logging(
                level=policy_config.logging.level.upper(),
                fmt=policy_config.logging.format,
            )
    if not configs:
        logger.info("No upstream servers configured — starting in pass-through mode")

    # Build pipeline with identity + governance hooks
    pipeline = _build_pipeline(identity_config, policy_config)

    # Fail-closed: refuse to start without security controls unless explicitly
    # opted out via MCP_ALLOW_INSECURE.  This prevents accidentally running
    # the gateway in production without authn/authz (see issue #52).
    if pipeline is None:
        if not _is_insecure_allowed():
            logger.critical(
                "REFUSING TO START: No identity provider or policy file configured. "
                "The gateway would run without authentication, authorization, or "
                "data protection — this is not safe for production. "
                "Set MCP_POLICY_FILE to a policy file, or set MCP_ALLOW_INSECURE=true "
                "to start without security controls (dev/testing only)."
            )
            sys.exit(78)  # EX_CONFIG per sysexits.h
        else:
            logger.warning(
                "INSECURE MODE: Starting without authentication or authorization. "
                "MCP_ALLOW_INSECURE is set — all tool calls will be proxied without "
                "identity validation, governance checks, or data masking. "
                "Do NOT use this in production."
            )

    # Build OBO auth provider when Okta OBO env vars are set
    auth_provider = _build_obo_provider(configs)

    server_manager = ServerManager(configs)
    proxy_server = ProxyServer(server_manager, pipeline=pipeline, auth_provider=auth_provider)
    app = create_app(proxy_server, server_manager)

    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8080"))

    # Startup summary — shows what's active at a glance for debugging
    fmt = os.environ.get("LOG_FORMAT", "json").strip().lower()
    if policy_config and policy_config.logging:
        fmt = policy_config.logging.format
    masking_active = policy_config is not None and policy_config.masking.presidio.enabled
    logger.info(
        "Gateway ready: servers=%d, identity=%s, governance=%s, masking=%s, "
        "log_format=%s, log_level=%s",
        len(configs),
        "enabled" if pipeline else "disabled",
        "enabled (%d rules)" % len(policy_config.policies) if policy_config else "disabled",
        "enabled" if masking_active else "disabled",
        fmt,
        logging.getLogger().level,
    )

    logger.info("Starting mcp-zero gateway on %s:%d", host, port)
    uvicorn.run(
        app,
        host=host,
        port=port,
        timeout_graceful_shutdown=5,
    )
