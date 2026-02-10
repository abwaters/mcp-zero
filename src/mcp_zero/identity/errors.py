"""Identity error hierarchy."""

from __future__ import annotations


class IdentityError(Exception):
    """Base error for all identity operations."""


class JWKSFetchError(IdentityError):
    """Failed to fetch JWKS from the identity provider.

    Args:
        message: Error description.
        issuer: The issuer URL that was unreachable.
    """

    def __init__(self, message: str, *, issuer: str = "") -> None:
        self.issuer = issuer
        super().__init__(message)


class TokenValidationError(IdentityError):
    """JWT validation failed.

    Args:
        message: Error description.
        reason: Machine-readable reason (e.g. "invalid_signature", "bad_audience").
    """

    def __init__(self, message: str, *, reason: str = "") -> None:
        self.reason = reason
        super().__init__(message)


class TokenExpiredError(TokenValidationError):
    """JWT has expired."""

    def __init__(self, message: str = "Token has expired") -> None:
        super().__init__(message, reason="expired")
