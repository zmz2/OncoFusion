"""Test authentic upstream review texts with the deterministic simulator, never as scientific scores."""
import argparse
import json
from pathlib import Path
import httpx
from oncofusion.config import presets
from oncofusion.datasets import read_jsonl
from oncofusion.engine import Engine
from oncofusion.evaluation import evaluate
from oncofusion.preparation import CIVIC_REVISION, download
from oncofusion.providers import MockProvider
from oncofusion.review_samples import UPSTREAM_REVIEW_BLOB, UPSTREAM_REVIEW_PATH, import_reviews


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, default=Path("data/raw/upstream-reviews.jsonl"))
    p.add_argument("--download", action="store_true")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--out", type=Path, default=Path("results/upstream_smoke"))
    args = p.parse_args()
    if args.limit < 1:
        p.error("limit must be positive")
    url = f"https://raw.githubusercontent.com/creisle/civicfact/{CIVIC_REVISION}/{UPSTREAM_REVIEW_PATH}"
    if args.download:
        with httpx.Client(timeout=60) as client:
            download(client, url, args.source, git_blob=UPSTREAM_REVIEW_BLOB)
    cases, gold = import_reviews(read_jsonl(args.source), args.limit)
    counts = []
    for name, config in presets().items():
        report = evaluate(cases, gold, Engine(MockProvider()), config, args.out / name)
        counts.append({"preset": name, "count": report["count"], "failed_or_incomplete": report["failed_or_incomplete"]})
    summary = {"source": url, "kind": "authentic manual-review sample text; not official held-out benchmark",
               "model": "simulated", "external_api_tested": False, "cases": len(cases),
               "case_executions": sum(x["count"] for x in counts), "configurations": counts}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0 if not any(x["failed_or_incomplete"] for x in counts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
