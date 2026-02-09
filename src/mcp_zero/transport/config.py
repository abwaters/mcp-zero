"""Transport configuration types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


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

    def __post_init__(self) -> None:
        if self.transport == TransportType.HTTP:
            if not self.url:
                raise ValueError(f"HTTP transport for '{self.name}' requires 'url'")
        elif self.transport == TransportType.STDIO:
            if not self.command:
                raise ValueError(f"stdio transport for '{self.name}' requires 'command'")
