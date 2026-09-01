# Note Master

**Local-first personal notes app with grounded AI retrieval.**

Dump text notes, voice memos, and documents into a chat-style composer, then ask anything in natural language and get a structured, cited answer pulled from your own data. Sensitive documents (Aadhaar, PAN, bank statements) are stored and answerable like everything else, badged in chat and audit-logged.

Everything runs on your machine — local Ollama models for chat/OCR/ASR/embeddings, a local ChromaDB vector store for semantic retrieval, SQLite for app state. Nothing leaves the machine: OCR, ASR, embeddings, chat answers, and files-on-disk all stay local.

## Features

- **Capture** — text notes, voice memos (local ASR transcription, original audio retained), and documents (PDFs via Docling → markdown with real tables, images via vision OCR, Word, Excel)
- **Grounded chat** — answers come only from your captured content, schema-constrained JSON output, citations, structured field-card answers, an honest not-found path, and typo tolerance
- **Hybrid retrieval** — semantic search over locally-embedded document chunks (nomic-embed-text) combined with a sparse-representation pin for label-matched documents, so enumeration questions ("list all my projects") surface complete answers
- **Document access** — "show me my resume" opens the original uploaded file in a preview, never an extracted-text dump
- **Guardrails** — sensitivity tiers (`none`/`moderate`/`high`) assigned at ingestion, surfaced as labels: sensitive sources are badged in chat and every sensitive retrieval is audit-logged (informational — nothing is blocked); prompt-injection resistant
- **Versioning** — re-uploading a document creates a new version (old ones retained, restorable); editable labels without re-extraction
- **Correction loop** — flag a wrong answer to store feedback and re-index the source
- **UI** — dark/light themes, responsive two-pane layout, playback for voice notes

## Architecture

```
┌─────────────────────────────┐   REST   ┌──────────────────────────────┐
│ Frontend: Next.js 16        │─────────▶│ Backend: FastAPI             │
│ (localhost:3000)            │          │  ingestion pipeline          │
│ capture + chat + settings   │          │  retrieval + guardrails      │
└─────────────────────────────┘          └──────────────┬───────────────┘
                                                        │
              ┌─────────────────────────────────────────┴────────────────┐
              ▼                                                          ▼
      ┌───────────────┐                                       ┌───────────────────────┐
      │ SQLite        │                                       │ ChromaDB              │
      │ app state     │                                       │ (local persist dir)   │
      │ tiers/audit   │                                       │ raw-content chunks    │
      │ versions      │                                       │ nomic embeddings      │
      └───────────────┘                                       └──────────┬────────────┘
              ▼                                                          │
      Ollama (localhost:11434)                                          │
      · llama3.2:3b — chat + intent                                     │
      · nomic-embed-text — embeddings  ◀────────────────────────────────┘
      · qwen2.5vl:3b — image OCR
```

Every capture is chunked, embedded (nomic-embed-text, locally), and stored raw in ChromaDB — there is no per-document-type parsing or graph layer anywhere in this repo. Chat retrieves semantically with a similarity floor, then grounds its answer strictly in the retrieved chunks. Tiers are labels, not barriers: sensitive docs index, answer, and are audit-logged like any other.

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 16 (App Router), shadcn/ui |
| Backend | FastAPI, SQLite (stdlib, no ORM) |
| PDF extraction | Docling (local, markdown tables) |
| Knowledge & retrieval | ChromaDB (local persistent vector store) + Ollama `nomic-embed-text` |
| Chat / intent | Ollama `llama3.2:3b` (schema-constrained JSON) |
| OCR | Ollama `qwen2.5vl:3b` (images) |
| ASR | faster-whisper (`base`, CPU) |
| Tracing | self-hosted Langfuse (optional) |

## Requirements

