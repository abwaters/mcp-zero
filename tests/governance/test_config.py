"""Tests for governance configuration dataclasses."""

import dataclasses

import pytest

from mcp_zero.governance.config import (
    IdentityProviderConfig,
    LoggingConfig,
    MaskingConfig,
    PolicyConfig,
    PolicyEffect,
    PolicyRule,
    PolicyServerAccess,
    PolicySubjects,
    PresidioConfig,
    ServerDefinition,
)


class TestPolicyEffect:
    def test_allow(self):
        assert PolicyEffect.ALLOW == "allow"

    def test_deny(self):
        assert PolicyEffect.DENY == "deny"

    def test_from_string(self):
        assert PolicyEffect("allow") is PolicyEffect.ALLOW
        assert PolicyEffect("deny") is PolicyEffect.DENY


class TestIdentityProviderConfig:
    def test_valid(self):
        cfg = IdentityProviderConfig(
            provider="okta",
            issuer="https://example.okta.com",
            audience="my-app",
            claim_mapping={"user_id": "sub"},
        )
        assert cfg.provider == "okta"
        assert cfg.issuer == "https://example.okta.com"
        assert cfg.audience == "my-app"
        assert cfg.claim_mapping == {"user_id": "sub"}

    def test_missing_provider(self):
        with pytest.raises(ValueError, match="identity.provider is required"):
            IdentityProviderConfig(issuer="https://x.com", audience="a")

    def test_missing_issuer(self):
        with pytest.raises(ValueError, match="identity.issuer is required"):
            IdentityProviderConfig(provider="okta", audience="a")

    def test_missing_audience(self):
        with pytest.raises(ValueError, match="identity.audience is required"):
            IdentityProviderConfig(provider="okta", issuer="https://x.com")

    def test_frozen(self):
        cfg = IdentityProviderConfig(provider="okta", issuer="https://x.com", audience="a")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.provider = "other"  # type: ignore[misc]

    def test_default_claim_mapping(self):
        cfg = IdentityProviderConfig(provider="okta", issuer="https://x.com", audience="a")
        assert cfg.claim_mapping == {}

    def test_http_issuer_rejected(self):
        with pytest.raises(ValueError, match="must use https://"):
            IdentityProviderConfig(provider="okta", issuer="http://example.com", audience="a")

    def test_http_issuer_allowed_with_allow_insecure(self):
        cfg = IdentityProviderConfig(
            provider="okta",
            issuer="http://example.com",
            audience="a",
            allow_insecure=True,
        )
        assert cfg.issuer == "http://example.com"


