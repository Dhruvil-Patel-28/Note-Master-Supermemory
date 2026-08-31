"""Agentic RAG loop.

Instead of one-shot retrieval, an iterative controller:
  1. RETRIEVE  a sub-query through the production assembly primitives
               (hybrid search + label-matched graph read + pin)
  2. MERGE     dedupe fresh hits into the context pool (global budget held)
  3. GRADE     a schema-constrained LLM verdict on whether the pool can
               answer the question {sufficient, missing_aspect,
               suggested_query, need_document_scope}
  4. DECIDE    answer now / refine the query / force the document-scoped
               graph read — up to RAG_MAX_ROUNDS

The controller is deterministic Python; the model only grades/suggests and
finally answers (grounded_answer, unchanged). Guardrails downstream
(scrub/intent/_grounded/audit) are untouched.
"""
import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field

from ..config import settings
from ..observability import get_prompt, tracer
from . import context as ctx
from .chat import _client

logger = logging.getLogger(__name__)

AGENT_MODEL = os.getenv("RAG_AGENT_MODEL", "hermes3")
MAX_ROUNDS = int(os.getenv("RAG_MAX_ROUNDS", "3"))
AGENTIC_ENABLED = os.getenv("RAG_AGENTIC", "1") == "1"

_GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "sufficient": {"type": "boolean"},
        "missing_aspect": {"type": "string"},
        "suggested_query": {"type": "string"},
        "need_document_scope": {"type": "boolean"},
    },
    "required": ["sufficient", "missing_aspect", "suggested_query", "need_document_scope"],
}

_DEFAULT_GRADE_SYSTEM = (
    "You judge whether retrieved notes are enough to answer a question about "
    "the user's own documents and notes. Reply ONLY with JSON.\n"
    "sufficient=true when the facts clearly present let you answer the question.\n"
    "missing_aspect = what is missing (empty string when sufficient).\n"
    "suggested_query = ONE better search query that would find the missing "
    "facts (empty string when sufficient or when nothing better comes to mind).\n"
    "need_document_scope=true when the question seems to ask for everything "
    "about one specific named document (resume, transcript, bill...) whose "
    "facts may live in a graph store rather than these search hits.\n"
    'Example: {"sufficient": false, "missing_aspect": "only one project found", '
    '"suggested_query": "Cortex customer analytics projects resume", '
    '"need_document_scope": true}'
)
_GRADE_SYSTEM = get_prompt("rag-grader", _DEFAULT_GRADE_SYSTEM)


@dataclass
class AgentRound:
    sub_query: str
    new_hits: int
    pool_size: int
    verdict: dict | None = None


@dataclass
class AgentOutcome:
    hits: list[dict] = field(default_factory=list)
    rounds: list[AgentRound] = field(default_factory=list)
    forced_scope: bool = False


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower().strip()


def _grade(query: str, pool: list[dict], trace=None) -> dict:
    """Schema-constrained sufficiency verdict from the agent model. Any
    failure fails OPEN (treated as sufficient) so a broken grader degrades to
    single-shot behavior instead of blocking answers."""
    grade_span = trace.span(name="grade", model=AGENT_MODEL,
                            input={"pool_size": len(pool)}) if trace else None
    digest_parts = []
    for h in pool[:8]:
        digest_parts.append(f"[c{h['capture_id']}] {_norm(h['snippet'])[:130]}")
    digest = (
        f"{len(pool)} retrieved facts"
        + (f" (showing {min(len(pool), 8)}):\n" + "\n".join(digest_parts) if pool else "")
    )
    try:
        response = _client().chat(
            model=AGENT_MODEL,
            messages=[
                {"role": "system", "content": _GRADE_SYSTEM},
                {
                    "role": "user",
                    "content": f"Question: {query}\n\nRetrieved notes:\n{digest}",
                },
            ],
            options={"temperature": 0.1, "think": False, "num_predict": 256},
            format=_GRADE_SCHEMA,
        )
        verdict = json.loads(response["message"]["content"])
        if isinstance(verdict, dict) and "sufficient" in verdict:
            if grade_span:
                grade_span.end(output=verdict)
            return verdict
    except Exception as exc:
        logger.warning("grader failed (%s) — treating pool as sufficient", exc)
    fallback = {"sufficient": True, "missing_aspect": "", "suggested_query": "", "need_document_scope": False}
    if grade_span:
        grade_span.end(output=fallback, metadata={"fallback": True})
    return fallback


