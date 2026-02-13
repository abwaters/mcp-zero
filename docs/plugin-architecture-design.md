# Plugin Architecture Design

> **STATUS**: This design has been **IMPLEMENTED**. The plugin infrastructure, entry-point
> discovery, `PluginManager`, and Presidio-as-a-plugin are all in production code. The
> built-in Presidio plugin lives at `src/mcp_zero/plugins/presidio_masking.py` and is
> registered via the `mcp_zero.plugins` entry-point group in `pyproject.toml`.
>
> Phase 2 (extracting Presidio into a separate package) and Phase 3 (example plugins)
> from the implementation plan below have not been started — Presidio remains a built-in
> plugin rather than a separate installable package.

## Problem Statement

The gateway's cross-cutting concerns (identity, governance, masking, auditing) are
currently wired together in `main.py` via direct imports and conditional `if` blocks.
Presidio is a hard dependency in `pyproject.toml`, its config type (`PresidioConfig`) is
embedded in `governance/config.py`, and `main.py` explicitly instantiates
`PresidioMaskingEngine`. This coupling means:

- Adding a new masking engine (e.g., regex-only, AWS Comprehend) requires editing
  `main.py`, `governance/config.py`, and `pyproject.toml`.
- Adding a new cross-cutting concern (rate limiting, metrics, caching) requires editing
  `main.py` to wire it into the pipeline.
- Presidio's heavy NLP dependencies are pulled in even when masking is disabled.
- Enterprise adopters can't extend the gateway without forking the core.

## Design Goals

1. **Presidio becomes a plugin** — removable from core deps, loaded only when configured.
2. **Uniform plugin contract** — one interface for all extension types (hooks, engines,
   providers).
3. **Config-driven activation** — plugins declared in the policy YAML; no code changes to
   add/remove.
4. **Entry-point discovery** — plugins distributed as separate packages, discovered via
   Python `importlib.metadata` entry points.
5. **Explicit-only loading** — no auto-discovery; plugins must be listed in the policy file
   to activate (defense-in-depth).
6. **Backward compatible** — existing policy files and env-var configs continue to work
   without changes during a transition period.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│                    Policy File (YAML)                 │
│                                                      │
│  plugins:                                            │
│    - name: presidio-masking                          │
│      package: mcp-zero-presidio      (entry point)   │
│      config:                                         │
│        entities: [PERSON, EMAIL_ADDRESS, ...]         │
│    - name: rate-limiter                              │
│      package: mcp-zero-ratelimit                     │
│      config:                                         │
│        max_requests_per_minute: 60                   │
└──────────────┬───────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────┐
│                  PluginManager                        │
│                                                      │
│  1. Reads plugin declarations from policy file       │
│  2. Resolves each package → entry point              │
│  3. Calls plugin_factory() → Plugin instance         │
│  4. Calls plugin.configure(config_dict)              │
│  5. Calls plugin.register(registry)                  │
│  6. On shutdown: plugin.teardown()                   │
└──────────────┬───────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────┐
│               HookRegistry / Pipeline                 │
│                                                      │
│  Plugins register LifecycleHooks at their chosen     │
│  priority. Pipeline executes hooks in order.         │
│  (Existing mechanism — no changes needed.)           │
└──────────────────────────────────────────────────────┘
```

---

## 1. Plugin Protocol

A single `Plugin` protocol defines the contract. All plugins implement this — whether
they contribute hooks, masking engines, auth providers, or transports.

```python
# src/mcp_zero/plugin.py

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from mcp_zero.pipeline.registry import HookRegistry


@runtime_checkable
class Plugin(Protocol):
    """Contract that every mcp-zero plugin must satisfy."""

    @property
    def name(self) -> str:
        """Unique plugin identifier (e.g. 'presidio-masking')."""
        ...

    def configure(self, config: dict[str, Any]) -> None:
        """Receive the plugin's config block from the policy file.

        Called once at startup before register(). The plugin should validate
        its configuration here and raise ValueError for bad config (fail-fast).
        """
        ...

    def register(self, registry: HookRegistry) -> None:
        """Register lifecycle hooks (or other extensions) into the pipeline.

        Called once after configure(). The plugin decides its own hook
        priorities — the PluginManager does not impose ordering beyond
        what the priority system already provides.
        """
        ...

    def teardown(self) -> None:
        """Release resources on gateway shutdown.

        Called once during graceful shutdown. Must not raise.
        """
        ...
