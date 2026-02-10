"""Tests for identity configuration."""

import pytest

from mcp_zero.identity.config import ClaimMapping, IdentityConfig


class TestClaimMapping:
    def test_defaults(self):
        m = ClaimMapping()
        assert m.user_id == "sub"
        assert m.email == "email"
        assert m.groups == "groups"

    def test_custom(self):
        m = ClaimMapping(user_id="uid", email="mail", groups="roles")
        assert m.user_id == "uid"
        assert m.email == "mail"
        assert m.groups == "roles"

    def test_frozen(self):
        m = ClaimMapping()
        with pytest.raises(AttributeError):
            m.user_id = "other"  # type: ignore[misc]


class TestIdentityConfig:
    def test_valid(self):
        cfg = IdentityConfig(issuer="https://okta.example.com", audience="my-app")
        assert cfg.provider == "okta"
        assert cfg.issuer == "https://okta.example.com"
        assert cfg.audience == "my-app"
        assert cfg.jwks_cache_ttl == 3600
        assert cfg.claim_mapping == ClaimMapping()

    def test_missing_issuer(self):
        with pytest.raises(ValueError, match="issuer is required"):
            IdentityConfig(audience="my-app")

    def test_missing_audience(self):
        with pytest.raises(ValueError, match="audience is required"):
            IdentityConfig(issuer="https://okta.example.com")

    def test_empty_issuer(self):
        with pytest.raises(ValueError, match="issuer is required"):
            IdentityConfig(issuer="", audience="my-app")

    def test_empty_audience(self):
        with pytest.raises(ValueError, match="audience is required"):
            IdentityConfig(issuer="https://okta.example.com", audience="")

    def test_frozen(self):
        cfg = IdentityConfig(issuer="https://okta.example.com", audience="my-app")
        with pytest.raises(AttributeError):
            cfg.issuer = "other"  # type: ignore[misc]

    def test_custom_claim_mapping(self):
        mapping = ClaimMapping(user_id="uid")
        cfg = IdentityConfig(
            issuer="https://okta.example.com",
            audience="my-app",
            claim_mapping=mapping,
        )
        assert cfg.claim_mapping.user_id == "uid"

    def test_custom_ttl(self):
        cfg = IdentityConfig(
            issuer="https://okta.example.com",
            audience="my-app",
            jwks_cache_ttl=300,
        )
        assert cfg.jwks_cache_ttl == 300

    def test_http_issuer_rejected(self):
        with pytest.raises(ValueError, match="must use https://"):
            IdentityConfig(issuer="http://okta.example.com", audience="my-app")

    def test_http_issuer_allowed_with_allow_insecure(self):
        cfg = IdentityConfig(
            issuer="http://okta.example.com",
            audience="my-app",
            allow_insecure=True,
        )
        assert cfg.issuer == "http://okta.example.com"

    def test_https_issuer_always_accepted(self):
        cfg = IdentityConfig(issuer="https://okta.example.com", audience="my-app")
        assert cfg.issuer == "https://okta.example.com"
