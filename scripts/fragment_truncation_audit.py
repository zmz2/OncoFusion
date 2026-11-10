"""Re-measure the document tail the pre-56492fd planner never showed the model.

`fragment_documents()` used to walk a document in `fragment_chars` chunks and stop after
`max_fragments_per_document` of them, so everything past that prefix was invisible while the run
still reported itself as evidence-grounded. This replays that exact walk (the loop as it stood at
commit 56492fd: stop = min(len, start+chars), snapped forward to the last ". ", "\n" or "; ") over
a dataset's inputs and counts, per split, how many cases and documents were cut and how many
characters were dropped. It reads only `inputs.jsonl`, never the gold sidecar, and prints
aggregates.

    .venv/bin/python scripts/fragment_truncation_audit.py --dataset data/mtbbench \
        --out results/v1/fragment_truncation_audit.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def old_walk(text: str, chars: int, per_document: int) -> tuple[int, int]:
    """Return (spans needed to cover the whole text, characters past the per-document cap)."""
    start, number, needed, dropped = 0, 1, 0, 0
    while start < len(text):
        stop = min(len(text), start + chars)
        if stop < len(text):
            cut = max(text.rfind(sep, start, stop) for sep in (". ", "\n", "; "))
            stop = cut + 2 if cut > start else stop
        needed += 1
        if number > per_document:
            dropped += stop - start
        number += 1
        start = stop
    return needed, (0 if needed <= per_document else dropped)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--chars", type=int, default=600, help="fragment_chars at 56492fd")
    parser.add_argument("--per-document", type=int, default=8, help="max_fragments_per_document at 56492fd")
    parser.add_argument("--case-ids", nargs="*", default=None,
                        help="restrict to these case ids (the recorded sample subset)")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    wanted = set(args.case_ids or [])
    totals = {"cases": 0, "cases_truncated": 0, "documents": 0, "documents_truncated": 0,
              "characters": 0, "characters_dropped": 0}
    for line in (args.dataset / "inputs.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        if wanted and case["id"] not in wanted:
            continue
        totals["cases"] += 1
        truncated = False
        for doc in case["documents"]:
            totals["documents"] += 1
            totals["characters"] += len(doc["text"])
            needed, dropped = old_walk(doc["text"], args.chars, args.per_document)
            if needed > args.per_document:
                truncated = True
                totals["documents_truncated"] += 1
                totals["characters_dropped"] += dropped
        totals["cases_truncated"] += int(truncated)
    totals["share_characters_dropped"] = round(
        totals["characters_dropped"] / max(1, totals["characters"]), 4)
    totals["dataset"] = str(args.dataset)
    totals["fragment_chars"] = args.chars
    totals["fragments_per_document"] = args.per_document
    totals["rule"] = "prefix walk as implemented in fragment_documents() at commit 56492fd"
    text = json.dumps(totals, indent=2, ensure_ascii=False)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
