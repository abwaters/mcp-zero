"""Tests for governance policy loader."""

import json

import pytest
import yaml

from mcp_zero.governance.config import PolicyConfig
from mcp_zero.governance.errors import (
    PolicyFileError,
    PolicyReferenceError,
    PolicyValidationError,
)
from mcp_zero.governance.loader import (
    convert_to_identity_config,
    convert_to_server_configs,
    load_policy_file,
)
from mcp_zero.identity.config import IdentityConfig
from mcp_zero.transport.config import ServerConfig, TransportType


def _minimal_policy() -> dict:
    """Return a minimal valid policy dict."""
    return {
        "version": 1,
        "default": "deny",
        "servers": [
            {
                "name": "api",
                "transport": "http",
                "url": "https://localhost:9000",
                "allow_insecure": False,
            },
        ],
        "policies": [
            {
                "id": "r1",
                "description": "Allow all",
                "effect": "allow",
                "mcp_servers": [{"name": "api", "tools": ["*"]}],
            },
        ],
    }


def _full_policy() -> dict:
    """Return a full policy dict with all sections."""
    return {
        "version": 1,
        "default": "deny",
        "identity": {
            "provider": "okta",
            "issuer": "https://example.okta.com",
            "audience": "my-app",
            "claim_mapping": {"user_id": "sub", "email": "email", "groups": "groups"},
        },
        "servers": [
            {
                "name": "api",
                "transport": "http",
                "url": "https://localhost:9000",
                "token_exchange": True,
                "target_audience": "api://server1",
                "required_scopes": ["read", "write"],
            },
            {
                "name": "local",
                "transport": "stdio",
                "command": "/usr/bin/mcp",
                "args": ["--verbose"],
                "env": {"MCP_DEBUG": "1"},
            },
        ],
        "policies": [
            {
                "id": "admin-allow",
                "description": "Admins can do anything",
                "effect": "allow",
                "subjects": {"users": ["admin@example.com"], "groups": ["admins"]},
                "mcp_servers": [{"name": "api", "tools": ["*"]}],
            },
            {
                "id": "dev-read",
                "description": "Devs can read",
                "effect": "allow",
                "subjects": {"groups": ["developers"]},
                "mcp_servers": [
                    {"name": "api", "tools": ["read_*"]},
                    {"name": "local", "tools": ["list_files"]},
                ],
            },
        ],
        "logging": {"level": "DEBUG", "include": ["identity", "governance"]},
        "masking": {
            "presidio": {"enabled": True, "entities": ["EMAIL", "PHONE"]},
        },
    }


class TestLoadPolicyFileYAML:
    def test_minimal_yaml(self, tmp_path):
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(_minimal_policy()))
        policy = load_policy_file(str(path))
        assert isinstance(policy, PolicyConfig)
        assert policy.version == 1
        assert len(policy.servers) == 1
        assert len(policy.policies) == 1

    def test_full_yaml(self, tmp_path):
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(_full_policy()))
        policy = load_policy_file(str(path))
        assert policy.version == 1
        assert policy.identity is not None
        assert policy.identity.provider == "okta"
        assert len(policy.servers) == 2
        assert len(policy.policies) == 2
        assert policy.logging.level == "DEBUG"
        assert policy.masking.presidio.enabled is True

    def test_yml_extension(self, tmp_path):
        path = tmp_path / "policy.yml"
        path.write_text(yaml.dump(_minimal_policy()))
        policy = load_policy_file(str(path))
        assert policy.version == 1


class TestLoadPolicyFileJSON:
    def test_minimal_json(self, tmp_path):
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(_minimal_policy()))
        policy = load_policy_file(str(path))
        assert isinstance(policy, PolicyConfig)
        assert policy.version == 1

    def test_full_json(self, tmp_path):
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(_full_policy()))
        policy = load_policy_file(str(path))
        assert policy.version == 1
        assert policy.identity is not None
        assert len(policy.servers) == 2


