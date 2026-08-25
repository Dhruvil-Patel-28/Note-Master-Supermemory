"""Unit tests for the agentic RAG loop — grader faked, retrieval primitives
monkeypatched. Deterministic: no Ollama, no supermemory."""
import pytest
from types import SimpleNamespace

from app.retrieval import agent as agent_mod


def _hit(cid, text, sim=0.5):
    return {"capture_id": cid, "snippet": text, "similarity": sim}


class FakeGrader:
    """Scripted verdicts consumed in order."""

    def __init__(self, *verdicts):
        self.verdicts = list(verdicts)
        self.calls = []

    def __call__(self, query, pool):
        self.calls.append(len(pool))
        v = self.verdicts.pop(0) if self.verdicts else {
            "sufficient": True, "missing_aspect": "", "suggested_query": "",
            "need_document_scope": False,
        }
        return dict(v)


@pytest.fixture()
def base_env(monkeypatch):
    from app.retrieval import context as ctx

    monkeypatch.setattr(
        ctx, "settings", SimpleNamespace(memory_enabled=True), raising=False
    )
    monkeypatch.setattr(ctx, "_memory_hits", lambda q: [])
    monkeypatch.setattr(ctx, "_match_document", lambda q: None)
    monkeypatch.setattr(ctx, "_document_scope_hits", lambda m, e: [])
    return ctx


def test_sufficient_first_round_single_shot_equivalent(base_env, monkeypatch):
    """Grader says sufficient immediately → one round, hits = baseline."""
    base_env._memory_hits = lambda q: [_hit(90, "The user built Glow Studio.")]
    monkeypatch.setattr(agent_mod, "_grade", FakeGrader())

    out = agent_mod.run_rag_agent("which are my projects")
    assert len(out.rounds) == 1
    assert len(out.hits) == 1
    assert "Glow Studio" in out.hits[0]["snippet"]


def test_insufficient_refines_then_answers(base_env, monkeypatch):
    """Round 1 finds one project; grader suggests a refined query; round 2
    merges fresh hits; grader then passes."""
    base_env._memory_hits = lambda q: (
        [_hit(90, "The user built Glow Studio.")] if "glow" in q.lower() or "projects" in q.lower()
        else [_hit(90, "The user built Cortex Research AI."), _hit(90, "The user built an AI-powered customer analytics platform.")]
    )
    monkeypatch.setattr(
        agent_mod, "_grade",
        FakeGrader(
            {"sufficient": False, "missing_aspect": "more projects", 
             "suggested_query": "cortex customer analytics", "need_document_scope": False},
            {"sufficient": True, "missing_aspect": "", "suggested_query": "", "need_document_scope": False},
        ),
    )
    out = agent_mod.run_rag_agent("which are my projects")
    assert len(out.rounds) == 2
    text = " ".join(h["snippet"] for h in out.hits)
    assert "Glow Studio" in text and "Cortex" in text and "customer analytics" in text


def test_max_rounds_held(base_env, monkeypatch):
    """A never-satisfied grader cannot loop past the configured cap."""
    monkeypatch.setenv("RAG_MAX_ROUNDS", "3")
    import importlib
    importlib.reload(agent_mod)

    base_env._memory_hits = lambda q: []
    grader = FakeGrader(*[
        {"sufficient": False, "missing_aspect": "x",
         "suggested_query": f"q{i}", "need_document_scope": False}
        for i in range(10)
    ])
    monkeypatch.setattr(agent_mod, "_grade", grader)
    out = agent_mod.run_rag_agent("anything")
    assert len(out.rounds) == 3
    assert len(grader.calls) == 2  # no grade after the final round


def test_no_fresh_hits_stops_cleanly(base_env, monkeypatch):
    """Insufficient verdict with nothing new retrieved and no suggestion →
    stop instead of spinning."""
    base_env._memory_hits = lambda q: [_hit(90, "some fact")]
    monkeypatch.setattr(
        agent_mod, "_grade",
        FakeGrader({"sufficient": False, "missing_aspect": "unknown",
                    "suggested_query": "", "need_document_scope": False}),
    )
    out = agent_mod.run_rag_agent("obscure question")
    assert len(out.rounds) == 1


def test_budget_held_across_rounds(base_env, monkeypatch):
    from app.retrieval.context import _CONTEXT_BUDGET

    big = "x" * 9000
    base_env._memory_hits = lambda q: (
        [_hit(90, "first " + big)] if "one" not in q
        else [_hit(90, "second " + big), _hit(91, "third " + big)]
    )
    monkeypatch.setattr(
        agent_mod, "_grade",
        FakeGrader(
            {"sufficient": False, "missing_aspect": "more",
             "suggested_query": "second batch", "need_document_scope": False},
            {"sufficient": True, "missing_aspect": "", "suggested_query": "", "need_document_scope": False},
        ),
    )
    out = agent_mod.run_rag_agent("question one")
    total = sum(len(h["snippet"]) for h in out.hits)
    assert total <= _CONTEXT_BUDGET


def test_grader_failure_fails_open(base_env, monkeypatch):
    """Broken grader backend → real _grade fails open (sufficient) →
    single-shot equivalent."""
    base_env._memory_hits = lambda q: [_hit(90, "fact one")]

    def boom(*a, **k):
        raise RuntimeError("no ollama")

    monkeypatch.setattr(agent_mod, "_client", boom)
    out = agent_mod.run_rag_agent("q")
    assert len(out.rounds) == 1 and out.hits


def test_agentic_off_returns_baseline(base_env, monkeypatch):
    monkeypatch.setenv("RAG_AGENTIC", "0")
    import importlib
    importlib.reload(agent_mod)
    calls = []
    base_env._memory_hits = lambda q: (calls.append(q), [_hit(90, "baseline fact")])[1]
    out = agent_mod.run_rag_agent("my projects")
    assert [h["snippet"] for h in out.hits] == ["baseline fact"]
    importlib.reload(agent_mod)  # restore default-enabled module state