- macOS (tested on Apple Silicon, 16GB)
- Python 3.14+ and [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- [Ollama](https://ollama.com) running on `localhost:11434`

## Quickstart

```bash
# 1. Pull the models (once)
ollama pull llama3.2:3b
ollama pull nomic-embed-text
ollama pull qwen2.5vl:3b        # image OCR only

# 2. Start backend + frontend
bash scripts/start-stack.sh     # backend (:8000) + frontend (:3000)

# 3. Backend alone, from backend/ (always `uv run`)
uv sync
MEMORY_ENABLED=1 uv run uvicorn app.main:app --reload
```

Open **http://localhost:3000**, dump a note or upload a document, then ask the chat pane about it.

> First-run costs: faster-whisper downloads its model on the first voice note (~2–20s); Docling downloads ~1GB of layout models and takes ~60s on the first PDF, then seconds per document. ChromaDB persist dir is created on first ingestion.

## Configuration

Env-driven, read at import time (`backend/app/config.py`). Key variables:

| Variable | Default | Purpose |
|---|---|---|
| `MEMORY_ENABLED` | `1` | Master switch for the vector layer. `0` → chat answers nothing (honest not-found), ingestion skips indexing |
| `CHROMA_PERSIST_DIR` | `backend/data/chromadb` | ChromaDB persistent storage location |
| `OLLAMA_MODEL` | `llama3.2:3b` | Chat/intent model |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Local embedding model (Ollama) |
| `DOCLING_ENABLED` | `1` | Docling PDF→markdown extraction (auto-falls back to pypdf/VLM OCR when off or failing) |
| `OCR_ENABLED` | `1` | Vision OCR for image uploads |
| `NOTE_MASTER_DATA_DIR` | `backend/data` | SQLite + uploads + collection storage (gitignored) |

## Start & stop

Nothing runs automatically — no login agents, no reboot revival.

```bash
bash scripts/start-stack.sh        # start backend + frontend
bash scripts/start-stack.sh stop   # stop both
bash scripts/run-langfuse.sh up    # Langfuse UI (:3001), when you want tracing
bash scripts/run-langfuse.sh down
```

Logs: `/tmp/nm-*.log`.

## Observability

Self-hosted Langfuse traces every chat question: intent, each agentic retrieval round (sub-queries, hits, similarities), grader verdicts, and the final generation.

```bash
bash scripts/run-langfuse.sh up     # UI at http://localhost:3001
# sign up -> Settings -> API Keys -> then before starting the backend:
export LANGFUSE_PUBLIC_KEY=pk-lf-... LANGFUSE_SECRET_KEY=sk-lf-...
```

Tracing is a no-op without keys. The agent loop itself: `RAG_MAX_ROUNDS=3` (default), grader model `RAG_AGENT_MODEL=hermes3`, disable entirely with `RAG_AGENTIC=0`.

## Maintenance

From `backend/scripts/`:

```bash
uv run python scripts/resync_memory.py            # re-index every latest capture into ChromaDB
uv run python scripts/purge_orphans.py            # list chunks whose captures were deleted locally
uv run python scripts/purge_orphans.py --delete   #   …remove them (--all = empty-store reset)
uv run python scripts/requeue_stuck.py            # re-run captures stuck in queued/processing
```

## Evals

A golden-dataset harness measures retrieval + answering quality end-to-end against the live store. From `backend/evals/`:

```bash
uv run python evals/runner.py --dataset golden  --repeats 3
uv run python evals/report.py --results results/latest.json
```

## Testing

From `backend/`:

```bash
uv run pytest tests -m "not llm"     # pure logic, fast, no Ollama needed
uv run pytest tests                  # full suite (real Ollama + whisper + one real Docling convert)
bash ../scripts/run-memory-tests.sh  # live e2e battery vs local ChromaDB + Ollama
bash ../scripts/run-retrieval-tests.sh  # context-only retrieval-quality assertions on real data
```

## Documentation

- `PLAN.md` — scope, decisions, and roadmap (source of truth)
- `AGENTS.md` — implementation constraints and non-obvious facts for contributors
- `HANDOFF.md` — phase-by-phase handoff notes