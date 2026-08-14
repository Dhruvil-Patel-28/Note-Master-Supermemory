def _rrf(hits: list[dict], k: int = 60) -> dict[int, float]:
    fused: dict[int, float] = {}
    for rank, hit in enumerate(hits):
        cid = hit["capture_id"]
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return fused


def fuse(
    fts_hits: list[dict],
    vector_hits: list[dict],
    graph_hits: list[dict] | None = None,
    limit: int = 10,
) -> list[dict]:
    if not vector_hits and not graph_hits:
        return fts_hits[:limit]
    scores = _rrf(fts_hits)
    for cid, score in _rrf(vector_hits).items():
        scores[cid] = scores.get(cid, 0.0) + score
    for cid, score in _rrf(graph_hits or []).items():
        scores[cid] = scores.get(cid, 0.0) + score

    best: dict[int, dict] = {}
    for hit in fts_hits + vector_hits + (graph_hits or []):
        cid = hit["capture_id"]
        if cid not in best or _rank(hit) < _rank(best[cid]):
            best[cid] = hit

    return [best[cid] for cid in sorted(scores, key=scores.get, reverse=True)[:limit]]


def _rank(hit: dict) -> float:
    return hit.get("score", 0.0)