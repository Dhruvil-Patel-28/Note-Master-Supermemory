#!/usr/bin/env bash
# Run the live @memory e2e battery against the local supermemory-server.
#
# Only entry point for `pytest -m memory` — the hermetic suite keeps
# MEMORY_ENABLED=0 and a test container tag; this runner flips the env before
# pytest imports app (settings are read at import time), pulls the API key
# from ~/.supermemory/api-key, and isolates all test writes to the nm_test
# container so the user's real data (user_main) is never touched.
#
# Requires: supermemory-server up (launch via scripts/run-supermemory.sh)
# and Ollama with the configured models.

set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/../backend" && pwd)"
KEY_FILE="$HOME/.supermemory/api-key"

if [[ ! -f "$KEY_FILE" ]]; then
    echo "error: $KEY_FILE not found — is supermemory-server installed?" >&2
    exit 1
fi

export MEMORY_ENABLED=1
export MEMORY_CONTAINER_TAG=nm_test
export MEMORY_API_KEY="$(cat "$KEY_FILE")"

cd "$BACKEND_DIR"
exec uv run pytest tests -m memory "$@"