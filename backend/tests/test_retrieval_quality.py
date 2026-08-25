"""Retrieval-quality battery against the LIVE user_main store (marker:
retrieval). Asserts ONLY on context assembly — the facts that reach the LLM —
never on model answers, so weak-model wording can never mask a retrieval
regression and a future model upgrade inherits a provably solid layer.

  - run via scripts/run-retrieval-tests.sh (MEMORY_ENABLED=1, user_main)
  - skips cleanly when supermemory-server is unreachable
  - read-only over the store: no captures are created or deleted

Cases encode expected facts per question; failures print exactly which facts
were missing from assembled context.
"""

import pytest

pytestmark = pytest.mark.retrieval


CASES = [
    {
        "id": "resume-projects-which",
        "q": "which are the 3 projects in my resume",
        "must": ["glow studio", "cortex research ai", "customer analytics"],
    },
    {
        "id": "resume-projects-count",
        "q": "how many projects are there in my resume",
        "must": ["glow studio", "cortex research ai", "customer analytics"],
    },
    {
        "id": "resume-projects-as-per",
        "q": "as per my resume which are my projects",
        "must": ["glow studio", "cortex research ai", "customer analytics"],
    },
    {
        "id": "transcript-cgpa",
        "q": "what is my cgpa",
        "must": ["7.57"],
    },
    {
        "id": "doc-scoped-cortex",
        "q": "get me about my cortex project",
        "must": ["cortex research ai"],
    },
    {
        "id": "transcript-semesters",
        "q": "which semester courses did i study",
        "must": ["semester"],
    },
    {
        "id": "certificate-oracle",
        "q": "what certificate do i have",
        "must": ["oracle"],
    },
    {
        # PAN card content must surface without writing the sensitive value
        # into this test file.
        "id": "pan-card-fact",
        "q": "what is my pan card",
        "must": ["pan card"],
    },
    {
        # Negative control: an out-of-vocabulary subject must never leak into
        # context. (A dense graph store makes fixed similarity floors admit
        # generic user-fact nodes on ANY query — that's acceptable; honest
        # not-found is enforced downstream by grounded_answer + _grounded.
        # What retrieval itself must guarantee is subject purity.)
        "id": "negative-zebra",
        "q": "do i own a zebra",
        "forbid": ["zebra"],
    },
]


@pytest.fixture(scope="module", autouse=True)
def _require_live_memory():
    from app.config import settings
    from app.memory.client import get_client

    if not settings.memory_enabled:
        pytest.skip("MEMORY_ENABLED != 1 — run via scripts/run-retrieval-tests.sh")
    if not get_client().healthy():
        pytest.skip("supermemory-server not reachable on 127.0.0.1:6767")


def _context(query: str) -> tuple[str, int]:
    from app.retrieval.context import build_context

    hits = build_context(query)
    return "\n".join(h["snippet"] for h in hits).lower(), len(hits)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_retrieval_quality(case):
    text, n_hits = _context(case["q"])
    if case.get("empty"):
        assert n_hits == 0, (
            f"[{case['id']}] expected empty context for an out-of-vocabulary "
            f"question, got {n_hits} hits"
        )
        return
    for fact in case.get("must", []):
        assert fact.lower() in text, (
            f"[{case['id']}] Q={case['q']!r} assembled {n_hits} hits but "
            f"MISSING expected fact {fact!r} — retrieval regression"
        )
    for banned in case.get("forbid", []):
        assert banned.lower() not in text, (
            f"[{case['id']}] unexpected content {banned!r} leaked into context"
        )


def test_assembly_budget_respected():
    """Every assembled context must stay inside the LLM budget."""
    from app.retrieval.context import _CONTEXT_BUDGET, build_context

    for case in CASES:
        if case.get("empty"):
            continue
        hits = build_context(case["q"])
        total = sum(len(h["snippet"]) for h in hits)
        assert total <= _CONTEXT_BUDGET, (
            f"[{case['id']}] context {total} chars exceeds {_CONTEXT_BUDGET} budget"
        )
