# Plugins

mcp-zero uses a plugin architecture to extend the gateway pipeline with custom hooks for masking, filtering, metrics, and more. Plugins are discovered via Python entry points and activated through the policy file.

## Quick Start

### 1. Enable a plugin in your policy file

Add a `plugins:` section to your policy YAML:

```yaml
version: 1
default: deny

servers:
  - name: github-server
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]

policies:
  - id: allow-github
    effect: allow
    mcp_servers:
      - name: github-server
        tools: ["*"]

plugins:
  - name: presidio-masking
    config:
      entities:
        - PERSON
        - EMAIL_ADDRESS
        - CREDIT_CARD

  - name: github-repo-filter
    config:
      mode: allowlist
      repos:
        - myorg/*
      servers:
        - github-server
```

### 2. Start the gateway with the policy file

```bash
MCP_POLICY_FILE=policy.yaml python -m mcp_zero
```

That's it. The gateway discovers installed plugins via entry points, loads only those listed in the policy file, and wires them into the pipeline.

## How Plugins Work

### Discovery

Plugins register themselves as Python entry points under the `mcp_zero.plugins` group in `pyproject.toml`:

```toml
[project.entry-points."mcp_zero.plugins"]
presidio-masking = "mcp_zero.plugins.presidio_masking:PresidioMaskingPlugin"
github-repo-filter = "mcp_zero.plugins.github_repo_filter:GitHubRepoFilterPlugin"
```

The `PluginManager` discovers all available entry points at startup but only loads plugins explicitly listed in the policy file (explicit-only loading).

### Lifecycle

1. **Discover** -- `PluginManager` scans `mcp_zero.plugins` entry points
2. **Load** -- For each plugin in the policy file, the entry point is resolved and the class is instantiated
3. **Configure** -- `plugin.configure(config)` is called with the `config:` dict from the policy file. Invalid config raises `PluginLoadError` and prevents startup (fail-fast).
4. **Register** -- `plugin.register(registry)` lets the plugin create lifecycle hooks and register them with the `HookRegistry` at a specific priority
5. **Run** -- Hooks execute on every request at their registered hook points
6. **Teardown** -- On shutdown, `plugin.teardown()` is called in reverse order for cleanup

### Pipeline Hook Points

Hooks execute in this order on every request:

| Hook Point | When | Typical Use |
|---|---|---|
| `pre_validation` | Before any validation | Early transforms |
| `post_validation` | After request validation | Governance, input filtering |
| `pre_masking` | Before masking stage | Input preparation |
| `post_masking` | After masking stage | Output filtering, redaction |
| `pre_audit` | Before audit logging | Metrics, enrichment |
| `on_error` | On pipeline error/denial | Error tracking |

### Hook Priorities

Hooks run in priority order (lower = earlier). Built-in priorities:

| Priority | Component |
|---|---|
| 10 | Identity (JWT validation) |
| 50 | Governance (policy engine) |
| 55 | GitHub repo filter (default) |
| 75 | Presidio masking (default) |
| 145 | Analytics |
| 150 | Audit logging |

All plugin priorities are configurable via the `priority` key in their policy config.

## Built-in Plugins

| Plugin | Entry Point | Purpose | Docs |
|---|---|---|---|
| [Presidio Masking](presidio-masking.md) | `presidio-masking` | PII detection and redaction on inputs and outputs | [presidio-masking.md](presidio-masking.md) |
| [GitHub Repo Filter](github-repo-filter.md) | `github-repo-filter` | Allowlist/blocklist enforcement on GitHub repository access | [github-repo-filter.md](github-repo-filter.md) |

## Writing a Custom Plugin

### 1. Create the plugin class

```python
from mcp_zero.plugin import BasePlugin
from mcp_zero.pipeline.hooks import LifecycleHook
from mcp_zero.pipeline.registry import HookRegistry
from mcp_zero.context import HookContext
from mcp_zero.pipeline.errors import ShortCircuitError
from typing import Any


class MyHook(LifecycleHook):
    async def on_post_validation(self, ctx: HookContext) -> HookContext:
        # Inspect or modify the request
        if ctx.tool_name == "dangerous_tool":
            raise ShortCircuitError("Tool not allowed", deny=True)
        return ctx


class MyPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "my-plugin"

    def configure(self, config: dict[str, Any]) -> None:
        self._setting = config.get("setting", "default")

    def register(self, registry: HookRegistry) -> None:
        registry.register(MyHook(), priority=60)
```

### 2. Register the entry point

In your package's `pyproject.toml`:

```toml
[project.entry-points."mcp_zero.plugins"]
my-plugin = "my_package.my_module:MyPlugin"
```

### 3. Activate in the policy file

```yaml
plugins:
  - name: my-plugin
    config:
      setting: custom-value
```

### Key APIs

- **`HookContext`** -- Immutable dataclass passed through hooks. Use `ctx.evolve(field=new_value)` to return a modified copy.
- **`ShortCircuitError(reason, deny=True)`** -- Raise to stop the pipeline. `deny=True` records a policy denial.
- **`BasePlugin`** -- Convenience base class with no-op defaults for `configure`, `register`, `teardown`.
- **`EventBus`** -- Plugins can optionally implement `register_event_handlers(bus)` to receive audit events.

### Design Principles

- **Fail-closed**: If a plugin encounters an error processing a request, it should deny the request rather than letting it through.
- **Explicit-only loading**: Plugins must be listed in the policy file. No auto-activation.
- **Config validation at startup**: Validate all configuration in `configure()` and raise `ValueError` for bad config. This prevents the gateway from starting with misconfigured plugins.
