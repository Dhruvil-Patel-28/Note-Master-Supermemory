# Note Master App — Functional & Technical Scope Document

**Status:** Draft for approval
**Version:** 0.1

> **v4 amendment:** the storage architecture below reflects original v1 planning.
> As of v4 ("vector-only"), retrieval/knowledge lives entirely in a **local
> ChromaDB vector store** (raw-content chunks + nomic embeddings, no graph, no
> external server); the supermemory-server layer, the deterministic fact layer,
> and the v1 FTS5/vector/graph runtimes were all retired. The authoritative
> description of what actually ships is `AGENTS.md`.

---

## 1. Product Vision

A single app to dump everything — text notes, voice notes, and documents (IDs, bills, PDFs, images, anything) — in an unstructured, chat-like way, and later retrieve any piece of it back through natural-language queries with a **structured** answer.

Two-pane UX:
- **Left pane — Capture:** WhatsApp-style composer with three input modes: text note, voice note, document upload.
- **Right pane — Retrieval/Chat:** ask anything in natural language, get a structured answer pulled from everything you've dumped.

Core promise: *"Dump messy, retrieve clean."*

---

## 2. Functional Scope

### 2.1 Capture (Left Pane)
| Mode | Behavior |
|---|---|
| Text note | Free-text entry, sent like a chat message, timestamped, stored as a "note" object |
| Voice note | Record → send; transcribed async; original audio retained; transcript becomes searchable text |
| Document upload | Any file type (PDF, image, docx, etc.); OCR/parse on ingestion; classified (e.g. ID proof, bill, statement, misc) |

Common behavior across all three:
- Each capture is timestamped, tagged with a source type, and queued for the ingestion pipeline (parse → extract → embed → link).
- User sees ingestion status (queued / processing / indexed / failed).
- User can edit/delete a capture after the fact; deletion must cascade to derived data (embeddings, graph nodes, FTS index).

### 2.2 Retrieval (Right Pane)
- Natural language query interface, chat-style.
- Answers are **structured**, not just prose dumps — e.g. asking for "PAN card" returns a card with extracted fields (PAN number, name, DOB) plus a link/preview to the source document, not just "here's what I found."
- Must support:
  - Direct fact lookup ("what's my PAN number")
  - Document retrieval ("show me my Aadhar card")
  - Aggregation/summarization ("what did I note about the Goa trip")
  - Follow-up/contextual queries within a chat thread
- Every answer should be traceable back to its source capture(s) (citation-style).

### 2.3 Guardrails (Functional Requirements)
- **No hallucinated answers** — if the system doesn't have the data, it must say so, not fabricate.
- **Sensitive data handling** — documents like Aadhar/PAN/bank statements are flagged as sensitive at ingestion; retrieval of these may require an extra confirmation step (configurable).
- **Data isolation** — this is inherently single-user personal data; if multi-user/multi-tenant is ever in scope, strict tenant isolation is mandatory (flag this decision explicitly — see open questions).
- **Audit trail** — every retrieval that surfaces sensitive data should be logged (what was asked, what was returned, when).
- **Correction loop** — user can flag a wrong answer, which should feed back into re-indexing/correction, not just be discarded.

### 2.4 Out of Scope (for v1, proposed)
- Multi-user collaboration / sharing notes with others
- Third-party integrations (Gmail, Drive import) — can be phase 2
- Mobile native app (assume responsive web via Next.js for v1)

---

## 3. Technical Scope

### 3.1 High-Level Architecture

```
Next.js (Frontend)
   │  REST/WebSocket
   ▼
FastAPI (Backend / Orchestration)
   ├── Ingestion Pipeline (async workers)
   ├── Retrieval Engine (hybrid)
   └── Guardrail Layer (pre/post processing)
        │
   ┌────┴─────────────┬─────────────────┬───────────────┐
   ▼                   ▼                 ▼               ▼
SQLite            Graph DB          Vector Index      FTS5 (SQLite)
(app state,       (property graph:  (embeddings for   (keyword/full-
metadata,         entities +        semantic search)  text search over
audit log)        relationships)                       transcripts/OCR text)
```

### 3.2 Storage Structure

**a) SQLite — system of record for app state**
- `captures` table: id, type (text/voice/doc), raw content ref, status, timestamps, sensitivity_flag, `document_group_id`, `version_number`, `is_latest`
- `users` (even if single-user for v1, keep the table — future-proofs multi-user)
- `audit_log`: query, retrieved_source_ids, timestamp, sensitive_access flag
- Raw files (audio, uploaded docs) stored on disk/object storage, referenced by path in SQLite — don't blob them into SQLite itself.

**Versioning implication:** a re-uploaded document doesn't overwrite the row — it inserts a new `captures` row sharing the same `document_group_id`, with an incremented `version_number` and `is_latest = true` (the prior version's flag flips to `false`). Retrieval defaults to `is_latest = true` unless the user explicitly asks for history ("show me the old version of my bank statement"). Graph nodes, vector entries, and FTS5 entries follow the same pattern — new entries per version, old ones retained but excluded from default retrieval, not deleted.

