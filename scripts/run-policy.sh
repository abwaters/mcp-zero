#!/usr/bin/env bash
# Run the gateway with a named policy from the policies/ directory.
# Usage: scripts/run-policy.sh <policy-name> [extra-args...]
# Example: scripts/run-policy.sh everything
#          scripts/run-policy.sh everything --host 0.0.0.0 --port 9000

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

if [ -z "$1" ]; then
    echo "Usage: scripts/run-policy.sh <policy-name> [extra-args...]"
    echo
    echo "Available policies:"
    for f in policies/*.yaml policies/*.yml policies/*.json; do
        [ -e "$f" ] && echo "  $(basename "${f%.*}")"
    done
    exit 1
fi

POLICY_NAME="$1"
shift

# Resolve the policy file (try .yaml, then .yml, then .json)
if [ -f "policies/${POLICY_NAME}.yaml" ]; then
    export MCP_POLICY_FILE="policies/${POLICY_NAME}.yaml"
elif [ -f "policies/${POLICY_NAME}.yml" ]; then
    export MCP_POLICY_FILE="policies/${POLICY_NAME}.yml"
elif [ -f "policies/${POLICY_NAME}.json" ]; then
    export MCP_POLICY_FILE="policies/${POLICY_NAME}.json"
else
    echo "Error: No policy file found for \"${POLICY_NAME}\""
    echo "Looked for: policies/${POLICY_NAME}.yaml, .yml, .json"
    exit 1
fi

echo "Using policy: ${MCP_POLICY_FILE}"
source .venv/bin/activate
python -m mcp_zero "$@"
