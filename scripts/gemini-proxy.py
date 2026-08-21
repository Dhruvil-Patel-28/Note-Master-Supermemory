#!/usr/bin/env python3
"""Local stitch-proxy for supermemory-server -> Gemini (OpenAI-compat).

WHY THIS EXISTS: Gemini 3.x thinking models attach a `thought_signature` to
every tool call and REQUIRE it back when the conversation continues (turn 2+).
supermemory-server's internal AI SDK parses tool calls into its own shape and
drops `extra_content.google.thought_signature` when re-serializing, so Gemini
rejects every follow-up turn with 400 "Function call is missing a
thought_signature". This proxy remembers the signatures from each response
(keyed by tool_call id) and injects them back into subsequent requests.

It also forces `Accept-Encoding: identity` upstream so response bodies are
plain JSON — the binary's fetch has shown ZlibError-class failures handling
compressed bodies through some paths.

Stateless across restarts is fine: a stash miss simply forwards the request
unchanged (worst case = the pre-existing 400).
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request
import urllib.error

UPSTREAM = "https://generativelanguage.googleapis.com"
PORT = int(os.environ.get("GEMINI_PROXY_PORT", "8766"))
DUMP = os.environ.get("GEMINI_PROXY_DUMP", "")  # set to a dir path to debug

_stash: dict[str, str] = {}
_lock = threading.Lock()
_n = 0


def _extract_signatures(response_bytes: bytes) -> None:
    try:
        d = json.loads(response_bytes)
    except Exception:
        return
    if isinstance(d, list):
        d = d[0]
    for choice in (d.get("choices") or []):
        for call in ((choice.get("message") or {}).get("tool_calls") or []):
            sig = ((call.get("extra_content") or {}).get("google") or {}).get("thought_signature")
            if sig and call.get("id"):
                with _lock:
                    if len(_stash) > 500:
                        _stash.clear()
                    _stash[call["id"]] = sig


def _inject_signatures(body: bytes) -> bytes:
    try:
        d = json.loads(body)
    except Exception:
        return body
    changed = False
    for msg in (d.get("messages") or []):
        for call in (msg.get("tool_calls") or []):
            cid = call.get("id")
            with _lock:
                sig = _stash.get(cid)
            if not sig or cid is None:
                continue
            ec = call.get("extra_content") or {}
            google = ec.get("google") or {}
            if not google.get("thought_signature"):
                google["thought_signature"] = sig
                ec["google"] = google
                call["extra_content"] = ec
                changed = True
    return json.dumps(d).encode() if changed else body


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        global _n
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        stitched = _inject_signatures(body)

        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("host", "content-length")}
        # NOTE: content-length MUST be dropped — the stitched body is longer
        # than the incoming one; urllib recomputes it from data.
        headers["Accept-Encoding"] = "identity"

        if DUMP:
            global _n
            with _lock:
                _n += 1
                i = _n
            os.makedirs(DUMP, exist_ok=True)
            with open(f"{DUMP}/{i:03d}_req.json", "wb") as f:
                f.write(stitched)

        req = urllib.request.Request(UPSTREAM + self.path, data=stitched,
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                resp_body = r.read()
                status = r.status
                resp_headers = dict(r.getheaders())
        except urllib.error.HTTPError as e:
            resp_body = e.read()
            status = e.code
            resp_headers = dict(e.headers or {})
        except Exception as e:
            msg = str(e).encode()
            self.send_response(502)
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return

        if DUMP:
            with open(f"{DUMP}/{i:03d}_resp_{status}.txt", "wb") as f:
                f.write(resp_body)

        _extract_signatures(resp_body)

        self.send_response(status)
        skipped = ("transfer-encoding", "content-length", "connection", "content-encoding")
        for k, v in resp_headers.items():
            if k.lower() in skipped:
                continue
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
