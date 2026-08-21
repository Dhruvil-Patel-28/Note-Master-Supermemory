#!/usr/bin/env bash
# Launch supermemory-server with a switchable LLM brain.
#
#   SUPERMEMORY_PROVIDER=groq|ollama     (default: groq)
#
# groq   — Groq Cloud (free tier) runs the memory agent, i.e. the LLM that
#          reads every synced document and writes the graph memories. This is
#          the one deliberate exception to the local-first rule: DOCUMENT TEXT
#          LEAVES THE MACHINE during ingestion only. Queries never hit Groq
#          (chat answers stay on the local Ollama 3b).
#          Key resolution order: $GROQ_API_KEY, then ~/.supermemory/groq-key.
#          Free-tier budgets (per model, per key):
#            llama-3.3-70b-versatile  30 RPM / 1K req/day / 100K tokens/day
#            openai/gpt-oss-120b      30 RPM / 1K req/day / 200K tokens/day
#            llama-3.1-8b-instant     30 RPM / 14.4K req/day / 500K tokens/day
#          Override the model with SUPERMEMORY_AGENT_MODEL (must support tool
#          calling). If you ingest many large docs per day, prefer gpt-oss-120b;
#          if the daily token cap bites, llama-3.1-8b-instant is the fallback.
# ollama — the original fully-local stack (hermes3). Nothing ever leaves the
#          machine. Use this when offline or out of Groq quota.
#
# Embeddings ALWAYS run locally on Ollama (nomic-embed-text): Groq serves no
# embedding models, and the binary silently inherits OPENAI_BASE_URL for
# embeddings when SUPERMEMORY_EMBEDDING_BASE_URL is unset — so that var is
# pinned here unconditionally, never derived from the chat provider.
#
# Env vars are exported here EXPLICITLY (not via ~/.supermemory/env): the
# server's lifecycle removes that file after first boot, which silently
# breaks the wrapper's `set -a; . env` sourcing and leaves the server
# pointing at a cwd-relative data dir with no LLM provider.
#
# Invariants kept across both profiles:
#   - OLLAMA_HOST stays http://localhost:11434
#   - no telemetry (SUPERMEMORY_DISABLE_TELEMETRY=1)
#   - data lives in ~/.supermemory, one directory

set -euo pipefail

PROVIDER="${SUPERMEMORY_PROVIDER:-groq}"

_groq_key() {
  if [ -n "${GROQ_API_KEY:-}" ]; then
    printf '%s' "$GROQ_API_KEY"
    return 0
  fi
  local keyfile="$HOME/.supermemory/groq-key"
  if [ -f "$keyfile" ]; then
    tr -d '[:space:]' < "$keyfile"
    return 0
  fi
  printf ''
}

case "$PROVIDER" in
  groq)
    GROQ_KEY="$(_groq_key)"
    if [ -z "$GROQ_KEY" ]; then
      echo "WARNING: SUPERMEMORY_PROVIDER=groq but GROQ_API_KEY is unset and" >&2
      echo "WARNING: ~/.supermemory/groq-key does not exist — falling back to the" >&2
      echo "WARNING: fully-local ollama profile." >&2
      PROVIDER="ollama"
    else
      export OPENAI_API_KEY="$GROQ_KEY"
      export OPENAI_BASE_URL="https://api.groq.com/openai/v1"
      export OPENAI_MODEL="${OPENAI_MODEL:-${SUPERMEMORY_AGENT_MODEL:-llama-3.3-70b-versatile}}"
    fi
    ;;
  ollama)
    ;;
  *)
    echo "ERROR: unknown SUPERMEMORY_PROVIDER '$PROVIDER' (expected groq|ollama)" >&2
    exit 2
    ;;
esac

if [ "$PROVIDER" = "ollama" ]; then
  export OPENAI_API_KEY="${OPENAI_API_KEY:-ollama}"
  export OPENAI_BASE_URL="http://localhost:11434/v1"
  export OPENAI_MODEL="${OPENAI_MODEL:-hermes3}"
fi

export OPENAI_FAST_MODEL="$OPENAI_MODEL"
export OPENAI_TEXT_MODEL="$OPENAI_MODEL"

# Embeddings: local, always (see header).
export SUPERMEMORY_EMBEDDING_PROVIDER="${SUPERMEMORY_EMBEDDING_PROVIDER:-openai}"
export SUPERMEMORY_EMBEDDING_BASE_URL="http://localhost:11434/v1"
export SUPERMEMORY_EMBEDDING_MODEL="${SUPERMEMORY_EMBEDDING_MODEL:-nomic-embed-text}"
export SUPERMEMORY_EMBEDDING_DIMENSIONS="${SUPERMEMORY_EMBEDDING_DIMENSIONS:-768}"
export SUPERMEMORY_DISABLE_TELEMETRY=1
export SUPERMEMORY_DATA_DIR="${SUPERMEMORY_DATA_DIR:-$HOME/.supermemory}"
export SUPERMEMORY_INGEST_CONCURRENCY=2
export SUPERMEMORY_EMBEDDING_RAM_LIMIT=1gb

exec "$HOME/.local/bin/supermemory-server" "$@"
