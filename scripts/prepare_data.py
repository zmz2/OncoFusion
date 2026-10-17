"""Prepare pinned local datasets; downloads require explicit source-license acknowledgement."""
import argparse
import json
from pathlib import Path
import httpx
from oncofusion.preparation import (CIVIC_URL, CIVIC_BLOB, download, acquire_mtb,
                                    prepare_civic, prepare_mtb)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("dataset", choices=("civicfact", "mtbbench"))
    p.add_argument("--raw", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--download", action="store_true")
    p.add_argument("--accept-source-terms", action="store_true")
    p.add_argument("--source", type=Path)
    p.add_argument("--path-map", type=Path)
    p.add_argument("--refutes-label", default="REFUTES", help="legacy identity value only; labels are preserved")
    p.add_argument("--verification-scheme", choices=("refutes", "revisions"), default="revisions")
    args = p.parse_args()
    if args.download and not args.accept_source_terms:
        p.error("review source data terms and pass --accept-source-terms to download")
    source, mapping = args.source, None
    if args.download:
        with httpx.Client(timeout=120) as client:
            if args.dataset == "civicfact":
                source = args.raw / "civicfact-2026.06.09.jsonl.gz"
                inventory = download(client, CIVIC_URL, source, git_blob=CIVIC_BLOB)
                (args.raw / "acquisition.json").write_text(json.dumps(inventory, indent=2))
            else:
                inventory = acquire_mtb(client, args.raw)
                source, mapping = args.raw / inventory["questions"], inventory["path_map"]
    if source is None:
        p.error("supply --source or --download")
    if args.path_map:
        mapping = json.loads(args.path_map.read_text())
    report = prepare_civic(source, args.out, args.refutes_label, verification_scheme=args.verification_scheme) if args.dataset == "civicfact" else prepare_mtb(source, args.raw, args.out, mapping)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
