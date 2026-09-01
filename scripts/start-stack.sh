#!/usr/bin/env bash
# Manual stack control — NOTHING auto-starts at login/reboot.
#
#   scripts/start-stack.sh          # start backend + frontend
#   scripts/start-stack.sh stop     # stop both
#
# Nothing here runs unless you invoke it. Langfuse is separate:
#   scripts/run-langfuse.sh up|down
#
# Env wiring when starting:
#   - Langfuse keys sourced from ~/.langfuse/keys (or your shell) if present
#
# Logs: /tmp/nm-backend.log, /tmp/nm-frontend.log

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

port_up() { nc -z 127.0.0.1 "$1" >/dev/null 2>&1; }

stop_all() {
  pkill -f "uvicorn app.main" 2>/dev/null || true
  pkill -f "next dev" 2>/dev/null || true
  sleep 1
  for port in 8000 3000; do
    port_up $port && echo "  :$port still up ❌" || echo "  :$port stopped ✅"
  done
}

if [ "${1:-up}" = "stop" ]; then
  stop_all
  exit 0
fi

# --- backend ----------------------------------------------------------------
if port_up 8000; then
  echo "backend      : already up (:8000)"
else
  [ -f "$HOME/.langfuse/keys" ] && source "$HOME/.langfuse/keys"
  export LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY LANGFUSE_HOST
  export MEMORY_ENABLED=1
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
echo "stop with: scripts/start-stack.sh stop"