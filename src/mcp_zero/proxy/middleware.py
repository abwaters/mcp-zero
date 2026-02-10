"""ASGI middleware for extracting the Authorization header into a context var."""

from __future__ import annotations

import contextvars

from starlette.types import ASGIApp, Receive, Scope, Send

auth_header_var: contextvars.ContextVar[str] = contextvars.ContextVar("auth_header_var", default="")


class AuthHeaderMiddleware:
    """Extracts the ``Authorization`` header from HTTP requests into a context var.

    Non-HTTP scopes (lifespan, websocket) are passed through unchanged.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        auth_value = ""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                auth_value = value.decode("latin-1")
                break

        token = auth_header_var.set(auth_value)
        try:
            await self._app(scope, receive, send)
        finally:
            auth_header_var.reset(token)
