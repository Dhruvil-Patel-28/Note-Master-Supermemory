#!/usr/bin/env bash
# Launch supermemory-server with the localhost-only Ollama stack.
#
# Env vars are exported here EXPLICITLY (not via ~/.supermemory/env): the
# server's lifecycle removes that file after first boot, which silently
# breaks the wrapper's `set -a; . env` sourcing and leaves the server
# pointing at a cwd-relative data dir with no LLM provider.
#
# Hard constraints (see AGENTS.md):
#   - OLLAMA_HOST must stay http://localhost:11434 (no hosted APIs, no keys)
#   - no telemetry (SUPERMEMORY_DISABLE_TELEMETRY=1)
#   - data lives in ~/.supermemory, one directory

set -euo pipefail

export OPENAI_API_KEY="${OPENAI_API_KEY:-ollama}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-http://localhost:11434/v1}"
export OPENAI_MODEL="${OPENAI_MODEL:-llama3.2:3b}"
export OPENAI_FAST_MODEL="${OPENAI_FAST_MODEL:-llama3.2:3b}"
export OPENAI_TEXT_MODEL="${OPENAI_TEXT_MODEL:-llama3.2:3b}"
export SUPERMEMORY_EMBEDDING_PROVIDER="${SUPERMEMORY_EMBEDDING_PROVIDER:-openai}"
export SUPERMEMORY_EMBEDDING_BASE_URL="${SUPERMEMORY_EMBEDDING_BASE_URL:-http://localhost:11434/v1}"
export SUPERMEMORY_EMBEDDING_MODEL="${SUPERMEMORY_EMBEDDING_MODEL:-nomic-embed-text}"
export SUPERMEMORY_EMBEDDING_DIMENSIONS="${SUPERMEMORY_EMBEDDING_DIMENSIONS:-768}"
export SUPERMEMORY_DISABLE_TELEMETRY=1
export SUPERMEMORY_DATA_DIR="${SUPERMEMORY_DATA_DIR:-$HOME/.supermemory}"
export SUPERMEMORY_INGEST_CONCURRENCY=2
export SUPERMEMORY_EMBEDDING_RAM_LIMIT=1gb

exec "$HOME/.local/bin/supermemory-server" "$@"