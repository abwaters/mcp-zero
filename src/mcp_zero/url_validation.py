"""URL scheme validation utilities."""

from __future__ import annotations


def require_https(url: str, field_name: str) -> None:
    """Raise ValueError if *url* does not use the ``https://`` scheme.

    Args:
        url: The URL to validate.
        field_name: Human-readable field name for the error message.

    Raises:
        ValueError: When the URL does not start with ``https://``.
    """
    if not url.lower().startswith("https://"):
        raise ValueError(
            f"{field_name} must use https:// (got {url!r}). "
            f"Set allow_insecure=True in the policy file, or set "
            f"MCP_SKIP_TLS_VALIDATION=true to permit http:// for local development."
        )
