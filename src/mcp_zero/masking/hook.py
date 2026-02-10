"""Masking lifecycle hook — bridges MaskingEngine to the request pipeline."""

from __future__ import annotations

import logging
from typing import Any

from mcp_zero.context import HookContext
from mcp_zero.governance.config import PresidioConfig
from mcp_zero.masking.engine import MaskingEngine
from mcp_zero.masking.errors import MaskingEngineError
from mcp_zero.pipeline.errors import ShortCircuitError
from mcp_zero.pipeline.hooks import LifecycleHook

logger = logging.getLogger(__name__)


class MaskingHook(LifecycleHook):
    """Masks PII and secrets in request and response payloads.

    Input masking (PRE_MASKING): walks top-level text fields in
    ``request_payload`` and applies the configured :class:`MaskingEngine`.

    Output masking (POST_MASKING): recursively walks ``response_payload``
    to find and mask all string values in nested structures.  On engine
    failure the response is blocked (fail-closed) to prevent unmasked
    data from reaching the client.

    Args:
        engine: The masking engine to use for detection and replacement.
        config: Presidio configuration (carries the entity list).
    """

    def __init__(self, engine: MaskingEngine, config: PresidioConfig) -> None:
        self._engine = engine
        self._config = config

    # ------------------------------------------------------------------
    # Input masking (request payloads)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Output masking (response payloads)
    # ------------------------------------------------------------------

    async def on_post_masking(self, ctx: HookContext) -> HookContext:
        """Mask PII/secrets in response payloads before returning to client.

        Recursively walks the response structure, masking all string values
        while preserving keys and structure.  On engine failure the pipeline
        is short-circuited (fail-closed) so the client never receives
        unmasked data.
        """
        if not self._config.enabled:
            return ctx

        payload = ctx.response_payload
        if not payload:
            return ctx

        correlation_id = ctx.request.correlation_id
        masked_fields: list[str] = []

        try:
            new_payload = await self._mask_recursive(
                value=payload,
                path="",
                masked_fields=masked_fields,
                correlation_id=correlation_id,
            )
        except MaskingEngineError as exc:
            logger.error(
                "Output masking engine failure — blocking response "
                "(correlation_id=%s): %s",
                correlation_id,
                exc,
                exc_info=True,
            )
            raise ShortCircuitError(
                f"Output masking failed: {exc}",
                deny=True,
            ) from exc

        if masked_fields:
            return ctx.evolve(
                response_payload=new_payload,
                output_masking_applied=True,
                output_masked_fields=masked_fields,
            )

        return ctx

    async def _mask_recursive(
        self,
        value: Any,
        path: str,
        masked_fields: list[str],
        correlation_id: str,
    ) -> Any:
        """Recursively walk *value* and mask all string leaves.

        Dicts: recurse into values, leave keys untouched.
        Lists: recurse into each element.
        Strings: apply the masking engine.
        Other types: pass through unchanged.

        Raises:
            MaskingEngineError: On engine failure (caller handles fail-closed).
        """
        if isinstance(value, str):
            result = await self._engine.mask_text(
                text=value,
                entities=self._config.entities,
                direction="response",
            )
            if result.has_masked:
                masked_fields.append(path)
                for event in result.events:
                    logger.info(
                        "Output masked %d %s entity(ies) at '%s' "
                        "(correlation_id=%s)",
                        event.count,
                        event.entity_type,
                        path,
                        correlation_id,
                    )
                return result.masked_text
            return value

        if isinstance(value, dict):
            new_dict = {}
            for k, v in value.items():
                child_path = f"{path}.{k}" if path else k
                new_dict[k] = await self._mask_recursive(
                    v, child_path, masked_fields, correlation_id
                )
            return new_dict

        if isinstance(value, list):
            new_list = []
            for i, item in enumerate(value):
                child_path = f"{path}[{i}]"
                new_list.append(
                    await self._mask_recursive(
                        item, child_path, masked_fields, correlation_id
                    )
                )
            return new_list

        return value
