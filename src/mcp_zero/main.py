"""Main application module."""

from __future__ import annotations

import atexit
import logging
import os
import sys

import uvicorn

from mcp_zero.analytics import AnalyticsConfig, AnalyticsHook
from mcp_zero.analytics.client import RedisAnalyticsClient
from mcp_zero.analytics.collector import AnalyticsCollector
from mcp_zero.analytics.config import RedisConfig
from mcp_zero.audit import AuditHook
from mcp_zero.events.bus import EventBus
from mcp_zero.governance import GovernanceHook, PolicyConfig, PolicyEffect, PolicyEngine
from mcp_zero.governance.errors import GovernanceError
from mcp_zero.governance.loader import (
    convert_to_identity_config,
    convert_to_server_configs,
    load_policy_file,
)
from mcp_zero.identity import IdentityConfig, IdentityHook, JWKSClient, JWTValidator
from mcp_zero.identity.obo import OBOClient, OBOConfig
from mcp_zero.logging import configure_logging
from mcp_zero.pipeline import HookRegistry, Pipeline
from mcp_zero.plugin_manager import PluginManager
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


def _is_strict_security() -> bool:
    """Return True when ``MCP_STRICT_SECURITY`` env var is truthy.

    When enabled, the gateway requires **both** identity and governance
    to be active (ENFORCING posture).  This is a production hardening
    flag that is not overridable by ``MCP_ALLOW_INSECURE``.
    """
    return os.environ.get("MCP_STRICT_SECURITY", "").strip().lower() in ("1", "true", "yes")


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


