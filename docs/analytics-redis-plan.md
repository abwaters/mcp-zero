# Analytics Redis Integration — Implementation Plan

> **STATUS**: This feature is **FULLY IMPLEMENTED** as of the current codebase.
> This document now serves as reference documentation for the analytics subsystem.
> See `src/mcp_zero/analytics/` for the implementation.

## Overview

Add an optional analytics subsystem to the MCP gateway that publishes real-time
operational metrics to Redis. When configured, every tool call, policy denial,
and data redaction event is recorded as aggregated counters in Redis with TTL,
providing a live snapshot of gateway activity without persisting long-term logs.

Multiple MCP gateway instances can share the same Redis cluster. Each gateway
writes to dynamically-namespaced keys (keyed by environment + gateway ID), so a
dashboard can discover all gateways and let the operator choose which one(s) to
inspect.

**Current scope**: populate Redis from the MCP gateway. Dashboard UI is a
separate conversation.

---

## Design Decisions

### 1. Time-Bucketed Counters (not raw events)

Rather than pushing individual events into Redis (which would require list
trimming and expensive scans), we use **time-bucketed hash counters**:

- Each bucket covers a configurable window (default: 60 seconds).
- Bucket ID = `floor(unix_epoch / bucket_seconds)`.
- Each bucket key gets a TTL = `retention_seconds` (default: 3600 = 1 hour).
- The dashboard reads recent buckets and aggregates client-side.

This gives both a current-state snapshot AND time-series trend data, while
keeping Redis memory usage bounded and predictable.

### 2. Fire-and-Forget / Non-Blocking

Analytics must never slow down or break the request pipeline:

- The `AnalyticsHook` enqueues lightweight event dicts onto an in-memory
  `asyncio.Queue`.
- A background `asyncio.Task` drains the queue and writes to Redis in batched
  pipelines.
- If Redis is unavailable, events are dropped with a warning log (no backpressure
  on the gateway).
- If the queue is full, new events are dropped (bounded queue, default 10,000).

### 3. Dynamic Key Namespace

All keys follow the pattern:

```
{prefix}:{environment}:{gateway_id}:...
```

- `prefix` — configurable, default `mcpgw`
- `environment` — configurable, e.g. `production`, `staging`, `dev`
- `gateway_id` — configurable unique instance identifier; auto-generated UUID if
  not set

### 4. Gateway Discovery via Registry

Each gateway periodically writes a heartbeat to a sorted set:

```
{prefix}:gateways  →  Sorted Set { member="{env}:{gw_id}", score=epoch }
```

Plus an info hash:

```
{prefix}:gw:{env}:{gw_id}:info  →  Hash { host, port, started_at, version, ... }
```

The dashboard scans the sorted set, filters by score > (now − timeout), and
reads info hashes for display.

---

## Redis Key Schema

All keys use the prefix `{p}` = `{prefix}:{env}:{gw}` for brevity below.

### Registry (gateway discovery)

| Key | Type | TTL | Description |
|-----|------|-----|-------------|
| `{prefix}:gateways` | Sorted Set | none (members self-expire via score) | All known gateways; score = last heartbeat epoch |
| `{prefix}:gw:{env}:{gw}:info` | Hash | 3× heartbeat interval | Gateway metadata: host, port, started_at, version, server_count |

### Time-Bucketed Counters

Bucket key component: `b:{bucket_id}` where `bucket_id = floor(epoch / bucket_seconds)`.

| Key | Type | TTL | Description |
|-----|------|-----|-------------|
| `{p}:b:{bid}:tool_calls` | Hash | retention | `{server}::{tool}` → call count |
| `{p}:b:{bid}:server_calls` | Hash | retention | `{server}` → call count |
| `{p}:b:{bid}:user_calls` | Hash | retention | `{user_id}` → call count |
| `{p}:b:{bid}:latency_sum` | Hash | retention | `{server}::{tool}` → cumulative ms |
| `{p}:b:{bid}:latency_count` | Hash | retention | `{server}::{tool}` → count (for avg) |
| `{p}:b:{bid}:denials` | Hash | retention | `{server}::{tool}` → denial count |
| `{p}:b:{bid}:denial_rules` | Hash | retention | `{rule_id}` → denial count |
| `{p}:b:{bid}:denial_users` | Hash | retention | `{user_id}` → denial count |
| `{p}:b:{bid}:redactions` | Hash | retention | `{entity_type}` → redaction count |
| `{p}:b:{bid}:redaction_tools` | Hash | retention | `{server}::{tool}` → event count |
| `{p}:b:{bid}:errors` | Hash | retention | `{server}::{tool}` → error count |
| `{p}:b:{bid}:request_bytes` | Hash | retention | `{server}::{tool}` → cumulative bytes |
| `{p}:b:{bid}:response_bytes` | Hash | retention | `{server}::{tool}` → cumulative bytes |

