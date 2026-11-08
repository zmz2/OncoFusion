"""Freeze the two-system expansion plans from the live profile and exact dataset IDs.

MTBBench uses every test case. CIViC-Fact uses a deterministic test subset with 50 cases per
verification label and at most three cases from any one article. The seven-agent arm runs the
live classroom profile. The one-agent arm keeps the same model, evidence selection, citation
resolution, output cap, repair policy and token budget, changing only the workflow structure.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from oncofusion.evaluation import load_evaluation
from oncofusion.experiments import StudyPlan, Treatment, stratified_case_ids
from oncofusion.profiles import available_backend, v1_class_config


DATASETS = {
    "mtb": Path("data/mtbbench"),
    "civic": Path("data/civicfact-pmidids"),
}


def treatment_configs() -> tuple[dict, dict]:
    backend = available_backend()
    profile = v1_class_config("langgraph" if backend == "langgraph" else None)
    multi = json.loads(profile.model_dump_json())
    single = dict(multi)
    single.update({
        "mode": "single_tools",
        "interaction_protocol": "legacy",
        "specialist_contracts": False,
        "latest_role_board": False,
    })
    return multi, single


def build_plan(name: str, task: str, case_ids: list[str],
               multi: dict, single: dict) -> StudyPlan:
    return StudyPlan(
        name=name,
        task=task,
        split="test",
        seeds=[0],
        case_ids=case_ids,
        treatments=[
            Treatment(name="v1_class", preset="full", overrides=multi, perturbation="none"),
            Treatment(name="single_tools_shared_evidence", preset="single_tools",
                      overrides=single, perturbation="none"),
        ],
        reference="v1_class",
        bootstrap_repeats=2000,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("experiments"))
    parser.add_argument("--sampling-seed", type=int, default=20261108)
    args = parser.parse_args()

    mtb_cases, mtb_gold = load_evaluation(
        DATASETS["mtb"] / "inputs.jsonl", DATASETS["mtb"] / "_gold" / "labels.jsonl"
    )
    civic_cases, civic_gold = load_evaluation(
        DATASETS["civic"] / "inputs.jsonl", DATASETS["civic"] / "_gold" / "labels.jsonl"
    )
    mtb_ids = sorted(
        record.case_id for record in mtb_gold
        if record.split == "test" and record.case_id in {case.id for case in mtb_cases}
    )
    civic_ids = stratified_case_ids(
        civic_cases, civic_gold, task="verification", split="test", per_label=50,
        max_per_group=3, sampling_seed=args.sampling_seed,
    )
    if len(mtb_ids) != 140:
        raise RuntimeError(f"expected 140 MTB test cases, found {len(mtb_ids)}")
    if len(civic_ids) != 150:
        raise RuntimeError(f"expected 150 CIViC sample cases, found {len(civic_ids)}")
    mtb_calibration_ids = stratified_case_ids(
        mtb_cases, mtb_gold, task="mcq", split="test", per_label=1,
        max_per_group=1, sampling_seed=args.sampling_seed,
    )
    civic_calibration_ids = stratified_case_ids(
        civic_cases, civic_gold, task="verification", split="test", per_label=1,
        max_per_group=1, sampling_seed=args.sampling_seed,
    )

    multi, single = treatment_configs()
    mtb_plan = build_plan("v1_compare_mtb_test140", "mcq", mtb_ids, multi, single)
    civic_plan = build_plan("v1_compare_civic_test150", "verification", civic_ids, multi, single)
    mtb_calibration = build_plan(
        "v1_calibrate_mtb2", "mcq", mtb_calibration_ids, multi, single
    )
    civic_calibration = build_plan(
        "v1_calibrate_civic3", "verification", civic_calibration_ids, multi, single
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for filename, plan in (
        ("v1_compare_mtb_test140.json", mtb_plan),
        ("v1_compare_civic_test150.json", civic_plan),
        ("v1_calibrate_mtb2.json", mtb_calibration),
        ("v1_calibrate_civic3.json", civic_calibration),
    ):
        path = args.output_dir / filename
        path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
        outputs[str(path)] = {
            "cases": len(plan.case_ids),
            "executions": len(plan.case_ids) * len(plan.treatments) * len(plan.seeds),
        }

    civic_labels = {record.case_id: record.label for record in civic_gold}
    civic_groups = {record.case_id: record.group_id for record in civic_gold}
    label_counts = Counter(civic_labels[case_id] for case_id in civic_ids)
    group_counts = Counter(civic_groups[case_id] for case_id in civic_ids)
    if set(label_counts) != {"SUPPORTS", "REVISIONS", "NEI"} or set(label_counts.values()) != {50}:
        raise RuntimeError(f"unbalanced CIViC sample: {dict(label_counts)}")
    if max(group_counts.values()) > 3:
        raise RuntimeError(f"CIViC article cap exceeded: {max(group_counts.values())}")
    print(json.dumps({
        "plans": outputs,
        "sampling_seed": args.sampling_seed,
        "mtb": {"cases": len(mtb_ids), "groups": len({g.group_id for g in mtb_gold if g.case_id in set(mtb_ids)})},
        "civic": {"cases": len(civic_ids), "labels": dict(sorted(label_counts.items())),
                  "articles": len(group_counts), "max_cases_per_article": max(group_counts.values())},
        "formal_case_executions": sum(
            row["executions"] for path, row in outputs.items() if "compare" in path
        ),
        "calibration_case_executions": sum(
            row["executions"] for path, row in outputs.items() if "calibrate" in path
        ),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
