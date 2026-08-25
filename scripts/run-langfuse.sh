#!/usr/bin/env bash
# Start/stop the self-hosted Langfuse stack (localhost-only observability).
#
#   scripts/run-langfuse.sh up       # start (idempotent)
#   scripts/run-langfuse.sh down     # stop, keep data
#
# After first `up`:
#   1. open http://localhost:3001 and sign up (local-only credentials)
#   2. Settings -> API Keys -> create one
#   3. export before starting the backend:
#        export LANGFUSE_PUBLIC_KEY=pk-lf-...
#        export LANGFUSE_SECRET_KEY=sk-lf-...
#      (or add to ~/.zshrc). Tracing is a no-op without keys.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../infra/langfuse" && pwd)"

case "${1:-up}" in
  up)
    docker compose -f "$DIR/docker-compose.yml" up -d
    echo "waiting for langfuse..."
    for i in $(seq 1 30); do
      if curl -s -m 2 -o /dev/null http://localhost:3001; then break; fi
      sleep 2
    done
    echo "UI:      http://localhost:3001"
    echo "sign up -> Settings -> API Keys -> export LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY"
    ;;
  down)
    docker compose -f "$DIR/docker-compose.yml" down
    ;;
  *)
    echo "usage: $0 [up|down]" >&2
    exit 2
    ;;
esac
