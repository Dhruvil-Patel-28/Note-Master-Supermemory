"""Generate a comparison report across multiple eval runs.

Usage:
    uv run python -m evals.report results_ollama.json results_hermes3.json ...
"""
import json
import sys
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def report(paths: list[str]) -> None:
    runs = [load(p) for p in paths]
    if not runs:
        print("no result files given")
        return

    labels = [r["label"] for r in runs]
    width = max(len(l) for l in labels) + 2

    header = f"{'metric':<22}" + "".join(f"{l:>{width}}" for l in labels)
    print(header)
    print("─" * len(header))

    for key in ("passed", "avg_recall", "avg_latency_s"):
        row = f"{key:<22}"
        for r in runs:
            v = r["summary"].get(key, "?")
            if isinstance(v, float):
                row += f"{v:>{width}.1%}" if key == "avg_recall" else f"{v:>{width}.1f}s"
            else:
                row += f"{v:>{width}}"
        print(row)

    # per-case breakdown
    print(f"\n{'─'*60}")
    print("PER-CASE:")
    case_ids = set()
    for r in runs:
        for cr in r["results"]:
            case_ids.add(cr["question"])
    for q in sorted(case_ids):
        row = f"  {q[:40]:42s}"
        for r in runs:
            match = next((cr for cr in r["results"] if cr["question"] == q), None)
            status = "✅" if match and match.get("passed") else "❌" if match else "—"
            row += f"  {status}"
        print(row)

    print(f"\nlabels: {labels}")


if __name__ == "__main__":
    report(sys.argv[1:])
