"""Tests for URL scheme validation."""

import pytest

from mcp_zero.url_validation import require_https


class TestRequireHttps:
    def test_https_passes(self):
        require_https("https://example.com", "test_field")

    def test_https_case_insensitive_passes(self):
        require_https("HTTPS://EXAMPLE.COM", "test_field")

    def test_http_raises(self):
        with pytest.raises(ValueError, match="must use https://"):
            require_https("http://example.com", "test_field")

    def test_http_uppercase_raises(self):
        with pytest.raises(ValueError, match="must use https://"):
            require_https("HTTP://EXAMPLE.COM", "test_field")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="must use https://"):
            require_https("", "test_field")

    def test_error_includes_field_name(self):
        with pytest.raises(ValueError, match="my_field"):
            require_https("http://x", "my_field")

    def test_error_includes_url(self):
        with pytest.raises(ValueError, match="http://bad"):
            require_https("http://bad", "field")

    def test_error_includes_allow_insecure_hint(self):
        with pytest.raises(ValueError, match="allow_insecure=True"):
            require_https("http://x", "field")
