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

## Key Design Decisions

- **Python 3.12+** required
- **setuptools** build backend with `pyproject.toml` as single config (build, deps, pytest, ruff)
- **ruff** for both linting and formatting (line-length 100, rules: E, F, I, W)
- **uvx-compatible** — has `[project.scripts]` entry point; keep all runtime deps in `dependencies` (not optional)
- Dev-only tools (pytest, ruff) go in `[project.optional-dependencies] dev`

## Planned Architecture (from docs/)

The gateway sits between enterprise AI tools and MCP servers:

- **Identity**: Okta OAuth2 with OBO (on-behalf-of) token exchange for downstream MCP servers
- **Governance**: Static YAML/JSON policy files, default-deny, server/tool/user-level controls
- **Data protection**: Inline Presidio masking for PII and secrets on inputs and outputs
- **Auditing**: Structured logs with user attribution, correlation IDs, policy decisions
- **Transports**: Streamable HTTP (primary enforcement path with OBO) and stdio (gateway-spawned servers, no OBO needed)

Key constraint: local developer stdio usage outside the gateway is observability-only (no endpoint control).
