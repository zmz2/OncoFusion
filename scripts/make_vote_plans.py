"""Freeze B0, generalist-K and professional-K vote development plans."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from oncofusion.evaluation import load_evaluation
from oncofusion.experiments import StudyPlan, Treatment, stratified_case_ids
from oncofusion.profiles import vote_v1_config
from oncofusion.voting import eligible_vote_roles


def config_dump(**updates) -> dict:
    return json.loads(vote_v1_config("native").model_dump_json()) | updates


def mtb_ids(dataset: Path) -> list[str]:
    cases, gold = load_evaluation(
        dataset / "inputs.jsonl", dataset / "_gold" / "labels.jsonl")
    labels = {row.case_id: row for row in gold}
    return sorted(
        case.id for case in cases
        if case.task == "mcq" and labels[case.id].split == "dev")


def civic_ids(dataset: Path) -> list[str]:
    cases, gold = load_evaluation(
        dataset / "inputs.jsonl", dataset / "_gold" / "labels.jsonl")
    return stratified_case_ids(
        cases,
        gold,
        task="verification",
        split="dev",
        per_label=20,
        max_per_group=1,
        sampling_seed=20261109,
    )


def balanced_cases(cases, gold, *, split: str, per_label: int, max_per_group: int,
                   excluded_groups: set[str], sampling_seed: int) -> list[str]:
    labels_by_id = {row.case_id: row for row in gold}
    eligible = [
        case for case in cases
        if labels_by_id[case.id].split == split
        and labels_by_id[case.id].group_id not in excluded_groups
    ]
    labels = sorted({labels_by_id[case.id].label for case in eligible})
    if not labels:
        raise ValueError(f"no eligible cases for split {split}")
    queues = {
        label: sorted(
            (case for case in eligible if labels_by_id[case.id].label == label),
            key=lambda case: hashlib.sha256(
                f"{sampling_seed}:{label}:{case.id}".encode()).digest())
        for label in labels
    }
    selected, counts, group_counts = [], Counter(), Counter()
    while any(counts[label] < per_label for label in labels):
        progressed = False
        for label in labels:
            if counts[label] >= per_label:
                continue
            queue = queues[label]
            while queue:
                case = queue.pop(0)
                group = labels_by_id[case.id].group_id
                if group_counts[group] >= max_per_group:
                    continue
                selected.append(case.id)
                counts[label] += 1
                group_counts[group] += 1
                progressed = True
                break
        if not progressed:
            break
    if not selected:
        raise ValueError(f"no balanced cases selected for split {split}")
    return sorted(selected)


def used_source_groups(dataset: Path, history_root: Path | None) -> set[str]:
    _, gold = load_evaluation(
        dataset / "inputs.jsonl", dataset / "_gold" / "labels.jsonl")
    group_by_case = {row.case_id: row.group_id for row in gold}
    used = set()
    if history_root is not None:
        for identity_file in sorted(history_root.glob("*/run/identity.json")):
            payload = json.loads(identity_file.read_text())
            case_ids = (
                payload.get("case_ids")
                or (payload.get("plan") or {}).get("case_ids")
                or [])
            used.update(
                group_by_case[case_id] for case_id in case_ids
                if case_id in group_by_case)
    return used


def build_plan(task: str, case_ids: list[str], cases_by_id: dict) -> tuple[StudyPlan, dict]:
    role_counts = Counter(
        len(eligible_vote_roles(cases_by_id[case_id], 5))
        for case_id in case_ids
    )
    expected_k = max(role_counts) if role_counts else 0
    treatments = [
        Treatment(
            name="b0_common_single",
            preset="full",
            overrides=config_dump(
                vote_pool="generalist",
                vote_members=1,
                vote_workers=1,
                vote_rule="v0",
                temperature=0.0,
                max_calls=3,
            ),
        ),
        Treatment(
            name=f"g_k{expected_k}",
            preset="full",
            overrides=config_dump(
                vote_pool="generalist",
                vote_members=expected_k,
                vote_workers=expected_k,
                vote_rule="v0",
                temperature=0.4,
                max_calls=expected_k * 3,
            ),
        ),
        Treatment(
            name="p_k_specialists",
            preset="full",
            overrides=config_dump(
                vote_pool="specialist",
                vote_members=expected_k,
                vote_workers=expected_k,
                vote_rule="v0",
                temperature=0.4,
                max_calls=expected_k * 3,
            ),
        ),
    ]
    return StudyPlan(
        name=f"vote_v1_{task}",
        task=task,
        split="dev",
        seeds=[0],
        case_ids=case_ids,
        treatments=treatments,
        reference="b0_common_single",
        bootstrap_repeats=2000,
    ), dict(sorted(role_counts.items()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mtb", type=Path, default=Path("data/mtbbench"))
    parser.add_argument("--civic", type=Path, default=Path("data/civicfact-pmidids"))
    parser.add_argument("--out-dir", type=Path, default=Path("experiments"))
    parser.add_argument("--history-root", type=Path, default=Path("results/v1"))
    args = parser.parse_args()

    outputs = []
    for task, dataset, ids_fn, filename in (
        ("mcq", args.mtb, mtb_ids, "vote_v1_mtb_dev43_20261109.json"),
        ("verification", args.civic, civic_ids,
         "vote_v1_civic_dev60_20261109.json"),
    ):
        cases, _ = load_evaluation(
            dataset / "inputs.jsonl", dataset / "_gold" / "labels.jsonl")
        cases_by_id = {case.id: case for case in cases}
        case_ids = ids_fn(dataset)
        plan, role_counts = build_plan(task, case_ids, cases_by_id)
        path = args.out_dir / filename
        path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
        smoke = plan.model_copy(update={
            "name": plan.name + "_smoke",
            "case_ids": case_ids[:2],
        })
        smoke_path = args.out_dir / filename.replace(".json", "_smoke.json")
        smoke_path.write_text(smoke.model_dump_json(indent=2) + "\n", encoding="utf-8")
        outputs.append({
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "smoke_path": str(smoke_path),
            "smoke_sha256": hashlib.sha256(smoke_path.read_bytes()).hexdigest(),
            "task": task,
            "cases": len(case_ids),
            "groups": len({
                gold.group_id
                for gold in load_evaluation(
                    dataset / "inputs.jsonl",
                    dataset / "_gold" / "labels.jsonl")[1]
                if gold.case_id in set(case_ids)
            }),
            "eligible_role_counts": role_counts,
            "executions": len(case_ids) * len(plan.treatments),
            "max_model_calls": len(case_ids) * sum(
                treatment.config(0).max_calls
                for treatment in plan.treatments),
        })
    cases, gold = load_evaluation(
        args.civic / "inputs.jsonl", args.civic / "_gold" / "labels.jsonl")
    cases_by_id = {case.id: case for case in cases}
    used = used_source_groups(args.civic, args.history_root)
    calibration_ids = balanced_cases(
        cases,
        gold,
        split="train",
        per_label=60,
        max_per_group=1,
        excluded_groups=used,
        sampling_seed=20261109,
    )
    calibration_plan, calibration_roles = build_plan(
        "verification", calibration_ids, cases_by_id)
    calibration_plan = calibration_plan.model_copy(update={
        "name": "vote_v1_civic_calibration",
        "split": "train",
        "treatments": [
            treatment for treatment in calibration_plan.treatments
            if treatment.name == "p_k_specialists"
        ],
        "reference": "p_k_specialists",
    })
    calibration_path = args.out_dir / "vote_v1_civic_calibration_20261109.json"
    calibration_path.write_text(
        calibration_plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    confirm_pool = used | {
        row.group_id for row in gold
        if row.case_id in set(calibration_ids)
    }
    confirm_ids = balanced_cases(
        cases,
        gold,
        split="dev",
        per_label=60,
        max_per_group=1,
        excluded_groups=confirm_pool,
        sampling_seed=20261110,
    )
    confirm_plan, confirm_roles = build_plan(
        "verification", confirm_ids, cases_by_id)
    confirm_plan = confirm_plan.model_copy(update={
        "name": "vote_v1_civic_confirm",
    })
    confirm_path = args.out_dir / "vote_v1_civic_confirm_20261109.json"
    confirm_path.write_text(
        confirm_plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    outputs.extend([
        {
            "path": str(calibration_path),
            "sha256": hashlib.sha256(calibration_path.read_bytes()).hexdigest(),
            "task": "verification",
            "purpose": "calibration",
            "split": "train",
            "cases": len(calibration_ids),
            "groups": len(calibration_ids),
            "eligible_role_counts": calibration_roles,
            "excluded_source_groups": len(used),
            "executions": len(calibration_ids) * len(calibration_plan.treatments),
            "max_model_calls": len(calibration_ids) * sum(
                treatment.config(0).max_calls
                for treatment in calibration_plan.treatments),
        },
        {
            "path": str(confirm_path),
            "sha256": hashlib.sha256(confirm_path.read_bytes()).hexdigest(),
            "task": "verification",
            "purpose": "confirmation",
            "split": "dev",
            "cases": len(confirm_ids),
            "groups": len(confirm_ids),
            "eligible_role_counts": confirm_roles,
            "excluded_source_groups": len(confirm_pool),
            "executions": len(confirm_ids) * len(confirm_plan.treatments),
            "max_model_calls": len(confirm_ids) * sum(
                treatment.config(0).max_calls
                for treatment in confirm_plan.treatments),
        },
    ])
    summary_path = args.out_dir / "vote_v1_plan_summary_20261109.json"
    summary_path.write_text(
        json.dumps(outputs, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps(outputs, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
