"""Presidio PII masking plugin for mcp-zero."""

from __future__ import annotations

import logging
from typing import Any

from mcp_zero.governance.config import PresidioConfig
from mcp_zero.masking.hook import MaskingHook
from mcp_zero.masking.presidio import PresidioMaskingEngine
from mcp_zero.pipeline.registry import HookRegistry
from mcp_zero.plugin import BasePlugin

logger = logging.getLogger(__name__)

DEFAULT_PRIORITY = 75


class PresidioMaskingPlugin(BasePlugin):
    """Plugin that registers Presidio-based PII masking into the pipeline.

    Configuration (via ``plugins[].config`` in the policy file)::

        plugins:
          - name: presidio-masking
            config:
              entities:
                - PERSON
                - EMAIL_ADDRESS
                - PHONE_NUMBER
    """

    def __init__(self) -> None:
        self._entities: list[str] = []
        self._priority: int = DEFAULT_PRIORITY

    @property
    def name(self) -> str:
        return "presidio-masking"

    def configure(self, config: dict[str, Any]) -> None:
        self._entities = config.get("entities", [])
        if not self._entities:
            raise ValueError(
                "presidio-masking plugin requires a non-empty 'entities' list in config"
            )
        if "priority" in config:
            self._priority = int(config["priority"])

    def register(self, registry: HookRegistry) -> None:
        presidio_config = PresidioConfig(enabled=True, entities=self._entities)
        engine = PresidioMaskingEngine(presidio_config)
        hook = MaskingHook(engine, presidio_config)
        registry.register(hook, priority=self._priority)
        logger.info(
            "Presidio masking plugin registered (entities=%s, priority=%d)",
            ", ".join(self._entities),
            self._priority,
        )