```

### Why a Protocol (not ABC)?

- Plugins don't need to inherit from a base class — structural subtyping is sufficient.
- Third-party packages can implement the protocol without importing `mcp_zero`.
- `runtime_checkable` allows the `PluginManager` to validate at load time.

### Convenience Base Class

For plugin authors who prefer inheritance, provide an optional base with no-op defaults:

```python
# src/mcp_zero/plugin.py (continued)

class BasePlugin:
    """Optional convenience base with no-op defaults."""

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def configure(self, config: dict[str, Any]) -> None:
        pass

    def register(self, registry: HookRegistry) -> None:
        pass

    def teardown(self) -> None:
        pass
```

---

## 2. Plugin Discovery via Entry Points

Plugins register themselves under the `mcp_zero.plugins` entry-point group in their
`pyproject.toml`:

```toml
# In the plugin package (e.g., mcp-zero-presidio/pyproject.toml)
[project.entry-points."mcp_zero.plugins"]
presidio-masking = "mcp_zero_presidio:create_plugin"
```

The entry point value is a callable (factory function) that returns a `Plugin` instance:

```python
# mcp_zero_presidio/__init__.py
def create_plugin() -> Plugin:
    return PresidioMaskingPlugin()
```

### Why Entry Points?

- Standard Python packaging mechanism — no custom discovery logic needed.
- `pip install mcp-zero-presidio` automatically makes the plugin available.
- No import-time side effects; the factory is only called when the plugin is activated.
- Works with virtual environments, system installs, and container images.

---

## 3. PluginManager

```python
# src/mcp_zero/plugin_manager.py

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import Any

from mcp_zero.pipeline.registry import HookRegistry
from mcp_zero.plugin import Plugin

logger = logging.getLogger(__name__)

# Entry-point group name for mcp-zero plugins
_EP_GROUP = "mcp_zero.plugins"


class PluginLoadError(Exception):
    """Raised when a plugin cannot be loaded or configured."""


class PluginManager:
    """Discovers, configures, and manages plugin lifecycle."""

    def __init__(self) -> None:
        self._plugins: list[Plugin] = []
        self._available: dict[str, Any] = {}  # name → factory callable
        self._discover()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover(self) -> None:
        """Scan installed entry points under the mcp_zero.plugins group."""
        eps = entry_points(group=_EP_GROUP)
        for ep in eps:
            self._available[ep.name] = ep
            logger.debug("Discovered plugin entry point: %s (%s)", ep.name, ep.value)
        logger.info("Discovered %d plugin entry point(s)", len(self._available))

    def available_plugins(self) -> list[str]:
        """Return names of all discovered (installed) plugins."""
        return sorted(self._available.keys())

    # ------------------------------------------------------------------
    # Loading & Configuration
    # ------------------------------------------------------------------

    def load_plugins(
        self,
        plugin_declarations: list[dict[str, Any]],
        registry: HookRegistry,
    ) -> None:
        """Load, configure, and register all plugins declared in the policy file.

        Args:
            plugin_declarations: List of plugin config dicts from the policy file.
                Each dict has: {"name": str, "package": str, "config": dict}
            registry: The HookRegistry plugins register their hooks into.

        Raises:
            PluginLoadError: If a declared plugin is not installed, fails to
                configure, or doesn't satisfy the Plugin protocol.
        """
        for decl in plugin_declarations:
            name = decl.get("name", "")
            package = decl.get("package", name)
            config = decl.get("config", {})

            plugin = self._load_one(name, package, config)
            plugin.register(registry)
            self._plugins.append(plugin)
            logger.info("Plugin '%s' registered (package=%s)", name, package)

    def _load_one(self, name: str, package: str, config: dict[str, Any]) -> Plugin:
        """Load and configure a single plugin by entry-point name."""
        ep = self._available.get(package)
        if ep is None:
            installed = ", ".join(self.available_plugins()) or "(none)"
            raise PluginLoadError(
                f"Plugin '{name}' references package '{package}' but no entry point "
                f"'{package}' is registered under [{_EP_GROUP}]. "
                f"Installed plugins: {installed}. "
                f"Install the plugin package and retry."
            )

        try:
            factory = ep.load()
        except Exception as exc:
            raise PluginLoadError(
                f"Failed to load entry point '{package}': {exc}"
            ) from exc

        plugin = factory()

        if not isinstance(plugin, Plugin):
            raise PluginLoadError(
                f"Factory for '{package}' returned {type(plugin).__name__}, "
                f"which does not satisfy the Plugin protocol."
            )

        try:
            plugin.configure(config)
        except Exception as exc:
            raise PluginLoadError(
                f"Plugin '{name}' failed to configure: {exc}"
            ) from exc

        return plugin

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def teardown_all(self) -> None:
        """Call teardown() on all loaded plugins (best-effort)."""
        for plugin in reversed(self._plugins):
            try:
                plugin.teardown()
                logger.debug("Plugin '%s' torn down", plugin.name)
            except Exception:
                logger.exception("Error tearing down plugin '%s'", plugin.name)

    @property
    def loaded_plugins(self) -> list[Plugin]:
        return list(self._plugins)
