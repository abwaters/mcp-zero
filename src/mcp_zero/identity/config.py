"""Identity provider configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

from mcp_zero.url_validation import require_https


@dataclass(frozen=True)
class ClaimMapping:
    """Maps JWT claims to internal identity fields."""

    user_id: str = "sub"
    email: str = "email"
    groups: str = "groups"


@dataclass(frozen=True)
class IdentityConfig:
    """Configuration for the identity provider.

    Args:
        provider: Identity provider name (e.g. "okta").
        issuer: Token issuer URL (required).
        audience: Expected audience claim (required).
        jwks_cache_ttl: Seconds to cache JWKS keys before re-fetching.
        claim_mapping: Maps JWT claims to identity fields.
    """

    provider: str = "okta"
    issuer: str = ""
    audience: str = ""
    jwks_cache_ttl: int = 3600
    claim_mapping: ClaimMapping = field(default_factory=ClaimMapping)
    allow_insecure: bool = False

    def __post_init__(self) -> None:
        if not self.issuer:
            raise ValueError("issuer is required")
        if not self.audience:
            raise ValueError("audience is required")
        if not self.allow_insecure:
            require_https(self.issuer, "issuer")