class TestLoadPolicyFileErrors:
    def test_file_not_found(self):
        with pytest.raises(PolicyFileError, match="not found"):
            load_policy_file("/nonexistent/policy.yaml")

    def test_unsupported_extension(self, tmp_path):
        path = tmp_path / "policy.toml"
        path.write_text("version = 1")
        with pytest.raises(PolicyFileError, match="Unsupported.*extension"):
            load_policy_file(str(path))

    def test_invalid_yaml(self, tmp_path):
        path = tmp_path / "policy.yaml"
        path.write_text(":\n  :\n    - [invalid yaml {{{")
        with pytest.raises(PolicyFileError, match="Failed to parse YAML"):
            load_policy_file(str(path))

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "policy.json"
        path.write_text("{invalid json")
        with pytest.raises(PolicyFileError, match="Failed to parse JSON"):
            load_policy_file(str(path))

    def test_non_mapping_top_level(self, tmp_path):
        path = tmp_path / "policy.yaml"
        path.write_text("- item1\n- item2\n")
        with pytest.raises(PolicyFileError, match="must contain a mapping"):
            load_policy_file(str(path))


class TestValidationErrors:
    def test_missing_version(self, tmp_path):
        data = _minimal_policy()
        del data["version"]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="Missing required field: version"):
            load_policy_file(str(path))

    def test_invalid_version_type(self, tmp_path):
        data = _minimal_policy()
        data["version"] = "one"
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="version must be an integer"):
            load_policy_file(str(path))

    def test_wrong_version(self, tmp_path):
        data = _minimal_policy()
        data["version"] = 2
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="policy version must be 1"):
            load_policy_file(str(path))

    def test_invalid_default(self, tmp_path):
        data = _minimal_policy()
        data["default"] = "maybe"
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="default must be 'allow' or 'deny'"):
            load_policy_file(str(path))

    def test_servers_not_list(self, tmp_path):
        data = _minimal_policy()
        data["servers"] = "not a list"
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="servers must be a list"):
            load_policy_file(str(path))

    def test_policies_not_list(self, tmp_path):
        data = _minimal_policy()
        data["policies"] = "not a list"
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="policies must be a list"):
            load_policy_file(str(path))

    def test_server_not_mapping(self, tmp_path):
        data = _minimal_policy()
        data["servers"] = ["not a dict"]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="servers\\[0\\] must be a mapping"):
            load_policy_file(str(path))

    def test_policy_not_mapping(self, tmp_path):
        data = _minimal_policy()
        data["policies"] = ["not a dict"]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="policies\\[0\\] must be a mapping"):
            load_policy_file(str(path))

    def test_identity_not_mapping(self, tmp_path):
        data = _minimal_policy()
        data["identity"] = "not a dict"
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="identity must be a mapping"):
            load_policy_file(str(path))

    def test_logging_not_mapping(self, tmp_path):
        data = _minimal_policy()
        data["logging"] = "not a dict"
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="logging must be a mapping"):
            load_policy_file(str(path))

    def test_masking_not_mapping(self, tmp_path):
        data = _minimal_policy()
        data["masking"] = "not a dict"
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="masking must be a mapping"):
            load_policy_file(str(path))


class TestDuplicateDetection:
    def test_duplicate_server_names(self, tmp_path):
        data = _minimal_policy()
        data["servers"] = [
            {"name": "api", "transport": "http", "url": "https://a"},
            {"name": "api", "transport": "http", "url": "https://b"},
        ]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="Duplicate server name: 'api'"):
            load_policy_file(str(path))

    def test_duplicate_policy_ids(self, tmp_path):
        data = _minimal_policy()
        data["policies"] = [
            {
                "id": "r1",
                "description": "Rule one",
                "mcp_servers": [{"name": "api"}],
            },
            {
                "id": "r1",
                "description": "Rule one again",
                "mcp_servers": [{"name": "api"}],
            },
        ]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="Duplicate policy id: 'r1'"):
            load_policy_file(str(path))


class TestCrossReferences:
    def test_unknown_server_in_policy(self, tmp_path):
        data = _minimal_policy()
        data["policies"][0]["mcp_servers"] = [{"name": "nonexistent", "tools": ["*"]}]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyReferenceError, match="unknown server 'nonexistent'"):
            load_policy_file(str(path))

    def test_reference_error_attrs(self, tmp_path):
        data = _minimal_policy()
        data["policies"][0]["mcp_servers"] = [{"name": "ghost"}]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyReferenceError) as exc_info:
            load_policy_file(str(path))
        assert exc_info.value.reference == "ghost"
        assert "mcp_servers" in exc_info.value.field