```

### Key Behaviors

| Behavior | Rationale |
|----------|-----------|
| Fail-fast on missing plugin | A declared plugin that isn't installed is a config error — fail at startup, not at first request. |
| Fail-fast on bad config | `configure()` errors halt startup. No silent degradation. |
| Teardown in reverse order | Mirrors the registration order — last registered, first torn down. |
| No auto-activation | A plugin must appear in the policy file's `plugins:` list to load. Installing a package alone does nothing. |

---

## 4. Policy File Changes

### New `plugins` Section

```yaml
version: 1
default: deny

# NEW — plugin declarations
plugins:
  - name: presidio-masking
    package: mcp-zero-presidio          # entry-point name
    config:
      entities:
        - PERSON
        - EMAIL_ADDRESS
        - PHONE_NUMBER
        - CREDIT_CARD
        - API_KEY
        - PASSWORD

  - name: rate-limiter
    package: mcp-zero-ratelimit
    config:
      max_requests_per_minute: 100
      burst: 20

# ... rest of policy file unchanged ...
identity:
  provider: okta
  # ...

servers:
  # ...

policies:
  # ...
```

### Backward Compatibility

During the transition period, the existing `masking.presidio` config block is still
supported. If both `masking.presidio.enabled: true` AND a `presidio-masking` plugin
declaration exist, the plugin declaration takes precedence and a deprecation warning is
logged.

If `masking.presidio.enabled: true` but no plugin declaration exists, the gateway checks
whether the `mcp-zero-presidio` entry point is installed. If so, it auto-creates the
plugin declaration from the legacy config. If not, it raises a clear error explaining
the migration path.

---

## 5. Config Model Changes

### `governance/config.py`

```python
@dataclass(frozen=True)
class PluginDeclaration:
    """A plugin declared in the policy file.

    Args:
        name: Human-readable plugin identifier.
        package: Entry-point name under [mcp_zero.plugins].
        config: Plugin-specific configuration dict.
    """
    name: str = ""
    package: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("plugin.name is required")


@dataclass(frozen=True)
class PolicyConfig:
    """Root policy configuration."""
    version: int = 0
    default: PolicyEffect = PolicyEffect.DENY
    identity: IdentityProviderConfig | None = None
    servers: list[ServerDefinition] = field(default_factory=list)
    policies: list[PolicyRule] = field(default_factory=list)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    masking: MaskingConfig = field(default_factory=MaskingConfig)         # kept for compat
    plugins: list[PluginDeclaration] = field(default_factory=list)       # NEW
