import ollama

from ..config import settings


def _client() -> ollama.Client:
    return ollama.Client(host=settings.ollama_host)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    response = _client().embed(model=settings.ollama_embed_model, input=texts)
    return [list(e) for e in response["embeddings"]]