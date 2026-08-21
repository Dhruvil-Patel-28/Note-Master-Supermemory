#!/usr/bin/env bash
# Launch supermemory-server with a switchable LLM brain.
#
#   SUPERMEMORY_PROVIDER=gemini|groq|ollama     (default: gemini)
#
# gemini — Google AI Studio's free tier runs the memory agent, i.e. the LLM
#          that reads every synced document and writes the graph memories.
#          This is the one deliberate exception to the local-first rule:
#          DOCUMENT TEXT LEAVES THE MACHINE during ingestion only. Queries
#          never hit the cloud (chat answers stay on the local Ollama 3b).
#          Key resolution order: $GOOGLE_API_KEY, then ~/.supermemory/gemini-key.
#          Free tier (gemini-3.5-flash-lite): ~15 RPM / ~1K req/day / ~250K TPM.
#          Model choice matters more than anything here: daily quotas are PER
#          MODEL, and the newest flagships get starved buckets for new keys
#          (gemini-3.6-flash = 20 req/day — exhausted by a single day of
#          testing; verified Aug 2026). Flash-Lite carries the largest free
#          bucket and is sufficient for extraction. This also sidesteps Groq's
#          free tier entirely: the agent's fixed prompt is ~13.8K tokens/call,
#          over Groq's 8K TPM cap on every free model. Override with
#          SUPERMEMORY_AGENT_MODEL (must support tool calling).
# groq   — Groq Cloud runs the memory agent. Requires the PAID dev tier: the
#          free tier's 8K TPM limit rejects every memory-agent request
#          ("Request too large ... Limit 8000"). Same privacy tradeoff as
#          gemini. Key resolution: $GROQ_API_KEY, then ~/.supermemory/groq-key.
# ollama — the original fully-local stack (hermes3). Nothing ever leaves the
#          machine. Use this when offline or out of cloud quota.
#
# Embeddings ALWAYS run locally on Ollama (nomic-embed-text): neither Gemini
# nor Groq serves embedding models here, and the binary silently inherits
# OPENAI_BASE_URL for embeddings when SUPERMEMORY_EMBEDDING_BASE_URL is unset
# — so that var is pinned here unconditionally, never derived from the chat
# provider.
#
# Env vars are exported here EXPLICITLY (not via ~/.supermemory/env): the
# server's lifecycle removes that file after first boot, which silently
# breaks the wrapper's `set -a; . env` sourcing and leaves the server
# pointing at a cwd-relative data dir with no LLM provider.
#
# Invariants kept across all profiles:
#   - OLLAMA_HOST stays http://localhost:11434
#   - no telemetry (SUPERMEMORY_DISABLE_TELEMETRY=1)
#   - data lives in ~/.supermemory, one directory

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROVIDER="${SUPERMEMORY_PROVIDER:-gemini}"
PROXY_PID=""

cleanup() {
  if [ -n "$PROXY_PID" ]; then
    kill "$PROXY_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

_key_from() { # _key_from ENV_VAR KEYFILE — prints key or empty string
  if [ -n "${!1:-}" ]; then
    printf '%s' "${!1}"
    return 0
  fi
  if [ -f "$2" ]; then
    tr -d '[:space:]' < "$2"
    return 0
  fi
  printf ''
}

case "$PROVIDER" in
  gemini)
    GEMINI_KEY="$(_key_from GOOGLE_API_KEY "$HOME/.supermemory/gemini-key")"
    if [ -z "$GEMINI_KEY" ]; then
      echo "WARNING: SUPERMEMORY_PROVIDER=gemini but GOOGLE_API_KEY is unset and" >&2
      echo "WARNING: ~/.supermemory/gemini-key does not exist — falling back to the" >&2
      echo "WARNING: fully-local ollama profile." >&2
      PROVIDER="ollama"
    else
      export OPENAI_API_KEY="$GEMINI_KEY"
      # Route through the thought-signature stitch proxy (scripts/gemini-proxy.py):
      # Gemini 3.x thinking models stamp tool calls with a thought_signature and
      # REQUIRE it back on follow-up turns; the binary's AI SDK drops it, so
      # every agent loop dies at turn 2 with 400 "missing thought_signature".
      # The proxy stashes signatures from responses and re-injects them.
      pkill -f "gemini-proxy.py" 2>/dev/null || true
      GEMINI_PROXY_PORT="${GEMINI_PROXY_PORT:-8766}"
      python3 "$SCRIPT_DIR/gemini-proxy.py" &
      PROXY_PID=$!
      sleep 1
      # Trailing-slash-free base: the proxy forwards the path verbatim.
      export OPENAI_BASE_URL="http://127.0.0.1:${GEMINI_PROXY_PORT}/v1beta/openai"
      export OPENAI_MODEL="${OPENAI_MODEL:-${SUPERMEMORY_AGENT_MODEL:-gemini-3.5-flash-lite}}"
    fi
    ;;
  groq)
    GROQ_KEY="$(_key_from GROQ_API_KEY "$HOME/.supermemory/groq-key")"
    if [ -z "$GROQ_KEY" ]; then
      echo "WARNING: SUPERMEMORY_PROVIDER=groq but GROQ_API_KEY is unset and" >&2
      echo "WARNING: ~/.supermemory/groq-key does not exist — falling back to the" >&2
      echo "WARNING: fully-local ollama profile." >&2
      PROVIDER="ollama"
    else
      export OPENAI_API_KEY="$GROQ_KEY"
      export OPENAI_BASE_URL="https://api.groq.com/openai/v1"
      export OPENAI_MODEL="${OPENAI_MODEL:-${SUPERMEMORY_AGENT_MODEL:-openai/gpt-oss-120b}}"
    fi
    ;;
  ollama)
    ;;
  *)
    echo "ERROR: unknown SUPERMEMORY_PROVIDER '$PROVIDER' (expected gemini|groq|ollama)" >&2
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

if [ -n "$PROXY_PID" ]; then
  # Foreground (not exec) so the EXIT trap can stop the proxy with us.
  "$HOME/.local/bin/supermemory-server" "$@"
else
  exec "$HOME/.local/bin/supermemory-server" "$@"
fi