```

### `governance/loader.py`

The loader gains a `_parse_plugins()` function that converts the raw YAML `plugins:`
list into `PluginDeclaration` objects. Validation is minimal at load time — plugins
validate their own config in `configure()`.

---

## 6. Changes to `main.py`

The `_build_pipeline()` function changes from explicit hook wiring to plugin-driven
registration:

```python
def _build_pipeline(
    identity_config: IdentityConfig | None = None,
    policy_config: PolicyConfig | None = None,
) -> tuple[Pipeline | None, PluginManager]:
    """Build pipeline with core hooks + plugin hooks."""

    registry = HookRegistry()
    plugin_manager = PluginManager()

    # --- Core hooks (identity, governance, audit) remain in main.py ---
    # These are gateway-intrinsic concerns, not plugins.
    identity_enabled = _register_identity_hook(registry, identity_config)
    _register_governance_hook(registry, policy_config, identity_enabled)

    # --- Plugins (masking, rate-limiting, metrics, etc.) ---
    if policy_config is not None:
        plugin_declarations = _resolve_plugin_declarations(policy_config)
        plugin_manager.load_plugins(plugin_declarations, registry)

    # --- Audit hook always last ---
    logging_config = policy_config.logging if policy_config else None
    audit_hook = AuditHook(logging_config=logging_config)
    registry.register(audit_hook, priority=150)

    # Build pipeline
    if not identity_enabled and policy_config is None:
        return None, plugin_manager

    registry.build()
    return Pipeline(registry), plugin_manager
```

### What Stays in Core vs. What Becomes a Plugin

| Concern | Location | Rationale |
|---------|----------|-----------|
| Identity (JWT/JWKS) | **Core** (`main.py`) | Foundational — everything else depends on knowing who the caller is. |
| Governance (policy eval) | **Core** (`main.py`) | Foundational — the deny/allow decision must happen before plugins can act on the request. |
| Audit (structured logging) | **Core** (`main.py`) | Foundational — must always be present for compliance. |
| Masking (Presidio) | **Plugin** | Implementation choice — could be Presidio, regex, AWS Comprehend, or nothing. |
| Rate limiting | **Plugin** | Optional operational concern. |
| Metrics/observability | **Plugin** | Optional — Prometheus, OpenTelemetry, Datadog, etc. |
| Request transformation | **Plugin** | Optional — payload enrichment, header injection, etc. |
| Custom validators | **Plugin** | Domain-specific validation that varies by deployment. |

---

## 7. Presidio as a Plugin Package

### Package Structure

```
mcp-zero-presidio/
├── pyproject.toml
├── src/
│   └── mcp_zero_presidio/
│       ├── __init__.py        # create_plugin() factory
│       ├── plugin.py          # PresidioMaskingPlugin
│       ├── engine.py          # PresidioMaskingEngine (moved from core)
│       └── hook.py            # MaskingHook (moved from core)
```

### `pyproject.toml`

```toml
[project]
name = "mcp-zero-presidio"
version = "0.1.0"
dependencies = [
    "mcp-zero>=0.2.0",
    "presidio-analyzer>=2.2",
    "presidio-anonymizer>=2.2",
]

[project.entry-points."mcp_zero.plugins"]
presidio-masking = "mcp_zero_presidio:create_plugin"
```

### Plugin Implementation

```python
# mcp_zero_presidio/plugin.py

from __future__ import annotations

from typing import Any

from mcp_zero.pipeline.registry import HookRegistry
from mcp_zero.plugin import BasePlugin

from mcp_zero_presidio.engine import PresidioMaskingEngine
from mcp_zero_presidio.hook import MaskingHook


class PresidioMaskingPlugin(BasePlugin):
    """Presidio-based PII masking plugin for mcp-zero."""

    @property
    def name(self) -> str:
        return "presidio-masking"

    def configure(self, config: dict[str, Any]) -> None:
        entities = config.get("entities", [])
        if not entities:
            raise ValueError(
                "presidio-masking plugin requires 'entities' list in config"
            )
        self._entities = entities
        self._engine = PresidioMaskingEngine(entities)

    def register(self, registry: HookRegistry) -> None:
        hook = MaskingHook(self._engine, self._entities)
        registry.register(hook, priority=75)

    def teardown(self) -> None:
        # Presidio has no cleanup needs
        pass