### Dashboard Slicing Dimensions

From the bucketed hashes, the dashboard can slice by:

- **Time** — aggregate across bucket ranges for trends
- **Server** — `server_calls` hash, or filter `tool_calls` by prefix
- **Tool** — `tool_calls` hash
- **User** — `user_calls`, `denial_users` hashes
- **Policy Rule** — `denial_rules` hash
- **Entity Type** — `redactions` hash
- **Cross-dimension** — tool calls per server, denials per user per tool, etc.

---

## Configuration

### Policy File Extension

```yaml
version: 1
# ... existing config ...

analytics:
  redis:
    url: "redis://localhost:6379/0"       # Redis URL (or first cluster node)
    cluster: false                         # Set true for Redis Cluster
    tls: false                             # Enable TLS
    password: null                         # Optional auth password
    socket_timeout: 5.0                    # Connection timeout (seconds)
    retry_on_timeout: true                 # Auto-retry on timeout
  environment: "production"                # Key namespace segment
  gateway_id: "gateway-east-1"            # Unique instance ID (auto-UUID if omitted)
  key_prefix: "mcpgw"                     # Redis key prefix
  bucket_seconds: 60                       # Time bucket width
  retention_seconds: 3600                  # TTL for all analytics keys
  heartbeat_seconds: 30                    # Gateway heartbeat interval
  queue_size: 10000                        # Max in-memory event queue depth
  flush_interval: 1.0                      # Background flush interval (seconds)
```

### Environment Variable Overrides

| Env Var | Overrides | Default |
|---------|-----------|---------|
| `ANALYTICS_REDIS_URL` | `analytics.redis.url` | _(none — analytics disabled)_ |
| `ANALYTICS_REDIS_CLUSTER` | `analytics.redis.cluster` | `false` |
| `ANALYTICS_REDIS_PASSWORD` | `analytics.redis.password` | _(none)_ |
| `ANALYTICS_ENVIRONMENT` | `analytics.environment` | `default` |
| `ANALYTICS_GATEWAY_ID` | `analytics.gateway_id` | _(auto-generated UUID)_ |
| `ANALYTICS_KEY_PREFIX` | `analytics.key_prefix` | `mcpgw` |
| `ANALYTICS_RETENTION_SECONDS` | `analytics.retention_seconds` | `3600` |

Analytics is **disabled by default**. It activates only when a Redis URL is
configured (via policy file or env var).

---

## Module Structure

```
src/mcp_zero/analytics/
├── __init__.py          # Public API: AnalyticsHook, AnalyticsConfig
├── config.py            # AnalyticsConfig, RedisConfig dataclasses
├── client.py            # RedisAnalyticsClient (standalone + cluster)
├── keys.py              # KeyBuilder — generates namespaced Redis keys
├── collector.py         # AnalyticsCollector — queue + background flush
└── hook.py              # AnalyticsHook — lifecycle hook
```

### config.py

```python
@dataclass(frozen=True)
class RedisConfig:
    url: str = ""
    cluster: bool = False
    tls: bool = False
    password: str | None = None
    socket_timeout: float = 5.0
    retry_on_timeout: bool = True

@dataclass(frozen=True)
class AnalyticsConfig:
    redis: RedisConfig = field(default_factory=RedisConfig)
    environment: str = "default"
    gateway_id: str = ""          # auto-generated if empty
    key_prefix: str = "mcpgw"
    bucket_seconds: int = 60
    retention_seconds: int = 3600
    heartbeat_seconds: int = 30
    queue_size: int = 10000
    flush_interval: float = 1.0
    enabled: bool = False         # computed: True when redis.url is set

    def __post_init__(self):
        if not self.gateway_id:
            object.__setattr__(self, 'gateway_id', str(uuid.uuid4())[:8])
        object.__setattr__(self, 'enabled', bool(self.redis.url))
```

### client.py

Wraps `redis.asyncio.Redis` and `redis.asyncio.RedisCluster`:

- `connect()` / `disconnect()` — lifecycle management
- `pipeline_write(ops: list[RedisOp])` — batched pipeline execution
- `heartbeat(key, info_key, info_data, ttl, score)` — ZADD + HSET
- Automatic reconnection with backoff on transient failures
- All operations are fire-and-forget with exception logging

### keys.py

```python
class KeyBuilder:
    def __init__(self, prefix: str, environment: str, gateway_id: str):
        self._base = f"{prefix}:{environment}:{gateway_id}"
        self._registry_prefix = prefix

    def bucket_key(self, metric: str, bucket_id: int) -> str:
        return f"{self._base}:b:{bucket_id}:{metric}"

    def registry_key(self) -> str:
        return f"{self._registry_prefix}:gateways"

    def info_key(self) -> str:
        return f"{self._registry_prefix}:gw:{self._env}:{self._gw}:info"
```

