"""Build the CIViC main table with debug-group and unused-group reporting."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from oncofusion.evaluation import classification_metrics


LABELS = ("SUPPORTS", "REVISIONS", "NEI")


def arm_rows(study: dict) -> dict[str, list[dict]]:
    # The completed study embeds no rows at the top level; arm summaries contain them.
    return {}


def summarize_rows(rows: list[dict]) -> dict:
    if not rows:
        return {"count": 0, "completed": 0, "completion_rate": None,
                "failed_or_incomplete": 0, "accuracy": None, "macro_f1": None,
                "per_class_recall": {label: None for label in LABELS},
                "calls": 0, "input_tokens": 0, "output_tokens": 0}
    completed = sum(row["status"] == "completed" for row in rows)
    metrics = classification_metrics(
        [row["gold"] for row in rows],
        [row["prediction"] for row in rows],
        list(LABELS),
    )
    observed = [row.get("usage", row.get("observed_usage", {})) for row in rows]
    return {
        "count": len(rows),
        "completed": completed,
        "completion_rate": completed / len(rows) if rows else None,
        "failed_or_incomplete": len(rows) - completed,
        "accuracy": metrics["accuracy"],
        "macro_f1": metrics["macro_f1"],
        "per_class_recall": {
            label: metrics["per_class"][label]["recall"] for label in LABELS
        },
        "calls": sum(item.get("calls", 0) for item in observed),
        "input_tokens": sum(item.get("input_tokens", 0) for item in observed),
        "output_tokens": sum(item.get("output_tokens", 0) for item in observed),
    }


def markdown_table(rows: list[dict]) -> str:
    lines = [
        "| Arm / split | N | Complete | Accuracy | Macro-F1 | SUPPORTS recall | REVISIONS recall | NEI recall | Calls | Input tokens | Output tokens |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        recall = row["per_class_recall"]
        if not row["count"]:
            lines.append(
                f"| {row['scope']} / {row['treatment']} | 0 | N/A | N/A | "
                "N/A | N/A | N/A | N/A | 0 | 0 | 0 |")
            continue
        lines.append(
            "| {scope} / {treatment} | {count} | {completion_rate:.1%} | {accuracy:.3f} | "
            "{macro_f1:.3f} | {SUPPORTS:.3f} | {REVISIONS:.3f} | {NEI:.3f} | {calls} | "
            "{input_tokens} | {output_tokens} |".format(
                **{**row, **recall, "scope": row["scope"]})
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--study-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path,
                        default=Path("experiments/civic_test_source_manifest.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    study = json.loads((args.study_dir / "study.json").read_text())
    manifest = json.loads(args.manifest.read_text())
    debug_groups = set(manifest["debug_group_ids"])
    by_arm = {}
    for treatment in study["plan"]["treatments"]:
        summary = json.loads(
            (args.study_dir / treatment["name"] / "0" / "summary.json").read_text()
        )
        by_arm[treatment["name"]] = summary["rows"]

    rows = []
    for treatment, arm in by_arm.items():
        debug = [row for row in arm if row["group_id"] in debug_groups]
        unused = [row for row in arm if row["group_id"] not in debug_groups]
        rows.append({"scope": "all", "treatment": treatment, **summarize_rows(arm)})
        rows.append({"scope": "debug", "treatment": treatment, **summarize_rows(debug)})
        rows.append({"scope": "unused", "treatment": treatment, **summarize_rows(unused)})

    failures = []
    for path in sorted(args.study_dir.rglob("*.failed.json")):
        data = json.loads(path.read_text())
        failures.append({
            "path": str(path.relative_to(args.study_dir)),
            "error": data.get("error"),
        })
    result = {
        "study_identity": study.get("identity"),
        "simulated": study.get("simulated"),
        "execution_order": study.get("execution_order"),
        "debug_group_ids": sorted(debug_groups),
        "debug_case_ids": manifest["debug_case_ids"],
        "table": rows,
        "failures": failures,
        "failure_status_counts": dict(Counter(
            row["status"] for arm in by_arm.values() for row in arm
        )),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        markdown_table(rows) + "\n\n```json\n"
        + json.dumps(result, ensure_ascii=False, indent=2) + "\n```\n",
        encoding="utf-8",
    )
    print(markdown_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