class TestServerDefinition:
    def test_valid_http(self):
        s = ServerDefinition(name="api", transport="http", url="http://localhost:9000")
        assert s.name == "api"
        assert s.transport == "http"
        assert s.url == "http://localhost:9000"

    def test_valid_stdio(self):
        s = ServerDefinition(name="local", transport="stdio", command="/usr/bin/mcp")
        assert s.name == "local"
        assert s.transport == "stdio"
        assert s.command == "/usr/bin/mcp"

    def test_missing_name(self):
        with pytest.raises(ValueError, match="server.name is required"):
            ServerDefinition(transport="http")

    def test_invalid_transport(self):
        with pytest.raises(ValueError, match="transport must be 'http' or 'stdio'"):
            ServerDefinition(name="bad", transport="grpc")

    def test_frozen(self):
        s = ServerDefinition(name="api", transport="http", url="http://x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            s.name = "other"  # type: ignore[misc]

    def test_defaults(self):
        s = ServerDefinition(name="x", transport="http")
        assert s.url is None
        assert s.command is None
        assert s.args == []
        assert s.env == {}
        assert s.token_exchange is False
        assert s.target_audience is None
        assert s.required_scopes == []


class TestPolicySubjects:
    def test_defaults(self):
        ps = PolicySubjects()
        assert ps.users == []
        assert ps.groups == []

    def test_with_values(self):
        ps = PolicySubjects(users=["alice"], groups=["admins"])
        assert ps.users == ["alice"]
        assert ps.groups == ["admins"]

    def test_frozen(self):
        ps = PolicySubjects()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ps.users = ["x"]  # type: ignore[misc]


class TestPolicyServerAccess:
    def test_valid(self):
        a = PolicyServerAccess(name="api", tools=["read_*"])
        assert a.name == "api"
        assert a.tools == ["read_*"]

    def test_missing_name(self):
        with pytest.raises(ValueError, match="name is required"):
            PolicyServerAccess()

    def test_default_tools(self):
        a = PolicyServerAccess(name="api")
        assert a.tools == []

    def test_frozen(self):
        a = PolicyServerAccess(name="api")
        with pytest.raises(dataclasses.FrozenInstanceError):
            a.name = "x"  # type: ignore[misc]


class TestPolicyRule:
    def test_valid(self):
        rule = PolicyRule(id="r1", description="Allow all", effect=PolicyEffect.ALLOW)
        assert rule.id == "r1"
        assert rule.description == "Allow all"
        assert rule.effect == PolicyEffect.ALLOW

    def test_missing_id(self):
        with pytest.raises(ValueError, match="policy.id is required"):
            PolicyRule(description="x")

    def test_missing_description(self):
        with pytest.raises(ValueError, match="description is required"):
            PolicyRule(id="r1")

    def test_defaults(self):
        rule = PolicyRule(id="r1", description="x")
        assert rule.effect == PolicyEffect.ALLOW
        assert rule.subjects == PolicySubjects()
        assert rule.mcp_servers == []

    def test_frozen(self):
        rule = PolicyRule(id="r1", description="x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            rule.id = "r2"  # type: ignore[misc]


class TestLoggingConfig:
    def test_defaults(self):
        lc = LoggingConfig()
        assert lc.level == "INFO"
        assert lc.format == "json"
        assert lc.include == []

    def test_valid_levels(self):
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            lc = LoggingConfig(level=level)
            assert lc.level == level

    def test_invalid_level(self):
        with pytest.raises(ValueError, match="logging.level must be one of"):
            LoggingConfig(level="TRACE")

    def test_valid_formats(self):
        for fmt in ("json", "text"):
            lc = LoggingConfig(format=fmt)
            assert lc.format == fmt

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="logging.format must be one of"):
            LoggingConfig(format="xml")

    def test_frozen(self):
        lc = LoggingConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            lc.level = "DEBUG"  # type: ignore[misc]


class TestPresidioConfig:
    def test_defaults(self):
        pc = PresidioConfig()
        assert pc.enabled is False
        assert pc.entities == []

    def test_with_values(self):
        pc = PresidioConfig(enabled=True, entities=["EMAIL", "PHONE"])
        assert pc.enabled is True
        assert pc.entities == ["EMAIL", "PHONE"]

    def test_frozen(self):
        pc = PresidioConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            pc.enabled = True  # type: ignore[misc]


class TestMaskingConfig:
    def test_defaults(self):
        mc = MaskingConfig()
        assert mc.presidio == PresidioConfig()

    def test_with_presidio(self):
        mc = MaskingConfig(presidio=PresidioConfig(enabled=True))
        assert mc.presidio.enabled is True

    def test_frozen(self):
        mc = MaskingConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            mc.presidio = PresidioConfig()  # type: ignore[misc]


class TestPolicyConfig:
    def test_valid_minimal(self):
        pc = PolicyConfig(version=1)
        assert pc.version == 1
        assert pc.default == PolicyEffect.DENY
        assert pc.identity is None
        assert pc.servers == []
        assert pc.policies == []

    def test_invalid_version(self):
        with pytest.raises(ValueError, match="policy version must be 1"):
            PolicyConfig(version=2)

    def test_version_zero(self):
        with pytest.raises(ValueError, match="policy version must be 1"):
            PolicyConfig()

    def test_frozen(self):
        pc = PolicyConfig(version=1)
        with pytest.raises(dataclasses.FrozenInstanceError):
            pc.version = 2  # type: ignore[misc]

    def test_full_config(self):
        pc = PolicyConfig(
            version=1,
            default=PolicyEffect.ALLOW,
            identity=IdentityProviderConfig(provider="okta", issuer="https://x.com", audience="a"),
            servers=[ServerDefinition(name="api", transport="http", url="http://x")],
            policies=[PolicyRule(id="r1", description="allow all")],
            logging=LoggingConfig(level="DEBUG"),
            masking=MaskingConfig(presidio=PresidioConfig(enabled=True)),
        )
        assert pc.version == 1
        assert pc.default == PolicyEffect.ALLOW
        assert pc.identity is not None
        assert len(pc.servers) == 1
        assert len(pc.policies) == 1
        assert pc.logging.level == "DEBUG"
        assert pc.masking.presidio.enabled is True
