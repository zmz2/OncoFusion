"""Export blinded citation reviews or score two independently completed review files."""
import argparse
import json
from pathlib import Path
from oncofusion.datasets import read_jsonl
from oncofusion.schemas import CaseInput
from oncofusion.review import export_review, score_reviews


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--study", type=Path, required=True)
    export.add_argument("--inputs", type=Path, required=True)
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--limit", type=int, default=200)
    score = sub.add_parser("score")
    score.add_argument("--first", type=Path, required=True)
    score.add_argument("--second", type=Path, required=True)
    score.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "export":
        result = export_review(args.study, [CaseInput.model_validate(row) for row in read_jsonl(args.inputs)], args.out, args.limit)
    else:
        result = score_reviews(args.first, args.second)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
