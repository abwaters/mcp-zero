"""Tests for identity error hierarchy."""

from mcp_zero.identity.errors import (
    IdentityError,
    JWKSFetchError,
    TokenExpiredError,
    TokenValidationError,
)


class TestIdentityError:
    def test_base_error(self):
        err = IdentityError("something broke")
        assert str(err) == "something broke"
        assert isinstance(err, Exception)


class TestJWKSFetchError:
    def test_with_issuer(self):
        err = JWKSFetchError("timeout", issuer="https://okta.example.com")
        assert str(err) == "timeout"
        assert err.issuer == "https://okta.example.com"
        assert isinstance(err, IdentityError)

    def test_default_issuer(self):
        err = JWKSFetchError("error")
        assert err.issuer == ""


class TestTokenValidationError:
    def test_with_reason(self):
        err = TokenValidationError("bad sig", reason="invalid_signature")
        assert str(err) == "bad sig"
        assert err.reason == "invalid_signature"
        assert isinstance(err, IdentityError)

    def test_default_reason(self):
        err = TokenValidationError("failed")
        assert err.reason == ""


class TestTokenExpiredError:
    def test_default_message(self):
        err = TokenExpiredError()
        assert str(err) == "Token has expired"
        assert err.reason == "expired"
        assert isinstance(err, TokenValidationError)
        assert isinstance(err, IdentityError)

    def test_custom_message(self):
        err = TokenExpiredError("custom expiry")
        assert str(err) == "custom expiry"
        assert err.reason == "expired"
