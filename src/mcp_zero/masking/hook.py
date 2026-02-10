"""Masking lifecycle hook — bridges MaskingEngine to the request pipeline."""

from __future__ import annotations

import logging
from typing import Any

from mcp_zero.context import HookContext
from mcp_zero.governance.config import PresidioConfig
from mcp_zero.masking.engine import MaskingEngine, MaskingEvent
from mcp_zero.masking.errors import MaskingEngineError
from mcp_zero.pipeline.errors import ShortCircuitError
from mcp_zero.pipeline.hooks import LifecycleHook

logger = logging.getLogger(__name__)


class MaskingHook(LifecycleHook):
    """Masks PII and secrets in request and response payloads.

    Input masking (PRE_MASKING): recursively walks the ``request_payload``
    structure and applies the configured :class:`MaskingEngine` to every
    string value found.  Dict keys, numbers, booleans, and ``None`` values
    pass through unchanged.  On engine failure the request is **denied**
    (fail-closed) so the upstream MCP server is never contacted.

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
            return ctx.evolve(masking_stage_completed=True)

        masked_fields: list[str] = []
        all_events: list[MaskingEvent] = []

        try:
            new_payload = await self._walk_and_mask(
                payload,
                self._config.entities,
                correlation_id,
                masked_fields,
                all_events,
                path="",
            )
        except MaskingEngineError as exc:
            logger.error(
                "Masking engine failure — denying request (correlation_id=%s): %s",
                correlation_id,
                exc,
            )
            raise ShortCircuitError(
                f"Masking failure: {exc}",
                deny=True,
            ) from exc

        if masked_fields:
            return ctx.evolve(
                request_payload=new_payload,
                masking_applied=True,
                masked_fields=masked_fields,
                masking_events=all_events,
                masking_stage_completed=True,
            )

        return ctx.evolve(masking_stage_completed=True)

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
            return ctx.evolve(masking_stage_completed=True)

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
                "Output masking engine failure — blocking response (correlation_id=%s): %s",
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
                masking_stage_completed=True,
            )

        return ctx.evolve(masking_stage_completed=True)

    # ------------------------------------------------------------------
    # Recursive walkers
    # ------------------------------------------------------------------

    async def _walk_and_mask(
        self,
        obj: Any,
        entities: list[str],
        correlation_id: str,
        masked_fields: list[str],
        all_events: list[MaskingEvent],
        path: str,
    ) -> Any:
        """Recursively walk *obj* and mask every string value found.

        - ``dict`` — recurse into values; keys are preserved untouched.
        - ``list`` — recurse into each item.
        - ``str``  — run through the masking engine.
        - Everything else (int, float, bool, None) — returned as-is.
        """
        if isinstance(obj, str):
            result = await self._engine.mask_text(
                text=obj,
                entities=entities,
                direction="request",
            )
            if result.has_masked:
                field_path = path or "<root>"
                masked_fields.append(field_path)
                all_events.extend(result.events)
                for event in result.events:
                    logger.info(
                        "Masked %d %s entity(ies) in field '%s' (correlation_id=%s)",
                        event.count,
                        event.entity_type,
                        field_path,
                        correlation_id,
                    )
                return result.masked_text
            return obj

        if isinstance(obj, dict):
            new_dict: dict[str, Any] = {}
            for key, value in obj.items():
                child_path = f"{path}.{key}" if path else key
                new_dict[key] = await self._walk_and_mask(
                    value, entities, correlation_id, masked_fields, all_events, child_path
                )
            return new_dict

        if isinstance(obj, list):
            new_list: list[Any] = []
            for i, item in enumerate(obj):
                child_path = f"{path}[{i}]"
                new_list.append(
                    await self._walk_and_mask(
                        item, entities, correlation_id, masked_fields, all_events, child_path
                    )
                )
            return new_list

        # Non-string, non-container values pass through unchanged
        return obj

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
                        "Output masked %d %s entity(ies) at '%s' (correlation_id=%s)",
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
                    await self._mask_recursive(item, child_path, masked_fields, correlation_id)
                )
            return new_list

        return value
