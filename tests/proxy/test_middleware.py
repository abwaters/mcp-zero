"""Tests for the AuthHeaderMiddleware."""

from __future__ import annotations

import pytest

from mcp_zero.proxy.middleware import AuthHeaderMiddleware, auth_header_var


def _make_http_scope(headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": headers or [],
    }


class TestAuthHeaderMiddleware:
    @pytest.mark.asyncio
    async def test_extracts_authorization_header(self):
        captured = {}

        async def inner_app(scope, receive, send):
            captured["auth"] = auth_header_var.get("")

        middleware = AuthHeaderMiddleware(inner_app)
        scope = _make_http_scope(headers=[(b"authorization", b"Bearer my-token")])

        await middleware(scope, None, None)

        assert captured["auth"] == "Bearer my-token"

    @pytest.mark.asyncio
    async def test_missing_header_defaults_to_empty(self):
        captured = {}

        async def inner_app(scope, receive, send):
            captured["auth"] = auth_header_var.get("")

        middleware = AuthHeaderMiddleware(inner_app)
        scope = _make_http_scope(headers=[])

        await middleware(scope, None, None)

        assert captured["auth"] == ""

    @pytest.mark.asyncio
    async def test_non_http_passthrough(self):
        called = {"inner": False}

        async def inner_app(scope, receive, send):
            called["inner"] = True

        middleware = AuthHeaderMiddleware(inner_app)
        scope = {"type": "lifespan"}

        await middleware(scope, None, None)

        assert called["inner"] is True
        # Context var should not be set for non-HTTP
        assert auth_header_var.get("") == ""

    @pytest.mark.asyncio
    async def test_context_var_reset_after_request(self):
        async def inner_app(scope, receive, send):
            pass

        middleware = AuthHeaderMiddleware(inner_app)
        scope = _make_http_scope(headers=[(b"authorization", b"Bearer temp-token")])

        await middleware(scope, None, None)

        # After the middleware completes, the var should be back to default
        assert auth_header_var.get("") == ""

    @pytest.mark.asyncio
    async def test_multiple_headers_uses_authorization(self):
        captured = {}

        async def inner_app(scope, receive, send):
            captured["auth"] = auth_header_var.get("")

        middleware = AuthHeaderMiddleware(inner_app)
        scope = _make_http_scope(
            headers=[
                (b"content-type", b"application/json"),
                (b"authorization", b"Bearer correct-token"),
                (b"x-request-id", b"abc-123"),
            ]
        )

        await middleware(scope, None, None)

        assert captured["auth"] == "Bearer correct-token"

    @pytest.mark.asyncio
    async def test_context_var_reset_on_exception(self):
        async def inner_app(scope, receive, send):
            raise RuntimeError("boom")

        middleware = AuthHeaderMiddleware(inner_app)
        scope = _make_http_scope(headers=[(b"authorization", b"Bearer token")])

        with pytest.raises(RuntimeError, match="boom"):
            await middleware(scope, None, None)

        assert auth_header_var.get("") == ""
