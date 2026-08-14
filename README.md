# Note Master

**Dump messy, retrieve clean.**

A local-first, single-user personal notes app. Dump text notes, voice memos, and documents (IDs, bills, PDFs, images — anything) into a chat-style composer, then ask anything in natural language and get a **structured** answer pulled from everything you've captured — with citations back to the source and a PIN gate for sensitive documents.

Everything runs on your machine. No hosted APIs, no API keys, no telemetry, no data leaving your computer.

---

## Table of Contents

- [Features (v0.1)](#features-v01)
- [Architecture](#architecture)
- [Decision Log — every choice and why](#decision-log--every-choice-and-why)
- [Privacy & Security Model](#privacy--security-model)
- [Requirements](#requirements)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [How Retrieval Works](#how-retrieval-works)
- [Testing](#testing)
- [Project Layout](#project-layout)
- [Status & Roadmap](#status--roadmap)

---

## Features (v0.1)

**Capture (left pane) — three input modes:**
- **Text notes** — free-form, timestamped, chat-message style.
- **Voice notes** — record in-browser (MediaRecorder) → transcribed locally → original audio retained and playable.
- **Document uploads** — PDF, images, Word, Excel, and more. Real text layer → extracted locally (no model); scanned/photographed docs (Aadhaar, PAN, receipts) → vision OCR.

**Everything after capture is queued through an async ingestion pipeline** with visible status: `queued → processing → indexed / failed`. Captures can be edited, deleted, or re-uploaded as a new version.

**Retrieval (right pane):**
- Natural-language chat over your notes, answered **only** from your captured content.
- **Structured answers** — asking for your PAN returns a field card (key/value), not prose soup.
- **Citations** — every answer links to its source capture(s); clicking a source jumps to and highlights the capture.
- Honest **not-found** path — "I don't have this in my notes" instead of hallucinating.
- **Correction loop** — flag a wrong answer; the feedback is stored and the source capture re-indexed.
- **Sensitivity guardrails** — captures are tiered `none` / `moderate` / `high` at ingestion; `high` (ID/financial docs) is PIN-gated at retrieval, every sensitive retrieval is audit-logged.
- **Versioned re-uploads** — re-uploading a bank statement creates version 2; old versions stay queryable via history and can be **restored** to latest.

**App shell & polish:**
- Shadcn/ui design system with **dark/light** themes, responsive layout (two panes on desktop, tabbed on mobile).
- **Settings panel** — set/change/remove the PIN, browse the **audit log**, and app info.
- **Search & filter** the capture list by type, status, and text.
- **Backend health indicator** in the header; graceful errors and toasts instead of silent failures.

---

## Architecture

```
┌──────────────────────────────┐          ┌───────────────────────────────┐
│  Frontend: Next.js 16 (App   │  REST    │  Backend: FastAPI             │
│  Router), localhost:3000     │─────────▶│  Orchestration layer          │
│  · CaptureComposer (text/    │          │   ├─ Ingestion pipeline (BG)  │
│    mic/file)                 │          │   ├─ Hybrid retrieval engine  │
│  · CaptureList (+playback)   │          │   └─ Guardrail layer (PIN,    │
│  · ChatPane (cards, PIN)     │          │      audit)                   │
└──────────────────────────────┘          └──────────┬────────────────────┘
                                                     │
        ┌──────────────────────────────┬─────────────┴──────────┐
        ▼                              ▼                        ▼
  ┌─────────────┐              ┌───────────────┐         ┌─────────────┐
  │ SQLite       │              │ LadybugDB      │         │ Disk files  │
  │ (one file)   │              │ (property      │         │ · uploads   │
  │ · app state  │              │  graph)        │         │ · audio     │
  │ · FTS5       │              │ · Entity nodes │         │ (referenced │
  │ · sqlite-vec │              │ · 1–2 hop walk │         │  by path)   │
  └─────────────┘              └───────────────┘         └─────────────┘
        ▲
  Ollama (localhost:11434)
  · llama3.2:3b   — chat answers + entity extraction
  · nomic-embed-text — embeddings (768-dim)
  · qwen2.5vl:3b  — OCR (vision), opt-in
  faster-whisper (base, CPU) — voice transcription
```

**Two embedded engines, zero standalone services.** One SQLite file holds app state + FTS5 full-text index + vector index (via the sqlite-vec extension); a second embedded store (LadybugDB) holds the knowledge graph; raw files live on disk referenced by path. There is nothing to run, configure, or back up separately — a consequence of the "single-user, local-first, minimal ops footprint" decision.

---

## Decision Log — every choice and why

All scope decisions were resolved in `PLAN.md` (§3.5, §3.7) before build. The table below records the plan rationale **and** every implementation deviation made during Phases 1–4, with the measured reason.

| Decision | Choice | Why |
|---|---|---|
| Frontend | **Next.js 16, responsive web** | Single-user v1; no native app until the product proves out. One codebase, no app-store friction. |
| Backend | **FastAPI** | Async ingestion with `BackgroundTasks`, pydantic-validated API, trivial test harness. |
| App state | **SQLite (stdlib `sqlite3`, no ORM)** | Zero deps, zero services; schema is small and hand-managed. |
| Full-text search | **SQLite FTS5** | Keyword/exact-token search (PAN numbers, dates, names) where semantic search is unreliable — and it lives in the same file as everything else. |
| Vector store | **sqlite-vec 0.1.9, embedded in the same SQLite file** | Keeps state + FTS5 + vectors in one file — minimal infra, no separate vector DB to run. |
| Graph DB | **LadybugDB (embedded, MIT — formerly Kuzu)** | Property-graph engine that runs in-process, no extra service; FalkorDB's built-in AI tooling and clustering are unneeded at this scale. Cypher queries at query time. |
| User model | **Single-user v1** | No near-term multi-user plan; avoids `user_id` isolation work across all four stores until actually needed. A `users` table is kept anyway (future-proofing). |
| Document re-upload | **Versioned, never overwritten** | Re-upload inserts a new `captures` row sharing `document_group_id`, bumps `version_number`, flips `is_latest`; old versions retained and queryable via history — preserves e.g. an updated bank statement instead of silently destroying the prior one. |
| Sensitivity model | **Tiers (`none`/`moderate`/`high`), not a boolean** | A flag is too coarse: meeting notes (moderate) deserve a warning label, ID/financial docs (high) deserve a gate. |
| Sensitive retrieval UX | **Banner for moderate, PIN gate for high only** | Full re-auth on every sensitive retrieval = too much friction for a single-user app; banner-only = too weak for Aadhaar/PAN/bank statements. WebAuthn biometric re-auth was considered and deferred — a cleaner fit for a future native app than a web app. |
| PIN implementation | **Local app-level passcode: scrypt (n=2¹⁴, r=8, p=1) hash, 30-min unlock token (sha256), `X-Pin-Token` header** | Not tied to any auth system (there is none) — a lightweight guardrail against casual snooping, explicitly documented as such. Token is stored hashed; `delete` allows an empty PIN as a local recovery path. |
| Sensitivity classifier | **Pure rules, no LLM** *(deviation from PLAN's "rule-based + ML/LLM classifier")* | Deterministic, instant, free: PAN/Aadhaar/account-number regexes + ID/financial keyword lists → `high`; meeting/doctor/address/phone keywords → `moderate`; else `none`. An LLM classifier adds cost and nondeterminism for zero correctness gain on known doc types. |
| Chat + entity-extraction model | **`llama3.2:3b` (~2GB, sub-second answers, ~1–3s extraction)** *(deviation from the originally picked qwen3:8b)* | **Measured: qwen3 models (8b AND 4b) are pathologically slow at JSON generation on this Mac — 19–150s per call.** The 3b model passes all grounding + structured-card tests and keeps the machine responsive. Overridable via `OLLAMA_MODEL` / `OLLAMA_EXTRACT_MODEL` (qwen3:8b and hermes3 remain installed). |
| Grounding prompt | **"You must NEVER use your own knowledge" + `think: false` + temperature 0.1** | Small models ignore weaker wording ("only answer from context") — the hardened phrasing is what makes the not-found path and PIN gate hold. |
| Embeddings | **`nomic-embed-text` via local Ollama (768-dim)** | Free, local, good enough for personal-note semantic search. |
| Vector honesty | **KNN fetches 12 candidates, cosine re-scores in Python, `MIN_COSINE_DISTANCE = 0.5`** | sqlite-vec 0.1.9 can't SELECT stored vectors back, so the embedding is denormalized as a BLOB into `capture_chunks` at index time and re-scored at query time. Unrelated hits are dropped so the PIN gate and the not-found path stay honest (without it, an unrelated query in a DB of only high-tier docs would misfire the PIN gate). |
| FTS query building | **Punctuation stripped + small stopword list before AND-then-OR fallback** | Without stopword filtering, the OR fallback matched common words like "is" and the PIN gate misfired on genuinely unrelated queries — found and fixed during Phase 4 testing. |
| Retrieval fusion | **Reciprocal-rank fusion of FTS + vector + graph, deduped by capture; top 5 fed to the LLM** | Hybrid recall with a single ranked list; more than ~5 hits adds noise that makes small models flip structured answers to prose. If embeddings fail, chat degrades to FTS-only. |
| OCR | **Routing: real text layer (PDF/Word/Excel) → local pypdf/python-docx/openpyxl (no model); scanned/photographed → `qwen2.5vl:3b` vision model, `OCR_ENABLED`-gated** *(deviation: PLAN named Qwen-OCR, which doesn't exist in Ollama's registry — switched to the vision model, user-approved)* | The majority of captures (digital docs) never touch a model; vision OCR only runs when genuinely needed. With `OCR_ENABLED=0`, scanned docs fail ingestion by design (explicit, not silent). |
| ASR | **faster-whisper (CTranslate2), `base` model, CPU, on-demand per note** | Free, no per-minute cost, and audio — which may contain spoken sensitive info — never leaves the machine. NVIDIA Canary-Qwen (more accurate but GPU-heavy) and hosted Whisper APIs (recurring cost + privacy trade-off) were considered and set aside. |
| Graph writes | **Best-effort** | LLM entity extraction can fail; a capture must still index. Failures are logged, never fatal. |
| Voice playback | **`GET /captures/{id}/audio` (FileResponse)** | Original audio is retained and playable from the capture list — the transcript is searchable, the recording stays yours. |
| Audio capture format | **MediaRecorder → webm/opus, uploaded to `POST /captures/audio`** | Browser-native, no upload dependency; backend accepts `.m4a/.webm/.wav/.mp3/.aiff/.ogg/.opus`. |
| Correction loop | **Built: `chat_feedback` table + `POST /feedback`** | Flagging a wrong answer stores the query/sources/reason and re-indexes the top source capture (best-effort) so future retrievals reflect the correction — the deferred Phase-5 item, shipped in the UI polish pass. |
| Deferred: encryption at rest | **Unbuilt (Phase 5+)** | User-approved deferral. Requires rebuilding SQLite around SQLCipher and file-level encryption — a meaningful storage-layer change. Documented here so it's a conscious, visible gap: **today the SQLite DB and raw files are unencrypted on disk.** |
| Out of scope (PLAN §2.4) | Multi-user collaboration, third-party integrations (Gmail/Drive), native mobile app | v1 is a single-user responsive web app; integrations could come as a future phase. |

---

## Privacy & Security Model

These are **hard constraints**, not preferences:

- **Localhost-only invariant.** All models run via local Ollama (`OLLAMA_HOST` must stay `http://localhost:11434`); uvicorn binds `127.0.0.1`; CORS allows only `localhost:3000`. No hosted APIs, no API keys, no telemetry.
- **Documents and audio never leave the machine.** Files live in `backend/data/` on disk, referenced by path — never blobbing into SQLite.
- **Guardrails are layered but honest:**
  - Retrieval grounding: answers come only from retrieved context, with an explicit not-found path.
  - Sensitivity tiers at ingestion (rules, no LLM).
  - PIN gate for `high`-tier content (30-min token; scrypt-hashed PIN).
  - Audit log: every retrieval that surfaces sensitive content records query, sources, timestamp, and a `sensitive_access` flag.
- **Known gaps (deliberate):** the PIN is a casual-snooping guardrail, not real auth; **no encryption at rest** (deferred — see Decision Log). Threat model = "someone who can physically sit at this unlocked machine", not "attacker with disk access".

---

## Requirements

- macOS (tested on Apple Silicon M5, 16GB) — Linux should work with minor tweaks
- Python **3.14+** and [`uv`](https://docs.astral.sh/uv/) (project pinned to 3.14)
- Node.js 20+ and npm
- [Ollama](https://ollama.com) running on `localhost:11434`
- macOS `say` command (only for generating test audio fixtures)

---

## Quickstart

1. **Install Ollama and pull the models** (once):

   ```bash
   ollama pull llama3.2:3b        # chat + entity extraction
   ollama pull nomic-embed-text   # embeddings
   ollama pull qwen2.5vl:3b       # OCR (scanned docs only)
   ```

2. **Backend** (from `backend/` — always `uv run`, never bare `uvicorn`; deps live in `.venv`):

   ```bash
   uv sync
   uv run uvicorn app.main:app --reload
   ```

3. **Frontend** (from `frontend/`):

   ```bash
   npm install
   npm run dev
   ```

4. Open **http://localhost:3000**. Dump a note, record a voice memo, or upload a document — then ask the chat pane about it.

> First voice note takes ~2–20s cold: faster-whisper downloads the `base` model on first use, then stays loaded in memory.

---

## Configuration

All settings are env-driven and read at import time (`backend/app/config.py`).

| Variable | Default | Purpose |
|---|---|---|
| `NOTE_MASTER_DATA_DIR` | `data` (in `backend/`) | Where SQLite, graph, and uploaded files live (gitignored) |
| `OLLAMA_HOST` | `http://localhost:11434` | Must stay localhost |
| `OLLAMA_MODEL` | `llama3.2:3b` | Chat/answers model |
| `OLLAMA_EXTRACT_MODEL` | `llama3.2:3b` | Entity-extraction (NER) model |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model (768-dim) |
| `OCR_ENABLED` | `0` | Set `1` to enable vision OCR for scanned/photographed docs (image uploads and image-only PDFs); when disabled, they fail ingestion by design |
| `OCR_MODEL` | `qwen2.5vl:3b` | Vision model used for OCR |
| `ASR_MODEL` | `base` | faster-whisper model size for voice transcription |

---

## API Reference

Base URL: `http://127.0.0.1:8000`. The frontend proxies `/api/*` → backend via Next rewrites.

### Captures
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/captures/text` | `{"content": "..."}` — text note |
| `POST` | `/api/captures/file` | multipart `file`, optional `document_group_id` (versioning) |
| `POST` | `/api/captures/audio` | multipart `file` — voice note (.m4a/.webm/.wav/.mp3/.aiff/.ogg/.opus) |
| `GET` | `/api/captures` | List captures (latest per group by default) |
| `GET` | `/api/captures/{id}` | Single capture + status (`queued/processing/indexed/failed`) |
| `GET` | `/api/captures/{id}/audio` | Audio playback (FileResponse; voice captures) |
| `GET` | `/api/captures/history/{group_id}` | All versions of a document group |
| `POST` | `/api/captures/{id}/restore` | Promote an older version to latest (flips `is_latest` in SQLite + graph) |
| `PATCH` | `/api/captures/{id}` | Edit content → reindexes FTS/vectors/graph |
| `DELETE` | `/api/captures/{id}` | Cascade: FTS rows, vector rows, graph node, files |

### Chat
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/chat` | `{"query": "...", "include_history": bool}`. Response: `{answer, found, sources[], structured?, needs_pin?}`. Send `X-Pin-Token: <token>` header to unlock `high`-tier retrieval. `sources[].sensitivity_tier` tells the UI what it surfaced. |

### PIN
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/pin/status` | `{set: bool}` |
| `POST` | `/api/pin/set` | `{"pin": "..."}` — set/change PIN |
| `POST` | `/api/pin/verify` | `{"pin": "..."}` → `{token}` (30-min TTL) |
| `DELETE` | `/api/pin/delete` | Remove PIN (allows empty pin — local recovery) |

### System
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | `{status, database, ollama}` — backend + model reachability |
| `GET` | `/api/audit?limit=100` | Recent `audit_log` entries (query, sources, sensitive flag, time) |
| `POST` | `/api/feedback` | `{query, capture_ids, kind, note}` — correction-loop feedback; re-indexes the top source capture |

---

## How Retrieval Works

**Ingestion** (per capture, in `BackgroundTasks`):

```
capture → route by type
  text: pass-through
  voice: faster-whisper transcription
  doc:  text layer? local parse : vision OCR (if OCR_ENABLED)
→ sensitivity tier (rules) → status: processing
→ chunk (~800 chars, ~100 overlap)
→ embed chunks (nomic-embed-text) → write capture_chunks + chunks_vec
→ raw text → FTS5 (captures_fts)
→ LLM NER → graph nodes/edges (best-effort)
→ status: indexed
```

**Query** (per chat message):

```
query → parallel retrieval
  FTS5 exact-token search (stopword-filtered, AND→OR fallback)
  vector KNN (12 candidates) → cosine re-score (≥0.5 threshold)
  graph 1-hop + 2-hop entity walk
→ reciprocal-rank fusion, deduped by capture, top 5
→ if any top hit is high-tier: require valid X-Pin-Token (no LLM call otherwise)
→ LLM with hardened grounding → structured JSON {kind: fields|prose|not_found}
→ answer + sources + audit log (sensitive_access=1 when high content surfaced)
```

---

## Testing

From `backend/`:

```bash
uv run pytest tests                  # full suite: 43 tests, ~70–85s (real Ollama + whisper)
uv run pytest tests -m "not llm"     # pure logic: 23 tests, <1s, no Ollama needed
```

Quirks that matter if you touch the suite:

- TestClient runs `BackgroundTasks` after the response → creates return `queued`; tests poll `GET /captures/{id}` until `indexed`.
- Tests share one session DB; the PIN persists across tests (an `unlock()` helper sets/verifies it) — `TestPin` clears it last (alphabetical file order).
- LLM-dependent assertions retry up to 3× — small models occasionally hallucinate or answer in prose in noisy multi-capture contexts (observed with several similar PAN docs in one DB).
- Audio e2e synthesizes a fixture with macOS `say -o file.aiff`; scanned-PDF OCR fixtures via `cupsfilter txt > pdf` (PDF goes to **stdout**) → `pymupdf` page render → `sips -s format pdf png --out scanned.pdf` (`qlmanage -t` hangs headless — never use it).

---

## Project Layout

```
backend/
  app/
    main.py                 # FastAPI app, routers, CORS
    config.py               # env-driven settings (see table above)
    db.py                   # SQLite + sqlite-vec wiring, schema init (guarded ALTER)
    schema.sql              # captures, capture_chunks, captures_fts, chunks_vec, audit_log, app_settings
    storage.py              # file-on-disk storage helpers
    graph.py                # LadybugDB schema, 1-hop/2-hop search, delete
    ingestion/
      pipeline.py           # orchestration: extract → chunk → embed → classify → indexes
      chunker.py            # ~800-char chunks, ~100 overlap
      embeddings.py         # Ollama nomic-embed-text
      extract.py            # LLM NER (JSON-only, few-shot) + normalization
      classify.py           # rule-based sensitivity tiers (no LLM)
      asr.py                # faster-whisper lazy singleton, transcribe()
      ocr.py                # qwen2.5vl:3b vision OCR (OCR_ENABLED-gated)
    retrieval/
      fts.py                # FTS5 search (stopword filter, AND→OR fallback)
      vector.py             # KNN + cosine re-score (0.5 threshold)
      fusion.py             # reciprocal-rank fusion
      chat.py               # grounding prompt, structured-JSON parsing
    guardrails/pin.py       # scrypt PIN, 30-min tokens, app_settings store
    routes/
      captures.py           # text/file/audio endpoints, versioning, delete cascade, playback, restore
      chat.py               # retrieval + PIN gate + audit log
      pin.py                # /pin/status|set|verify|delete
      health.py             # /health backend + Ollama reachability
      audit.py              # /audit log viewer
      feedback.py           # /feedback correction loop
  tests/
    test_api.py             # e2e API tests (llm-marked)
    test_units.py           # pure-logic unit tests (fast path)
frontend/
  components/
    app-shell (in page.tsx) # header (health, theme, settings) + two-pane grid + mobile tabs
    CaptureComposer.tsx     # text composer + mic (MediaRecorder) + drag-drop file upload
    CaptureList.tsx         # search/filter toolbar, badges, edit/delete dialogs, restore, playback
    ChatPane.tsx            # markdown answers, field cards, copy, flag-wrong-answer, PIN dialog
    SettingsDialog.tsx      # PIN mgmt + audit log viewer + about
    FeedbackDialog.tsx      # correction-loop flag flow
    HealthIndicator.tsx     # backend/Ollama status dot
    theme-toggle.tsx        # dark/light/system switcher
    ui/                     # shadcn/ui components (button, card, dialog, tabs, …)
  lib/api.ts                # typed API client (incl. X-Pin-Token)
```

---

## Status & Roadmap

**Shipped — v0.1 complete (Phases 1–4):**

1. Phase 1: capture pipeline (text + doc) + SQLite/FTS5 + grounded chat
2. Phase 2: hybrid retrieval (sqlite-vec + RRF) + structured field-card answers
3. Phase 3: LadybugDB property graph + LLM entity extraction + 3-way fusion
4. Phase 4: voice notes (faster-whisper) + guardrails (sensitivity tiers, PIN gate, audit log, vision OCR)

**Deferred (Phase 5+, user-approved):** encryption at rest.

**Out of scope for v1:** multi-user collaboration, third-party integrations, native mobile app.

- `PLAN.md` — scope source of truth (all decisions resolved)
- `AGENTS.md` — implementation constraints and non-obvious facts for anyone (or any agent) working on this codebase