class TestToolPatternValidation:
    def test_valid_standalone_wildcard(self, tmp_path):
        data = _minimal_policy()
        data["policies"][0]["mcp_servers"] = [{"name": "api", "tools": ["*"]}]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        assert policy.policies[0].mcp_servers[0].tools == ["*"]

    def test_valid_prefix_wildcard(self, tmp_path):
        data = _minimal_policy()
        data["policies"][0]["mcp_servers"] = [{"name": "api", "tools": ["read_*"]}]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        assert policy.policies[0].mcp_servers[0].tools == ["read_*"]

    def test_valid_suffix_wildcard(self, tmp_path):
        data = _minimal_policy()
        data["policies"][0]["mcp_servers"] = [{"name": "api", "tools": ["*_read"]}]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        assert policy.policies[0].mcp_servers[0].tools == ["*_read"]

    def test_valid_exact_name(self, tmp_path):
        data = _minimal_policy()
        data["policies"][0]["mcp_servers"] = [{"name": "api", "tools": ["read_file"]}]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        assert policy.policies[0].mcp_servers[0].tools == ["read_file"]

    def test_invalid_middle_wildcard(self, tmp_path):
        data = _minimal_policy()
        data["policies"][0]["mcp_servers"] = [{"name": "api", "tools": ["read*write"]}]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="Invalid tool wildcard pattern"):
            load_policy_file(str(path))

    def test_invalid_multiple_wildcards(self, tmp_path):
        data = _minimal_policy()
        data["policies"][0]["mcp_servers"] = [{"name": "api", "tools": ["*_*"]}]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="Invalid tool wildcard pattern"):
            load_policy_file(str(path))

    def test_invalid_double_wildcard(self, tmp_path):
        data = _minimal_policy()
        data["policies"][0]["mcp_servers"] = [{"name": "api", "tools": ["**"]}]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="Invalid tool wildcard pattern"):
            load_policy_file(str(path))


class TestServerHeaders:
    def test_headers_parsed_from_yaml(self, tmp_path):
        data = _minimal_policy()
        data["servers"] = [
            {
                "name": "github",
                "transport": "http",
                "url": "https://api.github.com/mcp/",
                "headers": {"Authorization": "Bearer ghp_xxxx", "X-Custom": "value"},
            },
        ]
        data["policies"][0]["mcp_servers"] = [{"name": "github", "tools": ["*"]}]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        assert policy.servers[0].headers == {
            "Authorization": "Bearer ghp_xxxx",
            "X-Custom": "value",
        }

    def test_headers_default_empty(self, tmp_path):
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(_minimal_policy()))
        policy = load_policy_file(str(path))
        assert policy.servers[0].headers == {}

    def test_headers_converted_to_server_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GH_TOKEN", "ghp_test123")
        data = _minimal_policy()
        data["servers"] = [
            {
                "name": "github",
                "transport": "http",
                "url": "https://api.github.com/mcp/",
                "headers": {"Authorization": "Bearer ${GH_TOKEN}"},
            },
        ]
        data["policies"][0]["mcp_servers"] = [{"name": "github", "tools": ["*"]}]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        configs = convert_to_server_configs(policy)
        # Env var expansion happens in ServerConfig.__post_init__
        assert configs[0].headers == {"Authorization": "Bearer ghp_test123"}


