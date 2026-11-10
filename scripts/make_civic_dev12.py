"""Freeze a 12-case, label-balanced CIViC development calibration set."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from oncofusion.evaluation import load_evaluation
from oncofusion.experiments import StudyPlan, Treatment, stratified_case_ids
from oncofusion.profiles import available_backend, v1_class_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path,
                        default=Path("data/civicfact-pmidids"))
    parser.add_argument("--sampling-seed", type=int, default=20261108)
    parser.add_argument("--output", type=Path,
                        default=Path("experiments/v1_civic_dev12_frozen.json"))
    args = parser.parse_args()

    cases, gold = load_evaluation(
        args.dataset / "inputs.jsonl", args.dataset / "_gold" / "labels.jsonl")
    case_ids = stratified_case_ids(
        cases, gold, task="verification", split="dev", per_label=4,
        max_per_group=1, sampling_seed=args.sampling_seed)
    profile = v1_class_config("langgraph" if available_backend() == "langgraph" else None)
    multi = json.loads(profile.model_dump_json())
    single = dict(multi)
    single.update({
        "mode": "single_tools",
        "interaction_protocol": "legacy",
        "specialist_contracts": False,
        "latest_role_board": False,
    })
    plan = StudyPlan(
        name="v1_civic_dev12_frozen",
        task="verification",
        split="dev",
        seeds=[0],
        case_ids=case_ids,
        treatments=[
            Treatment(name="v1_class", preset="full", overrides=multi,
                      perturbation="none"),
            Treatment(name="single_tools_shared_evidence", preset="single_tools",
                      overrides=single, perturbation="none"),
        ],
        reference="v1_class",
        bootstrap_repeats=2000,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    by_id = {record.case_id: record for record in gold}
    labels = Counter(by_id[case_id].label for case_id in case_ids)
    groups = Counter(by_id[case_id].group_id for case_id in case_ids)
    assert len(case_ids) == 12
    assert labels == {"SUPPORTS": 4, "REVISIONS": 4, "NEI": 4}
    assert max(groups.values()) == 1
    print(json.dumps({
        "case_ids": case_ids,
        "labels": dict(sorted(labels.items())),
        "articles": len(groups),
        "sampling_seed": args.sampling_seed,
        "executions": len(case_ids) * len(plan.treatments),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
