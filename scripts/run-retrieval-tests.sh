#!/usr/bin/env bash
# Retrieval-quality battery: asserts the facts that reach the LLM context for
# representative questions — independent of model answers.
#
# Runs against the REAL local ChromaDB vector store, read-only (no captures
# created or deleted). Requires:
#   - a populated ChromaDB store (captures indexed under NOTE_MASTER_DATA_DIR)
#   - Ollama on 127.0.0.1:11434 for nomic-embed-text
#
# Usage: bash scripts/run-retrieval-tests.sh [-k pattern] [extra pytest args]

set -euo pipefail

export MEMORY_ENABLED=1

# Reads the real captures DB (SELECT-only) and the real ChromaDB store. Must
# be exported before pytest imports app — conftest's setdefault yields to an
# existing var.
export NOTE_MASTER_DATA_DIR="${NOTE_MASTER_DATA_DIR:-"$(cd "$(dirname "$0")/../backend/data" && pwd)"}"

if ! uv run -C "$(dirname "$0")/../backend" python -c "import sys; sys.path.insert(0,'.'); from app.retrieval import vector_store as vs; assert vs.count() > 0" >/dev/null 2>&1; then
  echo "ERROR: local ChromaDB store empty or unreachable under NOTE_MASTER_DATA_DIR=$NOTE_MASTER_DATA_DIR — index captures first (scripts/start-stack.sh)" >&2
  exit 1
fi

cd "$(dirname "$0")/../backend"
exec uv run pytest tests -m retrieval "$@"