def _build_analytics_config(policy_config: PolicyConfig | None) -> AnalyticsConfig | None:
    """Build an AnalyticsConfig from policy file and/or environment variables.

    Environment variables override policy file values.  Analytics is enabled
    when a Redis URL is configured via either source.
    """
    # Start from policy file config or defaults
    if policy_config is not None and policy_config.analytics is not None:
        config = policy_config.analytics
    else:
        config = None

    # Check env var overrides
    redis_url = os.environ.get("ANALYTICS_REDIS_URL", "")
    if not redis_url and (config is None or not config.redis.url):
        return None  # Analytics not configured

    # Build Redis config with env var overrides
    base_redis = config.redis if config else RedisConfig()
    redis_config = RedisConfig(
        url=redis_url or base_redis.url,
        cluster=_env_bool("ANALYTICS_REDIS_CLUSTER", base_redis.cluster),
        tls=base_redis.tls,
        password=os.environ.get("ANALYTICS_REDIS_PASSWORD", base_redis.password),
        socket_timeout=base_redis.socket_timeout,
        retry_on_timeout=base_redis.retry_on_timeout,
    )

    env_default = config.environment if config else "default"
    gw_default = config.gateway_id if config else ""
    prefix_default = config.key_prefix if config else "mcpgw"
    retention_default = config.retention_seconds if config else 3600

    return AnalyticsConfig(
        redis=redis_config,
        environment=os.environ.get("ANALYTICS_ENVIRONMENT", env_default),
        gateway_id=os.environ.get("ANALYTICS_GATEWAY_ID", gw_default),
        key_prefix=os.environ.get("ANALYTICS_KEY_PREFIX", prefix_default),
        bucket_seconds=config.bucket_seconds if config else 60,
        retention_seconds=int(
            os.environ.get(
                "ANALYTICS_RETENTION_SECONDS",
                str(retention_default),
            )
        ),
        heartbeat_seconds=config.heartbeat_seconds if config else 30,
        queue_size=config.queue_size if config else 10000,
        flush_interval=config.flush_interval if config else 1.0,
    )


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean from an env var, falling back to *default*."""
    val = os.environ.get(name, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes")


def _build_pipeline(
    identity_config: IdentityConfig | None = None,
    policy_config: PolicyConfig | None = None,
    analytics_collector: AnalyticsCollector | None = None,
) -> tuple[Pipeline | None, PluginManager]:
    """Build a Pipeline with identity, governance, masking, analytics, and audit hooks.

    Identity and governance hooks are only registered when their configuration
    is present.  Masking and audit hooks are registered whenever a policy file
    is loaded, even without identity — so data protection works in local/demo
    setups that don't use OAuth2.

    If *identity_config* is provided (from a policy file), it is used directly.
    Otherwise falls back to ``OKTA_ISSUER`` / ``OKTA_AUDIENCE`` env vars.

    Returns:
        A tuple of (pipeline, plugin_manager).  The pipeline may be ``None``
        when no identity or policy configuration is found.
    """
    registry = HookRegistry()
    plugin_manager = PluginManager()
    event_bus = EventBus()
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
                "OKTA_ISSUER set but OKTA_AUDIENCE missing — identity validation disabled. "
                "This is a misconfiguration: set OKTA_AUDIENCE to enable identity validation."
            )

    if identity_config is not None:
        jwks_client = JWKSClient(identity_config)
        validator = JWTValidator(identity_config, jwks_client)
        identity_hook = IdentityHook(validator)
        registry.register(identity_hook, priority=10)
        identity_enabled = True
        logger.info("Identity validation enabled (issuer=%s)", identity_config.issuer)
    else:
        if policy_config is not None:
            logger.warning(
                "SECURITY POSTURE: Governance policy loaded WITHOUT identity validation. "
                "All requests will be evaluated as 'anonymous'. "
                "Configure identity (OKTA_ISSUER + OKTA_AUDIENCE or policy identity section) "
                "for authenticated access control."
            )
        else:
            logger.info("Identity validation disabled — no identity configuration found")

    # --- Governance hook (requires policy file) ---
    if policy_config is not None:
        engine = PolicyEngine(policy_config)
        governance_hook = GovernanceHook(engine, identity_required=identity_enabled)
        registry.register(governance_hook, priority=50)
        logger.info("Governance policy enforcement enabled (%d rules)", len(policy_config.policies))

    # --- Plugins (loaded from policy file declarations) ---
    if policy_config is not None and policy_config.plugins:
        plugin_manager.load_plugins(policy_config.plugins, registry, event_bus=event_bus)
        logger.info("Loaded %d plugin(s)", len(policy_config.plugins))

    # --- Analytics hook (optional, requires collector) ---
    if analytics_collector is not None:
        analytics_hook = AnalyticsHook(analytics_collector)
        registry.register(analytics_hook, priority=145)
        logger.info("Analytics hook registered")

    # --- Audit hook (always registered when pipeline exists) ---
    logging_config = policy_config.logging if policy_config else None
    audit_hook = AuditHook(logging_config=logging_config, event_bus=event_bus)
    registry.register(audit_hook, priority=150)

    if event_bus.handler_count > 0:
        logger.info("Event bus active with %d handler(s)", event_bus.handler_count)

    # Only build the pipeline if at least one functional hook was registered
    if not identity_enabled and policy_config is None:
        logger.warning("No identity or policy configuration — pipeline disabled")
        return None, plugin_manager

    registry.build()
    return Pipeline(registry), plugin_manager


def _build_obo_provider(
    configs: list[ServerConfig],
    *,
    identity_enabled: bool = True,
) -> AuthProvider | None:
    """Build an OBOAuthProvider when Okta OBO env vars are set.

    Reads ``OKTA_TOKEN_ENDPOINT``, ``OKTA_CLIENT_ID``, and ``OKTA_CLIENT_SECRET``.
    Returns ``None`` if any are missing or no servers have ``token_exchange`` enabled.

    Raises:
        SystemExit: If servers require OBO but identity pipeline is disabled
            and ``MCP_ALLOW_INSECURE`` is not set.
    """
    token_endpoint = os.environ.get("OKTA_TOKEN_ENDPOINT", "")
    client_id = os.environ.get("OKTA_CLIENT_ID", "")
    client_secret = os.environ.get("OKTA_CLIENT_SECRET", "")

    obo_servers = [c.name for c in configs if c.token_exchange]

    # Validate that OBO-enabled servers have a functioning identity pipeline
    if obo_servers and not identity_enabled:
        if not _is_insecure_allowed():
            logger.critical(
                "REFUSING TO START: Server(s) %s have token_exchange enabled but the "
                "identity pipeline is disabled. OBO token exchange requires authenticated "
                "user tokens — without identity validation, OBO will always fail. "
                "Configure identity (OKTA_ISSUER + OKTA_AUDIENCE or policy identity "
                "section), or set MCP_ALLOW_INSECURE=true (dev only).",
                obo_servers,
            )
            sys.exit(78)
        else:
            logger.warning(
                "Server(s) %s have token_exchange enabled but identity pipeline is "
                "disabled. OBO exchanges will fail at runtime for these servers.",
                obo_servers,
            )

    if not all([token_endpoint, client_id, client_secret]):
        # Check if any server actually needs OBO
        if obo_servers:
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

    # Build analytics collector (optional — enabled when Redis URL is configured)
    analytics_config = _build_analytics_config(policy_config)
    analytics_collector: AnalyticsCollector | None = None
    if analytics_config is not None and analytics_config.enabled:
        redis_client = RedisAnalyticsClient(analytics_config.redis)
        analytics_collector = AnalyticsCollector(analytics_config, redis_client)
        logger.info(
            "Analytics enabled: redis=%s, env=%s, gw=%s, retention=%ds",
            analytics_config.redis.url,
            analytics_config.environment,
            analytics_config.gateway_id,
            analytics_config.retention_seconds,
        )
    else:
        logger.info("Analytics disabled — no Redis URL configured")

    # Build pipeline with identity + governance + plugin hooks
    pipeline, plugin_manager = _build_pipeline(identity_config, policy_config, analytics_collector)
    atexit.register(plugin_manager.teardown_all)

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

    # Refuse startup on partial identity misconfiguration: OKTA_ISSUER is set
    # but OKTA_AUDIENCE is missing while a policy file is loaded.  This is almost
    # certainly a deployment mistake — the operator intended to enable identity
    # but the gateway would silently run without it (see F-03).
    if (
        policy_config is not None
        and identity_config is None
        and os.environ.get("OKTA_ISSUER", "")
        and not os.environ.get("OKTA_AUDIENCE", "")
        and not _is_insecure_allowed()
    ):
        logger.critical(
            "REFUSING TO START: OKTA_ISSUER is set but OKTA_AUDIENCE is missing. "
            "The gateway has a policy file but cannot enable identity validation — "
            "this is a misconfiguration. Set OKTA_AUDIENCE, or remove OKTA_ISSUER, "
            "or set MCP_ALLOW_INSECURE=true to start without identity (dev only)."
        )
        sys.exit(78)

    # Identity can be configured via policy file OR env vars (OKTA_ISSUER + OKTA_AUDIENCE).
    # Computed once — used by OBO validation (F-04), tool-listing auth (F-06), and startup summary.
    identity_enabled = identity_config is not None or (
        bool(os.environ.get("OKTA_ISSUER", "")) and bool(os.environ.get("OKTA_AUDIENCE", ""))
    )
    governance_active = policy_config is not None

    # Strict security mode (MZ-02): require BOTH identity AND governance
    # to be active (ENFORCING posture).  This is a production hardening
    # flag — not overridable by MCP_ALLOW_INSECURE.
    if _is_strict_security():
        if not identity_enabled or not governance_active:
            missing = []
            if not identity_enabled:
                missing.append("identity")
            if not governance_active:
                missing.append("governance")
            logger.critical(
                "REFUSING TO START: MCP_STRICT_SECURITY requires both identity and "
                "governance to be active (ENFORCING posture), but %s is not configured. "
                "Provide a policy file with identity section, or unset MCP_STRICT_SECURITY.",
                " and ".join(missing),
            )
            sys.exit(78)

    # Block default:allow + no identity (MZ-02): a policy that defaults to
    # 'allow' with no identity validation means every anonymous request is
    # permitted — the gateway *appears* governed but is effectively wide open.
    if (
        policy_config is not None
        and policy_config.default == PolicyEffect.ALLOW
        and not identity_enabled
        and not _is_insecure_allowed()
    ):
        logger.critical(
            "REFUSING TO START: Policy has 'default: allow' but no identity validation "
            "is configured. Every anonymous request would be allowed — this is almost "
            "certainly a deployment mistake. Configure identity (OKTA_ISSUER + OKTA_AUDIENCE "
            "or policy identity section), change the default to 'deny', or set "
            "MCP_ALLOW_INSECURE=true (dev/testing only)."
        )
        sys.exit(78)

    # Build OBO auth provider when Okta OBO env vars are set (F-04)
    auth_provider = _build_obo_provider(configs, identity_enabled=identity_enabled)

    # Build policy engine for tool-listing authorization (F-06)
    policy_engine = PolicyEngine(policy_config) if policy_config else None

    sse_enabled = _env_bool("MCP_SSE_ENABLED", default=True)

    server_manager = ServerManager(configs)
    proxy_server = ProxyServer(
        server_manager,
        pipeline=pipeline,
        auth_provider=auth_provider,
        policy_engine=policy_engine,
        identity_required=identity_enabled,
    )
    app = create_app(
        proxy_server,
        server_manager,
        analytics_collector=analytics_collector,
        sse_enabled=sse_enabled,
    )

    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8080"))

    # Startup summary — shows what's active at a glance for debugging
    fmt = os.environ.get("LOG_FORMAT", "json").strip().lower()
    if policy_config and policy_config.logging:
        fmt = policy_config.logging.format
    analytics_active = analytics_collector is not None
    plugin_count = len(plugin_manager.loaded_plugins)

    identity_active = pipeline is not None and identity_config is not None

    # Emit security posture at appropriate level
    if identity_active and governance_active:
        logger.info(
            "SECURITY POSTURE [ENFORCING]: identity=enabled, governance=enabled (%d rules)",
            len(policy_config.policies),
        )
    elif governance_active and not identity_active:
        logger.warning(
            "SECURITY POSTURE [DEGRADED]: identity=disabled, governance=enabled (%d rules). "
            "Policy rules will evaluate with anonymous identity.",
            len(policy_config.policies),
        )
    elif _is_insecure_allowed():
        logger.warning(
            "SECURITY POSTURE [INSECURE]: identity=disabled, governance=disabled. "
            "All requests proxied without security controls (MCP_ALLOW_INSECURE=true).",
        )

    logger.info(
        "Gateway ready: servers=%d, identity=%s, governance=%s, "
        "analytics=%s, plugins=%d, sse=%s, log_format=%s, log_level=%s",
        len(configs),
        "enabled" if identity_active else "disabled",
        "enabled (%d rules)" % len(policy_config.policies) if policy_config else "disabled",
        "enabled" if analytics_active else "disabled",
        plugin_count,
        "enabled" if sse_enabled else "disabled",
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
