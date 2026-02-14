# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

mcp-zero is an Enterprise MCP (Model Context Protocol) Gateway — a centrally hosted control point that enforces governance, auditing, and data protection for MCP traffic in regulated enterprise environments. It supports Streamable HTTP, SSE (deprecated), and stdio transports.

See `docs/prd.md` for full requirements and `docs/enterprise_mcp_gateway_architecture_diagram.md` for the logical architecture.

## Development Commands

```bash
# Setup (creates venv, installs package + dev deps)
scripts\install.bat

# Run tests
scripts\test.bat                # all tests
scripts\test.bat -v             # verbose
scripts\test.bat tests/test_main.py::test_run   # single test

# Lint and format
scripts\lint.bat
scripts\format.bat

# Run the application
scripts\run.bat
python -m mcp_zero
```

All scripts activate `.venv` automatically. The package is installed in editable mode (`pip install -e ".[dev]"`).

## Code Architecture

**`src` layout** — source lives in `src/mcp_zero/` to prevent accidental imports from the project root.

- `src/mcp_zero/main.py` — application entry point, wired as `mcp-zero` CLI via `[project.scripts]` in pyproject.toml
- `src/mcp_zero/__main__.py` — enables `python -m mcp_zero`
- `tests/` — pytest tests, configured via `[tool.pytest.ini_options]` in pyproject.toml

## Pre-Commit Checklist

**IMPORTANT**: Before every git commit, always run:

1. `ruff format src tests` — auto-format all source and test files
2. `ruff check src tests` — verify no lint errors

CI will reject PRs that fail `ruff format --check`. Do not skip this step.

## Key Design Decisions

- **Python 3.12+** required
- **setuptools** build backend with `pyproject.toml` as single config (build, deps, pytest, ruff)
- **ruff** for both linting and formatting (line-length 100, rules: E, F, I, W)
- **uvx-compatible** — has `[project.scripts]` entry point; keep all runtime deps in `dependencies` (not optional)
- Dev-only tools (pytest, ruff) go in `[project.optional-dependencies] dev`

## Important Implementation Notes

- **Fail-closed design goal**: Gateway is designed to enforce security by default, but without a policy file it runs in legacy mode with no enforcement (see security review F-03 for details). Set `MCP_POLICY_FILE` to enable governance/identity/masking.
- **OBO status**: OBO token exchange is FULLY IMPLEMENTED and operational. Requires explicit environment variables (`OKTA_TOKEN_ENDPOINT`, `OKTA_CLIENT_ID`, `OKTA_CLIENT_SECRET`) and per-server `token_exchange: true` configuration.
- **Presidio**: Masking uses Presidio as a built-in plugin (loaded via entry point), but Presidio is not yet extracted to a separate installable package
- **Plugin architecture**: FULLY IMPLEMENTED (entry point discovery, lifecycle management, hook registration). See `src/mcp_zero/plugin_manager.py` and `docs/plugin-architecture-design.md`

## Architecture

The gateway sits between enterprise AI tools and MCP servers:

- **Identity**: Okta OAuth2 JWT validation with OBO token exchange (requires explicit configuration, see docs/okta_obo_for_an_enterprise_mcp_gateway.md)
- **Governance**: Static YAML/JSON policy files, default-deny, server/tool/user/group-level controls
- **Data protection**: Inline Presidio masking (built-in plugin) for PII and secrets on inputs and outputs
- **Auditing**: Structured logs with user attribution, correlation IDs, policy decisions
- **Transports**: Streamable HTTP, SSE (deprecated), and stdio (all enforce full pipeline when configured)
- **Plugins**: Entry-point based plugin system for extending the pipeline with custom hooks (masking, metrics, etc.)

All transports (Streamable HTTP, SSE, stdio) enforce governance, masking, and auditing through the same unified pipeline when configured.

- **SSE transport**: Deprecated in MCP protocol version 2025-03-26. Provided for backward compatibility with clients/servers that haven't adopted Streamable HTTP. Controlled by `MCP_SSE_ENABLED` env var (default: `true`). Set to `false` to disable inbound SSE endpoints and reduce attack surface.

- **Analytics**: Optional Redis-based analytics subsystem (`src/mcp_zero/analytics/`). Enabled by setting `ANALYTICS_REDIS_URL`. See README for all `ANALYTICS_*` env vars. Use `docker compose up` to run Redis + RedisInsight locally.
