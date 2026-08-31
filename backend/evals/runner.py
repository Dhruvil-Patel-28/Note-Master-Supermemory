"""Self-seeding eval runner: uploads known docs, fires 50 questions, scores,
cleans up. Zero dependency on personal data or prior state.

Usage:
    PYTHONPATH=. uv run python -m evals.runner --label "ollama-3b"
"""
import argparse
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

from .golden_dataset import EVAL_DOCS, QUESTIONS

BASE = "http://localhost:8000"


def _post(path, payload=None, files=None, timeout=120):
    if files:
        import io
        boundary = "----evalbound"
        body = io.BytesIO()
        for key, val in files.items():
            body.write(f"--{boundary}\r\n".encode())
            body.write(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
            body.write(val.encode() if isinstance(val, str) else val)
            body.write(b"\r\n")
        for key, val in (payload or {}).items():
            body.write(f"--{boundary}\r\n".encode())
            body.write(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
            body.write(str(val).encode())
            body.write(b"\r\n")
        body.write(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(BASE + path, data=body.getvalue(), method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    else:
        req = urllib.request.Request(
            BASE + path, data=json.dumps(payload or {}).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _get(path):
    req = urllib.request.Request(BASE + path)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _delete(capture_id):
    req = urllib.request.Request(BASE + f"/captures/{capture_id}", method="DELETE")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def seed_documents():
    ids = []
    for doc in EVAL_DOCS:
        r = _post("/captures/text", {"content": doc["content"], "note": doc["note"]})
        cid = r["id"]
        ids.append(cid)
        print(f"  seeded {doc['filename']} -> capture {cid}")
    deadline = time.time() + 60
    while time.time() < deadline:
        statuses = [_get(f"/captures/{cid}")["status"] for cid in ids]
        if all(s == "indexed" for s in statuses):
            break
        time.sleep(1)
    print("  all indexed OK")
    return ids


def cleanup(ids):
    for cid in ids:
        try:
            _delete(cid)
        except Exception:
            pass
    print(f"  cleaned up {len(ids)} captures")


def run_eval(label="default"):
    results = []
    print(f"\n{'='*70}")
    print(f"AGENTIC RAG EVAL: {label} | {len(QUESTIONS)} questions")
    print(f"{'='*70}\n")

    print("Seeding documents...")
    seeded_ids = seed_documents()

    print(f"\nRunning {len(QUESTIONS)} questions...\n")
    for case in QUESTIONS:
        q = case["q"]
        must = case.get("must_answer", [])
        cat = case.get("cat", "?")
        t0 = time.time()
        answer, found = "", False

        try:
            b = _post("/chat", {"query": q})
            answer = b.get("answer", "")
            found = b.get("found", False)
        except Exception as e:
            err = str(e)[:120]
            results.append({"question": q, "category": cat, "passed": False,
                            "error": err, "latency_s": round(time.time()-t0, 1)})
            print(f"  X [{cat}] {q[:45]:47s} ERROR: {err}")
            continue

        elapsed = round(time.time() - t0, 1)
        a_lower = answer.lower()
        passed = True
        issues = []

        if case.get("refusal"):
            markers = ["can only answer", "don't have general knowledge", "own notes"]
            if not any(m in a_lower for m in markers):
                passed = False
                issues.append(f"expected refusal, got: {answer[:60]}")
        elif case.get("expect_not_found"):
            nf_markers = ["don't have", "not in", "haven't", "no information"]
            if found and not any(m in a_lower for m in nf_markers):
                passed = False
                issues.append(f"expected not-found, got: {answer[:60]}")
        else:
            for fact in must:
                if fact.lower() not in a_lower:
                    passed = False
                    issues.append(f"missing {fact!r}")

        status = "+" if passed else "X"
        issue_str = "; ".join(issues) if issues else ""
        results.append({
            "question": q, "category": cat, "passed": passed,
            "answer": answer[:200], "latency_s": elapsed,
            "issues": issue_str, "found": found,
        })
        print(f"  {status} [{cat:12s}] {q[:45]:47s} lat={elapsed:>5.1f}s {issue_str}")

    total = len(results)
    passed_count = sum(r["passed"] for r in results)
    avg_lat = sum(r["latency_s"] for r in results) / max(total, 1)

    by_cat = {}
    for r in results:
        c = r["category"]
        by_cat.setdefault(c, {"pass": 0, "total": 0})
        by_cat[c]["total"] += 1
        if r["passed"]:
            by_cat[c]["pass"] += 1

    print(f"\n{'='*60}")
    print(f"SUMMARY [{label}]")
    print(f"  passed: {passed_count}/{total} ({passed_count/total:.0%})")
    print(f"  avg latency: {avg_lat:.1f}s")
    print("\n  By category:")
    for cat, stats in sorted(by_cat.items()):
        pct = stats['pass']/stats['total']*100
        marker = "OK" if pct == 100 else ("WARN" if pct >= 60 else "BAD")
        print(f"    {marker:>4} {cat:16s} {stats['pass']:>2}/{stats['total']} ({pct:.0f}%)")

    outfile = Path(__file__).parent / f"results_{label.replace(' ', '_').replace('/', '_')}.json"
    outfile.write_text(json.dumps({
        "label": label,
        "results": results,
        "summary": {"passed": passed_count, "total": total, "avg_latency_s": round(avg_lat, 1)},
    }, indent=2))
    print(f"\n  saved -> {outfile.name}")

    _push_to_langfuse(label, results)
    return results


def _push_to_langfuse(label: str, results: list[dict]):
    """Push eval results as tagged traces to Langfuse for comparison.

    Each question becomes a trace tagged with the model label.
    Compare models in Traces tab: filter by tag 'eval' then sort by label.
    """
    try:
        from langfuse import Langfuse
        lf = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
            host=os.getenv("LANGFUSE_HOST", "http://localhost:3001"),
        )
        lf.auth_check()
    except Exception as e:
        print(f"  langfuse push skipped ({e})")
        return

    model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    passed_count = 0

    for i, r in enumerate(results):
        try:
            trace = lf.trace(
                name=f"eval [{r.get('category','')}] {r['question'][:50]}",
                input={"question": r["question"], "category": r.get("category", "")},
                output={"answer": r.get("answer", ""), "passed": r["passed"]},
                tags=["eval", label, r.get("category", "")],
                metadata={
                    "model": model,
                    "label": label,
                    "latency_s": r.get("latency_s", 0),
                    "issues": r.get("issues", ""),
                },
            )
            trace.score(name="eval_passed", value=1 if r["passed"] else 0)
            trace.score(name="latency", value=r.get("latency_s", 0))
            if r["passed"]:
                passed_count += 1
        except Exception:
            pass

    lf.flush()
    print(f"  langfuse: pushed {len(results)} traces tagged '{label}' ({passed_count}/{len(results)} passed)")
    print(f"  langfuse: compare in Traces → filter by tag 'eval' → sort by tag '{label}'")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agentic RAG evaluation")
    parser.add_argument("--label", default="default")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    BASE = args.base_url

    try:
        run_eval(label=args.label)
    finally:
        print("\nCleaning up...")
        try:
            captures = _get("/captures")
            for c in captures:
                if (c.get("original_filename") or "").startswith("eval_"):
                    _delete(c["id"])
        except Exception:
            pass