def _breakdown(hits: list[dict]) -> dict:
    """Per-source hit counts (hybrid-chunk / graph-memory / scoped-graph /
    pin) — surfaced in Langfuse retrieval spans."""
    return dict(Counter(h.get("source", "unknown") for h in hits))


def run_rag_agent(query: str, trace=None) -> AgentOutcome:
    """Iterative retrieve→merge→grade→decide over the production retrieval
    primitives. Round 1 reproduces the exact single-shot baseline
    (build_context), so agentic mode strictly adds refinement on top of it."""

    def span(name, **kw):
        return trace.span(name=name, **kw) if trace is not None else None

    def _noop_end(*a, **k):
        pass

    outcome = AgentOutcome()
    matched = ctx._match_document(query)
    matched = dict(matched) if matched else None

    pool: list[dict] = []
    seen: set[str] = set()

    def merge(hits: list[dict]) -> list[dict]:
        """Add fresh, in-budget hits to the pool. Returns the hits added."""
        added: list[dict] = []
        used = sum(len(h["snippet"]) for h in pool)
        for h in hits:
            key = _norm(h["snippet"])
            if key in seen or len(h["snippet"]) > _room(used):
                continue
            seen.add(key)
            used += len(h["snippet"])
            pool.append(h)
            added.append(h)
        return added

    def _room(used: int) -> int:
        return max(0, ctx._CONTEXT_BUDGET - used)

    sub_query = query
    forced_scope = False

    for round_no in range(1, MAX_ROUNDS + 1):
        sp = span(f"retrieval round {round_no}", input={"sub_query": sub_query})

        if round_no == 1:
            # Exact single-shot baseline: hybrid + enum-scoped graph read + pin.
            fresh = ctx.build_context(sub_query)
            # Re-base pin output against the pool-aware merge below.
        else:
            fresh = ctx._memory_hits(sub_query)
            if verdict.get("need_document_scope") and matched and not forced_scope:
                scoped = ctx._document_scope_hits(dict(matched), pool)
                forced_scope = scoped != []
                fresh = scoped + fresh

        added = merge(fresh)
        outcome.rounds.append(AgentRound(sub_query, added, len(pool)))
        if sp:
            sp.end(output={
                "new_hits": len(added),
                "new_by_source": _breakdown(added),
                "pool_size": len(pool),
                "pool_by_source": _breakdown(pool),
                "top_similarities": [round(h["similarity"], 2) for h in pool[:6]],
                "capture_ids": sorted({h["capture_id"] for h in pool}),
            })

        if round_no == MAX_ROUNDS:
            break

        verdict = _grade(query, pool, trace=trace)
        outcome.rounds[-1].verdict = verdict
        if sp:
            gsp = span(f"grade round {round_no}", input={"pool": len(pool)})
            gsp.end(output=verdict)

        if verdict.get("sufficient"):
            break
        nxt = (verdict.get("suggested_query") or "").strip()
        scope_wanted = bool(verdict.get("need_document_scope")) and matched and not forced_scope
        if not nxt and not scope_wanted:
            break  # insufficient but no actionable refinement — stop cleanly
        if nxt:
            sub_query = nxt

    if matched and not pool:
        # Nothing anywhere — still give the sparse-pin fallback its shot so
        # labeled documents surface even when search/graph both come up empty.
        pinned = ctx._apply_document_pin([], dict(matched))
        pool.extend(pinned)
        outcome.rounds.append(AgentRound("pin fallback", len(pinned), len(pool)))

    outcome.forced_scope = forced_scope
    outcome.hits = ctx._apply_document_pin(pool, matched)

    # Drop the internal pin marker hit duplication risk: pin was applied inside
    # round-1 build_context too — dedupe defensively by normalized snippet.
    deduped, seen2 = [], set()
    for h in outcome.hits:
        k = _norm(h["snippet"])
        if k in seen2:
            continue
        seen2.add(k)
        deduped.append(h)
    outcome.hits = deduped
    return outcome