```

### What Moves Out of Core

| File | Action |
|------|--------|
| `src/mcp_zero/masking/presidio.py` | **Move** → `mcp-zero-presidio/src/mcp_zero_presidio/engine.py` |
| `src/mcp_zero/masking/hook.py` | **Move** → `mcp-zero-presidio/src/mcp_zero_presidio/hook.py` |
| `src/mcp_zero/masking/engine.py` | **Keep in core** — the abstract `MaskingEngine` base stays as a shared interface |
| `src/mcp_zero/governance/config.py` (`PresidioConfig`) | **Deprecate** — plugin uses its own config dict |
| `pyproject.toml` (`presidio-analyzer`, `presidio-anonymizer`) | **Remove** from core deps |

---

## 8. Plugin Priority Conventions

Plugins choose their own hook priorities when calling `registry.register()`. To avoid
conflicts, document these conventions:

| Range | Slot | Purpose |
|-------|------|---------|
| 0–9 | Reserved | Future core use |
| 10–19 | Identity | Authentication (core) |
| 20–49 | Pre-governance plugins | Rate limiting, request validation |
| 50–69 | Governance | Policy evaluation (core) |
| 70–99 | Post-governance plugins | Masking, transformation, enrichment |
| 100–139 | General plugins | Metrics, caching, custom hooks |
| 140–149 | Reserved | Future core use |
| 150+ | Audit | Structured logging (core) |

Plugins document their recommended priority in their README. If two plugins collide,
the gateway operator adjusts via an optional `priority` field in the plugin declaration:

```yaml
plugins:
  - name: presidio-masking
    package: mcp-zero-presidio
    priority: 75          # explicit override
    config:
      entities: [PERSON, EMAIL_ADDRESS]
```

---

## 9. Implementation Plan

### Phase 1: Plugin Infrastructure (core changes)

1. Create `src/mcp_zero/plugin.py` — `Plugin` protocol + `BasePlugin`
2. Create `src/mcp_zero/plugin_manager.py` — `PluginManager`
3. Add `PluginDeclaration` to `governance/config.py`
4. Update `governance/loader.py` to parse `plugins:` section
5. Refactor `main.py`:
   - Extract identity/governance hook registration into helper functions
   - Replace hardwired Presidio block with `PluginManager.load_plugins()`
   - Add plugin teardown to shutdown path
6. Add tests for `PluginManager` (mock entry points, error cases)

### Phase 2: Extract Presidio Plugin

1. Create `mcp-zero-presidio/` package alongside the main repo (or as subdirectory
   under `plugins/`)
2. Move `masking/presidio.py` → `mcp_zero_presidio/engine.py`
3. Move `masking/hook.py` → `mcp_zero_presidio/hook.py`
4. Keep `masking/engine.py` (abstract base) in core
5. Remove `presidio-analyzer`, `presidio-anonymizer` from core `pyproject.toml`
6. Add backward-compat shim in `main.py` for `masking.presidio` config
7. Add integration tests for the plugin package
8. Update documentation

### Phase 3: Example Plugins (optional, validates the architecture)

1. Rate-limiting plugin (validates pre-governance hook slot)
2. OpenTelemetry metrics plugin (validates general hook slot)
3. Regex masking plugin (validates alternative masking engine)

---

## 10. Open Questions

1. **Monorepo vs. separate repos for plugins?**
   - Recommendation: Start with a `plugins/` subdirectory in this repo for first-party
     plugins. Third-party plugins live in their own repos.

2. **Should identity and governance eventually become plugins too?**
   - Not in this phase. They are foundational — the pipeline makes no sense without them.
     If a deployment truly doesn't need identity (e.g., local dev), the existing
     `MCP_ALLOW_INSECURE` mechanism handles that. Revisit if we see demand for
     alternative identity providers (Azure AD, Keycloak) — at that point, the identity
     *provider* (JWT validation strategy) could become pluggable while the identity
     *hook* stays in core.

3. **Plugin ordering guarantees across plugins?**
   - The priority system handles this. If two plugins must run in a specific order
     relative to each other, they coordinate via documented priority values. The
     `PluginManager` doesn't enforce inter-plugin ordering beyond what priorities provide.

4. **Plugin access to gateway internals beyond the HookRegistry?**
   - Phase 1 only exposes the `HookRegistry` to `register()`. If plugins need more
     (e.g., access to `ServerManager`, `PolicyConfig`), we can expand the `register()`
     signature or introduce a `PluginContext` object. Keep the surface small initially.
