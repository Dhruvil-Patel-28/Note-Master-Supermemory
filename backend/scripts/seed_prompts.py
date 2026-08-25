#!/usr/bin/env python3
"""Seed Langfuse Prompt Management with the current hardcoded prompt defaults.

Run once after Langfuse is up (and keys exist) so the Prompts tab shows all
three managed prompts immediately. After seeding, edit them in the UI — the
backend picks up changes within PROMPT_CACHE_TTL seconds (default 5 min).

Usage:
    LANGFUSE_PUBLIC_KEY=pk-... LANGFUSE_SECRET_KEY=sk-... \
        uv run python scripts/seed_prompts.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.observability import tracer  # noqa: E402

# Force init regardless of env timing
tracer._init()
if not tracer.enabled:
    print("ERROR: Langfuse not reachable or keys not set.")
    print("  export LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY first")
    sys.exit(1)

from app.retrieval.agent import _DEFAULT_GRADE_SYSTEM  # noqa: E402
from app.retrieval.intent import _CLASSIFIER_SYSTEM  # noqa: E402
from app.retrieval.chat import _DEFAULT_ANSWER_SYSTEM  # noqa: E402

PROMPTS = {
    "rag-grader": _DEFAULT_GRADE_SYSTEM,
    "intent-classifier": _CLASSIFIER_SYSTEM,
    "grounded-answer": _DEFAULT_ANSWER_SYSTEM,
}

for name, text in PROMPTS.items():
    try:
        tracer._lf.create_prompt(
            name=name,
            prompt=text,
            labels=["production"],
        )
        print(f"✅ seeded {name} ({len(text)} chars)")
    except Exception as exc:
        if "already exists" in str(exc).lower():
            print(f"⏭️  {name} already exists in Langfuse — skipping")
        else:
            print(f"❌ {name}: {exc}")

print("\nDone. Edit prompts at http://localhost:3001 → Prompts")
tracer.flush()
