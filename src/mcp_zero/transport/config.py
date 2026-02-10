"""Transport configuration types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from mcp_zero.url_validation import require_https


class TransportType(StrEnum):
    """Transport protocol type, matching YAML config values."""

    HTTP = "http"
    STDIO = "stdio"


@dataclass(frozen=True)
class ServerConfig:
    """Configuration for a downstream MCP server."""

    name: str
    transport: TransportType

    # HTTP transport
    url: str | None = None

    # stdio transport
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    # Process lifecycle (stdio only)
    max_restarts: int = 3
    restart_delay: float = 1.0  # seconds, base for exponential backoff

    # Timeout and retry
    timeout_seconds: float = 30.0
    max_retries: int = 2
    retry_delay_seconds: float = 1.0

    # OBO token exchange
    token_exchange: bool = False
    target_audience: str | None = None
    required_scopes: list[str] = field(default_factory=list)

    # Security
    allow_insecure: bool = False

    def __post_init__(self) -> None:
        if self.transport == TransportType.HTTP:
            if not self.url:
                raise ValueError(f"HTTP transport for '{self.name}' requires 'url'")
            if not self.allow_insecure:
                require_https(self.url, f"url for '{self.name}'")
        elif self.transport == TransportType.STDIO:
            if not self.command:
                raise ValueError(f"stdio transport for '{self.name}' requires 'command'")

        if self.token_exchange:
            if self.transport == TransportType.STDIO:
                raise ValueError(
                    f"token_exchange is not supported for stdio transport ('{self.name}')"
                )
            if not self.target_audience:
                raise ValueError(f"token_exchange for '{self.name}' requires 'target_audience'")
