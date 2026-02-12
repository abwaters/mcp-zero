#!/usr/bin/env bash
# Launch the MCP Inspector pointed at the running gateway.
# Usage: scripts/inspector.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "Connecting inspector to ${URL}"
npx -y @modelcontextprotocol/inspector