**b) Property Graph (FalkorDB / Kùzu-class embedded graph DB — confirm exact choice, see open question below)**
- **Nodes:** `Capture`, `Document`, `Entity` (Person, Account, Organization, Date, Amount, Location), `Topic`
- **Edges:** `MENTIONS`, `BELONGS_TO`, `ISSUED_BY`, `RELATED_TO`, `PART_OF_THREAD`
- Purpose: captures *relationships* — e.g. "this bill is linked to this account which is linked to this bank" — enabling multi-hop queries plain vector search can't do.
- Entity extraction (NER-style, LLM-assisted) runs at ingestion to populate nodes/edges.

**c) Vector Index**
- Embeddings generated per chunk (note text, transcript, OCR'd doc text) at ingestion.
- Stores chunk embedding + pointer back to the source `Capture` row and graph node.
- Used for semantic/fuzzy retrieval ("things about my car" without the word "car" appearing).

**d) FTS5 (SQLite full-text search)**
- Indexes raw text (transcripts, OCR output, note text) for exact/keyword matches — critical for things like PAN numbers, exact names, dates where semantic search is unreliable.

**Ingestion pipeline (applies to all 3 capture types):**
```
Capture → [Type-specific pre-processing] → Text extraction
  - text note: pass-through
  - voice note: ASR transcription
  - document: OCR / parsing (PDF text layer or OCR fallback)
→ Chunking → Entity extraction → Graph node/edge creation
→ Embedding generation → Vector index write
→ Raw text → FTS5 index write
→ Status: indexed
```

### 3.3 Retrieval — Hybrid (Graph + Vector + FTS5)

Proposed retrieval flow per query:
1. **Query understanding** — classify intent (fact lookup / document fetch / summarization / aggregation) and extract entities from the query itself.
2. **Parallel retrieval:**
   - Graph traversal for entity-anchored queries (e.g. query mentions "PAN card" → walk graph from that entity type)
   - Vector similarity search over chunk embeddings for semantic matches
   - FTS5 exact-match search for precise tokens (numbers, IDs, proper nouns)
3. **Fusion/re-ranking** — combine the three result sets (e.g. reciprocal rank fusion), dedupe by source capture.
4. **Structuring** — pass fused, ranked context to the LLM with instructions to output a structured response (field-based for documents, prose+citation for notes) and to explicitly say "not found" if context is empty/insufficient.
5. **Guardrail check** — sensitivity flag check before returning (confirmation step if the source doc was marked sensitive), audit log write.

### 3.4 Guardrails (Technical Implementation)
- **Grounding enforcement:** retrieval-augmented generation with strict "answer only from retrieved context" system prompt + a fallback "I don't have this" path when fused results are empty/low-confidence.
- **PII/sensitivity tagging:** classifier at ingestion time (rule-based for known doc types like Aadhar/PAN + ML/LLM classifier for the rest) — outputs a **tier** (`none` / `moderate` / `high`), not just a flag. See 3.7 for the resolved confirmation UX tied to this.
- **Access confirmation:** `high`-tier captures (ID documents, financial documents) are gated behind a local PIN before rendering at retrieval time; `moderate`/`none` tiers show a warning label only, no gate. See 3.7 for full rationale.
- **Data integrity on delete:** deleting a capture must cascade-delete its graph nodes/edges, vector entries, and FTS5 entries — orphaned index entries are a real risk with this architecture and need an explicit cleanup job.
- **Encryption:** at-rest encryption for SQLite DB and raw file storage at minimum, given the sensitivity of documents being stored.

### 3.5 Stack Summary

| Layer | Choice |
|---|---|
| Frontend | Next.js |
| Backend/API | FastAPI |
| App state / metadata | SQLite |
| Full-text search | SQLite FTS5 (retired in v2 — semantic search via supermemory) |
| Graph DB | ~~LadybugDB~~ — **retired in v2 Phase 4** (supermemory fact docs supersede it) |
| Vector store | ~~sqlite-vec~~ — **retired in v2 Phase 4** (supermemory embeddings supersede it) |
| Knowledge + retrieval | **supermemory-server (v2)** — local standalone runtime, third storage engine (knowledge layer: raw-content docs + fact docs, embeddings, semantic search) |
| OCR | **AnyDoc** (typed docs) + **Qwen-OCR** (scanned/image docs), routed by document type at ingestion (v1 shipped pypdf/python-docx/openpyxl + qwen2.5vl:3b instead — same routing, different tools) |
| ASR (voice) | **faster-whisper**, local CPU (small/base model) |
| User model | **Single-user for v1** — no auth/tenant-isolation layer required; `user_id` scoping deferred until/unless multi-user is revisited |
| Document versioning | **Re-uploads are versioned, not overwritten** — see 3.2a for schema implication |

