"""Audit source-group and label isolation for frozen vote-v1 plans."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from oncofusion.datasets import GoldRecord, read_jsonl
from oncofusion.experiments import StudyPlan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--plan", action="append", required=True,
                        help="NAME=PATH; repeat for every source set")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    plans = {}
    for item in args.plan:
        if "=" not in item:
            raise ValueError("plan must use NAME=PATH")
        name, raw_path = item.split("=", 1)
        if name in plans:
            raise ValueError("duplicate plan name: " + name)
        plans[name] = StudyPlan.model_validate_json(
            Path(raw_path).read_text(encoding="utf-8"))
    gold = {
        row.case_id: row
        for row in (
            GoldRecord.model_validate(item)
            for item in read_jsonl(
                args.dataset / "_gold" / "labels.jsonl")
        )
    }
    groups = {}
    details = {}
    for name, plan in plans.items():
        missing = [case_id for case_id in plan.case_ids if case_id not in gold]
        if missing:
            raise ValueError(
                f"{name} contains {len(missing)} cases absent from gold")
        groups[name] = {
            gold[case_id].group_id for case_id in plan.case_ids
        }
        details[name] = {
            "plan": plan.name,
            "cases": len(plan.case_ids),
            "groups": len(groups[name]),
            "labels": dict(sorted(Counter(
                gold[case_id].label for case_id in plan.case_ids).items())),
        }
    overlaps = {}
    for left, right in combinations(sorted(groups), 2):
        overlap = sorted(groups[left] & groups[right])
        overlaps[f"{left}__{right}"] = {
            "count": len(overlap),
            "groups": overlap,
        }
    by_group = defaultdict(list)
    for name, values in groups.items():
        for group_id in values:
            by_group[group_id].append(name)
    reused = {
        group_id: names for group_id, names in sorted(by_group.items())
        if len(names) > 1
    }
    payload = {
        "dataset": str(args.dataset),
        "plans": details,
        "pairwise_group_overlap": overlaps,
        "any_group_overlap": bool(reused),
        "reused_groups": reused,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps({
        "out": str(args.out),
        "any_group_overlap": payload["any_group_overlap"],
    }))
    return 0 if not reused else 2


if __name__ == "__main__":
    raise SystemExit(main())
