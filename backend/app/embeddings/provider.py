"""Embedding provider abstraction — pluggable across Ollama, Gemini, OpenAI.

Env: EMBEDDING_PROVIDER (ollama|gemini|openai), EMBEDDING_MODEL.
Default: ollama / nomic-embed-text (local, free).
"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "ollama")
_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

_client = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=60)
    return _client


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. Returns one vector per text."""
    if not texts:
        return []
    if _PROVIDER == "ollama":
        return _embed_ollama(texts)
    if _PROVIDER == "openai-compatible":
        return _embed_openai_compatible(texts)
    raise ValueError(f"unknown EMBEDDING_PROVIDER '{_PROVIDER}'")


def _embed_ollama(texts: list[str]) -> list[list[float]]:
    """Ollama embeddings via /api/embed. Batches to stay within API limits."""
    all_vecs = []
    batch_size = 32
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        r = _get_client().post(
            f"{_HOST}/api/embed",
            json={"model": _MODEL, "input": batch},
        )
        r.raise_for_status()
        all_vecs.extend(r.json()["embeddings"])
    return all_vecs


def _embed_openai_compatible(texts: list[str]) -> list[list[float]]:
    """Any OpenAI-compatible /v1/embeddings endpoint (OpenAI, Gemini compat,
    Together, etc.). Requires EMBEDDING_BASE_URL + EMBEDDING_API_KEY."""
    base = os.getenv("EMBEDDING_BASE_URL", "")
    key = os.getenv("EMBEDDING_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    r = _get_client().post(
        f"{base}/embeddings",
        json={"model": _MODEL, "input": texts},
        headers=headers,
    )
    r.raise_for_status()
    return [item["embedding"] for item in r.json()["data"]]
