# Note Master

**Local-first personal notes app with grounded AI retrieval.**

Dump text notes, voice memos, and documents into a chat-style composer, then ask anything in natural language and get a structured, cited answer pulled from your own data. Sensitive documents (Aadhaar, PAN, bank statements) are stored and answerable like everything else, badged in chat and audit-logged.

Everything runs on your machine — local Ollama models for chat/OCR/ASR/embeddings, a local supermemory-server for semantic retrieval, SQLite for app state. **One deliberate exception:** the knowledge layer's memory agent (which reads each document and builds the graph) runs on Google Gemini's free tier by default, so document text reaches Google during ingestion only. Queries never leave the machine. Set `SUPERMEMORY_PROVIDER=ollama` for a fully offline stack.

## Features

- **Capture** — text notes, voice memos (local ASR transcription, original audio retained), and documents (PDFs via Docling → markdown with real tables, images via vision OCR, Word, Excel)
- **Grounded chat** — answers come only from your captured content, schema-constrained JSON output, citations, structured field-card answers, an honest not-found path, and typo tolerance
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
                      ┌─────────────────────────────────┴──────────────┐
                      ▼                                                ▼
              ┌───────────────┐                             ┌──────────────────────┐
              │ SQLite        │                             │ supermemory-server   │
              │ app state     │                             │ (localhost:6767)     │
              │ tiers/audit   │                             │ raw-content docs     │
              │ memory ids    │                             │ embeddings + graph   │
              └───────────────┘                             └──────────┬───────────┘
                      ▼                                                │
              Ollama (localhost:11434)                    memory agent LLM (switchable):
              · llama3.2:3b — chat + intent               · gemini-3.5-flash-lite (default,
              · nomic-embed-text — embeddings               free tier; ingestion only)
              · qwen2.5vl:3b — image OCR                   · or local hermes3 (offline)
```

Every capture — all sensitivity tiers — mirrors into supermemory as exactly one raw-content doc (`nm-{capture_id}-raw`). The server's memory agent extracts the graph memories; there is no per-document-type parsing anywhere in this repo. Chat retrieves over hybrid search (chunks + graph nodes) with a similarity floor. Tiers are labels, not barriers: sensitive docs sync, answer, and are audit-logged like any other.

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 16 (App Router), shadcn/ui |
| Backend | FastAPI, SQLite (stdlib, no ORM) |
| PDF extraction | Docling (local, markdown tables) |
| Knowledge & retrieval | supermemory-server + Ollama `nomic-embed-text` |
| Memory agent | Google `gemini-3.5-flash-lite` (free tier) or local `hermes3` |
| Graph glue | `scripts/gemini-proxy.py` — re-injects Gemini thought signatures the server's SDK drops |
| Chat / intent | Ollama `llama3.2:3b` (schema-constrained JSON) |
| OCR | Ollama `qwen2.5vl:3b` (images) |
| ASR | faster-whisper (`base`, CPU) |

## Requirements

- macOS (tested on Apple Silicon, 16GB)
- Python 3.14+ and [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- [Ollama](https://ollama.com) running on `localhost:11434`
- A free [Google AI Studio API key](https://aistudio.google.com/apikey) (optional — omit for fully-local)

## Quickstart

```bash
# 1. Pull the models (once)
ollama pull llama3.2:3b
ollama pull nomic-embed-text
ollama pull qwen2.5vl:3b        # image OCR only

# 2. Configure the Gemini key (optional but default provider)
export GOOGLE_API_KEY=AIza...   # or write it to ~/.supermemory/gemini-key

# 3. Start the knowledge layer (must be launched via this script)
./scripts/run-supermemory.sh    # SUPERMEMORY_PROVIDER=ollama for fully-local

# 4. Backend (from backend/ — always `uv run`)
uv sync
uv run uvicorn app.main:app --reload

# 5. Frontend (from frontend/)
npm install
npm run dev
```

Open **http://localhost:3000**, dump a note or upload a document, then ask the chat pane about it.

> First-run costs: faster-whisper downloads its model on the first voice note (~2–20s); Docling downloads ~1GB of layout models and takes ~60s on the first PDF, then seconds per document.

## Configuration

Env-driven, read at import time (`backend/app/config.py`) plus the launcher script. Key variables:

| Variable | Default | Purpose |
|---|---|---|
| `SUPERMEMORY_PROVIDER` | `gemini` | Memory-agent LLM: `gemini` (cloud, ingestion-only), `groq` (paid dev tier only), or `ollama` (fully local) |
| `GOOGLE_API_KEY` / `~/.supermemory/gemini-key` | — | Google AI Studio key; missing key falls back to ollama with a warning |
| `SUPERMEMORY_AGENT_MODEL` | `gemini-3.5-flash-lite` | Cloud model override (must support tool calling) |
| `OLLAMA_MODEL` | `llama3.2:3b` | Chat/intent model |
| `DOCLING_ENABLED` | `1` | Docling PDF→markdown extraction (auto-falls back to pypdf/VLM OCR when off or failing) |
| `OCR_ENABLED` | `1` | Vision OCR for image uploads |
| `MEMORY_ENABLED` | `1` | Disable → chat answers nothing (honest not-found) |
| `MEMORY_URL` | `http://127.0.0.1:6767` | supermemory-server base URL |
| `MEMORY_CONTAINER_TAG` | `user_main` | supermemory container holding app docs |
| `NOTE_MASTER_DATA_DIR` | `backend/data` | SQLite + uploads location (gitignored) |

### Free-tier notes (Gemini)

Default `gemini-3.5-flash-lite`: ~15 req/min, ~1K req/day, ~250K tokens/min. Two things make Gemini work where Groq's free tier cannot: per-minute token headroom (the agent sends a fixed ~13.8K-token prompt per call, over Groq's 8K TPM cap on every free model), and per-model daily buckets — the newest flagships get starved limits for new keys (`gemini-3.6-flash` = only 20 req/day), while Flash-Lite carries ~1K/day. A bulk re-sync may still span days; `backend/scripts/resync_memory.py --delay 5` is throttled and idempotent, so re-run as needed. Quota exhaustion shows up as docs stuck `indexing`; flip `SUPERMEMORY_PROVIDER=ollama` to keep working offline.

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
uv run python scripts/resync_memory.py            # re-run agent extraction over all captures
uv run python scripts/purge_orphans.py            # list docs whose captures were deleted locally
uv run python scripts/purge_orphans.py --delete   #   …remove them (--all = empty-store reset)
uv run python scripts/clean_memories.py           # sweep duplicate/cross-attached graph memories
```

## Testing

From `backend/`:

```bash
uv run pytest tests                  # full suite (real Ollama + whisper + one real Docling convert)
uv run pytest tests -m "not llm"     # pure logic, no Ollama needed
bash ../scripts/run-memory-tests.sh  # live e2e battery vs supermemory-server
```

## Documentation

- `PLAN.md` — scope, decisions, and roadmap (source of truth)
- `AGENTS.md` — implementation constraints and non-obvious facts for contributors
- `HANDOFF.md` — phase-by-phase handoff notes
