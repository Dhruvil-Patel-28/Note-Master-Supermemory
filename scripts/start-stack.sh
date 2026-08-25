#!/usr/bin/env bash
# Start the full Note Master stack (idempotent — safe to re-run anytime):
#   1. supermemory-server   :6767 (Gemini-profile memory agent)
#   2. FastAPI backend      :8000 (with Langfuse tracing when keys exist)
#   3. Next.js frontend     :3000
#
# Env wiring:
#   - Langfuse keys sourced from ~/.supermemory/langfuse-keys if present
#   - supermemory API key from ~/.supermemory/api-key
#
# Logs: /tmp/nm-supermemory.log, /tmp/nm-backend.log, /tmp/nm-frontend.log

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

port_up() { nc -z 127.0.0.1 "$1" >/dev/null 2>&1; }

# --- supermemory -----------------------------------------------------------
if port_up 6767; then
  echo "supermemory  : already up (:6767)"
else
  (cd "$ROOT" && nohup ./scripts/run-supermemory.sh > /tmp/nm-supermemory.log 2>&1 &)
  for i in $(seq 1 30); do port_up 6767 && break; sleep 1; done
  port_up 6767 && echo "supermemory  : started (:6767)" || { echo "supermemory  : FAILED — see /tmp/nm-supermemory.log"; exit 1; }
fi

# --- backend ----------------------------------------------------------------
if port_up 8000; then
  echo "backend      : already up (:8000)"
else
  [ -f "$HOME/.supermemory/langfuse-keys" ] && source "$HOME/.supermemory/langfuse-keys"
  export LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY LANGFUSE_HOST
  [ -f "$HOME/.supermemory/api-key" ] && export MEMORY_API_KEY="$(tr -d '[:space:]' < "$HOME/.supermemory/api-key")"
  export MEMORY_ENABLED=1 MEMORY_CONTAINER_TAG=user_main
  (cd "$ROOT/backend" && nohup uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 > /tmp/nm-backend.log 2>&1 &)
  for i in $(seq 1 30); do port_up 8000 && break; sleep 1; done
  port_up 8000 && echo "backend      : started (:8000)" || { echo "backend      : FAILED — see /tmp/nm-backend.log"; exit 1; }
fi

# --- frontend ---------------------------------------------------------------
if port_up 3000; then
  echo "frontend     : already up (:3000)"
else
  (cd "$ROOT/frontend" && nohup npm run dev > /tmp/nm-frontend.log 2>&1 &)
  for i in $(seq 1 45); do port_up 3000 && break; sleep 2; done
  port_up 3000 && echo "frontend     : started (:3000)" || { echo "frontend     : FAILED — see /tmp/nm-frontend.log"; exit 1; }
fi

echo "stack ready ✅  (app: http://localhost:3000 · langfuse: http://localhost:3001)"
