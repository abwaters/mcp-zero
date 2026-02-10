"""Masking lifecycle hook — bridges MaskingEngine to the request pipeline."""

from __future__ import annotations

import logging

from mcp_zero.context import HookContext
from mcp_zero.governance.config import PresidioConfig
from mcp_zero.masking.engine import MaskingEngine
from mcp_zero.masking.errors import MaskingEngineError
from mcp_zero.pipeline.hooks import LifecycleHook

logger = logging.getLogger(__name__)


class MaskingHook(LifecycleHook):
    """Masks PII and secrets in request payloads at PRE_MASKING.

    Walks text-valued fields in ``request_payload`` and applies the
    configured :class:`MaskingEngine` to each.

    Args:
        engine: The masking engine to use for detection and replacement.
        config: Presidio configuration (carries the entity list).
    """

    def __init__(self, engine: MaskingEngine, config: PresidioConfig) -> None:
        self._engine = engine
        self._config = config

    async def on_pre_masking(self, ctx: HookContext) -> HookContext:
        if not self._config.enabled:
            return ctx

        correlation_id = ctx.request.correlation_id
        payload = ctx.request_payload
        if not payload:
            return ctx

        masked_fields: list[str] = []
        new_payload = dict(payload)

        for key, value in payload.items():
            if not isinstance(value, str):
                continue

            try:
                result = await self._engine.mask_text(
                    text=value,
                    entities=self._config.entities,
                    direction="request",
                )
            except MaskingEngineError:
                logger.error(
                    "Masking engine error on field '%s' (correlation_id=%s)",
                    key,
                    correlation_id,
                    exc_info=True,
                )
                continue

            if result.has_masked:
                new_payload[key] = result.masked_text
                masked_fields.append(key)

                for event in result.events:
                    logger.info(
                        "Masked %d %s entity(ies) in field '%s' (correlation_id=%s)",
                        event.count,
                        event.entity_type,
                        key,
                        correlation_id,
                    )

        if masked_fields:
            return ctx.evolve(
                request_payload=new_payload,
                masking_applied=True,
                masked_fields=masked_fields,
            )

        return ctx
