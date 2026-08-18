# Note_Master_Supermemory — Handoff for the v2 session

This is the supermemory-based rewrite of the Note Master app (v1: `/Users/dhruvilpatel/Developer/Note_Master`, GitHub `Dhruvil-Patel-28/Note-Master`, latest commit `7ced81c`). Follow this file top to bottom.

## 0. Bootstrap (run first)

```bash
cd ~/Developer/Note_Master_Supermemory
git clone https://github.com/Dhruvil-Patel-28/Note-Master.git .
git remote remove origin
git remote add origin https://github.com/Dhruvil-Patel-28/Note-Master-Supermemory.git
# env + deps
cd backend && uv venv && uv sync && cd ..
cd frontend && npm install && cd ..
# carry the real data (transcript, resumes, PAN/Aadhaar, voice notes — 29 captures)
cp -R ~/Developer/Note_Master/backend/data backend/data
# baseline check
cd backend && uv run pytest tests -m "not llm"   # expect 68 passed
```

Then verify the live server boots: `uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000` from `backend/`.

## 1. Why v2 exists (root cause from v1)

v1 stores **text dumps, not knowledge**. Failures observed (all fixed in v1, but by layered mechanisms that v2 should replace with one general design):

- "where do i study" → no output: notes say "institute", never "study" — pure lexical gap; retrieval returned nothing and the LLM was never called.
- "print my name in python" → `print(`: a code question forced through the notes-cage (no world knowledge + JSON + citations) produced garbage.
- v1's fix = intent classifier + stuck-expansion + inference rules (commits after `7ced81c` in the v1 repo, NOT yet on GitHub — the v1 working tree has them uncommitted; if you want them, copy `backend/app/retrieval/intent.py` + the `routes/chat.py`/`retrieval/chat.py` diffs from the v1 working tree).

**v2 architecture (the general design):**
```
KNOWLEDGE at ingest  →  INTENT at ask-time  →  GROUNDED answer
facts + relations        classify + route        citations to captures
```

## 2. Supermemory specifics (researched, decide before building)

- Self-host = single local binary `supermemory-server` on **127.0.0.1:6767**, data `~/.supermemory`, curl installer `https://supermemory.ai/install` (server is young, v0.0.3 — API churn expected).
- **Localhost-only invariant must hold** (v1 hard constraint): verify no outbound traffic with `lsof -i -n` while running; no hosted APIs, no telemetry.
- Embeddings: point it at local Ollama `nomic-embed-text` (skip its default ~130MB bge model download). Extraction model: `llama3.2:3b` (v1's chat/NER model).
- Scope decision from the user: **supermemory used "completely"** in v2 (knowledge + retrieval + graph). Keep deterministic Python parsers where structure exists (see §3).
- **Phase 0 gate before any code:** install, verify localhost-only + RAM delta (+0.3–0.6GB expected; machine has ~11GB free of 16GB), fact-quality spike on the carried-over notes with `llama3.2:3b`.

## 3. v1 constraints that MUST carry over (hard-won)

- **Deterministic > LLM where structure exists:** v1's transcript parsers (semester courses, total credits `Grand Total Credit : 122`, CGPA `7.57`) are Python regex/state-machine, because the 3b model drops list items ("3rd sem" → 2 of 6 courses). In v2, supermemory's LLM extraction must NOT be the sole source for these — keep the parsers or feed their output to supermemory as facts.
- **PIN/tier boundary:** sensitivity tiers (`none`/`moderate`/`high`, rule-based, no LLM) gate `high` at retrieval. In v2, **never ingest high-tier facts into memory** — the gate boundary moves to the knowledge layer. Rebuild tier-aware ingestion + a gate over supermemory results.
- **Model picks (16GB Mac):** chat/NER `llama3.2:3b`; embeddings `nomic-embed-text`; ASR faster-whisper `base` in-process (NOT Ollama); OCR `qwen2.5vl:3b` gated by `OCR_ENABLED`. **NEVER use qwen3 8b/4b for extraction — measured 19–150s per JSON call.** Chat options: temperature 0.1, `think: false`, `num_predict: 4096`.
- **Injection defense:** query scrubbed (`_INJECTION_PATTERNS`) before anything; instructions live in the system message, the question is an isolated user turn — never merge query into instructions.
- **JSON discipline:** never surface raw model output — balanced-brace extraction, salvage regexes, whitelist filtering; 3b wraps JSON in prose.
- **Citations:** every answer cites `[1]`..`[n]` to capture ids; supermemory memories must keep a link back to source capture_id.
- **Lifecycle:** edit/delete/version-restore must sync memory (delete+re-add; versioned docs have `is_latest` semantics supermemory doesn't know).
- **Graceful degradation:** if supermemory is down, chat must degrade (FTS fallback or clean error), never crash. v1 keeps FTS5+sqlite-vec+LadybugDB in `backend/data` — decide whether v2 keeps them as fallback or retires them (recommended: keep until green tests, then retire).
- **v1 test baseline:** 93 tests (68 pure-logic `-m "not llm"`, 25 `@llm`). Conventions: TestClient background-task polling, shared session DB, `unlock()` PIN helper, 3× retry on LLM assertions.

## 4. Suggested phases

1. **Phase 0** — install supermemory, localhost/RAM/fact-quality verification (gate!)
2. **Phase 1** — `app/memory/` client (add_document/delete/search/profile), `MEMORY_ENABLED`+`MEMORY_URL` env, all best-effort try/except
3. **Phase 2** — ingest-side: fact extraction (deterministic for transcript/resume/ID docs + 3b few-shot for free notes), tier filter (skip high), lifecycle sync
4. **Phase 3** — ask-side: intent classifier (port v1's `intent.py`: notes/code/general/hybrid; code+general → clean refusal) + fact-profile retrieval merged into context + PIN gate over supermemory results + citations
5. **Phase 4** — retire v1 retrieval stack behind green tests; docs (README/AGENTS/PLAN stack decision: supermemory becomes the third runtime — amend the "two embedded engines, no standalone services" decision)
6. **Phase 5** — `@memory` pytest marker + e2e: "where do i study" → IIIT Nagpur w/ citation, "where do i work" → Adapt Nova, PAN query → gated + no PAN facts in memory, code question → refusal, kill-server → graceful degradation

## 5. Verification battery (run after every phase)

- "where do i study" → IIIT Nagpur + citation
- "where do i work" → Adapt Nova
- "my 3rd semester courses" → 6 courses, deterministic
- "how many credits have i earned" → 122, no PIN
- "what is my pan number" → PIN-gated; verify PAN facts absent from memory store
- "please print my name in python" → refusal (clean, never `print(`)
- "byu batteries" → battery answer (query typo)
- "show me my resume" → doc preview
- kill supermemory-server → chat degrades gracefully