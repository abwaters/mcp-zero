"""Identity lifecycle hook for JWT-based authentication."""

from __future__ import annotations

import logging
from dataclasses import replace

from mcp_zero.context import HookContext
from mcp_zero.identity.errors import IdentityError
from mcp_zero.identity.jwt import JWTValidator
from mcp_zero.pipeline.errors import ShortCircuitError
from mcp_zero.pipeline.hooks import LifecycleHook

logger = logging.getLogger(__name__)


class IdentityHook(LifecycleHook):
    """Validates inbound JWT bearer tokens at PRE_VALIDATION.

    Reads the ``authorization`` key from ``ctx.extras``, parses the
    ``Bearer <token>`` value, and validates the JWT.  On success, the
    request context is enriched with user identity fields.  On failure
    the pipeline is short-circuited with a denial (fail closed).
    """

    def __init__(self, validator: JWTValidator) -> None:
        self._validator = validator

    async def on_pre_validation(self, ctx: HookContext) -> HookContext:
        auth_header = ctx.extras.get("authorization", "")

        if not auth_header:
            logger.warning("Missing Authorization header")
            raise ShortCircuitError("Missing Authorization header", deny=True)

        token = self._parse_bearer(auth_header)
        if token is None:
            logger.warning("Malformed Authorization header")
            raise ShortCircuitError("Malformed Authorization header", deny=True)

        try:
            claims = await self._validator.validate_token(token)
        except IdentityError as exc:
            logger.warning("Token validation failed: %s", exc)
            raise ShortCircuitError(f"Authentication failed: {exc}", deny=True) from exc

        # Enrich the request context with validated identity
        new_request = replace(
            ctx.request,
            user_id=claims.user_id,
            user_email=claims.email,
            user_groups=list(claims.groups),
        )
        return ctx.evolve(request=new_request)

    @staticmethod
    def _parse_bearer(header: str) -> str | None:
        """Extract the token from a ``Bearer <token>`` header value."""
        parts = header.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
        return parts[1]
