# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

mcp-zero is an Enterprise MCP (Model Context Protocol) Gateway — a centrally hosted control point that enforces governance, auditing, and data protection for MCP traffic in regulated enterprise environments. It supports both Streamable HTTP and stdio transports.

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

- **Fail-closed by default**: Gateway refuses to start without `MCP_POLICY_FILE` unless `MCP_ALLOW_INSECURE=true` is set
- **OBO status**: OBO token exchange infrastructure exists in code but is not invoked in the request flow
- **Presidio**: Masking is hardcoded to Presidio, not yet plugin-based (plugin architecture is planned)

## Architecture

The gateway sits between enterprise AI tools and MCP servers:

- **Identity**: Okta OAuth2 JWT validation (OBO token exchange infrastructure exists but not yet invoked in request flow)
- **Governance**: Static YAML/JSON policy files, default-deny, server/tool/user/group-level controls
- **Data protection**: Inline Presidio masking (hardcoded, not plugin-based yet) for PII and secrets on inputs and outputs
- **Auditing**: Structured logs with user attribution, correlation IDs, policy decisions
- **Transports**: Streamable HTTP and stdio (both enforce full pipeline when configured)

Both HTTP and stdio transports enforce governance, masking, and auditing through the same unified pipeline when configured.

- **Analytics**: Optional Redis-based analytics subsystem (`src/mcp_zero/analytics/`). Enabled by setting `ANALYTICS_REDIS_URL`. See README for all `ANALYTICS_*` env vars. Use `docker compose up` to run Redis + RedisInsight locally.
