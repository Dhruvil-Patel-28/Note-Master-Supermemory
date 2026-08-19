# Note Master

**Local-first personal notes app with grounded AI retrieval.**

Dump text notes, voice memos, and documents into a chat-style composer, then ask anything in natural language and get a structured, cited answer pulled from your own data — with a PIN gate for sensitive documents.

Everything runs on your machine: local Ollama models, a local supermemory-server for semantic retrieval, and SQLite for app state. No hosted APIs, no telemetry, nothing leaves your computer.

## Features

- **Capture** — text notes, voice memos (local ASR transcription, original audio retained), and documents (PDFs, images, Word, Excel; vision OCR for scanned/photographed docs)
- **Grounded chat** — answers come only from your captured content, with citations, structured field-card answers, an honest not-found path, and typo tolerance
- **Document access** — "show me my resume" opens the original uploaded file in a preview, never an extracted-text dump
- **Guardrails** — sensitivity tiers (`none`/`moderate`/`high`) assigned at ingestion; `high` (ID/financial docs) is PIN-gated at retrieval; every sensitive retrieval is audit-logged; prompt-injection resistant
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
              │ tiers/audit   │                             │ raw + fact docs      │
              │ memory ids    │                             │ embeddings + search  │
              └───────────────┘                             └──────────────────────┘
                      ▲                                                ▲
              Ollama (localhost:11434)                    files on disk (uploads/audio)
              · llama3.2:3b — chat + facts
              · qwen2.5vl:3b — OCR (opt-in)
```

Three runtimes, all localhost. Every non-high capture mirrors into supermemory as a raw-content doc plus deterministic fact docs; chat retrieves over it semantically with a similarity floor. High-tier captures never enter memory — the PIN gate re-attaches them via a local scan.

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 16 (App Router), shadcn/ui |
| Backend | FastAPI, SQLite (stdlib, no ORM) |
| Knowledge & retrieval | supermemory-server + Ollama `nomic-embed-text` |
| Chat / facts / intent | Ollama `llama3.2:3b` |
| OCR | Ollama `qwen2.5vl:3b` (opt-in) |
| ASR | faster-whisper (`base`, CPU) |

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
ollama pull qwen2.5vl:3b        # OCR only

# 2. Start the knowledge layer (must be launched via this script)
./scripts/run-supermemory.sh

# 3. Backend (from backend/ — always `uv run`)
uv sync
uv run uvicorn app.main:app --reload

# 4. Frontend (from frontend/)
npm install
npm run dev
```

Open **http://localhost:3000**, dump a note or upload a document, then ask the chat pane about it.

> The first voice note takes ~2–20s cold: faster-whisper downloads the `base` model on first use, then stays loaded.

## Configuration

Env-driven, read at import time (`backend/app/config.py`). Key variables:

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_MODEL` | `llama3.2:3b` | Chat/answers model |
| `OLLAMA_EXTRACT_MODEL` | `llama3.2:3b` | Note-facts model |
| `OCR_ENABLED` | `1` | Vision OCR for scanned/photographed docs (image uploads and image-only PDFs); set `0` to disable (then they fail ingestion by design) |
| `MEMORY_ENABLED` | `1` | Disable → chat answers nothing (honest not-found) |
| `MEMORY_URL` | `http://127.0.0.1:6767` | supermemory-server base URL |
| `MEMORY_CONTAINER_TAG` | `user_main` | supermemory container holding app docs |
| `NOTE_MASTER_DATA_DIR` | `backend/data` | SQLite + uploads location (gitignored) |

## Testing

From `backend/`:

```bash
uv run pytest tests                  # full suite: 79 tests (real Ollama + whisper)
uv run pytest tests -m "not llm"     # pure logic: 60 tests, no Ollama needed
bash ../scripts/run-memory-tests.sh  # live e2e battery vs supermemory-server (5 tests)
```

## Documentation

- `PLAN.md` — scope, decisions, and roadmap (source of truth)
- `AGENTS.md` — implementation constraints and non-obvious facts for contributors
- `HANDOFF.md` — v2 phase-by-phase handoff notes
