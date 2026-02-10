"""Policy file loader and validator."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import yaml

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
from mcp_zero.governance.errors import (
    PolicyFileError,
    PolicyReferenceError,
    PolicyValidationError,
)
from mcp_zero.identity.config import ClaimMapping, IdentityConfig
from mcp_zero.transport.config import ServerConfig, TransportType

logger = logging.getLogger(__name__)

# Wildcard patterns: standalone *, prefix like read_*, or suffix like *_read
_VALID_WILDCARD_RE = re.compile(r"^\*$|^\*[a-zA-Z0-9_]+$|^[a-zA-Z0-9_]+\*$")


def load_policy_file(file_path: str) -> PolicyConfig:
    """Load, parse, and validate a policy file.

    Args:
        file_path: Path to a YAML (.yaml/.yml) or JSON (.json) policy file.

    Returns:
        A validated PolicyConfig.

    Raises:
        PolicyFileError: If the file cannot be read or parsed.
        PolicyValidationError: If the policy schema is invalid.
        PolicyReferenceError: If cross-references are invalid.
    """
    path = Path(file_path)

    # 1. Check file exists
    if not path.exists():
        raise PolicyFileError(f"Policy file not found: {file_path}", file_path=file_path)

    # 2. Read content
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyFileError(f"Failed to read policy file: {exc}", file_path=file_path) from exc

    # 3. Parse based on extension
    data = _parse_content(content, path)

    # 4. Build and validate dataclasses
    policy = _build_policy_config(data, file_path)

    # 5. Validate cross-references
    _validate_cross_references(policy)

    # 6. Validate tool patterns
    _validate_tool_patterns(policy)

    logger.info(
        "Loaded policy file: %s (%d servers, %d rules)",
        file_path,
        len(policy.servers),
        len(policy.policies),
    )
    return policy


def convert_to_server_configs(policy: PolicyConfig) -> list[ServerConfig]:
    """Convert policy server definitions to transport ServerConfig objects.

    Args:
        policy: A validated PolicyConfig.

    Returns:
        List of ServerConfig for the transport layer.
    """
    configs = []
    for server in policy.servers:
        kwargs: dict = {
            "name": server.name,
            "transport": TransportType(server.transport),
            "token_exchange": server.token_exchange,
        }
        if server.url is not None:
            kwargs["url"] = server.url
        if server.command is not None:
            kwargs["command"] = server.command
        if server.args:
            kwargs["args"] = list(server.args)
        if server.env:
            kwargs["env"] = dict(server.env)
        if server.target_audience is not None:
            kwargs["target_audience"] = server.target_audience
        if server.required_scopes:
            kwargs["required_scopes"] = list(server.required_scopes)

        configs.append(ServerConfig(**kwargs))
    return configs


def convert_to_identity_config(policy: PolicyConfig) -> IdentityConfig | None:
    """Convert policy identity section to an IdentityConfig.

    Args:
        policy: A validated PolicyConfig.

    Returns:
        An IdentityConfig if identity is configured, None otherwise.
    """
    if policy.identity is None:
        return None

    identity = policy.identity
    claim_mapping = ClaimMapping(
        user_id=identity.claim_mapping.get("user_id", "sub"),
        email=identity.claim_mapping.get("email", "email"),
        groups=identity.claim_mapping.get("groups", "groups"),
    )
    return IdentityConfig(
        provider=identity.provider,
        issuer=identity.issuer,
        audience=identity.audience,
        claim_mapping=claim_mapping,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_content(content: str, path: Path) -> dict:
    """Parse file content based on extension."""
    suffix = path.suffix.lower()
    try:
        if suffix in (".yaml", ".yml"):
            data = yaml.safe_load(content)
        elif suffix == ".json":
            data = json.loads(content)
        else:
            raise PolicyFileError(
                f"Unsupported policy file extension '{suffix}' (expected .yaml, .yml, or .json)",
                file_path=str(path),
            )
    except yaml.YAMLError as exc:
        raise PolicyFileError(f"Failed to parse YAML: {exc}", file_path=str(path)) from exc
    except json.JSONDecodeError as exc:
        raise PolicyFileError(f"Failed to parse JSON: {exc}", file_path=str(path)) from exc

    if not isinstance(data, dict):
        raise PolicyFileError(
            "Policy file must contain a mapping at the top level", file_path=str(path)
        )
    return data


def _build_policy_config(data: dict, file_path: str) -> PolicyConfig:
    """Validate and build a PolicyConfig from parsed data."""
    # Version (required)
    if "version" not in data:
        raise PolicyValidationError("Missing required field: version", field="version")
    version = data["version"]
    if not isinstance(version, int):
        raise PolicyValidationError(
            f"version must be an integer, got {type(version).__name__}", field="version"
        )

    # Default effect
    default_raw = data.get("default", "deny")
    try:
        default = PolicyEffect(default_raw)
    except ValueError:
        raise PolicyValidationError(
            f"default must be 'allow' or 'deny', got '{default_raw}'", field="default"
        )

    # Identity (optional)
    identity = None
    if "identity" in data:
        identity = _build_identity(data["identity"])

    # Servers
    servers_raw = data.get("servers", [])
    if not isinstance(servers_raw, list):
        raise PolicyValidationError("servers must be a list", field="servers")
    servers = [_build_server(s, i) for i, s in enumerate(servers_raw)]

    # Check duplicate server names
    seen_names: set[str] = set()
    for server in servers:
        if server.name in seen_names:
            raise PolicyValidationError(f"Duplicate server name: '{server.name}'", field="servers")
        seen_names.add(server.name)

    # Policies
    policies_raw = data.get("policies", [])
    if not isinstance(policies_raw, list):
        raise PolicyValidationError("policies must be a list", field="policies")
    rules = [_build_policy_rule(p, i) for i, p in enumerate(policies_raw)]

    # Check duplicate policy IDs
    seen_ids: set[str] = set()
    for rule in rules:
        if rule.id in seen_ids:
            raise PolicyValidationError(f"Duplicate policy id: '{rule.id}'", field="policies")
        seen_ids.add(rule.id)

    # Logging (optional)
    logging_config = LoggingConfig()
    if "logging" in data:
        logging_config = _build_logging(data["logging"])

    # Masking (optional)
    masking_config = MaskingConfig()
    if "masking" in data:
        masking_config = _build_masking(data["masking"])

    try:
        return PolicyConfig(
            version=version,
            default=default,
            identity=identity,
            servers=servers,
            policies=rules,
            logging=logging_config,
            masking=masking_config,
        )
    except ValueError as exc:
        raise PolicyValidationError(str(exc), field="version") from exc


def _build_identity(data: dict) -> IdentityProviderConfig:
    """Build an IdentityProviderConfig from a dict."""
    if not isinstance(data, dict):
        raise PolicyValidationError("identity must be a mapping", field="identity")
    try:
        return IdentityProviderConfig(
            provider=data.get("provider", ""),
            issuer=data.get("issuer", ""),
            audience=data.get("audience", ""),
            claim_mapping=data.get("claim_mapping", {}),
        )
    except ValueError as exc:
        raise PolicyValidationError(str(exc), field="identity") from exc


def _build_server(data: dict, index: int) -> ServerDefinition:
    """Build a ServerDefinition from a dict."""
    if not isinstance(data, dict):
        raise PolicyValidationError(f"servers[{index}] must be a mapping", field="servers")
    try:
        return ServerDefinition(
            name=data.get("name", ""),
            transport=data.get("transport", ""),
            url=data.get("url"),
            command=data.get("command"),
            args=data.get("args", []),
            env=data.get("env", {}),
            token_exchange=data.get("token_exchange", False),
            target_audience=data.get("target_audience"),
            required_scopes=data.get("required_scopes", []),
        )
    except ValueError as exc:
        raise PolicyValidationError(str(exc), field=f"servers[{index}]") from exc


def _build_policy_rule(data: dict, index: int) -> PolicyRule:
    """Build a PolicyRule from a dict."""
    if not isinstance(data, dict):
        raise PolicyValidationError(f"policies[{index}] must be a mapping", field="policies")

    # Effect
    effect_raw = data.get("effect", "allow")
    try:
        effect = PolicyEffect(effect_raw)
    except ValueError:
        raise PolicyValidationError(
            f"policies[{index}].effect must be 'allow' or 'deny', got '{effect_raw}'",
            field=f"policies[{index}].effect",
        )

    # Subjects
    subjects = PolicySubjects()
    if "subjects" in data:
        s = data["subjects"]
        if not isinstance(s, dict):
            raise PolicyValidationError(
                f"policies[{index}].subjects must be a mapping",
                field=f"policies[{index}].subjects",
            )
        subjects = PolicySubjects(
            users=s.get("users", []),
            groups=s.get("groups", []),
        )

    # MCP servers
    mcp_servers_raw = data.get("mcp_servers", [])
    if not isinstance(mcp_servers_raw, list):
        raise PolicyValidationError(
            f"policies[{index}].mcp_servers must be a list",
            field=f"policies[{index}].mcp_servers",
        )
    mcp_servers = []
    for j, ms in enumerate(mcp_servers_raw):
        if not isinstance(ms, dict):
            raise PolicyValidationError(
                f"policies[{index}].mcp_servers[{j}] must be a mapping",
                field=f"policies[{index}].mcp_servers[{j}]",
            )
        try:
            mcp_servers.append(
                PolicyServerAccess(
                    name=ms.get("name", ""),
                    tools=ms.get("tools", []),
                )
            )
        except ValueError as exc:
            raise PolicyValidationError(
                str(exc), field=f"policies[{index}].mcp_servers[{j}]"
            ) from exc

    try:
        return PolicyRule(
            id=data.get("id", ""),
            description=data.get("description", ""),
            effect=effect,
            subjects=subjects,
            mcp_servers=mcp_servers,
        )
    except ValueError as exc:
        raise PolicyValidationError(str(exc), field=f"policies[{index}]") from exc


def _build_logging(data: dict) -> LoggingConfig:
    """Build a LoggingConfig from a dict."""
    if not isinstance(data, dict):
        raise PolicyValidationError("logging must be a mapping", field="logging")
    try:
        return LoggingConfig(
            level=data.get("level", "INFO"),
            include=data.get("include", []),
        )
    except ValueError as exc:
        raise PolicyValidationError(str(exc), field="logging") from exc


def _build_masking(data: dict) -> MaskingConfig:
    """Build a MaskingConfig from a dict."""
    if not isinstance(data, dict):
        raise PolicyValidationError("masking must be a mapping", field="masking")

    presidio = PresidioConfig()
    if "presidio" in data:
        p = data["presidio"]
        if not isinstance(p, dict):
            raise PolicyValidationError(
                "masking.presidio must be a mapping", field="masking.presidio"
            )
        presidio = PresidioConfig(
            enabled=p.get("enabled", False),
            entities=p.get("entities", []),
        )
    return MaskingConfig(presidio=presidio)


def _validate_cross_references(policy: PolicyConfig) -> None:
    """Check that server names in policies exist in the servers list."""
    server_names = {s.name for s in policy.servers}
    for rule in policy.policies:
        for access in rule.mcp_servers:
            if access.name not in server_names:
                raise PolicyReferenceError(
                    f"Policy '{rule.id}' references unknown server '{access.name}'",
                    field=f"policies.{rule.id}.mcp_servers",
                    reference=access.name,
                )


def _validate_tool_patterns(policy: PolicyConfig) -> None:
    """Validate wildcard patterns in tool lists.

    Valid patterns:
    - Exact names: "read_file"
    - Standalone wildcard: "*"
    - Prefix wildcard: "*_read"
    - Suffix wildcard: "read_*"

    Invalid:
    - Middle wildcards: "read*write"
    - Multiple wildcards: "**", "*_*"
    """
    for rule in policy.policies:
        for access in rule.mcp_servers:
            for tool in access.tools:
                if "*" in tool and not _VALID_WILDCARD_RE.match(tool):
                    raise PolicyValidationError(
                        f"Invalid tool wildcard pattern '{tool}' in policy '{rule.id}' "
                        f"for server '{access.name}'. Wildcards must be standalone '*', "
                        f"prefix '*suffix', or suffix 'prefix*'.",
                        field=f"policies.{rule.id}.mcp_servers.{access.name}.tools",
                    )