class TestConvertToServerConfigs:
    def test_http_server(self, tmp_path):
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(_minimal_policy()))
        policy = load_policy_file(str(path))
        configs = convert_to_server_configs(policy)
        assert len(configs) == 1
        assert isinstance(configs[0], ServerConfig)
        assert configs[0].name == "api"
        assert configs[0].transport == TransportType.HTTP
        assert configs[0].url == "https://localhost:9000"

    def test_full_conversion(self, tmp_path):
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(_full_policy()))
        policy = load_policy_file(str(path))
        configs = convert_to_server_configs(policy)
        assert len(configs) == 2

        http_cfg = configs[0]
        assert http_cfg.name == "api"
        assert http_cfg.transport == TransportType.HTTP
        assert http_cfg.token_exchange is True
        assert http_cfg.target_audience == "api://server1"
        assert http_cfg.required_scopes == ["read", "write"]

        stdio_cfg = configs[1]
        assert stdio_cfg.name == "local"
        assert stdio_cfg.transport == TransportType.STDIO
        assert stdio_cfg.command == "/usr/bin/mcp"
        assert stdio_cfg.args == ["--verbose"]
        assert stdio_cfg.env == {"MCP_DEBUG": "1"}

    def test_empty_servers(self):
        policy = PolicyConfig(version=1)
        configs = convert_to_server_configs(policy)
        assert configs == []


class TestConvertToIdentityConfig:
    def test_with_identity(self, tmp_path):
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(_full_policy()))
        policy = load_policy_file(str(path))
        config = convert_to_identity_config(policy)
        assert isinstance(config, IdentityConfig)
        assert config.provider == "okta"
        assert config.issuer == "https://example.okta.com"
        assert config.audience == "my-app"
        assert config.claim_mapping.user_id == "sub"
        assert config.claim_mapping.email == "email"
        assert config.claim_mapping.groups == "groups"

    def test_without_identity(self):
        policy = PolicyConfig(version=1)
        config = convert_to_identity_config(policy)
        assert config is None

    def test_custom_claim_mapping(self, tmp_path):
        data = _minimal_policy()
        data["identity"] = {
            "provider": "azure",
            "issuer": "https://login.microsoft.com",
            "audience": "my-app",
            "claim_mapping": {"user_id": "oid", "email": "upn", "groups": "roles"},
        }
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        config = convert_to_identity_config(policy)
        assert config.provider == "azure"
        assert config.claim_mapping.user_id == "oid"
        assert config.claim_mapping.email == "upn"
        assert config.claim_mapping.groups == "roles"


class TestHTTPSEnforcement:
    def test_http_server_url_rejected_via_convert(self, tmp_path):
        data = _minimal_policy()
        data["servers"] = [
            {"name": "api", "transport": "http", "url": "http://localhost:9000"},
        ]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        with pytest.raises(ValueError, match="must use https://"):
            convert_to_server_configs(policy)

    def test_http_server_url_allowed_with_allow_insecure(self, tmp_path):
        data = _minimal_policy()
        data["servers"] = [
            {
                "name": "api",
                "transport": "http",
                "url": "http://localhost:9000",
                "allow_insecure": True,
            },
        ]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        configs = convert_to_server_configs(policy)
        assert configs[0].url == "http://localhost:9000"

    def test_http_identity_issuer_rejected(self, tmp_path):
        data = _minimal_policy()
        data["identity"] = {
            "provider": "okta",
            "issuer": "http://example.okta.com",
            "audience": "my-app",
        }
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="must use https://"):
            load_policy_file(str(path))

    def test_http_identity_issuer_allowed_with_allow_insecure(self, tmp_path):
        data = _minimal_policy()
        data["identity"] = {
            "provider": "okta",
            "issuer": "http://example.okta.com",
            "audience": "my-app",
            "allow_insecure": True,
        }
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        assert policy.identity.issuer == "http://example.okta.com"

    def test_allow_insecure_passes_through_to_identity_config(self, tmp_path):
        data = _minimal_policy()
        data["identity"] = {
            "provider": "okta",
            "issuer": "http://example.okta.com",
            "audience": "my-app",
            "allow_insecure": True,
        }
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        config = convert_to_identity_config(policy)
        assert config.issuer == "http://example.okta.com"
        assert config.allow_insecure is True


