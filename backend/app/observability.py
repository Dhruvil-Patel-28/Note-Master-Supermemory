"""Langfuse tracing with graceful no-op.

Set LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY (+ optional LANGFUSE_HOST,
default http://localhost:3001) to enable; without keys every trace/span
call is a cheap no-op object, so the system never depends on Langfuse
being up. All data stays local when LANGFUSE_HOST points at the
self-hosted stack.

SDK note: pinned to langfuse 2.x to match the self-hosted v2 server — the
v3 SDK's client fails validating against v2 server responses.
"""
import logging
import os

logger = logging.getLogger(__name__)


class _NoopSpan:
    def update(self, **kw):
        return self

    def span(self, *a, **kw):
        return self

    def end(self, **kw):
        return self

    def score(self, *a, **kw):
        return self


class _NoopTrace(_NoopSpan):
    pass


class Tracer:
    """Lazy Langfuse client. Reads env at first use so tests/ops can set
    variables before import."""

    def __init__(self):
        self._lf = None
        self._checked = False
        self.enabled = False

    def _init(self):
        if self._checked:
            return
        self._checked = True
        pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        sk = os.getenv("LANGFUSE_SECRET_KEY", "")
        host = os.getenv("LANGFUSE_HOST", "http://localhost:3001")
        if not (pk and sk):
            return
        try:
            from langfuse import Langfuse

            self._lf = Langfuse(public_key=pk, secret_key=sk, host=host)
            self._lf.auth_check()  # fail fast on bad keys/host
            self.enabled = True
            logger.info("langfuse tracing enabled (%s)", host)
        except Exception as exc:
            logger.warning("langfuse unavailable (%s) — tracing disabled", exc)
            self._lf = None

    def trace(self, name: str, input=None, metadata=None, session_id=None):
        self._init()
        if not self.enabled:
            return _NoopTrace()
        try:
            return self._lf.trace(name=name, input=input, metadata=metadata or {}, session_id=session_id)
        except Exception as exc:
            logger.warning("langfuse trace failed: %s", exc)
            return _NoopTrace()

    def flush(self):
        if self.enabled and self._lf is not None:
            try:
                self._lf.flush()
            except Exception:
                pass


tracer = Tracer()
