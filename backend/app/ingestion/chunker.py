"""Text chunking — we own this now (the vector store indexes our chunks).

Chunk size, overlap, and split strategy directly affect retrieval quality
and are eval dimensions. Env-configurable via CHUNK_SIZE / CHUNK_OVERLAP.
"""
import os
import re

_CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
_CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))


def chunk(text: str, size: int = None, overlap: int = None) -> list[dict]:
    """Split text into overlapping chunks at paragraph boundaries where
    possible. Returns [{"text": ..., "index": ...}, ...]."""
    size = size or _CHUNK_SIZE
    overlap = overlap or _CHUNK_OVERLAP
    if not text or len(text) <= size:
        return [{"text": text.strip(), "index": 0}] if text and text.strip() else []

    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # If paragraph itself exceeds chunk size, hard-split it
        while len(para) > size:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:size])
            para = para[size - overlap:]
        if not para:
            continue
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # carry overlap from previous chunk into new one
            tail = current[-overlap:] if overlap and len(current) > overlap else ""
            current = f"{tail}\n\n{para}".strip() if tail else para

    if current.strip():
        chunks.append(current)

    return [{"text": c, "index": i} for i, c in enumerate(chunks)]