class TestCorsParsing:
    def test_valid_cors_section(self, tmp_path):
        data = _minimal_policy()
        data["cors"] = {
            "allow_origins": ["https://example.com"],
            "allow_methods": ["GET", "POST"],
            "allow_headers": ["Authorization"],
            "allow_credentials": True,
            "max_age": 300,
            "expose_headers": ["X-Request-Id"],
        }
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        assert policy.cors is not None
        assert policy.cors.allow_origins == ["https://example.com"]
        assert policy.cors.allow_methods == ["GET", "POST"]
        assert policy.cors.allow_headers == ["Authorization"]
        assert policy.cors.allow_credentials is True
        assert policy.cors.max_age == 300
        assert policy.cors.expose_headers == ["X-Request-Id"]

    def test_missing_cors_section_defaults_none(self, tmp_path):
        data = _minimal_policy()
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        assert policy.cors is None

    def test_cors_not_mapping_raises(self, tmp_path):
        data = _minimal_policy()
        data["cors"] = "not a dict"
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="cors must be a mapping"):
            load_policy_file(str(path))

    def test_cors_empty_origins_raises(self, tmp_path):
        data = _minimal_policy()
        data["cors"] = {"allow_origins": []}
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="allow_origins must be a non-empty list"):
            load_policy_file(str(path))

    def test_cors_negative_max_age_raises(self, tmp_path):
        data = _minimal_policy()
        data["cors"] = {"allow_origins": ["https://example.com"], "max_age": -1}
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="max_age must be >= 0"):
            load_policy_file(str(path))

    def test_cors_wildcard_with_credentials_raises(self, tmp_path):
        data = _minimal_policy()
        data["cors"] = {"allow_origins": ["*"], "allow_credentials": True}
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="cannot be used with allow_credentials"):
            load_policy_file(str(path))

    def test_cors_defaults(self, tmp_path):
        data = _minimal_policy()
        data["cors"] = {"allow_origins": ["*"]}
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        assert policy.cors.allow_origins == ["*"]
        assert policy.cors.allow_methods == ["GET", "POST", "OPTIONS"]
        assert policy.cors.allow_headers == ["Authorization", "Content-Type"]
        assert policy.cors.allow_credentials is False
        assert policy.cors.max_age == 600
        assert policy.cors.expose_headers == []


class TestPluginsParsing:
    def test_valid_plugins_section(self, tmp_path):
        data = _minimal_policy()
        data["plugins"] = [
            {"name": "my-plugin", "package": "my-pkg", "config": {"key": "val"}},
        ]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        assert len(policy.plugins) == 1
        assert policy.plugins[0].name == "my-plugin"
        assert policy.plugins[0].package == "my-pkg"
        assert policy.plugins[0].config == {"key": "val"}

    def test_missing_plugins_section_defaults_empty(self, tmp_path):
        data = _minimal_policy()
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        assert policy.plugins == []

    def test_plugins_not_list_raises(self, tmp_path):
        data = _minimal_policy()
        data["plugins"] = "not a list"
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="plugins must be a list"):
            load_policy_file(str(path))

    def test_plugin_missing_name_raises(self, tmp_path):
        data = _minimal_policy()
        data["plugins"] = [{"package": "some-pkg"}]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="plugin.name is required"):
            load_policy_file(str(path))

    def test_duplicate_plugin_names_raises(self, tmp_path):
        data = _minimal_policy()
        data["plugins"] = [
            {"name": "dup"},
            {"name": "dup"},
        ]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="Duplicate plugin name: 'dup'"):
            load_policy_file(str(path))

    def test_plugin_with_all_fields(self, tmp_path):
        data = _minimal_policy()
        data["plugins"] = [
            {
                "name": "full-plugin",
                "package": "full-pkg",
                "config": {"a": 1, "b": "two"},
                "priority": 42,
            },
        ]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        assert len(policy.plugins) == 1
        p = policy.plugins[0]
        assert p.name == "full-plugin"
        assert p.package == "full-pkg"
        assert p.config == {"a": 1, "b": "two"}
        assert p.priority == 42

    def test_plugin_package_defaults_to_name(self, tmp_path):
        data = _minimal_policy()
        data["plugins"] = [{"name": "my-plugin"}]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        policy = load_policy_file(str(path))
        assert policy.plugins[0].package == "my-plugin"

    def test_plugin_not_mapping_raises(self, tmp_path):
        data = _minimal_policy()
        data["plugins"] = ["not-a-dict"]
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.dump(data))
        with pytest.raises(PolicyValidationError, match="plugins\\[0\\] must be a mapping"):
            load_policy_file(str(path))
