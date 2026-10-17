"""Freeze reviewed public tool queries for a later, separate synthesis experiment."""
import argparse
import json
from pathlib import Path
from oncofusion.biomedical import ToolQuery, ToolUniverseAdapter, save_snapshot, enrich_synthesis_case
from oncofusion.schemas import CaseInput


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, required=True, help="JSON list of ToolQuery objects")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--case", type=Path, help="optional synthesis CaseInput to enrich")
    parser.add_argument("--case-out", type=Path, help="new output file for an enriched synthesis case")
    args = parser.parse_args()
    if bool(args.case) != bool(args.case_out):
        parser.error("supply both --case and --case-out")
    case = None
    if args.case:
        case = CaseInput.model_validate_json(args.case.read_text(encoding="utf-8"))
        if case.task != "synthesis" or args.case_out.exists():
            parser.error("use a synthesis input and a fresh --case-out path")
    if not args.allow_remote:
        parser.error("review public search terms and pass --allow-remote")
    if args.queries.stat().st_size > 100_000:
        parser.error("query file exceeds 100 KB")
    rows = json.loads(args.queries.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
        parser.error("supply a list of 1-20 reviewed queries")
    queries = [ToolQuery.model_validate(row) for row in rows]
    adapter = ToolUniverseAdapter()
    for index, query in enumerate(queries):
        path = args.out / f"{index:02}-{query.name}.json"
        if path.exists():
            parser.error(f"snapshot already exists: {path}")
    snapshots = []
    for index, query in enumerate(queries):
        snapshot = adapter.execute(query, allow_remote=True)
        snapshots.append(snapshot)
        save_snapshot(snapshot, args.out / f"{index:02}-{query.name}.json")
        print(json.dumps({"tool": query.name, "sha256": snapshot.response_sha256}))
    if case:
        enriched = enrich_synthesis_case(case, snapshots)
        args.case_out.parent.mkdir(parents=True, exist_ok=True)
        with args.case_out.open("x", encoding="utf-8") as stream:
            stream.write(enriched.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