### collector.py

Core event-processing engine:

```python
class AnalyticsCollector:
    """Accepts analytics events, batches them, writes to Redis."""

    async def start(self) -> None:
        """Start the background flush task and heartbeat task."""

    async def stop(self) -> None:
        """Stop background tasks and flush remaining events."""

    def record_tool_call(self, *, server, tool, user_id, duration_ms,
                         request_bytes, response_bytes) -> None:
        """Enqueue a tool call event (non-blocking)."""

    def record_denial(self, *, server, tool, user_id, rule_id) -> None:
        """Enqueue a policy denial event (non-blocking)."""

    def record_redaction(self, *, server, tool, entity_type, count) -> None:
        """Enqueue a redaction event (non-blocking)."""

    def record_error(self, *, server, tool) -> None:
        """Enqueue an error event (non-blocking)."""
```

The background flush task:
1. Drains the queue (up to batch_size items per cycle)
2. Groups increments by bucket key
3. Executes a single Redis pipeline: `HINCRBY` for each field + `EXPIRE` for each key
4. Runs every `flush_interval` seconds

The heartbeat task:
1. Runs every `heartbeat_seconds`
2. `ZADD {prefix}:gateways {now} "{env}:{gw_id}"`
3. `HSET {prefix}:gw:{env}:{gw_id}:info host ... port ... started_at ...`
4. `EXPIRE {prefix}:gw:{env}:{gw_id}:info {heartbeat_seconds * 3}`

### hook.py

```python
class AnalyticsHook(LifecycleHook):
    """Records analytics events at PRE_AUDIT hook point."""

    async def on_pre_audit(self, ctx: HookContext) -> HookContext:
        # Record tool call (always, for both allow and deny)
        # Record denial (if policy_decision == DENY)
        # Record redactions (if masking was applied)

    async def on_error(self, ctx: HookContext, error: Exception) -> None:
        # Record denial for ShortCircuitError with deny=True
        # Record error for other exceptions
```

---

## Integration Points

### main.py Changes

1. **`_load_policy_and_configs()`** — also returns `AnalyticsConfig | None`
2. **`_build_pipeline()`** — accepts optional `AnalyticsConfig`, creates and
   registers `AnalyticsHook` at priority 145 (just before AuditHook at 150)
3. **`run()`** — starts/stops the `AnalyticsCollector` via app lifespan

### governance/config.py Changes

Add `AnalyticsConfig` to `PolicyConfig`:

```python
@dataclass(frozen=True)
class PolicyConfig:
    # ... existing fields ...
    analytics: AnalyticsConfig | None = None
```

### governance/loader.py Changes

Add `_build_analytics()` parser, called from `_build_policy_config()`.

### proxy/app.py Changes

Wire the `AnalyticsCollector.start()` and `stop()` into the Starlette lifespan
context manager so the background tasks run for the lifetime of the app.

### pyproject.toml Changes

Add `redis>=5.0` to runtime dependencies (redis-py 5.x has built-in async
support and RedisCluster).

---

## Error Handling

- **Redis unavailable at startup**: Log warning, gateway starts normally without
  analytics. Collector retries connection in background.
- **Redis goes away mid-operation**: Log warning, drop events, attempt reconnect
  on next flush cycle.
- **Queue full**: Drop new events, log warning (rate-limited to avoid log spam).
- **Malformed event data**: Skip event, log error.
- **Never**: block the request pipeline, raise exceptions into the hook chain,
  or cause the gateway to crash.

---

## Data Flow Diagram

```
Client Request
      │
      ▼
  ProxyServer._call_tool()
      │
      ▼
  Pipeline.execute()
      │
      ├─ IdentityHook (PRE_VALIDATION)
      ├─ GovernanceHook (POST_VALIDATION)  ──→ denial info on ctx
      ├─ MaskingHook (PRE_MASKING)         ──→ masking events on ctx
      │
      │  ... upstream call ...
      │
      ├─ MaskingHook (POST_MASKING)        ──→ output masking events
      ├─ AnalyticsHook (PRE_AUDIT, 145)    ──→ enqueues to collector
      ├─ AuditHook (PRE_AUDIT, 150)        ──→ emits JSON logs
      │
      ▼
  Response to Client

                    ┌─────────────────────┐
  Collector Queue ──│ Background Flush Task│──→ Redis Pipeline
                    └─────────────────────┘
                    ┌─────────────────────┐
                    │ Background Heartbeat │──→ Redis ZADD + HSET
                    └─────────────────────┘
```
