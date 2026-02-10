"""Governance policy configuration models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from mcp_zero.url_validation import require_https


class PolicyEffect(StrEnum):
    """Effect of a policy rule."""

    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class IdentityProviderConfig:
    """Identity provider section of the policy file.

    Args:
        provider: Identity provider name (e.g. "okta").
        issuer: Token issuer URL.
        audience: Expected audience claim.
        claim_mapping: Maps JWT claims to identity fields.
    """

    provider: str = ""
    issuer: str = ""
    audience: str = ""
    claim_mapping: dict[str, str] = field(default_factory=dict)
    allow_insecure: bool = False

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("identity.provider is required")
        if not self.issuer:
            raise ValueError("identity.issuer is required")
        if not self.audience:
            raise ValueError("identity.audience is required")
        if not self.allow_insecure:
            require_https(self.issuer, "identity.issuer")


@dataclass(frozen=True)
class ServerDefinition:
    """A downstream MCP server definition.

    Args:
        name: Server identifier.
        transport: Transport type ("http" or "stdio").
        url: URL for HTTP transport.
        command: Command for stdio transport.
        args: Arguments for stdio command.
        env: Environment variables for stdio.
        token_exchange: Whether to enable OBO token exchange.
        target_audience: OBO target audience.
        required_scopes: OBO required scopes.
    """

    name: str = ""
    transport: str = ""
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    token_exchange: bool = False
    target_audience: str | None = None
    required_scopes: list[str] = field(default_factory=list)
    allow_insecure: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("server.name is required")
        if self.transport not in ("http", "stdio"):
            raise ValueError(
                f"server '{self.name}' transport must be 'http' or 'stdio', got '{self.transport}'"
            )


@dataclass(frozen=True)
class PolicySubjects:
    """Subjects a policy rule applies to.

    Args:
        users: List of user identifiers.
        groups: List of group names.
    """

    users: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PolicyServerAccess:
    """Server access within a policy rule.

    Args:
        name: Server name to match.
        tools: List of tool patterns (supports wildcards).
    """

    name: str = ""
    tools: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("policy mcp_server.name is required")


@dataclass(frozen=True)
class PolicyRule:
    """A single governance policy rule.

    Args:
        id: Unique rule identifier.
        description: Human-readable description.
        effect: ALLOW or DENY.
        subjects: Who this rule applies to.
        mcp_servers: Which servers/tools this rule controls.
    """

    id: str = ""
    description: str = ""
    effect: PolicyEffect = PolicyEffect.ALLOW
    subjects: PolicySubjects = field(default_factory=PolicySubjects)
    mcp_servers: list[PolicyServerAccess] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("policy.id is required")
        if not self.description:
            raise ValueError(f"policy '{self.id}' description is required")


@dataclass(frozen=True)
class LoggingConfig:
    """Logging configuration section.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        include: List of log categories to include.
    """

    _VALID_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

    level: str = "INFO"
    include: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.level.upper() not in self._VALID_LEVELS:
            raise ValueError(
                f"logging.level must be one of {sorted(self._VALID_LEVELS)}, got '{self.level}'"
            )


@dataclass(frozen=True)
class PresidioConfig:
    """Presidio PII detection configuration.

    Args:
        enabled: Whether Presidio masking is enabled.
        entities: List of PII entity types to detect.
    """

    enabled: bool = False
    entities: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MaskingConfig:
    """Data masking configuration section.

    Args:
        presidio: Presidio PII detection settings.
    """

    presidio: PresidioConfig = field(default_factory=PresidioConfig)


@dataclass(frozen=True)
class PolicyConfig:
    """Root policy configuration.

    Args:
        version: Policy schema version (must be 1).
        default: Default policy effect (allow or deny).
        identity: Identity provider configuration.
        servers: List of downstream server definitions.
        policies: List of governance policy rules.
        logging: Logging configuration.
        masking: Data masking configuration.
    """

    version: int = 0
    default: PolicyEffect = PolicyEffect.DENY
    identity: IdentityProviderConfig | None = None
    servers: list[ServerDefinition] = field(default_factory=list)
    policies: list[PolicyRule] = field(default_factory=list)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    masking: MaskingConfig = field(default_factory=MaskingConfig)

    def __post_init__(self) -> None:
        if self.version != 1:
            raise ValueError(f"policy version must be 1, got {self.version}")
