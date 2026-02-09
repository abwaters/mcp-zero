"""Pipeline execution result."""

from __future__ import annotations

from dataclasses import dataclass, field

from mcp_zero.context import HookContext


@dataclass(frozen=True)
class PipelineResult:
    """Outcome of a full pipeline execution."""

    context: HookContext
    success: bool
    error: Exception | None = None
    duration_ms: float = 0.0
    hooks_executed: list[str] = field(default_factory=list)
