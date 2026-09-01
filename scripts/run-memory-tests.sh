#!/usr/bin/env bash
# Run the live @memory e2e battery against the local ChromaDB vector store.
#
# Only entry point for `pytest -m memory` — the hermetic suite keeps
# MEMORY_ENABLED=0; this runner flips the env before pytest imports app
# (settings are read at import time).
#
# Requires: Ollama on 127.0.0.1:11434 (nomic-embed-text + the chat model)
# and a writable ChromaDB persist dir under NOTE_MASTER_DATA_DIR.

set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/../backend" && pwd)"

export MEMORY_ENABLED=1
export NOTE_MASTER_DATA_DIR="${NOTE_MASTER_DATA_DIR:-"$BACKEND_DIR/data"}"

cd "$BACKEND_DIR"
exec uv run pytest tests -m memory "$@"