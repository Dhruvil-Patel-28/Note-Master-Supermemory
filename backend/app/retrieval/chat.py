import ollama

from ..config import settings

NOT_FOUND_ANSWER = "I don't have this in my notes."


def _client() -> ollama.Client:
    return ollama.Client(host=settings.ollama_host)


def grounded_answer(query: str, hits: list[dict]) -> tuple[str, bool]:
    if not hits:
        return NOT_FOUND_ANSWER, False
    context = "\n".join(
        f"[{i + 1}] (capture {h['capture_id']}): {h['snippet']}" for i, h in enumerate(hits)
    )
    prompt = (
        "You are a retrieval assistant. Answer ONLY from the retrieved context below. "
        "Never invent facts that are not in the context. "
        "If the context does not contain the answer, reply exactly with the sentence:\n"
        f'"{NOT_FOUND_ANSWER}"\n'
        "When you use a context item, cite it at the end of your answer like [1], [2].\n\n"
        f"Retrieved context:\n{context}\n\n"
        f"Question: {query}\n\nAnswer:"
    )
    response = _client().chat(
        model=settings.ollama_model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1, "think": False},
    )
    answer = response["message"]["content"].strip()
    return answer, answer != NOT_FOUND_ANSWER and answer != f'"{NOT_FOUND_ANSWER}"'