**v2 amendment (Phase 4):** the "two engines" stack below is retired. Storage is now **three runtimes, all localhost**: one SQLite file holds app state, a local supermemory-server holds knowledge/retrieval (raw-content docs + deterministic fact docs, embeddings, semantic search), and files (audio, uploads) live on disk referenced by path. LadybugDB and sqlite-vec are deleted (Phase 4); semantic recall supersedes hand-rolled FTS5+vector+graph fusion. Original v1 text preserved for history:

**OCR routing detail:** at ingestion, a cheap file-type/content check decides the path — digital documents with a real text layer (Word, Excel, text-based PDFs, etc.) go through AnyDoc locally (no OCR model, no API cost, single-digit-millisecond conversion); scanned or photographed documents (Aadhar, PAN, physical receipts) route to Qwen-OCR for structured field/text extraction. This keeps the majority of captures off the OCR model entirely and only invokes it where genuinely needed.

**ASR detail:** voice notes are transcribed locally via `faster-whisper` (CTranslate2 backend) using a `small` or `base` model — sufficient accuracy for short personal voice notes, runs on-demand per note (not a persistent background process), and keeps voice data local rather than sending it to a third-party API — consistent with the local-first, privacy-conscious pattern already set by the embedded SQLite/LadybugDB storage and PIN-gated sensitive documents.

All open questions are now resolved — the scope is ready for sign-off.

### 3.7 Resolved Decisions Log
| Decision | Choice | Rationale |
|---|---|---|
| Graph DB | ~~LadybugDB~~ → **retired (v2 Phase 4)** | Embedded, MIT — but v2 replaced hand-rolled hybrid retrieval with supermemory fact docs + semantic search; the graph was deleted |
| Vector store | ~~sqlite-vec~~ → **retired (v2 Phase 4)** | Kept vectors embedded in SQLite — but v2's supermemory-server owns embeddings + semantic search; sqlite-vec deleted |
| User model | Single-user (v1) | No near-term plan for other users; avoids the `user_id`-everywhere isolation work across all four stores until actually needed |
| Document re-upload | Versioned | Preserves history instead of silently overwriting a prior version of a document (e.g. an updated bank statement) |
| Sensitive-doc confirmation UX | Tiered — banner by default, PIN gate for high-sensitivity tier only | Captures are classified into sensitivity tiers at ingestion (per 3.4 PII/sensitivity tagging); only the highest tier (ID docs, financial docs — Aadhar, PAN, bank statements) is gated behind a local PIN before rendering, everything else just shows a warning label. Chosen over full re-auth on every sensitive retrieval (too much friction for a single-user app) and over banner-only (too weak a guardrail for ID/financial data). Device biometric re-auth (WebAuthn) was considered but deferred — cleaner fit for a future native app than the current Next.js web app. |
| OCR | AnyDoc + Qwen-OCR, routed by document type | AnyDoc handles typed/digital documents locally (no ML, no API cost, single-digit-ms conversion) covering the majority of captures; Qwen-OCR (specialized OCR/document-intelligence model) is only invoked for scanned/photographed documents (Aadhar, PAN, physical receipts) that actually need vision-based extraction. Qwen-VL (general vision-language model) was considered but not adopted separately — Qwen-OCR is the purpose-built variant for this exact job. |
| ASR | faster-whisper, local CPU (small/base model) | Free, no per-minute cost; keeps voice notes local rather than sending audio (which may contain spoken sensitive info) to a third-party API — consistent with the local-first pattern set by the rest of the stack; short personal voice notes don't need GPU-scale throughput, so CPU inference is sufficient. NVIDIA Canary-Qwen (higher accuracy but GPU-heavy) and hosted Whisper API (simplest but recurring cost + privacy trade-off) were considered and set aside for this reason. |

**Implementation implication for 3.4 (Guardrails):** the sensitivity classifier at ingestion now needs to output a **tier**, not just a boolean flag — e.g. `none` / `moderate` (personal notes with names/dates) / `high` (ID documents, financial documents). Only `high` triggers the PIN gate at retrieval time. The PIN itself is a local app-level passcode (not tied to any auth system, consistent with single-user v1) with its own set/change/recovery flow to be scoped during the guardrails build phase.

---

## 4. Suggested Phasing
1. **Phase 1:** Capture pipeline (text + doc upload) + SQLite + FTS5 + basic chat retrieval (no graph/vector yet) — validate core loop. *(shipped as v1)*
2. **Phase 2:** Add vector search + embeddings, structured output formatting. *(shipped as v1)*
3. **Phase 3:** Add graph DB + entity extraction for relationship-aware queries. *(shipped as v1)*
4. **Phase 4:** Voice notes + guardrail hardening (sensitivity classification, audit log, access confirmation). *(shipped as v1)*
5. **v2 (Supermemory) Phases 0–5:** install + verify the local supermemory-server; memory client; ingest-side facts + lifecycle sync; ask-side retrieval + PIN gate over memory results; retire the v1 retrieval stack (done); `@memory` e2e battery. See `HANDOFF.md`.

---

*All decisions are resolved (see 3.7) — this doc is finalized and ready to be used as the basis for sprint/task breakdown.*
