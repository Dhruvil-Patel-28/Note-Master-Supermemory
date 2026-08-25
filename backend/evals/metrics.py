"""Retrieval + answer quality metrics.

Core evals: recall (did expected facts appear in context?) and answer
match (did the model answer with the expected content?). Designed for
deterministic, fast evaluation without LLM-as-judge complexity.
"""


def recall(expected_facts: list[str], context_text: str) -> float:
    """Fraction of must_contain strings present in the assembled context."""
    if not expected_facts:
        return 1.0
    ctx = context_text.lower()
    hits = sum(1 for f in expected_facts if f.lower() in ctx)
    return hits / len(expected_facts)


def precision_ratio(context_hits: list[dict], source_capture: int | None) -> float:
    """Of all retrieved hits, what fraction come from the expected source?"""
    if not context_hits or not source_capture:
        return 1.0  # can't measure without a target
    from_src = sum(1 for h in context_hits if h.get("capture_id") == source_capture)
    return from_src / len(context_hits)


def answer_match(answer: str, must_contain: list[str]) -> float:
    """Fraction of expected strings present in the final answer."""
    if not must_contain:
        return 1.0
    a = answer.lower()
    hits = sum(1 for f in must_contain if f.lower() in a)
    return hits / len(must_contain)


def is_refusal(answer: str, refusal_answer: str) -> bool:
    return answer.strip() == refusal_answer.strip()


def is_not_found(answer: str, not_found_answer: str) -> bool:
    return answer.strip() == not_found_answer.strip()
