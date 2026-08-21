#!/usr/bin/env bash
# Retrieval-quality battery: asserts the facts that reach the LLM context for
# representative questions — independent of model answers.
#
# Runs against the REAL user_main store, read-only (no captures created or
# deleted; only supermemory search/list endpoints are hit). Requires:
#   - supermemory-server on 127.0.0.1:6767 (scripts/run-supermemory.sh)
#   - ~/.supermemory/api-key
#
# Usage: bash scripts/run-retrieval-tests.sh [-k pattern] [extra pytest args]

set -euo pipefail

export MEMORY_ENABLED=1
export MEMORY_CONTAINER_TAG="${MEMORY_CONTAINER_TAG:-user_main}"

# Label-matching reads the real captures DB (SELECT-only). Must be exported
# before pytest imports app — conftest's setdefault yields to an existing var.
export NOTE_MASTER_DATA_DIR="${NOTE_MASTER_DATA_DIR:-"$(cd "$(dirname "$0")/../backend/data" && pwd)"}"

if [ -z "${MEMORY_API_KEY:-}" ] && [ -f "$HOME/.supermemory/api-key" ]; then
  export MEMORY_API_KEY="$(tr -d '[:space:]' < "$HOME/.supermemory/api-key")"
fi

if ! curl -s -m 5 http://127.0.0.1:6767/v3/health >/dev/null 2>&1; then
  echo "ERROR: supermemory-server not reachable on 127.0.0.1:6767 — launch scripts/run-supermemory.sh first" >&2
  exit 1
fi

cd "$(dirname "$0")/../backend"
exec uv run pytest tests -m retrieval "$@"
