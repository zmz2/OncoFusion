"""Prepare or score the independent CIViC-Fact passage retrieval task."""
import argparse
import json
from pathlib import Path
import httpx
from oncofusion.datasets import iter_jsonl
from oncofusion.evaluation import load_evaluation
from oncofusion.preparation import CIVIC_REVISION, download
from oncofusion.retrieval_benchmark import evaluate_retrieval, prepare_retrieval


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--queries", type=Path)
    prep.add_argument("--chunks", type=Path)
    prep.add_argument("--raw", type=Path, default=Path("data/raw/civic_retrieval"))
    prep.add_argument("--out", type=Path, required=True)
    prep.add_argument("--download", action="store_true")
    prep.add_argument("--accept-source-terms", action="store_true")
    prep.add_argument("--allow-exclusions", action="store_true")
    score = sub.add_parser("evaluate")
    score.add_argument("--dataset", type=Path, required=True)
    score.add_argument("--split", choices=("dev", "test", "train"), default="dev")
    score.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.command == "prepare":
        queries, chunks = args.queries, args.chunks
        if args.download:
            if not args.accept_source_terms:
                p.error("review licenses and pass --accept-source-terms")
            prefix = f"https://raw.githubusercontent.com/creisle/civicfact/{CIVIC_REVISION}/data_builder/builds/civicfact-2026.06.09/"
            queries, chunks = args.raw / "retreival.jsonl.gz", args.raw / "document_chunks.jsonl.gz"
            with httpx.Client(timeout=120) as client:
                records = [download(client, prefix + "retreival.jsonl.gz", queries, git_blob="4783a5ad0b63b9387b191f814a1e562337b39cb9"),
                           download(client, prefix + "document_chunks.jsonl.gz", chunks, git_blob="4a1b5acf727d9fb1b2ff000ccde9ea9b6702d60b")]
            (args.raw / "acquisition.json").write_text(json.dumps(records, indent=2))
        if queries is None or chunks is None:
            p.error("provide --queries and --chunks, or --download")
        report = prepare_retrieval(iter_jsonl(queries), iter_jsonl(chunks), args.out, args.allow_exclusions)
    else:
        cases, gold = load_evaluation(args.dataset / "inputs.jsonl", args.dataset / "_gold/labels.jsonl")
        gold = [g for g in gold if g.split == args.split]
        ids = {g.case_id for g in gold}
        report = evaluate_retrieval([c for c in cases if c.id in ids], gold)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
