import httpx

from ..config import settings

_TIMEOUT = httpx.Timeout(30.0)


class MemoryClient:
    """Best-effort client for the local supermemory-server.

    Every method returns a neutral value (None / empty list / empty dict)
    when the server is unreachable or misbehaving — callers degrade, never
    crash. The server's API key is auto-applied for unauthenticated
    localhost requests, so `api_key` is only attached when configured.
    """

    def __init__(self, base_url: str, api_key: str = ""):
        self._base = base_url.rstrip("/")
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        try:
            r = httpx.get(f"{self._base}{path}", params=params, headers=self._headers, timeout=_TIMEOUT)
            if r.status_code >= 400:
                return None
            return r.json()
        except Exception:
            return None

    def _post(self, path: str, payload: dict) -> dict | None:
        try:
            r = httpx.post(f"{self._base}{path}", json=payload, headers=self._headers, timeout=_TIMEOUT)
            if r.status_code >= 400:
                return None
            return r.json()
        except Exception:
            return None

    def _delete(self, path: str) -> bool:
        try:
            r = httpx.delete(f"{self._base}{path}", headers=self._headers, timeout=_TIMEOUT)
            return r.status_code < 400
        except Exception:
            return False

    def healthy(self) -> bool:
        return self._get("/v3/health") is not None

    def add_document(
        self,
        content: str,
        container_tag: str | None = None,
        metadata: dict | None = None,
        custom_id: str | None = None,
        entity_context: str | None = None,
    ) -> str | None:
        payload: dict = {"content": content}
        if container_tag:
            payload["containerTag"] = container_tag
        if metadata:
            payload["metadata"] = metadata
        if custom_id:
            payload["customId"] = custom_id
        if entity_context:
            payload["entityContext"] = entity_context
        data = self._post("/v3/documents", payload)
        return data.get("id") if data else None

    def document_status(self, doc_id: str) -> str | None:
        data = self._get(f"/v3/documents/{doc_id}")
        return data.get("status") if data else None

    def delete_document(self, doc_id: str) -> bool:
        return self._delete(f"/v3/documents/{doc_id}")

    def search(
        self,
        query: str,
        container_tag: str | None = None,
        search_mode: str = "hybrid",
        limit: int = 10,
        threshold: float = 0.0,
    ) -> list[dict]:
        if container_tag is None:
            container_tag = settings.memory_container_tag
        payload: dict = {
            "q": query,
            "searchMode": search_mode,
            "limit": limit,
            "threshold": threshold,
        }
        if container_tag:
            payload["containerTag"] = container_tag
        data = self._post("/v4/search", payload)
        if not data:
            return []
        results = data.get("results") or []
        out = []
        for r in results:
            content = r.get("chunk") or r.get("memory") or ""
            if not content:
                continue
            out.append(
                {
                    "content": content,
                    "metadata": r.get("metadata") or {},
                    "similarity": r.get("similarity", 0.0),
                }
            )
        return out

    def profile(self, container_tag: str | None = None) -> dict:
        if container_tag is None:
            container_tag = settings.memory_container_tag
        payload: dict = {"limit": 100}
        if container_tag:
            payload["containerTag"] = container_tag
        data = self._post("/v4/profile", payload)
        return data or {}


_client: MemoryClient | None = None


def get_client() -> MemoryClient:
    global _client
    if _client is None:
        _client = MemoryClient(settings.memory_url, settings.memory_api_key)
    return _client